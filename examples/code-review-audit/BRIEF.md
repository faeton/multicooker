# Task: audit an existing codebase and recommend the next work

## Goal

Read the code and notes under `./raw/`, find the most important issues,
and recommend what a downstream implementation round should do next.
This is a review and diagnosis cook, not a patch cook.

The valuable answer is calibrated: it should distinguish real bugs from
style preferences, identify root causes with citations, and avoid
rewriting load-bearing code just because it looks unfamiliar.

## Inputs

- `./raw/README.md` - product and architecture overview.
- `./raw/known-issue.md` - a specific bug or concern the maintainer
  wants investigated.
- `./raw/src/` - small placeholder source tree. Replace with a real
  project snapshot when adapting this example.

The whole `./raw/` directory is read-only.

## Output

Write these files under `./out/`:

1. `RESULT.md` - executive summary. State whether the next round should
   amend the existing code, rewrite a narrow slice, or stop and gather
   more evidence. Make one clear recommendation.
2. `01-code-review.md` - non-obvious findings with `file:line`
   citations, severity, root cause, and fix sketch.
3. `02-known-issue.md` - root-cause analysis for the bug in
   `./raw/known-issue.md`, with the minimum viable fix and second-order
   risks.
4. `03-next-plan.md` - prioritized work plan from P0 to P3, with
   acceptance criteria and verification steps.
5. `04-refine-guidance.md` - instructions for a downstream refine or
   implementation cook: what to patch, what to leave alone, and what
   evidence would change the recommendation.

## Constraints

- Do not modify `./raw/`.
- Do not write code patches unless the brief explicitly asks for a
  pseudo-diff inside the markdown deliverables.
- Use `file:line` citations for concrete findings.
- If you cannot verify a claim from source, mark it as an assumption.
- Prefer a short list of high-confidence issues over a long list of
  speculative complaints.

## Anti-goals

- Do not produce generic cleanup advice.
- Do not recommend a rewrite without naming the smallest coherent slice.
- Do not fabricate file paths, line numbers, tests, benchmarks, or
  runtime behavior.
- Do not spend the whole answer summarizing the product.
- Do not treat missing tests as the root cause of every issue.

## Success criteria

- **evidence-quality** - findings are grounded in source citations and
  real behavior, not vague impressions.
- **bug-analysis** - the known issue is explained with a defensible root
  cause, fix sketch, and second-order risks.
- **prioritization** - recommendations are severity-calibrated and
  ordered in a way a maintainer could execute.
- **refine-guidance** - the downstream implementation round gets clear
  amend-vs-rewrite calls and do-not-touch guidance.
- **honesty** - assumptions, unread areas, and uncertainty are explicit.
