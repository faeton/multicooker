# Setup: новая cook

Пошагово — как поднять новую задачу в мультиварке. Все команды
выполняются из корня репо `~/Sites/multivarka/`.

## 0. Предусловия

- Docker Desktop / Orbstack / Colima запущен.
- Один раз выполнен флоу из `docs/auth.md` (creds для всех flavor'ов
  доступны в контейнерах).
- `pip install -e .` выполнен в репо.

## 1. Скаффолд папки

```bash
multivarka new my-task
```

Создаёт `cooks/my-task/` копированием `templates/cook/`:

```
cooks/my-task/
├── BRIEF.md             # ты сюда пишешь задачу
├── brief.yaml           # участники, таймауты, рубрика
├── JUDGE_BRIEF.md       # инструкции судье + рубрика
├── raw/                 # ты сюда кладёшь справочники
├── participants/        # Dockerfile per flavor (унаследовано из templates/)
│   ├── claude/Dockerfile
│   ├── codex/Dockerfile
│   └── gemini/Dockerfile
└── judge/               # Dockerfile судьи (per flavor)
```

`work/` и `judging/` создадутся при `cook` / `judge`.

## 2. BRIEF.md

Шаблон уже подсказывает структуру. Минимально:

- **Goal** (1 параграф) — что делаем.
- **Inputs** — `BRIEF.md` сам, `raw/` (RO), опционально
  `raw/CONTEXT.md`.
- **Output** — что должно лежать в `/work/out/` (всегда есть
  `RESULT.md`, плюс артефакты при необходимости).
- **Constraints** — таймаут, отсутствие сети кроме API.
- **Success criteria** — рубрика. Эти же измерения должны быть в
  `JUDGE_BRIEF.md`.

Двусмысленность в постановке — нормально, на ней расходятся
участники. Двусмысленность в success criteria — баг.

## 3. brief.yaml

```yaml
name: my-task
timeout_s: 1800            # на участника
judge_timeout_s: 900       # на судью

participants:
  - {name: claude, flavor: claude}
  - {name: codex,  flavor: codex}
  - {name: gemini, flavor: gemini}

judges:
  - {name: claude-judge, flavor: claude}
  - {name: gemini-judge, flavor: gemini}

rubric:
  scale: [0, 5]
  dimensions:
    - {id: correctness,  weight: 40}
    - {id: quality,      weight: 25}
    - {id: honesty,      weight: 20}
    - {id: completeness, weight: 15}
```

Anti-self-judge: если судья той же `flavor`, что один из участников
— мультиварка печатает WARN. Хочешь жёстко — добавь третью flavor
в судьи и убери совпадающую.

## 4. JUDGE_BRIEF.md

Тот же rubric, что в `brief.yaml`, с описанием каждого dimension и
схемой `scores.json`. Если правишь рубрику — правь оба файла.

## 5. raw/

Кладёшь PDF, CSV, образцы, чужие репозитории. Всё это монтируется
read-only в `/work/raw/` каждому участнику. Никогда не клади сюда
секреты — участник может это прочитать.

## 6. Кастомные тулы в контейнере

Если задаче нужны `tshark`, `pandas`, компилятор Go и т.д. — правишь
**Dockerfile в этом cook**, не в `templates/cook/`. Причина: cook'и
независимы, новые задачи не должны утяжелять шаблон.

## 7. Запуск

```bash
multivarka cook   my-task     # параллельно поднимет N контейнеров
multivarka judge  my-task     # анонимизирует и запустит судей
multivarka report my-task     # напишет cooks/my-task/leaderboard.md
```

Между `cook` и `judge` можешь посмотреть `cooks/my-task/work/<p>/out/`
— что вышло у участников до анонимизации.

## 8. Что не делать

- Не правь `cooks/my-task/work/<p>/` после `cook` — это уже не его
  результат. Хочешь дать подсказку — обнови `BRIEF.md` / `raw/` и
  перезапусти cook.
- Не клади артефакты вне `cooks/<task>/`. Cross-cook сравнение —
  это будущая фича, сейчас её нет.
- Не пытайся отдать судье `stderr.log` участника — там ловятся
  фразы вроде "Claude is thinking" и весь смысл анонимизации
  теряется.
