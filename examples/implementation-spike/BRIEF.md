# Task: build a narrow working prototype

## Goal

Build the smallest useful prototype for the requested capability using
the context in `./raw/`. The point is not to finish a production system;
the point is to prove the core path with real code, clear boundaries,
and honest verification.

Participants should make conservative implementation choices that fit
the existing project shape described in `./raw/context.md`.

## Inputs

- `./raw/context.md` - existing project shape, tools, and conventions.
- `./raw/feature.md` - the capability to prototype.
- `./raw/acceptance.md` - minimum behavior the prototype should show.

## Output

Write everything under `./out/`.

Required files:

1. `README.md` - what was built, how to run it, and what to inspect.
2. `STATUS.md` - verified working behavior, unverified behavior,
   stubs, known gaps, and the exact commands run.
3. `src/` or equivalent source directory - real code for the prototype.
4. `tests/`, `examples/`, or a runnable smoke script - enough evidence
   that the core path works.

Participants may choose the language and structure unless
`./raw/context.md` says otherwise. If the prototype depends on packages,
include the smallest reasonable manifest for the chosen ecosystem.

## Constraints

- Write only under `./out/`.
- Build a narrow vertical slice. Do not scaffold an entire product shell
  unless the feature genuinely requires it.
- Prefer boring, inspectable code over clever abstractions.
- If something is stubbed, make the stub obvious in code and in
  `STATUS.md`.
- Include commands a judge can run from `./submissions/<letter>/out/`.
- Do not claim a command passed unless you actually ran it.

## Anti-goals

- Do not submit only a design document.
- Do not generate a large framework app with no working core behavior.
- Do not hide missing behavior behind TODO comments.
- Do not modify `./raw/`.
- Do not fake test output, screenshots, or benchmarks.

## Success criteria

- **buildability** - the submitted code installs or runs with the
  documented commands.
- **core-functionality** - the narrow feature path works, not just the
  surrounding scaffold.
- **integration-fit** - choices match the existing project conventions
  and use the provided context instead of forking the problem.
- **scope-control** - the prototype stays focused and cuts lower-value
  work cleanly.
- **honesty** - `STATUS.md` accurately distinguishes verified behavior,
  unverified behavior, stubs, and gaps.
