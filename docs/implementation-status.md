# Implementation status

**Status: shipped. Docker-only.**

multicooker now runs entirely in containers — there is no host-mode and no
`--docker` flag (it was the only mode, so the flag was dropped; see
`cook.py`). The old "v0.1 / not implemented" content this file used to carry is
obsolete and has been removed to avoid drifting out of sync with the code.

For the current picture, read the two living documents instead:

- **`control-plane-integration.md`** — the stable contract: every command, the
  machine-readable files (`status.json`, `events.jsonl`, `summary.json`,
  `artifacts.json`), states, visibility classes, namespaces, the Python API.
  This is what you build a control plane (Zuzoo) against.
- **`control-plane-readiness.md`** — the roadmap (P0–P3) that got us here. P0–P2
  are implemented and tested; P3 is partial (Python API shipped; declarative
  flavor registry and remote queues remain deferred to the orchestrator side).

What's wired up today, in one line each:

- `build-base` builds shared `mc-base-<flavor>` images (node:22-slim + each CLI).
- `creds.py` snapshots subscription auth for all four flavors
  (claude/codex/gemini/grok) into per-cook `.auth/`, bind-mounted RO. claude on
  macOS is read from the Keychain entry `Claude Code-credentials` (same JSON
  shape Linux expects) — this is intentional, not a thing to avoid.
- `compose_render.py` generates `cooks/<name>/compose.yaml`; `host_profile.py`
  sizes per-cell resource limits to the active docker host.
- `compose_runner.py` runs each cell, parses rate-limit signatures from
  `docker logs`, and writes the contract files.
- `cook` / `judge` / `refine` / `rejudge` / `report` plus the control commands
  `status` / `cancel` / `resume` / `tail` / `lint` / `artifacts` / `archive` /
  `prune` are all implemented (see `multicooker/*.py` and `tests/`).

Deferred (intentionally, see readiness P3): a declarative flavor registry and
any remote-worker/queue layer — the latter belongs in the orchestrator, not in
multicooker core.

## Operational caveats (still true)

- **claude `/login` UX** on a fresh host opens a URL / copies a callback —
  `build-base` / `doctor` should tell the user before it happens.
- **Docker Desktop license** on corporate Macs — Orbstack or Colima work.
- **docker network growth** — each cook gets its own bridge networks; `clean` /
  `prune` reclaim them.

## What NOT to do (unchanged)

- Don't add API keys as a "subscription expired" fallback — fail explicitly
  rather than quietly upgrade to the paid path.
- Don't add a middlebox/observer "just in case" — if a specific cook needs it,
  it adds it via `cooks/<task>/compose.override.yaml`.
- Don't remove dangerous-skip flags "for safety". The container IS the sandbox;
  without them the CLIs hang on an approval prompt.
</content>
</invoke>
