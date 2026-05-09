# Auth: подписочные CLI в контейнерах без API-ключей

Это перенос/расширение того, что было в
`reproxy/arena/coding-sandbox/README.md`. Цель — гонять `claude` /
`codex` / `gemini` внутри Linux-контейнеров на macOS-хосте, используя
подписки, без `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY`.

## TL;DR — два пути для claude

**Option A (default на macOS): Keychain snapshot.** Перед каждым
`cook` мультиварка вытаскивает credential JSON из Keychain
(`security find-generic-password -s "Claude Code-credentials" -w`)
и кладёт в `cooks/<task>/.auth/claude/.credentials.json`, который
RO-маунтится в `/root/.claude/`. Это формат, который Linux-сборка
claude-code понимает напрямую (тот же JSON, что Keychain хранит как
password value). Никакого `claude /login` не требуется.
Access token живёт ~5 часов, чего хватает на любой нормальный cook.

**Option B (fallback для Linux-хостов или если Keychain недоступен):
named volume + one-time login** — описан в разделах ниже. На
Linux-хосте клиент claude-code и так держит креды в
`~/.claude/.credentials.json`, можно bind-mount'ить напрямую (по
сути option A без шага извлечения).

## Где у каждого CLI лежат креды

| CLI    | macOS host                                          | Linux container               |
|--------|-----------------------------------------------------|-------------------------------|
| codex  | `~/.codex/auth.json` (plain file)                   | `/root/.codex/auth.json`      |
| gemini | `~/.gemini/oauth_creds.json` (plain file)           | `/root/.gemini/oauth_creds.json` |
| claude | **macOS Keychain** (нельзя достать в контейнер)     | `~/.claude/` (plain files после `claude /login`) |

`codex` и `gemini` — простой bind-mount RO. С `claude` хитрее.

## codex — bind-mount

В compose:

```yaml
volumes:
  - ${HOME}/.codex/auth.json:/root/.codex/auth.json:ro
```

CLI читает токен и обновляет его при необходимости — но т.к. mount
RO, refresh не запишется обратно. На практике подписочный токен
живёт долго, refresh внутри контейнера случается редко. Если вдруг
токен протух — обнови на хосте (`codex` на хосте), новый файл
автоматически виден в контейнере при следующем cook.

## gemini — bind-mount

Аналогично:

```yaml
volumes:
  - ${HOME}/.gemini/oauth_creds.json:/root/.gemini/oauth_creds.json:ro
```

Те же оговорки про refresh.

## claude — named volume + one-time login

На macOS токен `claude` лежит в Keychain — его нельзя bind-mount'ить
в Linux-контейнер (другая ОС, другой формат). На Linux `claude`
хранит токен в `~/.claude/` файлами, поэтому делаем разово
аутентификацию **внутри** Linux-контейнера и сохраняем результат в
named volume.

### Первоначальная настройка (один раз)

```bash
# 1. Собрать образ с claude-code:
docker build -t mv-claude-base \
  -f templates/cook/participants/claude/Dockerfile.base .

# 2. Залогиниться внутри контейнера, складывая creds в named volume:
docker run --rm -it \
  -v mv-claude-auth:/root/.claude \
  mv-claude-base \
  claude /login

# claude напечатает URL → откроешь в браузере на хосте → авторизуешь.
# Токен запишется в /root/.claude/ внутри контейнера, а это named
# volume mv-claude-auth, переживёт удаление контейнера.
```

`Dockerfile.base` (минимальный):

```Dockerfile
FROM node:22-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl && rm -rf /var/lib/apt/lists/*
RUN npm install -g @anthropic-ai/claude-code
WORKDIR /work
```

### При каждом cook

В compose-сервисе участника `claude`:

```yaml
volumes:
  - mv-claude-auth:/root/.claude          # из named volume, RW
  - ./BRIEF.md:/work/BRIEF.md:ro
  - ./raw/:/work/raw/:ro
  - ./work/claude/out/:/work/out/:rw
```

`mv-claude-auth` объявлен в `volumes:` секции compose как external
named volume, чтобы не пересоздавался каждым `down -v`.

### Когда токен протух

Перезапусти one-time login:

```bash
docker run --rm -it \
  -v mv-claude-auth:/root/.claude \
  mv-claude-base claude /login
```

Симптом: cook запускается, в логах `claude` видишь "Please run
/login" / "Unauthenticated".

## Изоляция: почему мы не передаём API-ключи

- Подписки уже есть, ключи стоят дополнительных $$.
- API-ключи — длинные секреты, которые легко утекают через
  `docker history`, `--env`, или скриншоты. OAuth-токены в
  bind-mount'ах протекают только если кто-то ходит в `~/.codex/`
  пользователя — это уже совсем другой класс инцидента.
- Мы повторяем поведение arena, где это уже было обкатано три
  ночи подряд.

## Сетевая часть auth

Контейнерам нужен egress наружу к auth-доменам и API:

- claude: `api.anthropic.com`, `console.anthropic.com`
- codex: `api.openai.com`, `auth.openai.com`, `chatgpt.com`
- gemini: `generativelanguage.googleapis.com`,
  `oauth2.googleapis.com`, `accounts.google.com`

Для arena-style allowlist'а можно поднять forward-proxy на
`llm-egress` сети с фильтром по SNI. v0.1 просто разрешает egress
на bridge-сети — за счёт того, что в контейнере нет ничего, что
могло бы экстра-фильтрацию обойти. Если задача чувствительная —
ставь explicit proxy в `cooks/<task>/compose.override.yaml`.

## Anti-self-judge при containerized auth

Раньше (arena, host-mode) anti-self-judge был проверкой
"flavor-match". Сейчас, когда судья — отдельный контейнер с теми же
кредами, что у участника той же flavor, это всё ещё работает: судья
видит только анонимизированные `submissions/{A,B,C}/` и не имеет
доступа к участникам. Но bias по стилю остаётся. Если хочешь жёстче
— подними двух судей разной flavor.
