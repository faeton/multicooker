# Orchestration: что внутри cook / judge

Инспирирована reproxy/arena. На один cook поднимается отдельный
docker compose project, чтобы сети и volume'ы были изолированы между
задачами.

## Картинка

```
                cooks/<task>/  (compose project: mv-<task>)
                 │
   ┌─────────────┼──────────────┬───────────────┐
   ▼             ▼              ▼               ▼
┌──────┐     ┌──────┐       ┌──────┐        ┌──────┐
│claude│     │codex │       │gemini│        │judges│  (запускаются после cook)
│  c1  │     │  c2  │       │  c3  │        │  jX  │
└───┬──┘     └───┬──┘       └───┬──┘        └──┬───┘
    │            │              │              │
    │  net: clients-<task>      │   net: judging-<task>
    │  (internal: true)         │   (internal: true)
    │                           │
    └──── llm-egress (control) ─┴────► api.anthropic.com / openai / google
                                       (allowlisted egress only)
```

## Сети

- `clients-<task>` — internal. На ней все участники. Между собой
  они не связаны (compose не проксирует контейнер-к-контейнеру если
  это не нужно, плюс в `network_mode: bridge` без link'ов имена
  чужих контейнеров не резолвятся).
- `judging-<task>` — internal. На ней только судьи и control.
- `llm-egress` — bridge с egress в интернет, но через прокси с
  allowlist-доменами (см. `docs/auth.md`). В неё подключены только
  участники / судьи; никаких посторонних сервисов.

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
- сеть `clients-<task>` `internal: true`, egress только на
  allowlist;
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
