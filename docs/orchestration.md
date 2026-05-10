# Orchestration: что внутри cook / judge

Инспирирована reproxy/arena. На один cook поднимается отдельный
docker compose project, чтобы сети и volume'ы были изолированы между
задачами.

## Картинка

```
              cooks/<task>/  (compose project: mv-<task>)
               │
   ┌───────────┼───────────┬───────────┬───────────┐
   ▼           ▼           ▼           ▼           ▼
┌──────┐   ┌──────┐    ┌──────┐    ┌──────┐    ┌──────┐
│claude│   │codex │    │gemini│    │judge1│    │judge2│
└──┬───┘   └──┬───┘    └──┬───┘    └──┬───┘    └──┬───┘
   │          │           │           │           │
   ▼          ▼           ▼           ▼           ▼
 net-      net-         net-       net-        net-
 part-     part-        part-      judge-      judge-
 claude    codex        gemini     <name>      <name>
   │          │           │           │           │
   └──────────┴───────────┴───────────┴───────────┘
                          │
                          ▼  egress в интернет открыт
                     (npm / pypi / github / LLM API)
```

## Сети

Каждый участник и каждый судья — на собственной bridge-сети
(`net-participant-<name>` / `net-judge-<name>`). Это даёт два
свойства:

- Контейнеры одного cook'а **не видят друг друга**: они в разных
  сетях, имена и IP не резолвятся. Участник не может подсмотреть
  чужой `/work/out/` через сеть, судья не может пингануть
  участников.
- **Egress в интернет открыт.** Участникам легитимно нужен npm /
  pypi / github / docs / LLM API для решения задачи. Жёсткий
  allowlist ломает реальные кейсы (пакеты, dataset, документация),
  поэтому дефолт — открытый egress, а sandbox-гарантия лежит на
  контейнере (cgroup, namespaces, RO bind-mounts), не на сети.

Если конкретный cook требует строгого allowlist'а (sensitive raw,
audit-режим), он добавляется локальным `compose.override.yaml` —
это решение на уровне cook'а, не дефолт.

## Контейнер участника

Imаge: `cooks/<task>/participants/<flavor>/Dockerfile`. Базовый
шаблон — `templates/cook/participants/<flavor>/Dockerfile`.

Mounts (read-only кроме `out/`):

| host                                   | container             | mode |
|----------------------------------------|-----------------------|------|
| `cooks/<task>/BRIEF.md`                | `/work/BRIEF.md`      | ro   |
| `cooks/<task>/raw/`                    | `/work/raw/`          | ro   |
| `cooks/<task>/work/<name>/out/`        | `/work/out/`          | rw   |
| (auth) см. `docs/auth.md`              | `/root/.codex` etc.   | ro/rw|

