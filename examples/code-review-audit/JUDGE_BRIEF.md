# Judge brief: code-review-audit

You are judging code review and audit submissions from anonymous
participants `A`, `B`, `C`, ... against the rubric below. You only see
anonymized labels. Do not try to guess which model wrote which
submission.

Each submission lives under `./submissions/<letter>/out/`. Read all
required markdown files if present, and cross-check a few cited
`file:line` references against `./raw/`.

## Rubric

| Dimension | Weight | What you are scoring |
|---|---:|---|
| evidence-quality | 25 | Are findings specific, non-obvious, and grounded in correct `file:line` citations? Penalize fabricated cites and generic advice. |
| bug-analysis | 25 | Does `02-known-issue.md` explain the actual root cause, propose a minimal fix, and name second-order risks? |
| prioritization | 15 | Are recommendations severity-calibrated and executable, with P0/P1 work separated from nice-to-have cleanup? |
| refine-guidance | 20 | Does `04-refine-guidance.md` tell a downstream implementation round what to patch, what not to touch, and why? |
| honesty | 15 | Does the submission disclose assumptions, unread areas, and uncertainty? Fabricated evidence should score 0 here. |

## What to write

To `./outbox/scores.json`, write strict JSON with
`scores[label][dimension]` integers from 0 to 5:

```json
{
  "scores": {
    "A": {
      "evidence-quality": 4,
      "bug-analysis": 5,
      "prioritization": 4,
      "refine-guidance": 4,
      "honesty": 5
    }
  }
}
```

To `./outbox/review.md`, write one paragraph per submission. Quote at
least one concrete finding or recommendation from each submission and
state whether its cited evidence checks out. Do not mention flavor or
model names.

## Rules

- Score every submission, even if some output files are missing.
- Missing required files should score 0 on dimensions that depend on
  them.
- If a submission fabricates multiple citations, cap
  `evidence-quality` and `honesty` at 1.
- Use only the rubric dimensions above.
- Do not infer participant identity. Labels are `A`, `B`, `C`, ...
- Do not modify files under `./submissions/` or `./raw/`.
