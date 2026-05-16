# multicooker

Запускает несколько LLM-агентов (`claude`, `codex`, `gemini`)
параллельно решать **одну и ту же задачу** — каждого в своём
docker-контейнере, со своей подписочной авторизацией — а потом
другие LLM-агенты читают результаты вслепую (под метками `A`/`B`/`C`),
выставляют оценки по твоей рубрике и пишут review.

На выходе — `leaderboard.md` + корпус из N расходящихся решений
одной задачи. **Без счетов за API**: ходит через твой `Claude Pro`
/ `ChatGPT Plus` / `Gemini Advanced`.

> «multicooker»: одна задача, несколько блюд готовятся параллельно
> в своих чашах; ты сравниваешь, что у кого получилось.

## Зачем это

Когда задача недоопределена — дизайн, написание текста, рефакторинг
с архитектурным выбором, ревью — у неё нет одного «правильного»
ответа. Любая модель что-то достроит из брифа сама, и **что именно**
она достроит — это и есть интересное. Один прогон через одну
модель этого не показывает; ты видишь только её интерпретацию и
думаешь, что это и есть «решение».

multicooker даёт **корпус расходящихся интерпретаций** одного и
того же брифа за один заход. Полезно когда:

- Выбираешь между моделями для повторяющейся задачи (рефакторинг,
  дизайн, написание докуминтации, code-review) и устал решать на
  вибе.
- Хочешь увидеть, где бриф недоопределён — расхождения между
  моделями подсвечивают именно эти места.
- Делаешь дизайн или копирайт и хочешь три варианта от разных
  «голов» вместо одного.
- Изучаешь, насколько модели согласны друг с другом на открытых
  задачах (часто — не очень).

## Как это устроено (поток одного cook'а)

```
                     ┌─────────────────────────────┐
                     │      cooks/260516-task/     │
                     │  BRIEF.md  JUDGE_BRIEF.md   │
                     │  brief.yaml      raw/       │
                     └──────────────┬──────────────┘
                                    │ multicooker cook
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
 ┌─────────────┐             ┌─────────────┐             ┌─────────────┐
 │  claude     │             │  codex      │             │  gemini     │
 │  container  │   (parallel)│  container  │  (parallel) │  container  │
 │  net-A      │             │  net-B      │             │  net-C      │
 │  /work/...  │             │  /work/...  │             │  /work/...  │
 └──────┬──────┘             └──────┬──────┘             └──────┬──────┘
        │ out/                      │ out/                      │ out/
        └───────────────────────────┼───────────────────────────┘
                                    ▼
                       ┌─────────────────────────┐
                       │   anonymize → A/B/C     │
                       │   mapping stays on host │
                       └──────────────┬──────────┘
                                      │ multicooker judge
                ┌─────────────────────┼─────────────────────┐
                ▼                                           ▼
       ┌─────────────────┐                         ┌─────────────────┐
       │  judge-1        │                         │  judge-2        │
       │  (claude/codex/ │  scores everyone except │  (different     │
       │   gemini)       │  its own flavor         │   flavor)       │
       └────────┬────────┘                         └────────┬────────┘
                │ scores.json + review.md                   │
                └─────────────────────┬─────────────────────┘
                                      ▼ multicooker report
                            ┌──────────────────┐
                            │ leaderboard.md   │
                            └──────────────────┘
```

Ключевое:

- **Изоляция.** Каждый участник в своём контейнере на своей
  bridge-сети — не видит ни остальных участников, ни брифа судьи,
  ни маппинга `A↔flavor`.
- **Параллельность.** Все стартуют одновременно. Rate-limit
  одного не блокирует других.
- **Анонимизация.** Судья видит только `A` / `B` / `C` без
  упоминаний моделей. Маппинг живёт только на хосте.
- **Anti-self-judge.** Судья не оценивает submission своего же
  flavor'а — claude не судит claude'овский out.
- **Без API-ключей.** Подписочные креды (`Claude Pro` /
  `ChatGPT Plus` / `Gemini Advanced`) пробрасываются в контейнер
  через bind-mount или named volume, RO. См.
  [`docs/auth.md`](docs/auth.md).

## Установка

```bash
git clone https://github.com/faeton/multicooker
cd multicooker
pip install -e .
```

Требования:

- macOS или Linux хост с запущенным Docker Desktop / colima.
- Python 3.10+.
- Хотя бы одна из CLI: `claude` (`claude /login`), `codex`
  (`codex` для входа), `gemini` (`gemini` для входа). Только те
  flavor'ы, которые реально хочешь гонять.

Хочешь попробовать pipeline без подписочных кредов — есть flavor
`dummy`. См. [`examples/hello-task`](examples/hello-task/).

## Быстрый старт: агент сам соберёт cook (10 секунд)

