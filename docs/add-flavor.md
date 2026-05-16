# Adding a new flavor (CLI agent)

Multicooker ships with `claude`, `codex`, `gemini`, and `dummy`. To add a
new CLI agent (например aider, cursor-cli, ollama-runner, локальный
binary) — пройди этот гайд. ~10 минут на копипасту, основное время уйдёт
на отладку argv твоего CLI.

## Что нужно решить заранее

1. **Как CLI авторизуется?** Через subscription OAuth-файлы на хосте
   (как у claude/codex/gemini)? Через API-ключ в env? Без auth (как
   `dummy`)? Это влияет на `creds.py`.
2. **Есть ли non-interactive флаг?** Если CLI зависает на approval-
   промптах в headless-режиме без флага вроде `--yes`, `--yolo`,
   `--dangerously-bypass-...` — нужно найти аналог. Без него таймаут
   убъёт раунд раньше, чем CLI напечатает первую строку.
3. **Самостоятельный или с base-образом?** Если установка тяжёлая
   (`npm i -g …`, `apt install …`) — бери layout B (shared base).
   Иначе layout A.

## Быстрая шпаргалка — какие файлы создать

```
multicooker/templates/
├── base/<flavor>/Dockerfile               (layout B only — heavy install)
└── cook/participants/<flavor>/
    ├── Dockerfile                          ← copy of _custom/Dockerfile.example
    ├── entrypoint.sh                       ← copy of _custom/entrypoint.sh.example
    └── .dockerignore                       ← std (`*` on line 1, `!entrypoint.sh` on 2)
```

И две правки в коде:

```
multicooker/creds.py               ← добавить _snapshot_<flavor>(...) + диспетчер
multicooker/brief_schema.py        ← добавить flavor в KNOWN_FLAVORS
```

## Шаг за шагом

### 1. Заскелетить flavor-папку

```bash
cp templates/cook/participants/_custom/Dockerfile.example     templates/cook/participants/myflavor/Dockerfile
cp templates/cook/participants/_custom/entrypoint.sh.example  templates/cook/participants/myflavor/entrypoint.sh
chmod +x templates/cook/participants/myflavor/entrypoint.sh
echo $'*\n!entrypoint.sh' > templates/cook/participants/myflavor/.dockerignore
```

### 2. Заполнить Dockerfile

`Dockerfile.example` — не комментарий-документация, а рабочий шаблон с
TODO. Поправь:

- `FROM mc-base-yourflavor:latest` → или твой публичный образ (layout A),
  или имя твоей base (layout B; см. шаг 5).
- `USER node` → юзер, который существует в base'е.

### 3. Заполнить entrypoint.sh

В `entrypoint.sh.example` две ветки: participant и judge. Контракт:

| input  (RO)                       | output                              |
|-----------------------------------|-------------------------------------|
| `/work/PROMPT.txt` (participant)  | `/work/out/RESULT.md`               |
| `/work/JUDGE_BRIEF.md` (judge)    | `/work/outbox/scores.json` + `review.md` |
| `/work/raw/` (both)               |                                     |
| `/work/submissions/A/`, B/, C/ … (judge) |                              |

Эталоны argv по существующим flavors — внутри
`entrypoint.sh.example`. Главное — non-interactive флаг и форвард
`MULTICOOKER_MODEL` (опционально, если CLI поддерживает выбор модели
через брифа).

### 4. Подключить в `creds.py`

Если flavor headless (без auth) — добавь его в ветку `elif f == "dummy":
pass` в `snapshot()`. Если есть подписочные креды — пиши собственный
`_snapshot_myflavor(into)`, аналог существующих `_snapshot_codex` /
`_snapshot_gemini`. Стандартная форма: проверить наличие исходника,
скопировать в `.auth/<flavor>/<file>` с `chmod 0600`. **Креды должны
жить в bind-mount RO** в контейнере; путь подцепляется в
`compose_render.py`.

### 5. (layout B) Написать base Dockerfile

```bash
mkdir -p templates/base/myflavor
$EDITOR templates/base/myflavor/Dockerfile
```

Здесь живёт всё тяжёлое: apt-пакеты, runtime (`node:22-slim` /
`python:3.12-slim`), `npm i -g …` или `pip install …`. Обычная форма:

```dockerfile
FROM node:22-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git && rm -rf /var/lib/apt/lists/*
RUN npm i -g <your-cli-package>
RUN groupadd -r node || true && useradd -r -g node -m -s /bin/bash node || true
USER node
WORKDIR /work
```

Build один раз: `multicooker build-base myflavor`.

### 6. Обновить schema

В `multicooker/brief_schema.py` добавь имя в `KNOWN_FLAVORS`. Иначе
валидатор брифа отклонит брифы с твоим flavor'ом.

### 7. Smoke

```bash
multicooker new add-flavor-test --participants a=myflavor
$EDITOR cooks/<date>-add-flavor-test/BRIEF.md  # любая мини-задача
multicooker doctor add-flavor-test
multicooker cook   add-flavor-test
multicooker judge  add-flavor-test  # понадобится хотя бы один
                                    # judge другого flavor'а
multicooker report add-flavor-test
```

`doctor` отловит большинство глупых ошибок (missing Dockerfile,
unknown flavor в схеме, отсутствие base). `cook` упадёт с понятным
exit code если `entrypoint.sh` не написал RESULT.md за `timeout_s`.

## Reference: что копировать у кого

- **Headless / без auth:** `templates/cook/participants/dummy/` (layout
  A, alpine, ~10 строк entrypoint).
- **Subscription OAuth + npm-installed CLI:**
  `templates/cook/participants/claude/` или `gemini/` (layout B,
  base = node:22-slim + npm).
- **Plain-file auth (`~/.<cli>/auth.json`)**: `codex` — самый простой
  пример с `_snapshot_codex` в `creds.py`.

## Что НЕ нужно делать

- Не добавляй API-key fallback как silent path. Если flavor требует
  API-ключ — пусть `_snapshot_<flavor>` падает с явной `CredsError`
  «set FOO env / log in via …», без молчаливого fallback.
- Не вешай новые тяжёлые тулы (компиляторы, наборы данных) в
  `templates/base/<flavor>/` — base должен быть стабильным. Cook-
  специфичные зависимости держи в Dockerfile конкретного `cooks/<task>/
  participants/<flavor>/Dockerfile` (он переопределяет шаблон).
- Не привязывай flavor к одной модели. Модель выбирается через
  `model:` в `brief.yaml` per participant — entrypoint обязан
  уважать `$MULTICOOKER_MODEL`, если CLI это умеет.
