# Security model

What multicooker protects against, what it doesn't, and why.

## TL;DR

- **The container is the sandbox.** Permission-bypass flags
  (`--dangerously-skip-permissions`, `--yolo`,
  `--dangerously-bypass-approvals-and-sandbox`) are required for
  headless operation and are safe inside the container — they
  cannot reach the host.
- **Every cell runs a hardened, non-root container.** `compose_render`
  emits `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`,
  and `user: "1000:1000"` on every participant and judge, and never
  emits anything that loosens Docker's default seccomp. See
  [Container hardening](#container-hardening-cve-2026-31431).
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
| Container escape via Docker / kernel CVEs | Mitigated, not eliminated. The in-container baseline (default seccomp + `cap_drop: ALL` + `no-new-privileges` + non-root) shrinks the attack surface; the *primary* barrier for kernel-CVE escapes is host-side (patched kernel, and for AF_ALG the `algif` modprobe block — see [Container hardening](#container-hardening-cve-2026-31431)). For stronger isolation, run multicooker inside a VM or under rootless Podman / userns-remap. |
| Stealing the participant's own creds | A compromised CLI binary has access to the auth files mounted for it. The cost of headless subscription auth. Mitigation: don't run multicooker with CLIs you don't trust. |
| Network-level data exfiltration | Egress is open. If your `raw/` is sensitive, see "Sensitive raw materials" below. |
| Accidentally including `.env`, secrets in `raw/` | You control `raw/`. We mount it RO; we don't scan it. |
| Re-using a leaked OAuth token | If your subscription creds leak, rotate them with the upstream provider (`claude /login`, `codex` re-auth, `gemini` re-auth, `grok login`). |
| Judge collusion / reward hacking by the model itself | Out of scope — this is an alignment problem, not a tooling one. |

## Container hardening (CVE-2026-31431)

Cells run untrusted, model-driven agents on a kernel **shared with the
host**. That is the exact threat model for local-priv-esc / container-escape
CVEs such as **CVE-2026-31431** ("Copy Fail" — `AF_ALG` / `algif_aead`
escalation via the shared page cache). The posture below is applied
automatically by `multicooker/compose_render.py` to every participant and
judge service:

| Setting | Why |
|---|---|
| Default seccomp profile (never `seccomp=unconfined`) | We never weaken the daemon's profile. Disabling it would re-expose syscalls the agent has no reason to call. |
| `cap_drop: [ALL]` | The CLIs need zero Linux capabilities — TCP/TLS egress, DNS, writes to the bind mounts, and OAuth token refresh all work with none. Nothing is added back. |
| `security_opt: [no-new-privileges:true]` | Blocks setuid/setcap privilege gain inside the cell. |
| `user: "1000:1000"` | Every flavor image is already non-root (uid 1000); pinning it at the compose layer keeps that true even if an image is swapped or a Dockerfile drops its `USER`. |

**The load-bearing rule:** never add `security_opt: seccomp=unconfined`,
`privileged: true`, or a `cap_add` of `SYS_ADMIN`/`SYS_MODULE` to a cell.
`tests/test_compose_hardening.py` fails if the render ever grows one.

### Important: default seccomp does NOT block AF_ALG by itself

A common assumption (including in the original hardening plan) is that
Docker's default seccomp profile already blocks `socket(AF_ALG)`. **That is
not true on current engines** — verified on Docker 29.x / OrbStack
(`docker info` → `seccomp,profile=builtin`), where `socket(AF_ALG,
SOCK_SEQPACKET)` succeeds inside a stock container. So for CVE-2026-31431 the
real barriers live on the **host**, outside this repo:

1. **Patched kernel** (Debian ≥ 6.12.86-1 / DSA-6238-1).
2. **`algif` modprobe block** so the vulnerable modules can't autoload:
   `install algif_aead /bin/false` (+ `algif_skcipher`, `algif_hash`,
   `algif_rng`, `af_alg`).
3. **Actually reboot** after a kernel security upgrade — unattended-upgrades
   installs the new kernel but does not reboot, so the box keeps running the
   old vulnerable one until `/var/run/reboot-required` is acted on.

These belong in host provisioning (Ansible / install-image post-step), not
in multicooker. To check a host's posture from the repo:

```bash
multicooker doctor --security      # probes socket(AF_ALG) in a throwaway container
```

`OK` means the socket is denied at the container layer; `WARN` means it is
creatable, so confirm the host kernel patch + modprobe block (`uname -r`,
`modprobe algif_aead` must fail). Add `--strict` to make the WARN a
non-zero exit for CI gating.

**Optional stronger isolation:** ship a custom seccomp profile that denies
`AF_ALG` and wire it into every cell via `security_opt: seccomp=<profile>`,
or run cells under rootless Podman / Docker userns-remap so even a seccomp
bypass lands as an unprivileged host uid. Both are larger changes; the host
kernel patch + modprobe block remain the primary defense.

## Sensitive raw materials

`raw/` is bind-mounted RO into the participant container, but the
participant has open internet egress. Treat anything in `raw/` as
"the model can see it and may exfiltrate it via API calls or web
fetches." If that's not acceptable:

- Don't put real secrets / PII / proprietary data into `raw/`.
- Or cut egress by adding `network_mode: none` (or a strict allowlist
  proxy) to the cells. Note: the runner invokes `docker compose -f
  compose.yaml`, which **disables** Compose's automatic merge of a
  `compose.override.yaml` — so a drop-in override file does *not* take
  effect. Edit the rendered `compose.yaml` and re-run the cell with
  `docker compose` directly, or patch `compose_render`. multicooker
  doesn't isolate the network by default because most cooks need internet.

## Credential handling

- Source-of-truth on the host:
  - `claude` (macOS): Keychain entry `"Claude Code-credentials"`.
  - `claude` (Linux): `~/.claude/.credentials.json`.
  - `codex`: `~/.codex/auth.json`.
  - `gemini`: `~/.gemini/oauth_creds.json` + `settings.json` etc.
  - `grok`: `~/.grok/auth.json`.
- Per-cook copy: `cooks/<task>/.auth/{claude,codex,gemini,grok}/` —
  mode `0600`, written by `multicooker.creds.snapshot()`, mounted
  RO into the matching participant only.
- Refresh: snapshot re-runs at every cook/refine/judge — token
  rotations on the host are picked up next run. There is no
  long-lived cache.
- Clean-up: `multicooker clean <task>` removes `.auth/` (unless
  `--keep-creds`). `multicooker clean --all` does it for every cook.

## OAuth files inside the sandbox

The price of headless subscription auth: the participant's own
OAuth/session files are bind-mounted into its container so the CLI
can refresh tokens. This means **the agent process inside the
sandbox can read its own creds** — `~/.claude/.credentials.json`,
`~/.codex/auth.json`, `~/.gemini/oauth_creds.json`. A compromised
or prompt-injected CLI could:

- Print the token to its `out/` (then it lands on the host via the
  RW bind-mount), or
- Exfiltrate it over open egress to an attacker-controlled host.

This is **by design and not mitigated**. Reasons:

- Without the creds in the container, the CLI can't authenticate
  in non-interactive mode — and the whole point of multicooker is
  headless subscription use.
- Per-cook bridge networks isolate participants from each other,
  but egress to the public internet is open (npm/pypi/docs/LLM
  APIs), so network-level exfil prevention isn't on the table by
  default.
- Each participant only sees its own creds — claude's container
  has no access to codex's `auth.json`, etc.

What you can do:

- **Don't run multicooker against CLIs you don't trust.** Treat the
  four official CLIs as you'd treat any other tool you log into.
- **Rotate aggressively if a leak is suspected:** `claude /login`,
  re-auth `codex` and `gemini`, `grok login` from the host. The next
  snapshot picks up the new tokens.
- **For high-stakes raw data**, cut egress with `network_mode: none`
  or a strict allowlist proxy — at the cost of breaking package
  fetches. (As above, a drop-in `compose.override.yaml` is *not*
  auto-merged because the runner pins `-f compose.yaml`; edit the
  rendered `compose.yaml` or patch `compose_render`.)

## Anti-self-judging (anonymization)

Anonymization happens in `multicooker/judge.py`:

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
