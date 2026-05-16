# multicooker — what it is

`multicooker` is a CLI tool that runs several LLM coding agents
(`claude`, `codex`, `gemini`) on the **same task** at the same time,
each in its own docker container with its own subscription auth.
When the agents finish, **other** LLM agents read the outputs blind
(labeled `A` / `B` / `C`) and score them against a rubric you
defined. You get a leaderboard plus per-submission reviews — a
small corpus of how the same brief gets interpreted differently.

## Who it's for

- Engineers picking between models for a recurring task (refactor,
  doc-write, design, review) and tired of vibes-based judgement.
- Designers and PMs who want to see what an underspecified brief
  collapses into when different models read it.
- Researchers studying model-vs-model disagreement on creative or
  open-ended tasks.

## What's distinctive

- **No API keys.** It uses your `Claude Pro` / `ChatGPT Plus` /
  `Gemini Advanced` subscriptions through the official CLIs.
- **Real isolation.** Each agent runs in its own docker container
  on its own bridge network; they can't see each other's outputs,
  and the judge can't see which output came from which agent.
- **Parallel by default.** All agents start at once. One being
  rate-limited doesn't block the others.
- **Reproducible.** Every cook is a self-contained directory with
  the brief, the configs, the outputs, and the judge transcripts.
  Re-runnable, diff-able across rounds.

## What it isn't

- Not a benchmark suite — you write the task and the rubric.
- Not an API gateway — agents talk to their own backends directly.
- Not free to run forever — your subscriptions have rate limits.
