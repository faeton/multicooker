# Auth: subscription CLIs in containers without API keys

This is a port/extension of what was in
`reproxy/arena/coding-sandbox/README.md`. Goal: run `claude` /
`codex` / `agy` inside Linux containers on a macOS host, using
subscriptions, without `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` /
`GEMINI_API_KEY`.

## TL;DR — two paths for claude

**Option A (default on macOS): Keychain snapshot.** Before each
`cook` multicooker pulls the credential JSON out of Keychain
(`security find-generic-password -s "Claude Code-credentials" -w`)
and writes it to `cooks/<task>/.auth/claude/.credentials.json`,
which is RO-mounted into `/root/.claude/`. That's the format the
Linux build of claude-code understands directly (same JSON that
Keychain stores as the password value). No `claude /login` needed.
The access token lives ~5 hours, which is plenty for any normal
cook.

**Option B (fallback for Linux hosts or when Keychain is
unavailable): named volume + one-time login** — described in the
sections below. On a Linux host the claude-code client already
keeps creds in `~/.claude/.credentials.json`, so you can bind-mount
directly (essentially option A without the extraction step).

## Where each CLI keeps its creds

| CLI    | macOS host                                          | Linux container               |
|--------|-----------------------------------------------------|-------------------------------|
| codex  | `~/.codex/auth.json` (plain file)                   | `/root/.codex/auth.json`      |
| agy    | **macOS Keychain** (`go-keyring`, svc `gemini` / acct `antigravity`) | `~/.gemini/antigravity-cli/antigravity-oauth-token` (plain JSON) |
| grok   | `~/.grok/auth.json` (plain file)                    | `/home/node/.grok/auth.json`  |
| claude | **macOS Keychain** (can't pull into a container)    | `~/.claude/` (plain files after `claude /login`) |

`codex` and `grok` — simple RO bind-mount. `agy` and `claude` are
trickier (Keychain on macOS).

## codex — bind-mount

In compose:

```yaml
volumes:
  - ${HOME}/.codex/auth.json:/root/.codex/auth.json:ro
```

The CLI reads the token and refreshes it as needed — but because
the mount is RO, the refresh can't write back. In practice the
subscription token lives long, refresh inside the container is
rare. If the token does go stale — refresh on the host (`codex` on
the host), the new file is automatically visible inside the
container on the next cook.

## agy — Keychain snapshot (macOS) / file copy (Linux)

agy (Google Antigravity CLI, the successor to gemini-cli) does **not**
keep its session in a plain file on macOS — it uses the login Keychain
via `zalando/go-keyring`, stored under service `gemini` / account
`antigravity`, with the value wrapped as
`go-keyring-base64:<base64(json)>`.

The Linux build of agy is different: it reads its OAuth token from a
plain file, `~/.gemini/antigravity-cli/antigravity-oauth-token`
(the decoded token JSON), and never touches a keyring. So the snapshot
bridges the two:

- **macOS host:** `creds.py` extracts the Keychain blob
  (`security find-generic-password -s gemini -a antigravity -w`),
  strips the `go-keyring-base64:` prefix, base64-decodes it, and writes
  the result to
  `cooks/<task>/.auth/agy/antigravity-cli/antigravity-oauth-token`.
- **Linux host:** agy already stores that file at
  `~/.gemini/antigravity-cli/antigravity-oauth-token` — it's copied
  verbatim.

Alongside the token, the small `~/.gemini` account-config files
(`oauth_creds.json`, `settings.json`, `google_accounts.json`,
`installation_id`, `trustedFolders.json`) are copied so agy knows which
account the token belongs to. The whole `.auth/agy/` snapshot is mounted
**RW** at `/home/node/.gemini/` (agy refreshes the access token and
writes runtime state under `antigravity-cli/`; RW keeps those writes
cook-local instead of failing). Re-snapshotted each cook, so a host
re-login is picked up automatically.

If you only bind-mounted `oauth_creds.json` (the gemini-cli leftover),
agy would ignore it and drop to interactive Google sign-in — the token
file is the piece that actually authenticates.

## grok — bind-mount

Identical pattern to codex (OAuth oidc token in a single JSON file):

```yaml
volumes:
  - ${HOME}/.grok/auth.json:/home/node/.grok/auth.json:ro
```

The bake-time install drops a static binary and bundled agents into
`/home/node/.grok/` inside the image; the single-file bind only
overlays `auth.json` on top, leaving the rest of the install intact.
Grok's access token lives ~6 hours, comfortably longer than any cook.
Refresh on the host (`grok` interactive once) to rotate.

## claude — named volume + one-time login

On macOS the `claude` token sits in Keychain — you can't
bind-mount it into a Linux container (different OS, different
format). On Linux `claude` keeps the token in `~/.claude/` as
files, so we do auth one time **inside** a Linux container and
save the result into a named volume.

### Initial setup (one time)

```bash
# 1. Build an image with claude-code:
docker build -t mc-claude-base \
  -f templates/cook/participants/claude/Dockerfile.base .

# 2. Log in inside the container, stashing creds into a named volume:
docker run --rm -it \
  -v mc-claude-auth:/root/.claude \
  mc-claude-base \
  claude /login

# claude prints a URL → open it in the browser on the host → authorize.
# The token is written to /root/.claude/ inside the container, which is
# the named volume mc-claude-auth — it survives container removal.
```

`Dockerfile.base` (minimal):

```Dockerfile
FROM node:22-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl && rm -rf /var/lib/apt/lists/*
RUN npm install -g @anthropic-ai/claude-code
WORKDIR /work
```

### On every cook

In the participant's compose service `claude`:

```yaml
volumes:
  - mc-claude-auth:/root/.claude          # from named volume, RW
  - ./BRIEF.md:/work/BRIEF.md:ro
  - ./raw/:/work/raw/:ro
  - ./work/claude/out/:/work/out/:rw
```

`mc-claude-auth` is declared in the `volumes:` section of compose
as an external named volume so it doesn't get recreated by each
`down -v`.

### When the token expires

Re-run the one-time login:

```bash
docker run --rm -it \
  -v mc-claude-auth:/root/.claude \
  mc-claude-base claude /login
```

Symptom: cook launches, in `claude` logs you see "Please run
/login" / "Unauthenticated".

## Isolation: why we don't pass API keys

- Subscriptions are already paid for, keys cost extra $$.
- API keys are long-lived secrets that leak easily through
  `docker history`, `--env`, or screenshots. OAuth tokens in
  bind-mounts only leak if someone walks into the user's
  `~/.codex/` — that's a completely different class of incident.
- We mirror arena's behavior, which has been battle-tested over
  three nights.

## Network side of auth

Containers need egress out to auth domains and APIs:

- claude: `api.anthropic.com`, `console.anthropic.com`
- codex: `api.openai.com`, `auth.openai.com`, `chatgpt.com`
- agy: `antigravity.google`, `*.googleapis.com`,
  `oauth2.googleapis.com`, `accounts.google.com`
- grok: `cli-chat-proxy.grok.com`, `auth.x.ai`, `accounts.x.ai`,
  `x.ai` (installer + binary downloads, build-time only)

For an arena-style allowlist you can stand up a forward-proxy on
the `llm-egress` network with SNI filtering. v0.1 just permits
egress on the bridge network — relying on the fact that inside
the container there's nothing that could bypass extra filtering.
If the task is sensitive — drop an explicit proxy into
`cooks/<task>/compose.override.yaml`.

## Anti-self-judge with containerized auth

Previously (arena, host-mode) anti-self-judge was a "flavor-match"
check. Now, when the judge is a separate container with the same
creds as the participant of the same flavor, it still works: the
judge only sees anonymized `submissions/{A,B,C}/` and has no
access to participants. But style bias remains. If you want it
stricter — bring up two judges of different flavors.
