# code-review-audit - review, bug hunt, refine guidance

Use this shape when you want agents to read a real codebase snapshot and
produce diagnosis, not code. It is useful before a risky implementation
round because it asks participants to separate:

- real bugs from style opinions;
- root cause from symptoms;
- "amend this" from "rewrite this narrow slice";
- load-bearing ugly code from code that should actually change.

The judge brief is intentionally evidence-heavy. Judges should
cross-check a few cited lines against `raw/`, because fabricated
citations are the fastest way for review cooks to become noise.

## Adapt

Replace `raw/src/` with the project snapshot and rewrite
`raw/known-issue.md` with the maintainer's concrete concern. For large
repos, add an orientation file that names the important subtrees and the
files participants should read first.
