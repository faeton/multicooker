# Task

> Replace this section with what you want the participants to do. Be specific
> about the goal, the inputs, the constraints, and what counts as a good
> answer. Ambiguity is fine in places — that's where participants diverge
> interestingly — but the **success criteria must be unambiguous**.

## Goal

(One paragraph: what are we trying to produce / decide / build?)

## Inputs

- `./BRIEF.md` (this file).
- `./raw/` — reference material the user has dropped here. Read freely.
  Examples: PDFs, datasets, code samples, screenshots, prior work.
- (optional) `./raw/CONTEXT.md` — extra prose context the user wrote.

## Output

You must produce, under `./out/`:

- `RESULT.md` — your main answer. Lead with the bottom line; then
  reasoning, assumptions, alternatives considered.
- (optional, depending on task) `<artifact-files>` — code, data,
  diagrams. Mention each artifact and its purpose in RESULT.md.

## Constraints

- Time budget: as configured in brief.yaml (default 30 minutes).
- No network calls except those your CLI does for its own LLM API.
- Do not assume any other tools are installed beyond what's in the
  participant's environment. If you need something, propose it in
  RESULT.md rather than failing.

## Success criteria

You will be judged on:

- **correctness** — does the answer actually solve the stated goal?
- **quality** — is it well-reasoned, well-organized, well-written?
- **honesty** — are uncertainties flagged? are assumptions documented?
- **completeness** — are all required artifacts present?

(Edit / add dimensions to match your task. Keep them in JUDGE_BRIEF.md
in sync.)
