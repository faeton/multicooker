# Design notes — отложенные идеи

Тут лежат соображения по фичам, которые **не делаем сейчас**, но
не хотим потерять контекст. Когда дойдут руки — берём отсюда
готовый каркас trade-off'ов вместо того, чтобы передумывать с нуля.

Соответствующие пункты живут в `docs/todo.md` (статус и приоритет),
а здесь — почему именно так, какие альтернативы рассматривались,
что сломается на простом пути.

---

## Multi-account creds (профили)

**Почему отложено.** MVP покрывает 95% кейсов: один пользователь —
один аккаунт на каждый flavor. Профили нужны для (а) разделения
личного/рабочего, (б) vendor-benchmark под разными подписками,
(в) dedicated judging account.

**Текущее состояние.** `creds.py` хардкодит источники:

- claude (macOS): Keychain entry `"Claude Code-credentials"`.
- claude (Linux): `~/.claude/.credentials.json`.
- codex: `~/.codex/auth.json`.
- gemini: `~/.gemini/oauth_creds.json` + `settings.json`.

Snapshot читает источник и кладёт в `cooks/<task>/.auth/<flavor>/`.

**Дизайн.**

1. Поле `profile:` в brief.yaml на участнике/судье. Default
   `"default"` ⇒ текущее поведение.
   ```yaml
   participants:
     - name: claude-work
       flavor: claude
       profile: work
     - name: claude-home
       flavor: claude
       profile: personal
   ```
2. Хранилище: `~/.multicooker/profiles/<profile>/<flavor>/` —
   filesystem, не Keychain. Плоская структура, явное копирование.
3. `creds.py:snapshot_for_profile(flavor, profile)` — если
   `profile == "default"`, текущая логика. Иначе читает
   `~/.multicooker/profiles/<profile>/<flavor>/`.
4. **Login wrapper** — самая мутная часть. `multicooker login
   <flavor> --profile <name>` запускает CLI в одноразовом
   контейнере с пустым `HOME`, юзер делает OAuth интерактивно,
   потом снимок `$HOME/.<cli>/` копируется в
   `~/.multicooker/profiles/<name>/<flavor>/`.
   - **claude — особый случай.** На macOS он пишет в Keychain, не
     в файл. В контейнере он падает в `~/.claude/.credentials.json`
     (Linux fallback). Это **то, что нам нужно** — мы как раз
     хотим файловый артефакт. Но это означает, что для профилей
     у пользователя получается линукс-стилевой `claude` логин,
     не интегрированный с системным Keychain. Документировать.
5. `doctor` валидирует существование `~/.multicooker/profiles/<p>/<f>/`
   для каждого упомянутого профиля, прежде чем cook.

**Что сломается на простом пути.** Если просто добавить `profile:`
без login-wrapper'а, юзеру придётся вручную копировать
`~/.codex/auth.json` в `~/.multicooker/profiles/work/codex/auth.json`
и т.п. Это работает, но плохой UX. Login-wrapper — основной труд.

**Скоуп.** Две сессии. Можно делить:
- сессия 1: `profile:` поле + ручное хранилище + `doctor` checks.
- сессия 2: `multicooker login --profile`.

---

## Replayable traces — full version

**Лайт сделан.** `trace.json` per-cell + `multicooker rejudge`. Этого
достаточно для пересудить тот же snapshot с новой рубрикой без
повторного cook'а.

**Что не сделано (full).** Structured trace tool-call'ов модели:
prompt → tool_calls[] → tool_results[] → final output. Нужно
для:
- replay через **другого** судью без оригинального CLI;
- diff'ать trace'ы между моделями (claude vs codex на одной задаче);
- ground truth для regression-тестов на самих CLI.

**Почему трудно.** Текущие argv (`--print`, `exec`, `-p`) не дают
structured output. Существуют режимы:

- claude: `--output-format stream-json` — даёт JSONL
  с tool calls/results.
- codex: `exec` имеет `--json` (стрим event'ов).
- gemini: на момент написания нет structured режима.

То есть переход на structured trace ломает gemini support, либо
требует двух режимов: structured где есть, текстовый дамп где нет.

**Прагматика.** Если когда-нибудь делать — стартовать с claude-only
(`--output-format stream-json`) и дамп остальных как stdout-blob.
Рядом с `out/` положить `trace.jsonl`.

**Скоуп.** Минимум одна сессия на claude. Полный multi-flavor —
ещё одна. Не делаем, пока **конкретный** use-case не возник.

---

## Registry / versioned task specs

**Идея.** `~/.multicooker/registry/<spec-name>@<version>/` —
шаблон арены (BRIEF.md, JUDGE_BRIEF.md, brief.yaml.template,
raw/). `multicooker new --from-spec <spec>@<v>` материализует.

**Зачем.** Стандартные арены: `arc-style`, `code-review-pr@1.2`,
`pr-summary@1.0`. Шарятся между людьми/проектами, версионируются,
прогресс на одном spec'е сравним через время.

**Почему НЕ сейчас.** Текущая база — один пользователь, нет нужды
в registry. Плоский git-clone «task-pack» репо ничем не хуже до
тех пор, пока пользователей единицы. Делать registry до спроса —
overengineering.

**Если когда-нибудь.**
- Версионирование: semver, immutable. Breaking change в schema
  brief.yaml ⇒ major bump.
- Конфликт registry ↔ user override: registry даёт template,
  cook-specific brief.yaml поверх него.
- Distribution: git-based registry (`multicooker pull <git-url>` →
  локальный clone). Не делать центральный server.
- Required raw materials: spec может объявить `raw/` requirements
  (file globs + checksums); `new --from-spec` падает если в
  локальной папке нужных raw нет.

**Скоуп.** Одна сессия на minimal pull-from-git, ещё одна на
versioning + validation. Триггер: 3+ юзера попросили.

---

## Sandbox-providers / k8s

**Идея.** Абстракция `Runner` (cook + judge) → интерфейс. Default
импл — Docker Compose (как сейчас). Альтернативный — k8s pod
runner.

**Зачем.** Team setup; long-running benchmarks (10+ cooks
одновременно); cooks с heavy compute (нужен GPU node).

**Почему НЕ сейчас.**
- Текущий single-machine setup тянет до десятков параллельных
  cook'ов. Bottleneck не там.
- k8s-impl большой: NetworkPolicy для воссоздания bridge-net
  изоляции, Secret для creds (и refresh внутри pod'а — нетривиально
  для OAuth), PVC для `out/`, Job-оркестрация замест Compose.
- Подписочные creds в k8s — отдельная боль. OAuth refresh обычно
  пишет обратно в `~/.<cli>/`; в k8s это writable EmptyDir на pod,
  и refresh теряется при удалении pod'а. Нужно либо persistent
  PVC per-profile, либо специальный auth sidecar.

**Прагматика.** До k8s-impl рефакторнуть `compose_runner.py` за
интерфейс `Runner` (с одним Compose-impl) полезно как
internal-cleanup. Но без второй реализации — это вкус
overengineering'а.

**Скоуп.** Минимум 2 сессии: рефакторинг + k8s-impl. Триггер:
пользователь с k8s-кластером и рекуррентной задачей benchmark.
