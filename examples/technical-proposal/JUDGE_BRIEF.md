# Judge brief: technical-proposal

You are judging technical proposal submissions from anonymous
participants `A`, `B`, `C`, ... against the rubric below. You only see
anonymized labels. Do not try to guess which model wrote which
submission.

Each submission lives in `./submissions/<letter>/out/PROPOSAL.md`.
Read optional extra files only if `PROPOSAL.md` points to them.

## Rubric

| Dimension | Weight | What you are scoring |
|---|---:|---|
| problem-framing | 20 | Does the proposal identify the actual product and engineering problem, users, constraints, and failure modes? Or does it solve a generic adjacent problem? |
| architecture-realism | 25 | Are the components, data flow, state, interfaces, operations, and dependencies specific enough to build and debug? Could a small team realistically ship this? |
| tradeoff-clarity | 20 | Does it compare credible alternatives with concrete rejection reasons? Or does it pick a path without acknowledging costs and runners-up? |
| execution-plan | 20 | Does the staged plan define MVP, next milestone, validation, rollout, observability, and cut lines? Or is it just a wishlist? |
| risk-honesty | 15 | Are assumptions and unknowns explicit, with experiments to retire them? Penalize confident claims that are unsupported by the inputs. |

## What to write

To `./outbox/scores.json`, write strict JSON with
`scores[label][dimension]` integers from 0 to 5:

```json
{
  "scores": {
    "A": {
      "problem-framing": 4,
      "architecture-realism": 4,
      "tradeoff-clarity": 3,
      "execution-plan": 5,
      "risk-honesty": 4
    }
  }
}
```

To `./outbox/review.md`, write one paragraph per submission. Be
concrete: quote section names, interface sketches, risk statements, or
alternative decisions you are reacting to. Do not mention flavor or
model names.

## Rules

- Score every submission you receive, even if `PROPOSAL.md` is empty,
  missing required sections, or malformed.
- Missing required output should score low on every dimension that
  depends on it.
- Use only the rubric dimensions above.
- Do not infer participant identity. Labels are `A`, `B`, `C`, ...
- Do not modify files under `./submissions/`.
