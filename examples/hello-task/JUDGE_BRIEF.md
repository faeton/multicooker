# Judge brief: hello-task

You are judging haiku submissions from anonymous participants `A`, `B`,
`C`, … against the rubric below. You only see anonymized labels — do
not try to guess which model wrote which submission.

## Rubric

| Dimension | Weight | What you're scoring (0–5) |
|---|---|---|
| correctness | 40 | Is it actually a haiku (5–7–5 syllables)? |
| quality | 25 | Does it evoke the project's spirit (offline-first proxy, hostile network)? |
| honesty | 20 | If a rule was bent, is it acknowledged in the note? |
| completeness | 15 | Are both the haiku and the two-sentence note present? |

## What to write

To `./outbox/scores.json`, **strict JSON** in this shape:

```json
{
  "scores": {
    "A": { "correctness": 5, "quality": 4, "honesty": 5, "completeness": 5 },
    "B": { "correctness": 4, "quality": 5, "honesty": 3, "completeness": 5 },
    "C": { "correctness": 5, "quality": 3, "honesty": 5, "completeness": 4 }
  }
}
```

To `./outbox/review.md`, a short paragraph per submission with concrete
quotes / counts (e.g. syllable count per line) — no summary, no
ranking, no flavor names.

## Rules

- Score every submission you receive, even if it's empty (give 0s and
  say so in the review).
- Use only the rubric dimensions above; don't invent new ones.
- No mention of `claude` / `codex` / `agy` / specific model names —
  the labels are `A`, `B`, `C`, …
