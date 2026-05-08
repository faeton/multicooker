# Judging brief

You are scoring participants who solved the same task independently and
in parallel. The original task brief is reproduced below. After that,
the rubric. **Score against the rubric, not your own taste.**

---

## Task brief (verbatim copy of what participants saw)

> When running, the cook step copies `BRIEF.md` to the judge's working
> directory. If you ever read this from a templates/ folder, the brief
> is at `./BRIEF.md` next to this file in the live cook.

(see `./BRIEF.md` for the actual task)

---

## Rubric

Score each dimension on a 0–5 scale (0 = absent / wrong, 5 = excellent).

| Dimension | Weight | What it measures |
|---|---|---|
| **correctness** | 40 | Does the answer actually solve the stated goal? Does it satisfy explicit constraints? |
| **quality** | 25 | Is reasoning clear and well-organized? Is the writing tight? Is structure logical? |
| **honesty** | 20 | Are uncertainties flagged? Are assumptions documented? Are alternatives considered? Does the participant pretend to know things it doesn't? |
| **completeness** | 15 | Are all required artifacts present? Is the answer self-contained? |

Total = sum of (dimension_score × weight) / 5. Max possible total = 100.

## Hard rules

- **Do not infer participant identity.** Submissions are labeled A, B, C, ...
  If you guess "this looks like claude," your score is invalid.
- **Missing artefact = 0 on completeness for that artefact's dimension.**
  Don't extrapolate from what you "think they meant."
- **Empty / broken submissions** get honest low scores. Do not give pity points.

## Output format

Write two files under `./outbox/`:

### `scores.json`
```json
{
  "A": {
    "dimensions": {
      "correctness": 4,
      "quality": 3,
      "honesty": 5,
      "completeness": 4
    },
    "total": 78.0
  },
  "B": { ... },
  "C": { ... }
}
```

### `review.md`
One short paragraph per participant explaining the score, then a final
ranking with one-line justification per place.

When done, exit. Do not modify any files under `./submissions/`.
