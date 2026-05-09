# TODO: подготовка к open source

Этот список фиксирует, что нужно сделать перед публичной публикацией
multivarka. Главный принцип: сначала сделать публичное поведение честным
и воспроизводимым, потом уже полировать внешний вид.

## Блокеры перед публикацией

- [ ] Выбрать и явно описать текущий статус проекта:
  - либо `v0.1` = host-mode experimental, Docker-mode roadmap;
  - либо сначала доделать Docker-mode и сделать его дефолтом.
- [ ] Синхронизировать `README.md`, `CLAUDE.md` / `AGENTS.md`,
  `HOWTO.md` и `docs/implementation-status.md`, чтобы они не обещали
  разные security/runtime модели.
- [ ] Удалить из рабочей копии все локальные run-артефакты и секреты:
  `cooks/*/.auth/`, логи, judge outputs, приватные raw-файлы.
- [ ] Проверить git history secret scanner'ом перед публикацией.
- [ ] Добавить `LICENSE`. Практичный дефолт для такого инструмента:
  MIT или Apache-2.0.
- [ ] Добавить `CONTRIBUTING.md` и `SECURITY.md`.
- [ ] Добавить CI: lint, tests, package build, secret scan.

## Docker-mode

- [ ] Реализовать `compose_runner.py`:
  - build / up / logs-follow / wait / timeout / rm;
  - перенос rate-limit detection из `host_runner.py`;
  - корректный статус `ok`, `rate_limited`, `timed_out`,
    `non_zero_exit`.
- [ ] Подключить `compose_render.render_compose()` и `creds.snapshot()`
  из `cook.py`.
- [ ] Сделать Docker-mode дефолтом или явно оставить под
  `--docker --experimental`.
- [ ] Добавить `--legacy-host`, если host-mode остается как fallback.
- [ ] Реализовать Docker judging:
  - материализация judge input копиями, не симлинками;
  - запуск judge service через compose;
  - сбор `outbox/scores.json` и `review.md`.
- [ ] Согласовать сетевую модель:
  - целевой вариант: `clients-<task>` internal + отдельный egress;
  - MVP-вариант: обычный bridge, но честно помеченный как weaker
    isolation.
- [ ] Решить, нужен ли allowlist egress proxy в первой OSS-версии.

## Auth и секреты

- [ ] Добавить команду `multivarka init-auth` или `multivarka doctor`,
  которая проверяет доступность creds для выбранных flavors.
- [ ] Сделать сообщения об auth failure конкретными: какой CLI, какой
  файл, какая команда логина нужна.
- [ ] Убедиться, что `.auth/` добавляется в `.gitignore` каждого cook и
  никогда не попадает в examples.
- [ ] Документировать риск: подписочные OAuth-файлы монтируются в
  контейнер и доступны агенту внутри sandbox.
- [ ] Проверить актуальность формата Claude Code credentials. Сейчас код
  ожидает `claudeAiOauth` в Keychain JSON.

## Packaging

- [ ] Исправить packaging templates. Текущий `pyproject.toml` использует
  package-data на `../templates/**/*`; лучше:
  - перенести templates внутрь `multivarka/templates/`; или
  - добавить корректный `MANIFEST.in` и тест wheel/sdist.
- [ ] Добавить smoke-test установленного пакета:
  `pip install dist/*.whl && multivarka new smoke`.
- [ ] Убрать `__pycache__` из рабочей копии перед публикацией.
- [ ] Добавить `.dockerignore` для сборки participant images.

## Tests

- [ ] Unit tests для `new_cook`:
  - дата-префикс;
  - не дублирует `YYMMDD-`;
  - participants попадают в `brief.yaml`.
- [ ] Unit tests для anonymization в `judge.py`:
  - mapping создается;
  - judge input не содержит flavor names;
  - материалы копируются, не симлинкуются.
- [ ] Unit tests для `report.py`:
  - агрегация нескольких судей;
  - missing/invalid scores не ломают отчет;
  - корректная обработка `total = 0`.
- [ ] Tests для rate-limit parser по sample stderr/stdout каждого CLI.
- [ ] Integration smoke-test без реальных LLM CLI через fake flavor или
  dummy entrypoint.

## Документация

- [ ] Переписать README вокруг одного понятного first-run сценария.
- [ ] Добавить `docs/architecture.md` или обновить
  `docs/orchestration.md` с фактической схемой runtime.
- [ ] Добавить `docs/security.md`:
  - threat model;
  - что защищает Docker;
  - что не защищено;
  - как обращаться с raw-файлами и creds.
- [ ] Добавить sanitized example в `examples/hello-task`, который можно
  запустить без приватных материалов.
- [ ] Описать lifecycle артефактов:
  `work/`, `logs/`, `judging/`, `leaderboard.md`, cleanup.

## Идеи из аналогов

- [ ] Взять у OpenHands явное разделение sandbox providers:
  Docker recommended, process/host unsafe-fast, remote/future.
- [ ] Взять у agentevals идею replayable traces: сохранять
  структурированный run trace, чтобы можно было пересуживать без
  повторного `cook`.
- [ ] Взять у OpenAI Evals registry-подход: versioned eval/task specs,
  которые можно шарить как шаблоны.
- [ ] Взять у Giskard / NeMo Evaluator проверки качества и безопасности:
  `multivarka check <task>` для rubric/schema/secrets/isolation.
- [ ] Взять у AgentV / Iris локальный YAML-first workflow:
  формализовать `brief.yaml` через JSON Schema и добавить deterministic
  validators до LLM-судей.

## Не делать

- [ ] Не публиковать репозиторий с реальными `cooks/` и `.auth/`.
- [ ] Не обещать Docker isolation, пока CLI реально запускает host-mode.
- [ ] Не добавлять API-key fallback как тихий путь. Если подписочная auth
  недоступна, лучше явная ошибка.
- [ ] Не копировать stderr/stdout участников в judge input: это ломает
  анонимизацию.
