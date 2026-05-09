# TODO

Что осталось сделать в multivarka — реалистично, по приоритетам.
Главный принцип не меняется: сначала честное и воспроизводимое
поведение, потом полировка. Раздел "Сделано (история)" внизу — для
ориентира, что уже выкошено за последние сессии.

## Приоритет 0 — следующая сессия

- [ ] Сетевая модель в compose-render. Сейчас один обычный bridge,
  все участники в одной сети, egress открыт. Целевой вариант:
  - `clients-<task>` сеть `internal: true` (между участниками
    видимости нет, в интернет — нет);
  - отдельная `llm-egress` сеть, к которой подключён
    allowlist-proxy, и только проксирующая известные домены LLM
    API (anthropic, openai, googleapis + auth-домены).
  - На время разработки прокси можно сделать опциональным
    (compose.override.yaml), но дефолт должен ехать с internal
    isolation хотя бы между участниками.
- [ ] `multivarka doctor` уже есть, но
  - [ ] Расширить: проверять, что для всех flavors из brief.yaml
    есть Dockerfile в `templates/cook/participants/<flavor>/`.
  - [ ] Добавить флаг `--strict`, чтобы не было warn-only по
    отсутствию Dockerfile, а сразу exit=1.
- [ ] Image size. Сейчас на каждый cook ставятся независимые
  `mv-<task>-{claude,codex,gemini}` поверх node:22-slim, каждый
  ~600 MB. Фактический shared слой (npm i -g <cli>) ставится 3
  раза. Решения:
  - shared `mv-base` image, локально один раз; cook'и наследуются
    `FROM mv-base` и добавляют только entrypoint;
  - либо общая base через docker bake / buildx с named target.

## Приоритет 1 — после v0.2 cook'а

- [ ] Tests:
  - [ ] unit для `new_cook.parse_participant` (NAME, NAME=FLAVOR,
    дубли, пустые сегменты);
  - [ ] unit для `add_participant` (idempotency, missing brief);
  - [ ] unit для `runner_common.detect_rate_limit` по sample
    stdout/stderr каждого CLI;
  - [ ] unit для `judge._anonymize` (mapping создаётся, в judge
    input нет flavor names);
  - [ ] unit для `report` (агрегация, missing/invalid scores,
    total=0).
- [ ] Integration smoke без реальных LLM CLI: `dummy` flavor с
  Dockerfile, который просто `cat PROMPT.txt > out/RESULT.md`.
  Тогда CI проверяет cook→judge→report end-to-end без auth.
- [ ] Packaging:
  - [ ] перенести templates внутрь `multivarka/templates/`;
  - [ ] `pip install dist/*.whl && multivarka new smoke` smoke;
  - [ ] `.dockerignore` в каждый participant template.
- [ ] CI: lint (ruff), tests, package build, secret scan.

## Приоритет 2 — перед публикацией

- [ ] LICENSE (MIT или Apache-2.0).
- [ ] CONTRIBUTING.md, SECURITY.md.
- [ ] Переписать README вокруг одного first-run сценария:
  `doctor → new → cook → judge → report` с docker как единственным
  режимом.
- [ ] Синхронизировать HOWTO.md с реальностью:
  - выпилить упоминания `~/.multivarka/auth.env` и API-ключей
    (line ~284 — наследие host-mode);
  - выпилить host-mode инструкции;
  - добавить refine-режим в основной flow.
- [ ] `docs/security.md`: threat model, что защищает Docker, что
  не защищено, как обращаться с raw/ и creds.
- [ ] `examples/hello-task` — sanitized пример, который запускается
  без приватных материалов и без LLM (через dummy flavor).
- [ ] Описать lifecycle артефактов: `work/`, `logs/`, `judging/`,
  `rounds/`, `RUN_RESULT.json`, `REFINE_*.json`, cleanup через
  `clean`.
- [ ] Проверить git history secret scanner'ом (gitleaks/trufflehog).

## Auth + creds

- [ ] Расширить `creds.py` для случая, когда у пользователя
  несколько Anthropic/Google аккаунтов и нужно выбирать профиль.
  Сейчас Keychain entry один, gemini config один.
- [ ] Документировать риск: подписочные OAuth-файлы монтируются в
  контейнер и доступны агенту внутри sandbox. Compromised CLI
  может их прочитать. Это плата за headless подписочную auth.
- [ ] Watcher для `claudeAiOauth` ключа: если Anthropic поменяет
  shape JSON, мы упадём с понятным сообщением (уже есть, но
  стоит протестировать на mock-ключе и зафиксировать regression
  test).

