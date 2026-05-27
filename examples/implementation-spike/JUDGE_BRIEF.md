# Judge brief: implementation-spike

You are judging implementation spike submissions from anonymous
participants `A`, `B`, `C`, ... against the rubric below. You only see
anonymized labels. Do not try to guess which model wrote which
submission.

Each submission lives in `./submissions/<letter>/out/`. Start with
`README.md` and `STATUS.md`, then inspect source and run commands only
if your judging environment supports them.

## Rubric

| Dimension | Weight | What you are scoring |
|---|---:|---|
| buildability | 25 | Do the documented install/run/test commands work or at least have a coherent manifest and entrypoint? A project that cannot start scores low. |
| core-functionality | 30 | Does the narrow feature path actually work with real code? Stubs and UI-only shells score low. |
| integration-fit | 15 | Does the solution follow the raw context, project conventions, data shapes, and constraints? Or does it silently fork the problem? |
| scope-control | 15 | Is this a focused vertical slice with clear cuts, or a broad unfinished scaffold? |
| honesty | 15 | Does `STATUS.md` accurately report verified commands, gaps, stubs, and unverified claims? |

## What to write

To `./outbox/scores.json`, write strict JSON with
`scores[label][dimension]` integers from 0 to 5:

```json
{
  "scores": {
    "A": {
      "buildability": 4,
      "core-functionality": 3,
      "integration-fit": 4,
      "scope-control": 5,
      "honesty": 4
    }
  }
}
```

To `./outbox/review.md`, write one paragraph per submission. Mention
what you inspected, any command results you observed, and one concrete
strength or failure. Do not mention flavor or model names.

## Rules

- Score every submission, even if `out/` is empty.
- Empty output scores 0 across all dimensions.
- If build commands fail, still inspect source and score other
  dimensions honestly, but cap `buildability` at 2.
- If `README.md` claims behavior that source does not implement, penalize
  `honesty`.
- Use only the rubric dimensions above.
- Do not infer participant identity. Labels are `A`, `B`, `C`, ...
- Do not modify files under `./submissions/`.
