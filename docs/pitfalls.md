# Pitfalls: грабли из reproxy/arena

Это перенос lessons learned из ночных запусков reproxy-arena. Все
эти баги мы уже один раз ловили — экономь время, не лови повторно.

## #1. Симлинки внутрь sandbox-allowlist'а CLI — не работают

CLI-сэндбоксы (`claude --add-dir <dir>`, `codex --sandbox
workspace-write`) разрешают чтение/запись только внутри указанной
папки. **Если внутри папки лежит симлинк, ведущий наружу — путь
рассольвится в "наружу" и Read/Write/Bash тихо откажут.** Никаких
ошибок, просто пустой результат.

В arena-judge'е это вылезло так: судья получал `./inbox` и
`./outbox` симлинками — 97% оценок оказались плейсхолдерами.

**Правило:** в сэндбокс CLI монтируем **только реальные пути**, без
симлинков. Если нужно "показать" файл — копируем (`cp`), не
симлинкуем. Это особенно важно в `judge`: материалы в work-dir'е
судьи всегда копируются.

## #2. Variadic argv flags съедают позиционный prompt

```bash
# СЛОМАНО:
claude --add-dir /work --print "prompt"
# claude трактует "prompt" как ещё один path для --add-dir,
# stdin пустой, выход 0 байт.

# ПРАВИЛЬНО:
claude --print "prompt" --add-dir /work
```

То же бывает у codex и gemini — порядок argv проверь по
`reproxy/arena/coding-sandbox/host_runner.py:CLI_COMMANDS`. Это
эталон.

## #3. exit-code = 0 ≠ всё хорошо

Все три CLI (claude, codex, gemini) возвращают 0 даже когда
упёрлись в rate-limit, потому что они "успешно сообщили о лимите".
Если ориентироваться на exit-code, ты пометишь rate-limited cell как
успешный.

**Правило:** всегда парси stderr на known-bad patterns. Шаблоны —
в `multicooker/host_runner.py:_RL_PATTERNS`, наследие из arena.

## #4. Codex quota раз в ~5 часов

OpenAI ChatGPT Plus квота обычно ресетится раз в ~5 часов. Codex
посреди cook'а часто умирает, остальные участники не должны
блокироваться.

**Правило:** rate-limit одного участника = `deferred`-флаг для
этого слота, остальные продолжают. Никаких inline-sleep'ов.
Resume — отдельный flow (`multicooker resume <task>`, в TODO для
v0.2).

## #5. Не верь leaderboard'у первого запуска

reproxy-arena overnight #1 показал gemini > codex > claude. После
починки argv-бага и judge-симлинков порядок изменился. Если
смоук-тест не зелёный — leaderboard ничего не значит.

**Правило:** прежде чем верить результатам, убедись:
- работают ли все три CLI базово (`out/RESULT.md` непуст);
- судья написал `scores.json` с реальными числами, а не
  плейсхолдерами;
- mapping A↔flavor рандомизирован per-run, а не закэширован.

## #6. macOS sleep кладёт API-коннекты

Закрытая крышка → `caffeinate -dimsu` иногда не помогает (clamshell
mode без внешнего питания) → коннекты к Anthropic API рвутся.
Симптом: участник вышел рано с какой-то transient-ошибкой.

**Правило:** wall-clock vs monotonic skew > 60s = ноут спал.
Одна попытка retry. Логика — в arena `host_runner.py`. Для cook
в контейнере это работает иначе (Docker сам должен переподключиться
после wake), но wall-clock детектор не помешает.

## #7. Артефакты съедают диск

reproxy-arena: 4.3 GB за две ночи. У multicooker артефакт = только
`cooks/<task>/`, без снапшотов раундов, лимит ниже. Но привычка
чистить старые cook'и полезна:

```bash
find cooks/ -maxdepth 1 -type d -mtime +30 -name '[!_]*' -print
# review → delete → пересобрать leaderboard если нужно
```

## #8. Stagger при старте параллельных CLI

Если поднять три CLI одновременно — они одновременно дёргают auth
refresh. Keychain (для claude на хосте) или OAuth refresh-эндпоинты
(для codex/gemini) под нагрузкой могут вернуть transient-ошибку.

**Правило:** 2-секундный stagger между запусками. Унаследовано из
`multicooker/host_runner.py:run_all`.

## #9. Не пиши markdown-инструкции вместо промпта

Если положишь "не делай X" в `BRIEF.md` — участник прочтёт, но не
обязательно учтёт. **Если что-то критично для оценки — это идёт в
prompt, а не в файл.** В multicooker prompt контейнера = "Read
/work/BRIEF.md and complete the task" + опционально hard rules.
Hard rules дописывай в `Dockerfile.cmd` или в обёртку, не в
`BRIEF.md`.

## #10. Рубрики между BRIEF и JUDGE_BRIEF расходятся

Самый частый "оценки рандомные" — рубрика в `JUDGE_BRIEF.md` не
синхрона с тем, что обещано в `BRIEF.md`. Чек: после правки одного
открой второй и убедись, что dimensions совпадают по id, весу, и
шкале.

## #11. stderr участника содержит флаги его flavor

`claude` в stderr пишет "Claude is thinking..." и т.п. Если эти
логи попадут судье — анонимизация лопнула. **Правило:** в
`judging/_inbox/<p>/` копируем **только worktree** участника, без
`logs/`.