## Расширяемость участников

- [x] Поддержать N участников вместо хардкода 3 в CLI (готово —
  `--participants` парсит `NAME=FLAVOR`, `add-participant`).
- [ ] Поддержать **разные модели одного flavor**: сейчас claude в
  контейнере зовёт `claude --print`, без указания модели. Хочется
  `name: claude-opus, flavor: claude, env: {ANTHROPIC_MODEL: opus}`
  или argv-extension через brief.yaml.
- [ ] Поддержать **новые CLI** без правки шаблонов: добавить
  `templates/cook/participants/_custom/Dockerfile.example` и
  документ "как добавить свой flavor за 10 минут".
- [ ] Per-participant timeout (сейчас глобальный `timeout_s`).

## Refine

- [ ] Описать refine-контракт в `docs/orchestration.md`: что
  переживает round (`out/`), что снапшотится (`rounds/N/`), как
  устроен FEEDBACK.md и FEEDBACK_<flavor>.md.
- [ ] `multivarka refine --feedback <path>` — позволить указать
  один FEEDBACK файл вне cook_dir (для повторного использования
  feedback'а между cook'ами).
- [ ] Возможность refine только подмножества участников
  (`--participants`) уже есть; покрыть тестом.
- [ ] `multivarka diff <task> N M` — показать diff между раундами
  N и M по конкретному участнику (sanity-check, что refine
  реально что-то поменял).

## Идеи из аналогов

- [ ] Replayable traces (agentevals): сохранять структурированный
  run trace, чтобы можно было пересуживать без повторного cook.
- [ ] Registry-подход (OpenAI Evals): versioned eval/task specs,
  шарящиеся как шаблоны.
- [ ] Deterministic validators (AgentV / Iris) — валидировать
  brief.yaml через JSON Schema до LLM-судей.
- [ ] Sandbox-providers как у OpenHands: Docker по умолчанию,
  remote/Kubernetes как опция.

## Не делать

- [ ] Не возвращать host-mode. Если что-то перестало работать
  без него — починить в docker-mode.
- [ ] Не добавлять API-key fallback как тихий путь. Если
  подписочная auth недоступна, лучше явная ошибка `doctor`/`cook`.
- [ ] Не копировать stderr/stdout участников в judge input — это
  ломает анонимизацию.
- [ ] Не публиковать репозиторий с реальными `cooks/` и `.auth/`.

---

## Сделано (история, для ориентира)

- ✅ `compose_runner.py` — build / up / logs-follow / wait / timeout / rm,
  rate-limit detection (мигрировал в `runner_common.py`),
  статусы ok/rate_limited/timed_out/non_zero_exit.
- ✅ `compose_render.render_compose()` + `creds.snapshot()` подключены
  в `cook.py` и `refine.py` и `judge.py`.
- ✅ Docker-mode стал единственным; `--docker` флаг убран. Host-mode
  и `host_runner.py` удалены.
- ✅ `runner_common.py` отдельным модулем (RunResult + detect_rate_limit
  + tail) вместо разделяемых private-helpers из host_runner.
- ✅ Docker judging: материализация копиями, deterministic
  `_work-<judge>` для предсказуемых mount'ов, сбор
  `outbox/scores.json` + `review.md`.
- ✅ Friendly auth failure: `_snapshot_creds_or_die` ловит
  `CredsError`, печатает причину + remediation, exit=2 без
  traceback'а. Используется в cook/judge/refine.
- ✅ `multivarka doctor` — preflight для docker + creds, по
  cook-имени или по списку flavors.
- ✅ `multivarka add-participant <task> NAME[=FLAVOR]` — расширение
  существующего cook'а без правки brief.yaml вручную.
- ✅ `--participants NAME=FLAVOR` в `new`/`cook`/`refine` поддерживает
  множественные участники одного flavor (claude-a, claude-b…).
- ✅ `multivarka refine` — round-N итерация поверх предыдущего
  output'а; снапшот в `rounds/<N>/`, inline shared+personal
  FEEDBACK в PROMPT.txt.
- ✅ `multivarka clean` — `compose down -v --rmi local` для одного
  cook'а или `--all`; флаги `--keep-creds`, `--dry-run`.
- ✅ `.auth/` записывается в per-cook `.gitignore` через
  `creds.snapshot()`.
- ✅ Подтверждена актуальность `claudeAiOauth` Keychain JSON формата
  (cook 260509-steamping-design прошёл с реальными creds).
- ✅ `cooks/` глобально в .gitignore — креды и LLM-выходы никогда не
  попадают в индекс.
