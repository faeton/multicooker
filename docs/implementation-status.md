# Implementation status

What actually works in the repo right now vs what's described in
`CLAUDE.md` / `docs/` as the target (and only supported) behavior.
If `multicooker cook --docker` fails with "not implemented" — this file
shows what needs to be written.

## Target behavior (see CLAUDE.md, docs/orchestration.md)

- All participants and judges in containers, in parallel.
- Subscription auth via bind-mount / named volume.
- Dangerous-skip / bypass / yolo flags inside containers.
- Per-service bridge networks: `net-participant-<name>` /
  `net-judge-<name>`. No visibility between containers, egress is open
  (see `docs/orchestration.md`).
- Anonymization and copy (not symlink) for judges.

## What's actually in the code (v0.1)

| component                              | state                                                  |
|----------------------------------------|--------------------------------------------------------|
| `multicooker new <task>`                | ✅ works, copies `templates/cook/`                      |
| `templates/cook/BRIEF.md/brief.yaml/JUDGE_BRIEF.md` | ✅ present                               |
| `templates/cook/participants/<f>/Dockerfile` | ✅ present, but **not used** by the runtime       |
| `multicooker cook <task>` host-mode     | ✅ works (`host_runner.py`) — temporary fallback        |
| `multicooker cook <task> --docker`      | ❌ `error: --docker mode not implemented in v0.1`       |
| `multicooker judge <task>`              | ✅ host-mode; copies (doesn't symlink) — that's right   |
| `multicooker judge <task> --docker`     | ❌ nope                                                 |
| Subscription auth in containers        | ❌ not wired up                                         |
| compose.yaml per cook                  | ❌ not generated                                        |
| Per-service bridge networks            | ✅ `net-participant-<n>` / `net-judge-<n>` per cook     |
| Allowlist egress proxy                 | ❌ opt-in via compose.override.yaml, not default        |

## What needs doing to bring the code in line with CLAUDE.md

### 1. Auth setup (`multicooker init-auth`)

New command. See `docs/auth.md` — it checks/prepares:
- `~/.codex/auth.json` is present;
- `~/.gemini/oauth_creds.json` is present;
- builds the `mc-claude-base` Docker image;
- runs interactive `claude /login` in a container with the named
  volume `mc-claude-auth`;
- echo-test all three.

### 2. compose template in `templates/cook/`

`templates/cook/compose.yaml.tmpl` — generated on `cook` into
`cooks/<task>/compose.yaml`. Parameterized via `cooks/<task>/.env`.
Skeleton is in `docs/orchestration.md`.

Hard rules in the template:
- argv order per flavor (see CLAUDE.md);
- dangerous-skip flags (the container IS the sandbox);
- per-service bridge networks (`net-participant-<n>`, `net-judge-<n>`);
- volumes: bind-mount BRIEF/raw RO, out/ RW, auth.

### 3. `compose_runner.py`

Replaces `host_runner.py` (or lives next to it; host stays as a
deprecated fallback). Contract:

```python
def run_cell(cook_dir, participant_name, flavor, timeout_s) -> CellResult:
    # docker compose -p mc-<task> up -d participant-<name>
    # docker logs --follow → parse rate-limit signatures
    # wait timeout / exit
    # docker compose -p mc-<task> rm -fv participant-<name>
    ...
```

Rate-limit parsing — port from `host_runner.py:_RL_PATTERNS` one to one,
the stream source changes to `docker logs --follow`.

### 4. `cook.py` via compose

```python
def cook(name, root, ...):
    cook_dir = root / name
    if not (cook_dir / "compose.yaml").exists():
        render_compose(cook_dir, brief)
    sh(["docker", "compose", "-p", project, "build"])
    futures = []
    with ThreadPoolExecutor(max_workers=len(participants)) as ex:
        for i, p in enumerate(participants):
            time.sleep(2 * i)                          # stagger
            futures.append(ex.submit(run_cell, ...))
        results = [f.result() for f in futures]
    sh(["docker", "compose", "-p", project, "down", "-v"])
    write_run_result(...)
```

The `--docker` flag stops being opt-in (becomes the default). The host
branch is either deleted, or lives under `--legacy-host` for development.

### 5. `judge.py` via compose

Same as cook, only:
- materialize `judging/_judge_input/` (copies, not symlinks — already
  done correctly in the current `judge.py`);
- compose service per judge;
- copy `outbox/` back after `down`.

### 6. (optional) egress allowlist proxy

A transparent HTTP/HTTPS forward proxy on the `egress` network,
filtering by SNI against a list of auth+API domains. Tinyproxy / squid
/ Caddy — any will do. For the first docker iteration it's not a
blocker, but desirable later.

## Risks / open questions

- **claude /login UX.** Open a URL in the host browser, copy the
  callback — standard procedure for claude-code on Linux. A Mac user
  has never seen this. The `init-auth` script should explicitly say
  "a URL is about to open, log in".
- **Docker Desktop license** on corporate Macs. Workaround: Orbstack
  or Colima.
- **docker network limit.** Each cook = its own network. Clean up
  finished ones: `docker network prune`.

## What NOT to do

- Don't wire in API keys as a "subscription expired" fallback. Better
  an explicit fail than a quiet upgrade to the paid path.
- Don't try to extract the claude token from the macOS Keychain via
  bind-mount — the format is binary and OS-specific. Only named
  volume + one-shot `/login`.
- Don't add a middlebox/observer "just in case" — that's
  reproxy-specific. If a particular cook needs it, it adds it via
  `cooks/<task>/compose.override.yaml`.
- Don't remove dangerous-skip flags "for safety". The container IS
  the sandbox; without the flags the CLIs will hang on an approval
  prompt.