Самый быстрый способ работать с multicooker — запустить
LLM-агента **внутри репозитория** и дать ему собрать и прогнать
cook за тебя. В репо лежит `CLAUDE.md` (и симлинк `AGENTS.md` для
codex / gemini), который уже объясняет любому агенту устройство
проекта, форму cook'а и правило что рубрика синхронизируется
между `brief.yaml` и `JUDGE_BRIEF.md`. Агент читает это и делает
рутинную часть за тебя.

```bash
git clone https://github.com/faeton/multicooker && cd multicooker
pip install -e .

claude        # или: codex, или: gemini — все читают AGENTS.md
```

Дальше просто опиши задачу словами:

> *«Собери cook `landing-redesign`. Сравни claude / codex / gemini
> на single-file HTML hero для [продукт]. Суди по visual-hierarchy,
> typography, color-discipline, content-fit, polish. Референсы —
> `~/work/brand/notes.md` и `~/work/brand/voice.md`. Потом запусти
> cook + judge + report.»*

Агент читает `CLAUDE.md` и `examples/design-landing/` как шаблон,
пишет `BRIEF.md` / `JUDGE_BRIEF.md` / `brief.yaml`, копирует твои
референсы в `raw/`, запускает `multicooker cook`, дожидается, потом
прогоняет `judge` и `report`. Ты читаешь leaderboard.

Итерация — тем же разговором:

> *«Общий фидбек: слишком много воздуха, ужми layout. Конкретно для
> `claude`: палитру оставь, но подтяни type scale. Refine.»*

Или — новый cook с теми же референсами (другая задача, те же
brand-assets):

> *«Референсы как в прошлом cook'е. Новый бриф: 3-кадровая
> onboarding-последовательность вместо одного лендинга. Суди те
> же dimensions плюс story-clarity. Запусти.»*

Это канонический workflow. Ручной режим ниже полезен чтобы
понять что под капотом, но повседневно ты так пользоваться не
будешь.

## Ручной режим (за 5 минут, полный контроль)

```bash
# 1. Preflight — docker, compose, креды для каждого flavor
multicooker doctor

# 2. Скаффолд (имя автоматически префиксится датой → 260509-my-task)
multicooker new my-task

# 3. Описать задачу
cd cooks/260509-my-task
$EDITOR BRIEF.md          # что должны сделать участники
$EDITOR JUDGE_BRIEF.md    # как судьи будут оценивать
$EDITOR brief.yaml        # участники, судьи, таймаут, рубрика
cp ~/some-reference.* raw/   # справочники (mount RO в контейнер)

# 4. Cook — все участники параллельно, каждый в своём контейнере
multicooker cook 260509-my-task

# 5. Judge — анонимно: судьи видят только метки A/B/C
multicooker judge 260509-my-task

# 6. Сводка → leaderboard.md
multicooker report 260509-my-task
cat cooks/260509-my-task/leaderboard.md
```

## Примеры

В репо два готовых примера, которые можно скопировать и запустить:

- **[`examples/hello-task`](examples/hello-task/)** — sanitized
  smoke-тест на `dummy` flavor, без LLM-кредов. ~10 секунд от
  старта до leaderboard'а. Полезно один раз прогнать, чтобы
  увидеть форму cook'а на самом простом примере.

- **[`examples/design-landing`](examples/design-landing/)** —
  настоящая design-задача: каждая модель рисует свой лендинг для
  `multicooker`. Три HTML-файла, которые ты потом сравниваешь
  в браузере. Подробнее ниже.

## Use case: дизайн и креативные задачи

Самое наглядное применение — задачи, у которых нет правильного
ответа, но есть критерии качества. Дизайн, копирайт, нейминг,
архитектурные эссе. Тут модели расходятся не из-за бага в одной
из них, а из-за разных «эстетических убеждений», и сравнение
становится содержательным.

`examples/design-landing` — рабочий шаблон такого cook'а. Бриф:
*«нарисуй лендинг для multicooker, single-file HTML, без сборки»*.
Что обычно видно когда открываешь три `index.html` рядом:

- **Палитра.** Одна модель приходит к строгому monochrome,
  другая накидывает шесть акцентных цветов и потом не знает что
  с ними делать, третья сидит на тёмной теме по умолчанию.
- **Типографика.** Кто-то берёт system stack, кто-то Inter с
  Google Fonts, кто-то оставляет `serif` — и hero-блоки от этого
  читаются совершенно по-разному.
- **Плотность.** Один пакует фичи в трёхколоночный grid с мелким
  текстом, другой делает один большой блок на пол-экрана.
- **Содержание.** Кто-то цитирует `raw/product.md` дословно,
  кто-то перепридумывает продукт под свои представления о
  «правильном лендинге» (и тут срабатывает dimension
  `content-fit` в рубрике).
