# Judge brief: multi-concept-ui

You are judging UI concept submissions from anonymous participants `A`,
`B`, `C`, ... against the rubric below. You only see anonymized labels.
Do not try to guess which model wrote which submission.

Each submission lives in `./submissions/<letter>/out/` and should
contain `concept-a/index.html`, `concept-b/index.html`,
`concept-c/index.html`, and `RESULT.md`.

## Rubric

| Dimension | Weight | What you are scoring |
|---|---:|---|
| concept-spread | 25 | Are the three concepts genuinely different across layout, interaction, density, visual language, or metaphor? Three reskins of one layout score low. |
| workflow-fit | 25 | Do the concepts support the workflow in `./raw/workflow.md` and use sample data honestly? Penalize generic dashboards that ignore the task. |
| interaction-quality | 20 | Are controls, states, navigation, feedback, and transitions coherent? Is there enough real interaction to evaluate the concept? |
| visual-craft | 20 | Are typography, spacing, color, hierarchy, and responsiveness deliberate and polished? |
| honesty | 10 | Does `RESULT.md` accurately explain tradeoffs, mocked behavior, and incomplete pieces? |

## What to write

To `./outbox/scores.json`, write strict JSON with
`scores[label][dimension]` integers from 0 to 5:

```json
{
  "scores": {
    "A": {
      "concept-spread": 5,
      "workflow-fit": 4,
      "interaction-quality": 4,
      "visual-craft": 5,
      "honesty": 4
    }
  }
}
```

To `./outbox/review.md`, write one paragraph per submission. Be
specific: compare the three concepts, quote visible labels or style
choices, and identify missing or broken required files. Do not mention
flavor or model names.

## Rules

- Score every submission, even if one or more concept files are missing.
- Missing concept files should score low on `concept-spread`,
  `workflow-fit`, `interaction-quality`, and `visual-craft`.
- A concept that does not open from `file://` should be penalized on
  relevant dimensions.
- Use only the rubric dimensions above.
- Do not infer participant identity. Labels are `A`, `B`, `C`, ...
- Do not modify files under `./submissions/`.
