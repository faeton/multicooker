# Task: propose a practical architecture for an underspecified feature

## Goal

You are helping a small engineering team decide how to build a new
capability into an existing product. The capability is intentionally
underspecified: the useful answer is not a summary of the inputs, but a
clear recommendation that chooses a direction, rejects alternatives, and
names the risks.

Use `./raw/context.md` as the product and codebase context, and
`./raw/problem.md` as the feature request. You may disagree with the
notes in `./raw/constraints.md`, but if you do, explain the tradeoff and
offer a better replacement.

## Inputs

- `./raw/context.md` - the current product, codebase, users, and
  operating environment.
- `./raw/problem.md` - the feature or system change to design.
- `./raw/constraints.md` - hard constraints, soft preferences, and
  known unknowns.

## Output

Write `./out/PROPOSAL.md`, a single self-contained technical proposal.
It must include these sections, in this order:

1. **Bottom line** - the recommended direction in 5-10 bullets.
2. **Problem framing** - what the team is really trying to solve, who it
   is for, and what would make the work a failure.
3. **Proposed architecture** - components, data flow, storage, external
   dependencies, operational boundaries, and critical interfaces.
4. **Alternatives considered** - at least three credible alternatives
   and why you rejected them.
5. **Implementation plan** - MVP, next milestone, later hardening, and
   what to cut if time is short.
6. **Validation plan** - tests, manual checks, observability, rollout,
   and failure-mode drills.
7. **Risks and open questions** - real unknowns, not generic "write
   more tests" filler.

Optional extra artifacts under `./out/` are welcome if they sharpen the
answer: diagrams, interface sketches, state-machine notes, or config
examples. Mention every extra artifact from `PROPOSAL.md`.

## Constraints

- This is a design/proposal cook, not an implementation cook.
- Do not modify `./raw/`.
- Prefer concrete interfaces, state records, command examples, and
  decision tables over broad architecture prose.
- Do not pretend every unknown is solved. Label assumptions and name the
  experiment or spike that would retire each important risk.
- Keep the proposal sized for a small team to execute. Avoid
  enterprise-platform designs unless the inputs clearly require one.

## Anti-goals

- Do not merely restate the raw documents.
- Do not produce a tutorial or survey article.
- Do not choose every option. Make tradeoffs.
- Do not invent metrics, benchmarks, provider APIs, or customer evidence.
- Do not hide security, cost, operations, or migration behind vague
  "configuration" language.

## Success criteria

- **problem-framing** - understands the real goal, users, boundaries,
  and failure modes.
- **architecture-realism** - proposes components and interfaces that a
  small team can build, operate, and debug.
- **tradeoff-clarity** - considers credible alternatives and rejects them
  for concrete reasons.
- **execution-plan** - gives a staged plan with validation, rollout, and
  cut lines.
- **risk-honesty** - flags assumptions, unknowns, and experiments
  instead of overclaiming.