- **Полировка.** Hover-state'ы, ритм отступов, code-block-styling,
  футер — мелкие решения, которые отличают «черновик» от
  «дочистил».

Рубрика в [`examples/design-landing/JUDGE_BRIEF.md`](examples/design-landing/JUDGE_BRIEF.md)
оценивает по `visual-hierarchy / typography / color-discipline /
content-fit / polish`. Два судьи разных flavor'ов оценивают
анонимно — и часто между собой не соглашаются. Это полезный
сигнал: на design-задачах судейское разногласие говорит, что
победителя «по очкам» нет, а есть три разных направления, и
выбирать надо глазами.

```bash
# Запуск design-примера (нужны claude/codex/gemini логины)
multicooker new landing --participants claude,codex,gemini
TASK=$(basename "$(ls -d cooks/*-landing | tail -1)")
cp examples/design-landing/{BRIEF.md,JUDGE_BRIEF.md,brief.yaml} cooks/$TASK/
cp examples/design-landing/raw/* cooks/$TASK/raw/

multicooker cook   $TASK
multicooker judge  $TASK
multicooker report $TASK

# Открыть все три варианта рядом и leaderboard
open cooks/$TASK/out/*/index.html
cat  cooks/$TASK/leaderboard.md
```

Адаптируется под любую дизайн-задачу: логотип в SVG, README-header,
email template, мокап dashboard'а — нужно только переписать
`BRIEF.md` под свой output и подкрутить dimensions в рубрике
(`brand-fit`, `accessibility`, `density`, `motion-restraint` —
любые, лишь бы совпадали между `brief.yaml` и `JUDGE_BRIEF.md`).
См. [`examples/design-landing/README.md`](examples/design-landing/README.md)
для подробной инструкции по адаптации.

## Итерация поверх результата

```bash
$EDITOR cooks/260509-my-task/FEEDBACK.md          # общий фидбек
$EDITOR cooks/260509-my-task/FEEDBACK_claude.md   # перс. (опционально)

multicooker refine 260509-my-task    # round N+1 поверх предыдущего out/
multicooker judge  260509-my-task
multicooker report 260509-my-task
```

Прошлые раунды сохраняются в `rounds/<N>/`, ничего не теряется.
`multicooker diff <task>` показывает, что подвинулось между
раундами на уровне файлов — полезно понять, какая модель
прислушалась к фидбеку, а какая просто перефразировала старый
вариант.

## Несколько участников одного flavor / разные модели

```bash
multicooker new comparison \
  --participants claude-a=claude,claude-b=claude,codex,gemini
```

Per-participant модель — в `brief.yaml`:

```yaml
participants:
  - { name: claude-sonnet, flavor: claude, model: claude-sonnet-4-6 }
  - { name: claude-opus,   flavor: claude, model: claude-opus-4-7 }
  - { name: codex }
```

Это позволяет сравнить, например, `sonnet` против `opus` на одной
и той же задаче — две лошадки одного flavor'а под разными именами,
с разной моделью.

## Изоляция и безопасность (коротко)

- Один docker compose project на cook (`mc-<task>`).
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
[`docs/auth.md`](docs/auth.md),
[`docs/lifecycle.md`](docs/lifecycle.md).

## Команды

| Команда | Что делает |
|---|---|
| `multicooker new <task> [--participants ...]` | Создать cook из шаблонов. |
| `multicooker doctor [<task>]` | Preflight: docker, compose, creds, Dockerfile-ы, base images. |
| `multicooker build-base [<flavor>...]` | Собрать shared base-образ (автоматически собирается перед первым cook'ом). |
| `multicooker cook <task>` | Запуск всех участников параллельно. |
| `multicooker refine <task>` | Round N+1 с feedback'ом поверх предыдущего out. |
| `multicooker judge <task>` | Анонимизированное судейство всеми judge'ами. |
| `multicooker rejudge <task>` | Перезапустить судейство (e.g. после правок `JUDGE_BRIEF.md`). |
| `multicooker report <task>` | Свод в `leaderboard.md`. |
| `multicooker diff <task>` | Diff файлов между двумя refine-раундами. |
| `multicooker add-participant <task> NAME[=FLAVOR]` | Расширить cook новым участником. |
| `multicooker clean [<task>] [--all]` | `compose down -v --rmi local` + удалить `.auth/`. |

## Статус

`v0.2`. Протестировано на macOS + Docker Desktop. На Linux должно
работать; `claude` creds на darwin берутся из Keychain, на Linux —
из `~/.claude/.credentials.json`.

Баги → GitHub issues. Безопасность: [`SECURITY.md`](SECURITY.md).

## Лицензия

[MIT](LICENSE).
