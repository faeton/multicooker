# hello-task — sanitized smoke example

Тривиальная задача (написать хайку про reproxy) на flavor `dummy`,
без подписочных кредов. Гоняется локально за ~10 секунд и существует
для двух целей:

1. Показать форму cook'а (BRIEF.md / JUDGE_BRIEF.md / brief.yaml /
   raw/) на минимальном осмысленном примере.
2. Дать готовый smoke-сценарий, не требующий доступа к LLM.

## Запуск

```bash
# Скопируй пример в свой cooks/ как обычный cook:
multivarka new hello-smoke --participants a=dummy,b=dummy,c=dummy
cp examples/hello-task/BRIEF.md       cooks/$(date +%y%m%d)-hello-smoke/
cp examples/hello-task/JUDGE_BRIEF.md cooks/$(date +%y%m%d)-hello-smoke/
cp examples/hello-task/raw/about.md   cooks/$(date +%y%m%d)-hello-smoke/raw/

multivarka cook   $(date +%y%m%d)-hello-smoke
multivarka judge  $(date +%y%m%d)-hello-smoke
multivarka report $(date +%y%m%d)-hello-smoke
```

`dummy` flavor:

- участник копирует `PROMPT.txt` → `out/RESULT.md` (без обращений к
  моделям);
- судья ставит фиксированные оценки и пишет review с `A/B/C`-метками.

Хочется попробовать на настоящих агентах? Поменяй `flavor: dummy` в
`brief.yaml` на `claude`/`codex`/`gemini` — в остальном пример
устроен ровно как «боевой» cook.
