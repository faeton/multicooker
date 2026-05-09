# Security model

What multivarka protects against, what it doesn't, and why.

## TL;DR

- **The container is the sandbox.** Permission-bypass flags
  (`--dangerously-skip-permissions`, `--yolo`,
  `--dangerously-bypass-approvals-and-sandbox`) are required for
  headless operation and are safe inside the container — they
  cannot reach the host.
- **Per-cook bridge networks isolate participants from each other.**
  Each participant and each judge gets its own
  `net-{participant,judge}-<name>` network. They cannot DNS or
  IP-reach siblings in the same cook.
- **Egress is open.** Agents need npm / pypi / GitHub / docs /
  the model APIs. Sandboxing is the container, not the network.
- **Anonymization is anti-gaming, not security.** Participants are
  relabelled `A/B/C` for the judge and the `A↔flavor` mapping
  stays on the host. Don't rely on it for confidentiality.
- **Subscription creds are bind-mounted RO into the participant's
  own container.** A compromised CLI binary would see its own creds.

## Threat model

### What we defend against

| Threat | Defence |
|---|---|
| Participant A reads participant B's `out/` mid-cook | Separate bridge networks; B's volume is not mounted into A's container. |
| Participant tries to bias the judge by signing its output | Anonymization (`A/B/C`) before the judge sees anything. |
| Judge sees stdout/stderr / logs / mapping | Judge only gets copies of `BRIEF.md` + `JUDGE_BRIEF.md` + `raw/` + sealed anonymized `submissions/`. `_mapping.json` never leaves the host. |
| Buggy/malicious CLI deletes `~/Documents` | CLI runs in a Linux container with explicit bind mounts only (`/work`, `/home/node/.<creds>`); host paths outside those mounts are not visible. |
| Re-running cook silently picks up old creds | `creds.snapshot()` re-runs at every `cook` / `refine` / `judge` and rebuilds `.auth/`. |
| `.auth/` accidentally committed | `creds.snapshot()` adds `.auth/` to per-cook `.gitignore`; `cooks/` is in the repo `.gitignore`. |

### What we explicitly don't defend against

| Non-goal | Why |
|---|---|
| Container escape via Docker / kernel CVEs | We trust Docker's isolation. If you need stronger isolation, run multivarka inside a VM. |
| Stealing the participant's own creds | A compromised CLI binary has access to the auth files mounted for it. The cost of headless subscription auth. Mitigation: don't run multivarka with CLIs you don't trust. |
| Network-level data exfiltration | Egress is open. If your `raw/` is sensitive, see "Sensitive raw materials" below. |
| Accidentally including `.env`, secrets in `raw/` | You control `raw/`. We mount it RO; we don't scan it. |
| Re-using a leaked OAuth token | If your subscription creds leak, rotate them with the upstream provider (`claude /login`, `codex` re-auth, `gemini` re-auth). |
| Judge collusion / reward hacking by the model itself | Out of scope — this is an alignment problem, not a tooling one. |

## Sensitive raw materials

`raw/` is bind-mounted RO into the participant container, but the
participant has open internet egress. Treat anything in `raw/` as
"the model can see it and may exfiltrate it via API calls or web
fetches." If that's not acceptable:

- Don't put real secrets / PII / proprietary data into `raw/`.
- Or, drop a per-cook `compose.override.yaml` that adds
  `network_mode: none` or a strict allowlist proxy. multivarka
  doesn't ship this by default because most cooks need internet.

## Credential handling

- Source-of-truth on the host:
  - `claude` (macOS): Keychain entry `"Claude Code-credentials"`.
  - `claude` (Linux): `~/.claude/.credentials.json`.
  - `codex`: `~/.codex/auth.json`.
  - `gemini`: `~/.gemini/oauth_creds.json` + `settings.json` etc.
- Per-cook copy: `cooks/<task>/.auth/{claude,codex,gemini}/` —
  mode `0600`, written by `multivarka.creds.snapshot()`, mounted
  RO into the matching participant only.
- Refresh: snapshot re-runs at every cook/refine/judge — token
  rotations on the host are picked up next run. There is no
  long-lived cache.
- Clean-up: `multivarka clean <task>` removes `.auth/` (unless
  `--keep-creds`). `multivarka clean --all` does it for every cook.

## Anti-self-judging (anonymization)

Anonymization happens in `multivarka/judge.py`:

1. Each participant's sealed `out/` is copied (not symlinked) into
   `cooks/<task>/judging/_inbox/<participant>/`.
2. Names are shuffled into stable labels `A`, `B`, `C`, … and the
   inbox is re-laid as `judging/<judge>/submissions/{A,B,C}/`.
3. `_mapping.json` (label → participant name → flavor) is written
   to `judging/_mapping.json` on the host. **Not** mounted into
   any judge container.
4. The judge prompt only references `A/B/C` labels.
5. Reverse-mapping happens after the judge writes
   `outbox/scores.json`, on the host.

Symlinks were tried and rejected — CLI sandbox allowlists don't
follow symlinks (`docs/pitfalls.md`).

## Reporting

See [`SECURITY.md`](../SECURITY.md) for the contact and disclosure
process.
