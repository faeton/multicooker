# multivarka — для Клода

Мультиварка — это арена для LLM: одна задача, несколько участников
(`claude` / `codex` / `gemini`) параллельно решают её **каждый в
своём docker-контейнере** с подписочной авторизацией, потом судьи
(тоже LLM в контейнерах) сравнивают и выставляют оценки.
Архитектура унаследована из `~/Sites/reproxy/arena/` (бранч
`archive/arena`) — compose-оркестрация, anti-self-judge,
анонимизация, rate-limit handling.

## Главное правило (HARD)

1. **Всё в docker.** Это не "будущая миграция" — это спец-дизайн:
   контейнер сам по себе является OS-level sandbox'ом, и именно
   поэтому участники запускаются с **dangerously-skip / bypass /
   yolo** флагами. Без них CLI в non-interactive режиме зависают
   на approval-промптах. Внутри изолированного контейнера эти
   флаги безопасны — host'у они навредить не могут.
2. **Никаких API-ключей.** Подписочные креды (`Claude Pro`,
   `ChatGPT Plus`, `Gemini Advanced`) пробрасываются в контейнер
   из хоста: bind-mount файлов для codex/gemini, named volume с
   one-time `claude /login` для claude. См. `docs/auth.md`.
3. **Новая задача = новая папка `cooks/<имя>/`** через
   `multivarka new <имя>` — копирует скелет из `templates/cook/`.
   Имя автоматически префиксится сегодняшней датой:
   `multivarka new foo` → `cooks/260509-foo/` (если уже передан
   префикс `YYMMDD-`, он не дублируется). Дальше во всех командах
   используется полное имя с датой: `multivarka cook 260509-foo`.
   Никогда не правь чужие cooks и не клади артефакты вне
   `cooks/<имя>/`.
4. **Параллельность.** Все участники стартуют одновременно
   (с 2-сек stagger'ом для auth refresh), независимо друг от
   друга. Rate-limit одного — не блокирует других.

## Permission-флаги в контейнерах (важно)

Эталонные argv по каждой flavor (см.
`reproxy/arena/coding-sandbox/host_runner.py` для канонического
порядка — нарушение порядка ломает CLI):

```bash
# claude  (промпт ВСЕГДА перед --add-dir, иначе variadic --add-dir съест его)
claude --print "<prompt>" --dangerously-skip-permissions --add-dir /work

# codex
codex exec --cd /work --skip-git-repo-check \
      --dangerously-bypass-approvals-and-sandbox "<prompt>"

# gemini
gemini --yolo -p "<prompt>"
```

Эти dangerous-флаги — **сознательное и обязательное** условие, а
не workaround. Они гарантируют, что:

- участник не зависнет на "may I write to ./out/RESULT.md? [y/N]";
- но при этом он не сможет дотянуться до хоста, потому что
  контейнер — это и есть его sandbox.

Сетевая изоляция между контейнерами: каждый участник и каждый
судья — на собственной bridge-сети (`net-participant-<name>` /
`net-judge-<name>`). Контейнеры одного cook'а не видят друг друга
по DNS/IP, поэтому участник не может подсмотреть чужой `out/`.
Egress в интернет открыт: участники легитимно ходят за npm/pypi/
docs/github для решения задачи. Sandbox обеспечивает контейнер,
не сеть.

## Канонический поток

```bash
multivarka new <task>                 # → cooks/<task>/ из templates/cook/
$EDITOR cooks/<task>/BRIEF.md         # ЧТО участники должны сделать
$EDITOR cooks/<task>/brief.yaml       # КТО, таймауты, рубрика
$EDITOR cooks/<task>/JUDGE_BRIEF.md   # КАК судить (рубрика == brief.yaml)
cp <refs>... cooks/<task>/raw/        # справочники (RO mount)

multivarka cook   <task>              # параллельный запуск в контейнерах
multivarka judge  <task>              # анонимизированное судейство в контейнерах
multivarka report <task>              # → cooks/<task>/leaderboard.md
```

## Когда тебя просят «сделай новую арену под X»

1. `multivarka new <task>`.
2. Перепиши `BRIEF.md`: цель, входы (придут в `/work/raw/` RO),
   что должно лежать в `/work/out/`, success criteria.
   Двусмысленность в постановке — ок (на ней расходятся участники),
   в success criteria — нет.
3. Синхронизируй рубрику между `brief.yaml` (`rubric.dimensions`) и
   `JUDGE_BRIEF.md` (таблица + JSON-схема `scores.json`).
4. Материалы — в `raw/`.
5. Если задача требует кастомных тулов в контейнере (`tshark`,
   `pandas`, компилятор Go) — добавляй их в Dockerfile **этого
   cook**, не в шаблон. Cook'и независимы.
6. `multivarka cook <task>` → `judge` → `report`.

Перед overnight — глянь `docs/pitfalls.md`.

## Изоляция (как в reproxy/arena)

- Каждый участник — свой контейнер на собственной bridge-сети
  `net-participant-<name>`. Видит: `/work/BRIEF.md` (RO),
  `/work/raw/` (RO), `/work/out/` (RW), свои creds. **Не видит**:
  других участников (они в других сетях), `judging/`, маппинг
  `A↔flavor`, остальной репо.
- Egress в интернет открыт. Это сознательно: участникам нужен
  доступ к LLM API + npm/pypi/github/docs. Sandbox-гарантия —
  контейнер, а не сеть. Если конкретный cook требует жёсткого
  allowlist'а, это делается локальным `compose.override.yaml`.
- Судья — отдельный контейнер на своей `net-judge-<name>`,
  доступа к участникам нет. Получает **копии** (не симлинки) `BRIEF.md` /
  `JUDGE_BRIEF.md` / `raw/` / анонимизированных
  `submissions/{A,B,C}/`. Симлинки внутрь sandbox-allowlist'а CLI
  не работают — баг #1 из reproxy/arena.
- `_mapping.json` (A→claude, B→codex, ...) живёт **только** на
  хосте, в контейнеры не прокидывается.

Детали — `docs/orchestration.md`.

## Дальше — детали

- `README.md` — TL;DR для пользователя.
- `HOWTO.md` — длинное описание механики и lessons learned. Там
  ещё всплывает host-mode (легаси v0.1 фоллбек) — игнорируй,
  целевой режим docker.
- `docs/setup-new-cook.md` — пошагово: как сделать новый cook.
- `docs/orchestration.md` — compose-устройство, сети, mounts,
  argv per flavor, что в каком контейнере крутится.
- `docs/auth.md` — подписочная авторизация в контейнерах без
  API-ключей.
- `docs/pitfalls.md` — грабли из reproxy/arena.
- `docs/implementation-status.md` — что уже работает в коде, что
  нужно дописать (если `multivarka cook --docker` сейчас падает с
  "not implemented" — это сюда).