Никаких других host-путей. В частности **никаких симлинков** в
`/work/` наружу — они рассольвятся в путь вне sandbox'а CLI и Read/
Write/Bash тихо откажут (баг #1 из reproxy/arena).

CMD — фиксированная для каждой flavor. **Контейнер = sandbox**,
поэтому используем dangerous-skip флаги (без них CLI в
non-interactive режиме зависают на approval-промптах):

```bash
# claude
claude --print "$PROMPT" --dangerously-skip-permissions --add-dir /work

# codex
codex exec --cd /work --skip-git-repo-check \
      --dangerously-bypass-approvals-and-sandbox "$PROMPT"

# gemini
gemini --yolo -p "$PROMPT"
```

Промпт ВСЕГДА **до** `--add-dir` (claude), иначе вариативный флаг
съест позиционный prompt (баг #2 из reproxy/arena). Эталон argv —
`reproxy/arena/coding-sandbox/host_runner.py:CLI_COMMANDS`.

Эти флаги безопасны именно потому, что:
- контейнер изолирован от host'а (cgroup, network namespace, no
  bind-mounts наружу `/work` и creds);
- участник на собственной bridge-сети, других участников и судей
  по сети не видит;
- `out/` — единственный rw bind-mount, повреждать там нечего
  кроме результата самого участника.

## Контейнер судьи

После `cook` мультиварка собирает `judging/_judge_input/`:

- копирует (НЕ симлинкует) `BRIEF.md`, `JUDGE_BRIEF.md`, `raw/`;
- копирует `work/<participant>/out/` в `submissions/<letter>/`,
  где letter = A/B/C по случайной перестановке `_mapping.json`;
- сборка лежит на хосте, монтируется RO в контейнер судьи.

Контейнер судьи получает:

| host                                             | container                | mode |
|--------------------------------------------------|--------------------------|------|
| `cooks/<task>/judging/_judge_input/`             | `/work/`                 | ro   |
| `cooks/<task>/judging/<judge-name>/outbox/`      | `/work/outbox/`          | rw   |
| (auth)                                            | …                        |      |

Судья пишет `outbox/scores.json` и `outbox/review.md`. Подсказки
по формату — в `JUDGE_BRIEF.md`. Анонимная карта `letter→flavor`
лежит **только** на хосте в `_mapping.json`, в контейнер не
прокидывается.

## Жизненный цикл cell'а

Для каждого `(participant, scenario_or_task)` cell:

1. `docker compose -p mv-<task> up -d <participant>`. Healthcheck
   ждёт, что CLI готов.
2. `docker exec` запускает CLI с фиксированным промптом, читающим
   `/work/BRIEF.md` + `/work/raw/`, пишущим в `/work/out/`.
3. Wall-clock cap (`brief.yaml: timeout_s`) убивает зависший
   контейнер.
4. На выходе: `docker logs` → `cooks/<task>/logs/<participant>/`,
   `out/` уже на хосте через bind-mount.
5. `docker compose down -v` для этого участника.

Параллельность: все участники поднимаются одновременно (с 2-сек
stagger'ом, чтобы Keychain/OAuth не получили простуду от
одновременных refresh'ей — наследие из arena).

## Refine: round N+1 поверх round N

`multivarka refine <task>` — итерация: участники получают свой
**предыдущий** `out/` как стартовое состояние и фидбек, а не
чистый лист. Это другой режим, чем cook (bake-off с нуля), и
артефакты лежат рядом.

### Что переживает round, что снапшотится

Состояние раунда N до запуска round N+1:

```
cooks/<task>/
├── work/<p>/out/              ← живой output round N (RW bind-mount)
├── judging/_inbox/<p>/out/    ← sealed копия round N для судейства
└── rounds/                    ← (создаётся при первом refine)
```

Перед запуском round N+1 `refine` делает один атомарный шаг:

1. **Снапшот round N** → `rounds/<N>/<p>/` (copytree, не симлинк).
   Плюс `rounds/<N>/_inbox/` — sealed-копия judge input'а, чтобы
   историю судейства тоже можно было воспроизвести.
2. **Не трогает** `work/<p>/out/` — он остаётся в RW bind-mount
   для контейнера, и участник в round N+1 видит свой round-N
   результат на месте, как «черновик для правок».
3. После завершения round N+1: `_seal_for_judging()` пересобирает
   `judging/_inbox/` поверх (старый inbox теперь живёт только в
   `rounds/<N>/_inbox/`).

Принцип: **`work/` — всегда «текущий round», `rounds/<N>/` —
immutable history**. `out/` никогда не удаляется — он просто
эволюционирует. Если round N+1 испортил результат, вернуть
прошлое можно копированием `rounds/<N>/<p>/` обратно в
`work/<p>/out/` (мультиварка не делает этого автоматически —
осознанное решение пользователя).

### FEEDBACK.md и FEEDBACK_<flavor>.md

Refine читает два файла **из корня cook'а** (не из `work/`):

| файл                       | назначение                                   |
|----------------------------|----------------------------------------------|
| `FEEDBACK.md`              | shared фидбек, виден всем участникам         |
| `FEEDBACK_<flavor>.md`     | personal фидбек для конкретного flavor       |

Оба inline-вставляются в `PROMPT.txt` round'а N+1 — отдельным
заголовком («Shared feedback» и «Personal feedback»). FEEDBACK
файлы НЕ монтируются в контейнер сами по себе — только через
содержимое `PROMPT.txt`. Это сознательно: участник видит ровно
тот текст, что мы ему адресовали, и не получит «случайно»
фидбек, написанный для другого flavor.

`FEEDBACK.md` опциональный — если его нет, refine стартует с
warning'ом и пустым shared-блоком. `FEEDBACK_<flavor>.md` тоже
опциональный — отсутствует ⇒ personal-блок не добавляется.

`multivarka refine --feedback <path>` подменяет источник shared
feedback'а на произвольный файл (вне cook_dir). Полезно, когда
один и тот же фидбек применяется к нескольким cook'ам, или
feedback живёт в общем «issue tracker» репо отдельно от арен.
Personal-feedback всегда читается из `cook_dir/FEEDBACK_<flavor>.md`
(per-cook).

Один FEEDBACK живёт **столько раундов, сколько ты его не
перезаписал**. Между раундами `refine` не очищает FEEDBACK
файлы. Хочешь свежий фидбек на round N+2 — перепиши `FEEDBACK.md`
вручную перед запуском.

### Round-counter

`rounds/` определяет нумерацию: если в нём `{1,2}`, то `work/`
содержит round 3 (только что закончен), и следующий refine — это
round 4. Если `rounds/` пустой/отсутствует, `work/` = round 1
(оригинальный cook), refine = round 2.

Метаданные раунда: `REFINE_<N>.json` (старт) и
`REFINE_<N>_RESULT.json` (статусы по участникам). Удалять их
нежелательно — `report` потенциально опирается на них для
истории прогресса (см. `docs/lifecycle.md`).

### Что НЕ переносится между раундами

- `judging/<judge-name>/` (scores) — каждый round пересудится
  заново через `multivarka judge`. История прошлых scores лежит
  в `rounds/<N>/_inbox/` и в `judging/_logs/`.
- `_mapping.json` — пересоздаётся каждое судейство (новая
  случайная перестановка A/B/C, чтобы судья не натренировался).

## Что мы НЕ переносим из arena

- Middlebox / observer / origin контейнеров здесь нет — у нас
  задачи не сетевые, наблюдать за SNI не за чем. Если конкретный
  cook требует сетевого мониторинга, добавляешь observer'а в его
  локальный `compose.override.yaml`.
- Variants (cold/warm) — пока нет. Если понадобится, естественное
  место — отдельные `participants` в brief.yaml с разными
  `model:` или env'ами.
