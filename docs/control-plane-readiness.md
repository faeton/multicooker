# Control-plane readiness plan

This document describes the work needed to make `multicooker` a stable
execution engine for an external control plane such as Zuzoo.

The intended shape is deliberately conservative:

- `multicooker` remains a CLI and cook-directory based Docker execution
  engine.
- Zuzoo, or any other control plane, owns chat UI, approvals, durable
  user-facing state, quota policy, and scheduling.
- The boundary between them is a small, boring contract: task files in;
  structured status, events, results, and artifacts out.

Do not turn `multicooker` into a server as the first step. Stabilize the
CLI/filesystem contract first.

## Goal

Make `multicooker` safe and predictable for repeated unattended use:

- launch a cook from another process;
- observe progress without scraping stdout;
- cancel a running cook;
- resume failed or rate-limited cells;
- receive a machine-readable final result;
- publish only safe artifacts;
- preserve the existing standalone local workflow.

## Non-goals

- Do not merge Zuzoo and `multicooker`.
- Do not make `multicooker` the Zuzoo state store.
- Do not make participant agents aware of Zuzoo, other participants, or
  judge mappings.
- Do not add a distributed scheduler, queue, daemon, Kubernetes backend,
  or Python API before the CLI/filesystem contract is stable.

## P0: correctness gaps

### 1. Fix `RUN_RESULT.json`, refine, and report semantics

Problem: after `refine`, `report` can still rely on round-1
`RUN_RESULT.json`. That makes leaderboard metadata such as status,
duration, and token usage stale after later rounds.

Required work:

- Introduce one aggregate result builder used by `report`.
- Make `report` understand the latest relevant phase or round:
  initial cook, refine round N, rejudge, and report.
- Add a terminal `summary.json` that represents the current final state.
- Keep legacy `RUN_RESULT.json` readable for compatibility, but stop
  treating it as the only source of truth.

Acceptance:

- A test for `cook -> refine -> judge -> report` shows status, duration,
  and usage from the latest round.
- Existing reports for one-round cooks keep working.

### 2. Make anti-self-judge a policy, not a warning

Problem: the docs describe anti-self-judging as a guarantee, but the
runtime currently warns and continues when judge flavors overlap
participant flavors.

Required work:

- Add an explicit judging policy, either in `brief.yaml` or as a
  documented default:

  ```yaml
  judging:
    policy: require_distinct_flavor
  ```

- Supported values:
  - `require_distinct_flavor`
  - `warn`
  - `allow_self`
- Under `require_distinct_flavor`, self-flavor judge/submission pairs
  must either be filtered from aggregation or fail early before judging.
- `report` should record which pairs were excluded.

Acceptance:

- A self-flavor judge score cannot affect aggregate results under the
  strict policy.
- Regression tests cover strict exclusion and permissive mode.

### 3. Remove sealed judging inbox identity leakage

Problem: sealed judge input may include files such as `trace.json`,
`PROMPT.txt`, usage data, or logs that reveal participant flavor names.
This weakens blind judging.

Required work:

- When sealing submissions, copy only:
  - participant `out/`;
  - a curated `meta.json` that does not contain flavor, model, or
    participant-name leakage.
- Do not copy `PROMPT.txt`, `trace.json`, `usage/`, raw logs, or host
  metadata into judge-visible submissions.
- Keep `_mapping.json` host-only.

Acceptance:

- A regression test scans sealed judge input for known flavor names and
  fails if they appear outside participant-authored output.

## P1: machine contract for orchestrators

### 4. Add `status.json`

Create `cooks/<name>/status.json` as the current state file for the cook.
It must be updated atomically with temp-file plus rename.

Example:

```json
{
  "schema_version": 1,
  "cook": "260527-example",
  "phase": "cook",
  "state": "running",
  "round": 1,
  "updated_at": "2026-05-27T18:20:00Z",
  "cells": {
    "codex": {
      "role": "participant",
      "flavor": "codex",
      "state": "running",
      "started_at": "2026-05-27T18:19:10Z",
      "exit_class": null
    }
  }
}
```

Cook-level states:

- `created`
- `preflighting`
- `building`
- `cooking`
- `sealed`
- `judging`
- `reported`
- `cancelled`
- `failed`

Cell-level states:

- `pending`
- `starting`
- `running`
- `ok`
- `rate_limited`
- `timed_out`
- `cancelled`
- `start_failed`
- `oom_killed`
- `non_zero_exit`
- `artifact_missing`

Acceptance:

- `status.json` exists and changes while a cook is running, not only at
  the end.
- External tools do not need to parse stdout to know the current phase.

### 5. Add `events.jsonl`

Create `cooks/<name>/events.jsonl` as an append-only event stream.

Each line should contain:

```json
{
  "ts": "2026-05-27T18:20:00Z",
  "event": "cell.exited",
  "cook": "260527-example",
  "phase": "cook",
  "actor": "codex",
  "payload": {
    "exit_class": "ok",
    "duration_s": 326.7
  }
}
```

Initial event set:

- `cook.created`
- `phase.started`
- `image.build.started`
- `image.build.finished`
- `cell.started`
- `cell.exited`
- `cell.rate_limited`
- `seal.started`
- `seal.finished`
- `judge.started`
- `judge.finished`
- `report.written`
- `cook.cancel_requested`
- `cook.cancelled`

Acceptance:

- Zuzoo or another orchestrator can follow progress by reading
  `events.jsonl`.
- Existing human logs remain unchanged.

### 6. Add `summary.json`

Create `cooks/<name>/summary.json` after `report`.

It should be the canonical machine-readable final result and include:

- schema version;
- cook name;
- latest round;
- run statuses, durations, token usage, and costs where available;
- participant ranking;
- per-judge breakdown;
- skipped or excluded judge/submission pairs;
- artifact pointers;
- path to `leaderboard.md`.

Acceptance:

- `leaderboard.md` remains the human-readable report.
- Orchestrators use `summary.json` for core logic and do not parse
  markdown.

### 7. Add `artifacts.json`

Create `cooks/<name>/artifacts.json` as a manifest of important files.
Each entry should include path, kind, size, hash where cheap, and
visibility.

Visibility classes:

- `public`: safe to publish to a chat topic, for example `leaderboard.md`,
  participant `out/`, and sanitized reviews.
- `operator`: useful for debugging but not public by default, for example
  logs and traces.
- `secret`: credentials or secret-bearing files.
- `host_only`: files that must stay on the host, for example judge
  mappings and de-anonymized internals.

Acceptance:

- A control plane can publish only `public` artifacts.
- `.auth`, `_mapping.json`, raw logs, and similar files are not published
  accidentally.

## P1: control commands

### 8. Add `multicooker status <cook> --json`

Required behavior:

- Read `status.json`.
- Fall back to existing result files for older cooks where possible.
- Return valid JSON.
- Do not return nonzero merely because a participant failed; reserve
  nonzero for invalid or unreadable cook directories.

Acceptance:

- Works while a cook is still running.
- Gives enough information for a control plane status card.

### 9. Add `multicooker cancel <cook>`

Required behavior:

- Write a cancellation marker into the cook directory.
- Stop the related compose project and running services.
- Preserve partial outputs.
- Update `status.json`.
- Append cancellation events to `events.jsonl`.

Acceptance:

- Can be called from another terminal while `cook` is running.
- After cancellation, `report` either works with partial results or
  clearly reports why it cannot.

### 10. Add `multicooker resume <cook>`

Required behavior:

- Rerun only cells in retryable terminal states:
  - `rate_limited`
  - `timed_out`
  - `start_failed`
  - `non_zero_exit`
- Do not overwrite successful outputs unless `--force` is set.
- Preserve attempt history.
- Re-seal and rejudge as needed.

Acceptance:

- A rate-limited participant can be resumed without re-running all
  successful participants.
- Later `judge` and `report` use the resumed outputs.

### 11. Add `multicooker tail <cook> [actor]`

Required behavior:

- Stream existing stdout and stderr files.
- Prefix each line with actor name.
- Work without the caller knowing flavor-specific log filenames.

Acceptance:

- Useful for humans.
- Usable by a control plane for optional log display, but not required
  for core state.

## P2: output and rubric validation

### 12. Add required artifact validation

Problem: `out/RESULT.md` or `out/PROPOSAL.md` is currently a prompt
convention, not an enforced contract.

Add optional output declarations to `brief.yaml`:

