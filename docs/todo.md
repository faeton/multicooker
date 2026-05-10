# TODO

Что осталось сделать в multivarka — реалистично, по приоритетам.
Главный принцип не меняется: сначала честное и воспроизводимое
поведение, потом полировка. Раздел "Сделано (история)" внизу — для
ориентира, что уже выкошено за последние сессии.

## Приоритет 0 — следующая сессия

## Приоритет 1 — после v0.2 cook'а

- [x] Tests: parse_participant, add_participant, detect_rate_limit
  (с fixture'ами per CLI), `judge._anonymize`, `report`
  агрегация. Integration smoke через subprocess на dummy flavor
  (auto-skip если docker не доступен). 40 тестов, 7-8 секунд.
- [x] Integration smoke без реальных LLM CLI: `dummy` flavor готов
  (`templates/cook/participants/dummy/`, alpine-based, no auth).
  Один entrypoint покрывает participant- и judge-режимы (branch
  на `MULTIVARKA_JUDGE`). Полный `new→cook→judge→report` цикл
  отрабатывает за ~10 секунд без подписочных кредов.
- [x] Packaging: `templates/` переехал внутрь `multivarka/templates/`;
  все Path-ссылки отвязаны от `parents[1]` (раньше работало только
  из репо, теперь работает после `pip install`). `.dockerignore`
  в каждом participant-шаблоне. Wheel build + smoke install в
  чистый venv проверены вручную.
- [x] CI: GitHub Actions (`.github/workflows/ci.yml`): ruff
  (E9+F), pytest на 3.10/3.12, wheel build, smoke install.
  Secret scan — пока не добавлен (отдельный пункт ниже).
- [x] CI: gitleaks для secret scan (отдельный job в `.github/workflows/ci.yml`).

## Приоритет 2 — перед публикацией

- [x] LICENSE — MIT.
- [x] CONTRIBUTING.md (направление + dev loop + flavor extension).
- [x] SECURITY.md (контакт + scope + out-of-scope).
- [x] README переписан вокруг docker-only first-run:
  `doctor → new → cook → judge → report` + refine-петля + multi-flavor.
- [x] HOWTO.md синхронизирован: выпилены упоминания
  `~/.multivarka/auth.env` / API-ключей / host_runner; добавлен
  раздел про refine; раздел "Host-mode vs Docker-mode" заменён на
  "Docker-mode (единственный)".
- [x] `docs/security.md` — threat model: что защищает Docker, что
  не защищено, как обращаться с raw/ и creds.
- [x] `examples/hello-task` теперь на dummy flavor — гоняется без
  LLM-кредов; добавлены `JUDGE_BRIEF.md` и `examples/hello-task/README.md`.
- [x] `docs/lifecycle.md` — что создаёт каждый шаг, что безопасно
  удалить, что чинит `clean`.
- [x] Git history secret scan (gitleaks) висит в CI.

## Auth + creds

- [ ] Расширить `creds.py` для случая, когда у пользователя
  несколько Anthropic/Google аккаунтов и нужно выбирать профиль.
  Сейчас Keychain entry один, gemini config один.
- [ ] Документировать риск: подписочные OAuth-файлы монтируются в
  контейнер и доступны агенту внутри sandbox. Compromised CLI
  может их прочитать. Это плата за headless подписочную auth.
- [x] Watcher для `claudeAiOauth` ключа: regression test на mock
  блобе (`tests/test_creds_claude_shape.py`) — 4 кейса:
  good shape, unexpected shape, invalid JSON, missing entry.
  Shape с v0.1 ни разу не менялся, тест preventive.

## Расширяемость участников

- [x] Поддержать N участников вместо хардкода 3 в CLI (готово —
  `--participants` парсит `NAME=FLAVOR`, `add-participant`).
- [x] Поддержать **разные модели одного flavor**: brief.yaml
  принимает `model:` per participant/judge; compose-render
  пробрасывает в контейнер как `MULTIVARKA_MODEL=...`, и каждый
  entrypoint.sh добавляет соответствующий argv (`--model` для
  claude и gemini, `-c model=...` для codex). Дефолт без model =
  CLI выбирает сам как раньше.
- [ ] Поддержать **новые CLI** без правки шаблонов: добавить
  `templates/cook/participants/_custom/Dockerfile.example` и
  документ "как добавить свой flavor за 10 минут".
- [x] Per-participant / per-judge timeout: brief.yaml поддерживает
  optional `timeout_s:` на уровне participant'а или судьи; глобальный
  `timeout_s` / `judge_timeout_s` остаётся дефолтом. Динамический
  дефолт по сложности брифа отвергнут — нет надёжного сигнала.

## Refine

- [x] Refine-контракт описан в `docs/orchestration.md` §"Refine":
  что переживает round (`out/` остаётся в `work/`), что
  снапшотится (`rounds/N/<p>/` + `rounds/N/_inbox/`), как
  inline-вставляются FEEDBACK.md / FEEDBACK_<flavor>.md в
  PROMPT.txt, round-counter, что НЕ переносится между раундами.
- [ ] `multivarka refine --feedback <path>` — позволить указать
  один FEEDBACK файл вне cook_dir (для повторного использования
  feedback'а между cook'ами).
- [ ] Возможность refine только подмножества участников
  (`--participants`) уже есть; покрыть тестом.
- [x] `multivarka diff <task> N M [--participants ...]` — unified
  diff между раундами по каждому участнику. Хэндлит added/
  deleted/modified/binary, "no changes" notice. Покрыт тестами
  (`tests/test_diff_rounds.py`).

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

- ✅ Shared base images: `templates/base/<flavor>/Dockerfile` ставит
  тяжёлое (node:22-slim + apt + `npm i -g <cli>` + `node` user).
  Cook participant Dockerfile укоротился до `FROM mv-base-<flavor>`
  + entrypoint — build cook-образа ~1 сек вместо 2-3 минут. CLI:
  `multivarka build-base [<flavor>...] [--force]`. cook/refine/
  judge сами зовут `base_images.ensure_built()` перед compose
  build, так что для пользователя это прозрачно.
- ✅ `multivarka doctor` расширен: проверка Dockerfile per flavor
  (FAIL если нет ни в `cooks/<task>/participants/<flavor>/` ни в
  templates), проверка наличия `mv-base-<flavor>:latest` (WARN по
  умолчанию, FAIL под `--strict`).
- ✅ Сетевая изоляция между контейнерами одного cook'а: каждый
  участник и каждый судья — на собственной bridge-сети
  (`net-participant-<name>` / `net-judge-<name>`). Egress в
  интернет открыт намеренно (участникам нужен npm/pypi/docs);
  threat model: sandbox = контейнер, не сеть. Жёсткий allowlist
  оставлен как опт-ин через `compose.override.yaml` per cook.
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
