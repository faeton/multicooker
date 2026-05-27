# implementation-spike - narrow working prototype

Use this shape when you want agents to build a small, testable slice
instead of writing a proposal. It works best after a proposal or review
cook has already narrowed the target.

Good fits:

- implement one transport adapter;
- build a minimal CLI around a new data model;
- prove a parser, migration, or routing path;
- create a tiny UI widget with real state transitions.

The brief intentionally requires `STATUS.md`. In implementation cooks,
truthful scope reporting is often as important as raw feature count.

## Adapt

Replace `raw/context.md`, `raw/feature.md`, and `raw/acceptance.md`.
If the target stack is fixed, say so in `context.md`; otherwise let
participants choose and judge them on fit.