```yaml
outputs:
  required:
    - path: PROPOSAL.md
      kind: markdown
```

Required behavior:

- Validate participant `out/` after each cell exits.
- If the process exits successfully but required files are missing, mark
  the cell as `artifact_missing`.
- Continue judging if appropriate, but make the status honest.

Acceptance:

- A dummy participant that does not write the required file gets
  `artifact_missing`.

### 13. Add rubric linting

Problem: `brief.yaml`, `BRIEF.md`, and `JUDGE_BRIEF.md` can drift.

Required work:

- Add `multicooker lint <cook>`.
- Check that every rubric dimension ID in `brief.yaml` appears in
  `JUDGE_BRIEF.md`.
- Check scale and weights.
- Have `doctor` run lint before expensive operations.

Acceptance:

- A cook with a missing judge rubric dimension fails before participant
  execution.

### 14. Add strict judge output mode

The current tolerant report parser is useful, but automation needs a
strict mode.

Add:

```yaml
judging:
  strict_schema: true
```

Required behavior:

- In strict mode, require judge output to match the documented schema:
  `scores[label][dimension]: int`.
- Mark malformed judge output explicitly instead of silently repairing it.

Acceptance:

- Malformed judge output is visible in `status.json`, `summary.json`, and
  `report`.

## P2: operations and retention

### 15. Add `multicooker archive <cook>`

Required behavior:

- Produce a publishable archive or directory.
- Include only safe artifacts by default.
- Exclude `.auth`, `_mapping.json`, raw logs, and host-only internals
  unless explicitly requested.

Acceptance:

- The archive can be posted or stored by a control plane without leaking
  credentials or judge mappings.

### 16. Extend `clean` and add pruning behavior

Required behavior:

- Prune cooks older than N days.
- Optionally prune images and build cache associated with the cook
  namespace.
- Preserve `summary.json` and `leaderboard.md` if requested.

Acceptance:

- A server-like installation can run periodic cleanup safely.

### 17. Add compose/image namespace support

Required behavior:

- Add `--namespace`.
- Add `MULTICOOKER_NAMESPACE`.
- Compose project names should include the namespace:
  `mc-<namespace>-<cook>`.

Acceptance:

- Two orchestrators can run cooks with the same suffix in different
  namespaces without conflicting compose projects, images, or logs.

## P3: later work

### 18. Public Python API

Do this only after the CLI/filesystem contract is stable.

Potential API:

- `CookRequest`
- `CookStatus`
- `CookResult`
- `run_cook`
- `run_judge`
- `run_report`

The CLI should remain the primary integration surface until the schemas
above are proven.

### 19. Declarative flavor registry

Current flavor support is spread across schemas, credential handling,
compose rendering, metrics, templates, and docs.

Later, move flavor metadata into a registry:

- auth source;
- entrypoint;
- base image;
- usage parser;
- model override support;
- known rate-limit patterns.

### 20. Remote workers and queues

Do not put this in `multicooker` core yet.

If Zuzoo needs a queue, implement it in the Zuzoo adapter or worker:

- Zuzoo stores jobs in SQLite or a queue.
- A worker claims a job.
- The worker materializes a cook directory.
- The worker invokes the `multicooker` CLI.
- The worker reads `status.json`, `events.jsonl`, `summary.json`, and
  `artifacts.json`.

`multicooker` should not become a distributed scheduler unless repeated
real deployments prove that need.

## Recommended implementation order

1. Add `summary.json`, `status.json`, and `events.jsonl`.
2. Add `status`, `cancel`, and `resume`.
3. Fix anti-self-judge enforcement and sealed inbox leakage.
4. Add required output validation and rubric linting.
5. Add `artifacts.json` and `archive`.
6. Add prune and namespace support.
7. Consider a Python API only after the file contract has stabilized.

## Zuzoo-ready definition of done

`multicooker` is ready for Zuzoo-style orchestration when an external
process can:

- create a cook directory;
- run `multicooker cook`, `multicooker judge`, and `multicooker report`;
- read live progress from `status.json` and `events.jsonl`;
- cancel through `multicooker cancel`;
- resume retryable cells through `multicooker resume`;
- read final results from `summary.json`;
- publish safe files according to `artifacts.json`;
- avoid parsing markdown, stdout, or raw logs for core control logic.
