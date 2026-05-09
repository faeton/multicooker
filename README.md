# multivarka

Запускает несколько LLM-агентов (`claude`, `codex`, `gemini`)
параллельно решать одну задачу — каждого в своём docker-контейнере,
со своей подписочной авторизацией — а потом судьи (тоже LLM-агенты)
сравнивают результаты и выставляют оценки.

> «Мультиварка»: одна задача, несколько блюд готовятся параллельно в
> своих чашах.

## Зачем

Бывают задачи, которые недоопределены настолько, что одного
«правильного» ответа не существует. Хочется посмотреть, как разные
модели интерпретируют один и тот же brief, на чём расходятся, что
каждая считает важным. Мультиварка даёт корпус из N расходящихся
решений + структурированное сравнение, **без счетов за API**: она
ходит через твой `Claude Pro` / `ChatGPT Plus` / `Gemini Advanced`.

## Требования

- macOS или Linux хост с запущенным **Docker Desktop / colima**.
- Python 3.10+.
- Хотя бы одна из CLI: `claude` (`claude /login`), `codex`
  (`codex` для входа), `gemini` (`gemini` для входа). Только те
  flavor'ы, которые реально хочешь гонять.

Если хочется попробовать pipeline без подписочных кредов — есть
flavor `dummy`. См. [`examples/hello-task`](examples/hello-task/).

## Установка

```bash
git clone https://github.com/faeton/multivarka
cd multivarka
pip install -e .
```

## Первый запуск (за 5 минут)

```bash
# 1. Preflight — docker, compose, креды для каждого flavor
multivarka doctor

# 2. Скаффолд (имя автоматически префиксится датой → 260509-my-task)
multivarka new my-task

# 3. Описать задачу
cd cooks/260509-my-task
$EDITOR BRIEF.md          # что должны сделать участники
$EDITOR JUDGE_BRIEF.md    # как судьи будут оценивать
$EDITOR brief.yaml        # участники, судьи, таймаут, рубрика
cp ~/some-reference.* raw/   # справочники (mount RO в контейнер)

# 4. Cook — все участники параллельно, каждый в своём контейнере
multivarka cook 260509-my-task

# 5. Judge — анонимно: судьи видят только метки A/B/C
multivarka judge 260509-my-task

# 6. Сводка → leaderboard.md
multivarka report 260509-my-task
cat cooks/260509-my-task/leaderboard.md
```

## Итерация поверх результата

```bash
$EDITOR cooks/260509-my-task/FEEDBACK.md          # общий фидбек
$EDITOR cooks/260509-my-task/FEEDBACK_claude.md   # перс. (опционально)

multivarka refine 260509-my-task    # round N+1 поверх предыдущего out/
multivarka judge  260509-my-task
multivarka report 260509-my-task
```

Прошлые раунды сохраняются в `rounds/<N>/`, ничего не теряется.

## Несколько участников одного flavor / разные модели

```bash
multivarka new comparison \
  --participants claude-a=claude,claude-b=claude,codex,gemini
```

Per-participant модель — в `brief.yaml`:

```yaml
participants:
  - { name: claude-sonnet, flavor: claude, model: claude-sonnet-4-6 }
  - { name: claude-opus,   flavor: claude, model: claude-opus-4-7 }
  - { name: codex }
```

## Как это устроено (кратко)

- Один docker compose project на cook (`mv-<task>`).
- Каждый участник — свой контейнер на своей bridge-сети
  (`net-participant-<name>`); они не видят друг друга по DNS/IP.
- Подписочные креды снапшотятся в `cooks/<task>/.auth/<flavor>/`
  (mode `0600`, в `.gitignore`) и bind-mount'ятся RO только в
  соответствующий контейнер.
- После cook'а sealed `out/` анонимизируется в `A/B/C/…` перед
  судейством. Маппинг `A↔flavor` живёт только на хосте, в
  контейнеры судей не попадает.
- Egress в интернет открыт. Sandbox — это контейнер, не сеть.
  Threat model: [`docs/security.md`](docs/security.md).

Длинная версия: [`HOWTO.md`](HOWTO.md). Внутренности:
[`docs/orchestration.md`](docs/orchestration.md),
[`docs/auth.md`](docs/auth.md), [`docs/lifecycle.md`](docs/lifecycle.md).

## Команды

| Команда | Что делает |
|---|---|
| `multivarka new <task> [--participants ...]` | Создать cook из шаблонов. |
| `multivarka doctor [<task>]` | Preflight: docker, compose, creds, Dockerfile-ы, base images. |
| `multivarka build-base [<flavor>...]` | Собрать shared base-образ (автоматически собирается перед первым cook'ом). |
| `multivarka cook <task>` | Запуск всех участников параллельно. |
| `multivarka refine <task>` | Round N+1 с feedback'ом поверх предыдущего out. |
| `multivarka judge <task>` | Анонимизированное судейство всеми judge'ами. |
| `multivarka report <task>` | Свод в `leaderboard.md`. |
| `multivarka add-participant <task> NAME[=FLAVOR]` | Расширить cook новым участником. |
| `multivarka clean [<task>] [--all]` | `compose down -v --rmi local` + удалить `.auth/`. |

## Статус

`v0.2`. Протестировано на macOS + Docker Desktop. На Linux должно
работать; `claude` creds на darwin берутся из Keychain, на Linux —
из `~/.claude/.credentials.json`.

Баги → GitHub issues. Безопасность: [`SECURITY.md`](SECURITY.md).

## Лицензия

[MIT](LICENSE).
