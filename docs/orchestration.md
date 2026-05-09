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

## Что мы НЕ переносим из arena

- Middlebox / observer / origin контейнеров здесь нет — у нас
  задачи не сетевые, наблюдать за SNI не за чем. Если конкретный
  cook требует сетевого мониторинга, добавляешь observer'а в его
  локальный `compose.override.yaml`.
- Variants (cold/warm) и rounds — пока нет, у мультиварки
  однораундовый формат. Hooks для рераунда — в TODO (см.
  `HOWTO.md` §Расширения).
