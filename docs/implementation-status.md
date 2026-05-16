# Implementation status

Что в репо реально работает на текущий момент vs что описано в
`CLAUDE.md` / `docs/` как целевое (и единственное поддерживаемое)
поведение. Если `multicooker cook --docker` падает с "not
implemented" — этот файл показывает, что нужно дописать.

## Целевое поведение (см. CLAUDE.md, docs/orchestration.md)

- Все участники и судьи — в контейнерах, параллельно.
- Подписочная auth через bind-mount / named volume.
- Dangerous-skip / bypass / yolo флаги внутри контейнеров.
- Per-service bridge networks: `net-participant-<name>` /
  `net-judge-<name>`. Между контейнерами видимости нет, egress
  открыт (см. `docs/orchestration.md`).
- Анонимизация и copy (не symlink) для судей.

## Что реально в коде (v0.1)

| компонент                              | состояние                                              |
|----------------------------------------|--------------------------------------------------------|
| `multicooker new <task>`                | ✅ работает, копирует `templates/cook/`                 |
| `templates/cook/BRIEF.md/brief.yaml/JUDGE_BRIEF.md` | ✅ есть                                  |
| `templates/cook/participants/<f>/Dockerfile` | ✅ есть, но **не используются** runtime'ом       |
| `multicooker cook <task>` host-mode     | ✅ работает (`host_runner.py`) — это временный фоллбек  |
| `multicooker cook <task> --docker`      | ❌ `error: --docker mode not implemented in v0.1`       |
| `multicooker judge <task>`              | ✅ host-mode; копирует (не симлинкует) — это правильно  |
| `multicooker judge <task> --docker`     | ❌ нет                                                  |
| Подписочная auth в контейнерах         | ❌ не подключено                                        |
| compose.yaml per cook                  | ❌ не генерируется                                      |
| Per-service bridge networks            | ✅ `net-participant-<n>` / `net-judge-<n>` per cook     |
| Allowlist egress proxy                 | ❌ опт-ин через compose.override.yaml, не дефолт        |

## Что нужно сделать, чтобы привести код к CLAUDE.md

### 1. Auth setup (`multicooker init-auth`)

Новая команда. См. `docs/auth.md` — она проверяет/готовит:
- `~/.codex/auth.json` присутствует;
- `~/.gemini/oauth_creds.json` присутствует;
- собрать `mc-claude-base` Docker image;
- запустить интерактивный `claude /login` в контейнере с named
  volume `mc-claude-auth`;
- echo-test всех трёх.

### 2. compose-шаблон в `templates/cook/`

`templates/cook/compose.yaml.tmpl` — генерируется при `cook` в
`cooks/<task>/compose.yaml`. Параметризация через
`cooks/<task>/.env`. Скелет — в `docs/orchestration.md`.

Hard-rules в шаблоне:
- argv-порядок per flavor (см. CLAUDE.md);
- dangerous-skip флаги (контейнер = sandbox);
- per-service bridge сети (`net-participant-<n>`, `net-judge-<n>`);
- volumes: bind-mount BRIEF/raw RO, out/ RW, auth.

### 3. `compose_runner.py`

Заменяет `host_runner.py` (или живёт рядом, host остаётся как
deprecated fallback). Контракт:

```python
def run_cell(cook_dir, participant_name, flavor, timeout_s) -> CellResult:
    # docker compose -p mc-<task> up -d participant-<name>
    # docker logs --follow → парсим rate-limit signatures
    # wait timeout / exit
    # docker compose -p mc-<task> rm -fv participant-<name>
    ...
```

Парсинг rate-limit'ов — переносим из `host_runner.py:_RL_PATTERNS`
один в один, источник стрима меняется на `docker logs --follow`.

### 4. `cook.py` через compose

```python
def cook(name, root, ...):
    cook_dir = root / name
    if not (cook_dir / "compose.yaml").exists():
        render_compose(cook_dir, brief)
    sh(["docker", "compose", "-p", project, "build"])
    futures = []
    with ThreadPoolExecutor(max_workers=len(participants)) as ex:
        for i, p in enumerate(participants):
            time.sleep(2 * i)                          # stagger
            futures.append(ex.submit(run_cell, ...))
        results = [f.result() for f in futures]
    sh(["docker", "compose", "-p", project, "down", "-v"])
    write_run_result(...)
```

`--docker` flag перестаёт быть опт-ин (становится дефолтом).
Host-ветка либо удаляется, либо живёт под `--legacy-host` для
разработки.

### 5. `judge.py` через compose

То же, что cook, только:
- материализация `judging/_judge_input/` (копии, не симлинки —
  это уже сделано правильно в текущем `judge.py`);
- compose-сервис per judge;
- copy `outbox/` обратно после `down`.

### 6. (опционально) egress-allowlist proxy

Прозрачный HTTP/HTTPS forward-proxy на сети `egress`, фильтрующий
по SNI на список auth+API-доменов. Tinyproxy / squid / Caddy —
любой подойдёт. Для первой docker-итерации — не блокер, но
желательно потом.

## Risks / open questions

- **claude /login UX.** Открыть URL в браузере хоста, скопировать
  callback — обычная процедура для claude-code на Linux. На маке
  пользователь её не видел никогда. Скрипт `init-auth` должен
  явно говорить "сейчас откроется URL, авторизуйся".
- **Docker Desktop license** на корпоративных маках. Workaround:
  Orbstack или Colima.
- **Лимит docker-сетей.** Каждый cook = своя сеть. Чисти
  завершённые: `docker network prune`.

## Что НЕ нужно делать

- Не подключать API-ключи как fallback "если подписка протухла".
  Лучше явный fail, чем тихий апгрейд на платный путь.
- Не пытаться вытащить токен claude из macOS Keychain
  bind-mount'ом — формат бинарный, OS-specific. Только named
  volume + одноразовый `/login`.
- Не добавлять middlebox/observer "на всякий случай" — это
  reproxy-специфика. Если конкретный cook требует — добавит в
  `cooks/<task>/compose.override.yaml`.
- Не убирать dangerous-skip флаги "для безопасности". Контейнер
  и есть sandbox; без флагов CLI зависнут на approval-промпте.
