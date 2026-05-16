# multicooker — HOWTO (the long version)

Подробное описание того, как multicooker работает, что она делает,
почему именно так, и какие правила нельзя нарушать. Если ты хочешь
просто запустить — см. [README.md](README.md). Этот файл — для
понимания внутренностей и для расширения.

## Содержание

1. [Зачем это вообще](#зачем-это-вообще)
2. [Mental model](#mental-model)
3. [Структура папки `cook`](#структура-папки-cook)
4. [Что происходит в `multicooker cook`](#что-происходит-в-multicooker-cook)
5. [Что происходит в `multicooker judge`](#что-происходит-в-multicooker-judge)
6. [Правила (которые легко нарушить)](#правила-которые-легко-нарушить)
7. [Docker-mode (единственный)](#docker-mode-единственный)
8. [Авторизация и стоимость](#авторизация-и-стоимость)
9. [Что делать, когда что-то сломалось](#что-делать-когда-что-то-сломалось)
10. [Расширения и следующие шаги](#расширения-и-следующие-шаги)
11. [Уроки из reproxy/arena](#уроки-из-reproxyarena)

---

## Зачем это вообще

Иногда задача недоопределена настолько, что одного "правильного"
решения не существует. Хочется посмотреть, как разные LLM
интерпретируют её и что из этого выйдет — не столько чтобы
"объявить победителя", сколько чтобы получить **корпус из 3+
расходящихся решений** одной и той же задачи. Это даёт:

- идеи, которые ты бы сам не придумал;
- понимание, в чём LLM согласны, а в чём расходятся (расхождения
  обычно подсвечивают, где задача недоопределена);
- честный, за пределами маркетинга, sanity-check, кто из моделей
  лучше справляется именно с твоим типом задач.

Прародитель — `reproxy/arena/` (теперь на бранче `archive/arena`),
который гонял claude/codex/gemini в трёхраундовом турнире над
сетевыми сценариями и из этого собрался релиз v0.1.0. Из того опыта
выжаты уроки, описанные в конце.

## Mental model

```
                          one task
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         ┌────────┐      ┌────────┐      ┌────────┐
         │ claude │      │ codex  │      │ gemini │      ← parallel, isolated
         │ /work/ │      │ /work/ │      │ /work/ │
         └───┬────┘      └───┬────┘      └───┬────┘
             │ raw/ (read-only, shared)      │
             └────────────┬───────────────────┘
                          ▼
                   sealed snapshots
                          │
              ┌───────────┴────────────┐
              ▼                        ▼
         ┌────────┐              ┌────────┐
         │ judge  │              │ judge  │           ← scoring panel
         │ claude │              │ gemini │             (anonymized A/B/C)
         └───┬────┘              └───┬────┘
             │                       │
             └─────────┬─────────────┘
                       ▼
                 leaderboard.md
```

Ключевые свойства:

1. **Параллельность.** Все участники работают одновременно (потоки на
   хосте, или контейнеры в docker-mode). Никто никого не ждёт.
2. **Изоляция.** Каждый видит только свою папку `work/<имя>/` плюс
   общую `raw/` (read-only). Друг друга — нет.
3. **Анонимизация судьи.** Судье участники приходят как `A`, `B`,
   `C`, ... — он не знает, какая модель что написала. Маппинг
   восстанавливается только в финальном отчёте.
4. **Антисамосуд.** Если судья той же flavor, что и какой-то участник,
   multicooker печатает WARN (но судит). Анонимизация уже частично
   снимает bias; для жёсткой изоляции добавь судью третьей flavor
   (например ещё codex-judge), которой нет среди участников.

## Структура папки `cook`

После `multicooker new my-task`:

```
cooks/my-task/
├── BRIEF.md             # ты сюда пишешь задачу для участников
├── brief.yaml           # участники, таймауты, рубрика
├── JUDGE_BRIEF.md       # инструкции судье + рубрика
├── raw/                 # ты сюда кладёшь справочники
│   └── .gitkeep
└── work/                # рабочие папки участников (создаются пустыми)
    ├── claude/
    ├── codex/
    └── gemini/
```

После `multicooker cook my-task` добавляются:

```
cooks/my-task/
├── RUN.json                          # метаданные запуска
├── RUN_RESULT.json                   # статусы участников
├── work/<p>/BRIEF.md                 # симлинк на ../../BRIEF.md
├── work/<p>/raw/                     # симлинк на ../../raw
├── work/<p>/out/                     # сюда участник пишет результат
├── logs/<p>/<flavor>.stdout.log      # сырой stdout CLI
└── logs/<p>/<flavor>.stderr.log      # сырой stderr CLI
```

После `multicooker judge my-task`:

```
cooks/my-task/judging/
├── _inbox/<p>/                       # замороженная копия work/<p>/
├── _judge_input/                     # анонимизированный вход для судей
│   └── submissions/{A,B,C}/
├── _logs/<judge-name>/               # CLI-логи судьи
├── _mapping.json                     # A→claude, B→codex, ...
├── <judge-name>/scores.json          # сырые оценки (по A/B/C)
├── <judge-name>/scores_deanon.json   # с раскрытыми именами
└── <judge-name>/review.md            # текстовое обоснование
```

После `multicooker report my-task`:

```
cooks/my-task/leaderboard.md
```

## Что происходит в `multicooker cook`

Псевдокод:

```python
for participant in brief.participants:
    setup work/<participant>/                 # папка + симлинк BRIEF.md + симлинк raw/
    spawn thread:
        run host CLI(<flavor>) in work/<participant>/ with prompt = brief
        capture stdout/stderr to logs/<participant>/
        on rate-limit: record evidence, return (don't sleep — другие работают)
        on success/timeout: copy work/<participant>/ → judging/_inbox/<participant>/
join all threads
write RUN_RESULT.json
```

Конкретные технические нюансы:

### Stagger при старте
Между запуском участников 2-секундная пауза. Иначе все три CLI
одновременно дёргают auth-refresh, и Keychain под нагрузкой может
ответить ошибкой.

### Rate-limit handling
Каждый CLI имеет свои паттерны "ты упёрся в лимит" (см.
`multicooker/runner_common.py:_RL_PATTERNS`). Если они находятся в хвосте
stdout/stderr — участник помечается `rate_limited` со ссылкой на
конкретную evidence-строку. **Не блокируем других** — у claude и
gemini лимиты независимые, codex может умереть, claude и gemini
закончат нормально.

### macOS sleep detection
На маке `caffeinate -dimsu -w <pid>` блокирует засыпание системы пока
CLI работает. Но если ноут на закрытой крышке — caffeinate не
помогает. Тогда сравниваем `time.time()` (wall) и
`time.monotonic()` (на macOS пауза при сне) и если разница > 60с —
считаем, что ноут спал, и одну попытку повторяем (API-соединения
почти наверняка порвались).

### Argv-порядок
Один из багов arena: claude CLI имеет вариативный `--add-dir`,
который съедает позиционный prompt как ещё один path. Поэтому
**промпт идёт ПЕРЕД `--add-dir`**:

```bash
claude --print "<prompt>" --add-dir /work
```

а не

```bash
claude --add-dir /work --print "<prompt>"   # ←  prompt теряется
```

Это запечено в `templates/cook/participants/claude/entrypoint.sh` —
канонический порядок argv per flavor см. в `docs/orchestration.md`.

### Выходной "контракт"
Участник должен положить результат под `./out/`. Это конвенция,
прописанная в шаблонном промпте. Судья смотрит туда же.
Если участник проигнорировал и накидал файлы в корень — судья всё
равно их увидит (он видит весь worktree, кроме симлинков).

## Что происходит в `multicooker judge`

```python
participants = brief.participants
mapping = {A: claude, B: codex, C: gemini} (random shuffle)
copy each work/<participant>/ → _judge_input/submissions/<letter>/
for judge in brief.judges:
    warn if judge.flavor == any participant.flavor   # anti-self-judge (advisory only)
    copy JUDGE_BRIEF.md + raw/ + submissions/ into a fresh _work-<judge>-XXX/
    run host CLI(<judge.flavor>) in that work-dir
    expect ./outbox/scores.json + ./outbox/review.md
    deanonymize scores using mapping
    write deanon to judging/<judge-name>/scores_deanon.json
```

### Почему симлинки в judge work-dir — нельзя
Главный баг arena #1: судья получал `./inbox` и `./outbox` симлинками
на реальные папки. CLI-сэндбоксы (`claude --add-dir <work>`)
разрешают чтение/запись только внутри своего work-dir. Симлинк
ведущий наружу — резолвится в путь, который не в allowlist, и
Read/Bash/Write **тихо** отказывают. В итоге 97% оценок были
плейсхолдерами.

Решение: **никаких симлинков**. JUDGE_BRIEF.md, raw/, submissions/
**копируются** в work-dir судьи (не симлинкаются). После прогона
содержимое `work/outbox/` копируется обратно в
`judging/<judge-name>/`.

### Почему анонимизация важна
Если судья видит "submission claude/" — claude-судья будет
склоняться оценивать "своего" выше (или, наоборот, занижать,
пытаясь компенсировать). Анонимизация вместе с anti-self-judge
правилом убирают самые грубые источники предвзятости.

Стоит понимать: **полностью предвзятость не убирается**. Стиль кода
у claude vs gemini узнаваем. Если хочешь сильнее — добавь третьего
судью (любой anti-bias выигрывает от большего N), и/или попроси
agent-обёртку перефразировать выходы перед судом (не реализовано в
v0.1, в TODO).

## Правила (которые легко нарушить)

1. **Не давай судье читать stderr.log участника.** В stderr CLI
   часто кладёт что-то вроде "Claude is thinking..." — мгновенный
   деанон. У нас в judging/_inbox/ кладётся **только work-tree
   участника**, без logs/.

2. **JUDGE_BRIEF.md и BRIEF.md должны иметь одинаковую рубрику.**
   Если ты добавишь измерение в BRIEF.md и забудешь про
   JUDGE_BRIEF.md, судья будет оценивать не то, что обещал брифу.

3. **Не редактируй work/<p>/ после cook.** Если хочешь "помочь"
   участнику — это уже не его результат. Если хочешь дать всем
   подсказку — обнови BRIEF.md или raw/, и cook заново.

4. **raw/ — read-only по соглашению.** Технически файловая система
   позволяет участнику туда писать (мы используем симлинк). Не
   доверяй: если задача чувствительная, после cook сделай
   `diff -r raw/ <expected>/` и убедись, что участник её не
   изменил. Или установи на raw/ chmod 555 перед cook.

5. **API-лимиты непредсказуемы.** Не запускай overnight cook без
   `RUN_RESULT.json` поста-обработки. Утром проверь: были ли
   `rate_limited` участники? Если да, и они тебе важны — резерв
   на резапуск (не реализован в v0.1: запускай руками после
   восстановления квоты).

## Docker-mode (единственный)

Начиная с v0.2 multicooker работает только в docker-mode. Host-mode
и `host_runner.py` удалены — если что-то ломалось без них, чинится
в docker-mode.

- Каждый участник и каждый судья — собственный контейнер на
  собственной bridge-сети (`net-participant-<name>` /
  `net-judge-<name>`). Inter-container DNS/IP-видимости в одном
  cook'е нет.
- Egress в интернет открыт. Sandbox — это контейнер, не сеть.
  Если конкретный cook требует жёсткий allowlist — кладёшь
  локальный `compose.override.yaml`.
- Подписочные креды (Claude Pro / ChatGPT Plus / Gemini Advanced)
  снапшотятся в `cooks/<task>/.auth/<flavor>/` (mode `0600`,
  `.gitignore`) и bind-mount'ятся RO в соответствующий контейнер.
  **API-ключей не нужно**, и silent-fallback на API-ключ не
  предусмотрен. См. `docs/auth.md`.
- Permission-bypass флаги (`--dangerously-skip-permissions`,
  `--yolo`, `--dangerously-bypass-approvals-and-sandbox`) внутри
  контейнера обязательны: без них CLI зависают на
  approval-промптах. Безопасны, потому что контейнер их сдерживает.
- Shared base images (`mc-base-<flavor>:latest`) ставят тяжёлое
  (`npm i -g <cli>`), а cook-Dockerfile укорочен до
  `FROM mc-base-<flavor>` + entrypoint. Build cook-образа ~1 сек
  вместо 2-3 мин. `multicooker build-base` собирает руками; cook /
  refine / judge сами зовут `base_images.ensure_built()`, поэтому
  для пользователя это прозрачно.

Threat model и что именно защищает контейнер: см.
[`docs/security.md`](docs/security.md).

## Авторизация и стоимость

### Подписки
- Только подписочная авторизация: Claude Pro $20/м, ChatGPT Plus
  $20/м, Gemini Advanced $20/м. Достаточно для нескольких задач в
  день; лимиты низкие — типичный cook на 3 участника гоняет
  ≈ 30k–200k токенов на каждого.
- API-ключи не используются и **не подключаются как fallback**: если
  подписочный creds недоступен, `multicooker doctor` / `cook` падают
  явно с remediation-сообщением, а не уходят молча на платный API.

### Бюджет на cook
Рассчитывается грубо:

```
участники × токены_на_участника × $/токен
+ судьи × токены_на_судью × $/токен
```

Для типичной "напиши эссе на 2 страницы" задачи: ~$0.30–$1.50.
Для "перепиши вот этот репозиторий": ~$5–$30 (зависит от размера).

В v0.1 нет cost-tracker. Если нужно — смотри prompt+completion
в логах подписочного CLI или в API-ledger. В v0.2 хочется
автоматический ledger (одна из TODO).

## Что делать, когда что-то сломалось

### "claude CLI not in PATH"
```
brew install claude-code     # или официальный установщик anthropic
```
Аналогично `codex` и `gemini`. Если не нужен какой-то участник —
удали его из `brief.yaml` перед cook.

### "судья не написал scores.json"
Смотри `cooks/<name>/judging/_logs/<judge>/<flavor>.stdout.log`.
Самое частое:
- судья сам уперся в rate-limit;
- судья счёл задачу слишком ambiguous и попросил уточнений
  (читается в его выводе);
- судья наткнулся на симлинк-баг (не должно случаться с этой
  версией судьи — мы копируем, не симлинкуем).

### "оценки выглядят случайными"
Чаще всего рубрика непонятна судье. Перечитай свой
`JUDGE_BRIEF.md` глазами незаинтересованного человека. Если в
дименшнах прописано "quality" без определения — судья ставит
наугад. Чем конкретнее формулировка ("did the answer reference
all 3 source documents?"), тем стабильнее оценки.

### "claude занял всё CPU"
Каждый CLI многопоточный сам по себе. Три параллельных claude'а
могут забить ноут. Снизь параллелизм:
```yaml
participants:
  - name: claude
    flavor: claude
  # codex и gemini закомментированы; запусти в две очереди
```
В v0.2 хочется флаг `--max-parallel N`.

## Refine: round N+1 поверх предыдущего результата

Не каждая задача решается в один раунд. `multicooker refine <task>`
прогоняет ещё один раунд поверх предыдущего output'а:

- Каждый участник видит свой прошлый `./out/` **на месте, RW** —
  редактирует/заменяет/расширяет.
- Перед запуском прошлый раунд снапшотится в `rounds/<N>/<p>/`
  (immutable history), плюс sealed `judging/_inbox/` копируется в
  `rounds/<N>/_inbox/`.
- Inline в `PROMPT.txt` подставляются:
  - **shared feedback** из `cooks/<task>/FEEDBACK.md` (общий
    review для всех);
  - **personal feedback** из `cooks/<task>/FEEDBACK_<flavor>.md`
    (опционально, адресовано конкретному участнику).
- `--participants <list>` позволяет refine'ить подмножество.
- `--feedback <path>` подменяет источник shared feedback'а на
  произвольный файл — удобно, когда один фидбек применяется к
  нескольким cook'ам.
- `multicooker diff <task> N M` показывает unified diff между
  раундами по каждому участнику — sanity-check, что refine реально
  что-то поменял.

Артефакты раунда: `REFINE_<N>.json` (метаданные старта),
`REFINE_<N>_RESULT.json` (status + duration + rate-limit info per
participant). Полный lifecycle артефактов — в
[`docs/lifecycle.md`](docs/lifecycle.md).

После refine ожидаем тот же шаг judging'а:
`multicooker judge <task>` → `multicooker report <task>`.

### `multicooker rejudge <task>`

Отдельная команда: пере-судить **тот же** snapshot без повторного
cook'а. Полезно когда правил `JUDGE_BRIEF.md` (рубрика, веса) или
вручную поправил `out/<p>/RESULT.md`. Делает три вещи:

1. Пере-сильит `judging/_inbox/<p>/` из текущего `work/<p>/out/`
   (важно — обычный `judge` использует уже сильнутый inbox и
   правки в `out/` пропустит).
2. Чистит `judging/<judge>/` outbox'ы прошлых судей.
3. Зовёт обычный `judge` flow (фрэшная анонимизация — `_mapping.json`
   всегда пере-генерится, anti-bias guarantee не ослабляем).

Параметры: `--judges` (как у `judge`).

Каждый запуск участника также пишет `work/<p>/trace.json` с
`{prompt, model, exit_code, duration_s, started_at, status}` —
дешёвый структурированный артефакт для debugging'а и для будущих
replay-сценариев. Полная structured-trace версия (tool calls)
отложена — см. `docs/design-notes.md`.

## Расширения и следующие шаги

Что осталось в TODO (см. `docs/todo.md` для актуального списка):

1. **Cost ledger** — на каждый запуск парсим usage из CLI и пишем
   `cook/cost_ledger.json`.
2. **Resume** — `multicooker resume <name>` повторяет только
   `rate_limited` или `error` участников, не трогая `ok`.
3. **Per-participant timeout** (сейчас глобальный `timeout_s`).
4. **`multicooker diff <task> N M`** — сравнение раундов.
5. **Replayable traces / registry** — структурированный run trace,
   versioned task specs (идеи из agentevals / OpenAI Evals).
6. **Web report** — `multicooker serve <name>` показывает HTML с
   diff-ами между submissions, judging logs, leaderboard'ом.
7. **Cross-cook leaderboard** — глобальная таблица "claude
   выигрывает в 7 из 10 задач, codex в 2, gemini в 1".

## Уроки из reproxy/arena

Что overnight runs научили нас не делать:

- **Variadic CLI flags ВСЕГДА съедают позиционные args.** `claude`
  с `--add-dir <wt>` после prompt-а оставляет prompt висеть на
  stdin → 0 байт diff → "0/100 на correctness". Решение: prompt
  ПЕРЕД переменными флагами.
- **Symlinks внутрь sandbox-allowlist'а.** Не работают. CLI видит
  путь, который резолвится наружу, тихо отказывает, никаких
  ошибок — только пустой outbox. Решение: никогда не симлинкуем
  в work-dir, который мы передаём в CLI с `--add-dir`. Только
  copy.
- **Codex quota перерасход.** OpenAI ChatGPT Plus квота раз в
  ~5 часов кончалась посреди раунда → один из трёх "обнулялся".
  Решение: смириться (нельзя обойти) и в orchestrator-е сделать
  per-participant deferred-retry, чтобы остальные не блокировались.
- **Не доверять exit-code.** Многие CLI возвращают 0 даже когда
  упёрлись в лимит, потому что они "успешно сообщили о лимите".
  Решение: всегда парсить stderr на known-bad patterns.
- **Не пишите markdown-handover для CLI, ожидая что он его
  прочтёт.** Прочтёт. Но не учтёт. Если хочешь, чтобы участник
  изменил поведение — пиши это в **prompt**, не в файл.
- **Sleep mid-run на маке.** Connection drops к Anthropic API ←
  закрытая крышка. caffeinate не всегда помогает. Решение —
  retroactive detection через wall-vs-monotonic skew + одна
  попытка retry.
- **Не верь leaderboard'у первого запуска.** Reproxy-arena
  overnight #1 показал gemini > codex > claude. После починки
  argv-бага и judge-симлинков порядок изменился. Только после
  смоук-теста и второго прогона цифры были осмысленными.
- **Артефакты съедают диск быстро.** Reproxy-arena: 4.3 ГБ за два
  overnight'а. В multicooker артефакт = только `cook/<name>/`,
  без снапшотов раундов; лимит низкий, но привычка очищать
  старые cooks полезна.
