# Changelog

Notable changes to multicooker. Newest first.

## Unreleased

### Added
- **Machine-readable control-plane contract.** Every cook now writes
  `status.json` (live point-in-time snapshot, updated atomically with
  per-cell state), `events.jsonl` (append-only event log), and
  `summary.json` (canonical final result after `report`: ranking,
  per-judge breakdown, latest-round metrics, excluded self-flavor
  pairs). All written through a cross-process `fcntl.flock` +
  temp-file-rename so an external orchestrator can drive cooks without
  scraping stdout or parsing markdown. Legacy `*_RESULT.json` are now
  written atomically too. See `docs/control-plane-readiness.md`.
- **`multicooker status <task> [--json]`.** Current cook state from
  `status.json`, with a synthesized fallback for pre-contract cooks.
  Nonzero exit only for an unreadable cook dir, never for a failed
  participant.
- **`multicooker cancel <task>`.** Stops the compose project, writes a
  cancel marker, marks unfinished cells `cancelled`, and records the
  cancelled state — atomically, so a concurrently-finishing `cook`
  can't clobber it back to `sealed`. Partial outputs are preserved.
- **`multicooker resume <task> [--force]`.** Re-runs only the
  retryable cells (`rate_limited` / `timed_out` / `start_failed` /
  `non_zero_exit`) of the latest round, reusing each cell's exact
  prompt, archiving the prior attempt under
  `attempts/round-<N>/<p>/attempt-<k>/`, and merging new results over
  the prior result file so successful participants survive.
- **`multicooker tail <task> [actor]`.** Streams cell logs prefixed by
  actor, without the caller needing to know flavor-specific log
  filenames.
- **Required output validation.** Optional `outputs.required` in
  `brief.yaml` (`[{path, kind}]`, path relative to `out/`). A cell that
  exits cleanly but doesn't write a declared deliverable (or writes an
  empty/symlinked one) is recorded as `artifact_missing` instead of
  `ok`, in `status.json`, `trace.json`, the result file, and the
  `cell.exited` event — judging still proceeds, but the status is
  honest. More specific failures (`timed_out`, `rate_limited`, …) are
  never masked by this check.
- **`multicooker lint <task>` + rubric gating.** Cross-file check that
  every rubric dimension id in `brief.yaml` appears in `JUDGE_BRIEF.md`
  (and that `JUDGE_BRIEF.md` exists when a rubric + judges are defined).
  `doctor` runs it; `cook` and `refine` refuse to start if it fails, so
  a drifted rubric is caught before any container work.
- **Strict judge schema.** `judging.strict_schema: true` in `brief.yaml`
  makes a judge whose `scores.json` doesn't match the canonical
  `{label: {dimensions: {dim: int}}}` shape record `malformed_schema`
  (surfaced in `status.json`, `JUDGE_RESULT.json`, `summary.json`, and
  the leaderboard) with its scores excluded from aggregation — no silent
  repair. A stale `scores_deanon.json` from a prior run is cleared at the
  start of each judge so a now-failing judge can't aggregate old scores.
- **Anti-self-judge policy.** `judging.policy` in `brief.yaml`
  (`require_distinct_flavor` | `warn` | `allow_self`, default `warn`).
  Under `require_distinct_flavor`, `report` drops same-flavor
  (judge, participant) score pairs and records them in `summary.json`.
- **Cell exit classification.** `start_failed` (compose-up failure) and
  `oom_killed` (`docker inspect .State.OOMKilled`) are now detected and
  distinguished from a plain `non_zero_exit`.

### Changed
- **Sealed judge inbox no longer leaks identity.** `judging/_inbox/<p>/`
  now contains only the participant's `out/` plus a sanitized
  `meta.json` (`exit_class` + `round`); `PROMPT.txt`, `trace.json`,
  `usage/`, and logs — which name the flavor — are no longer copied
  into the blind judge input.
- **`report` round semantics.** `report` now reads the latest round's
  result file (`REFINE_<N>_RESULT.json` when present, else
  `RUN_RESULT.json`), so leaderboard metadata isn't stale after a
  refine, and ignores judge folders not listed in `brief.yaml`.

- **`grok` flavor.** xAI's CLI is now a first-class participant /
  judge alongside `claude` / `codex` / `gemini`. Uses
  `~/.grok/auth.json` (OAuth oidc, ~6h token), single-file RO
  bind-mount into the container, codex-style headless invocation
  (`grok -p "$PROMPT" --always-approve`). Pinned to
  `GROK_VERSION=0.1.220` in the base Dockerfile; override via
  `--build-arg`. Models: `grok-build` (default), `grok-build-latest`.
  See `docs/auth.md` for the cred layout.
