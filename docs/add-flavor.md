# Adding a new flavor (CLI agent)

Multicooker ships with `claude`, `codex`, `agy`, `grok`, `triad`, and
`dummy`. To add a new CLI agent (e.g. aider, cursor-cli, ollama-runner, a
local binary) — follow this guide. ~10 minutes of copy-paste; most of the
time will go into debugging your CLI's argv.

> **`triad` is a *composite* flavor** — Claude as the lead engineer with
> Codex and Grok installed in the **same cell** as in-cell reviewers it
> consults via Bash. It's the worked example for a flavor that bundles
> several CLIs and several cred sets in one container. See
> [§ Composite flavors](#composite-flavors-triad) below.

## What to decide up front

1. **How does the CLI authenticate?** Via subscription OAuth files on the
   host (like codex/grok), or the OS keyring (like claude/agy)? Via an API
   key in env? No auth
   (like `dummy`)? This affects `creds.py`.
2. **Is there a non-interactive flag?** If the CLI hangs on approval
   prompts in headless mode without something like `--yes`, `--yolo`,
   `--dangerously-bypass-...` — you need to find the equivalent. Without
   it the timeout will kill the round before the CLI prints a single line.
3. **Standalone or with a base image?** If the install is heavy
   (`npm i -g …`, `apt install …`) — go with layout B (shared base).
   Otherwise layout A.

## Quick cheatsheet — which files to create

```
multicooker/templates/
├── base/<flavor>/Dockerfile               (layout B only — heavy install)
└── cook/participants/<flavor>/
    ├── Dockerfile                          ← copy of _custom/Dockerfile.example
    ├── entrypoint.sh                       ← copy of _custom/entrypoint.sh.example
    └── .dockerignore                       ← std (`*` on line 1, `!entrypoint.sh` on 2)
```

And two code edits:

```
multicooker/creds.py               ← add _snapshot_<flavor>(...) + dispatcher
multicooker/brief_schema.py        ← add flavor to KNOWN_FLAVORS
```

## Step by step

### 1. Scaffold the flavor directory

```bash
cp templates/cook/participants/_custom/Dockerfile.example     templates/cook/participants/myflavor/Dockerfile
cp templates/cook/participants/_custom/entrypoint.sh.example  templates/cook/participants/myflavor/entrypoint.sh
chmod +x templates/cook/participants/myflavor/entrypoint.sh
echo $'*\n!entrypoint.sh' > templates/cook/participants/myflavor/.dockerignore
```

### 2. Fill in the Dockerfile

`Dockerfile.example` is not a doc comment — it's a working template with
TODOs. Fix:

- `FROM mc-base-yourflavor:latest` → either your public image (layout A),
  or your base's name (layout B; see step 5).
- `USER node` → a user that exists in the base.

### 3. Fill in entrypoint.sh

`entrypoint.sh.example` has two branches: participant and judge. Contract:

| input  (RO)                       | output                              |
|-----------------------------------|-------------------------------------|
| `/work/PROMPT.txt` (participant)  | `/work/out/RESULT.md`               |
| `/work/JUDGE_BRIEF.md` (judge)    | `/work/outbox/scores.json` + `review.md` |
| `/work/raw/` (both)               |                                     |
| `/work/submissions/A/`, B/, C/ … (judge) |                              |

Reference argv for the existing flavors is inside
`entrypoint.sh.example`. The key things: the non-interactive flag and
forwarding `MULTICOOKER_MODEL` (optional, if the CLI supports model
selection from the brief).

### 4. Wire it into `creds.py`

If the flavor is headless (no auth) — add it to the `elif f == "dummy":
pass` branch in `snapshot()`. If it has subscription creds — write your
own `_snapshot_myflavor(into)`, analogous to the existing `_snapshot_codex`
(plain file) or `_snapshot_agy` (extracts an OS-keyring secret on macOS,
copies a file on Linux). Standard form: check the source exists, copy into
`.auth/<flavor>/<file>` with `chmod 0600`. **Creds must live in a RO
bind-mount** inside the container; the path is wired up in
`compose_render.py`.

### 5. (layout B) Write the base Dockerfile

```bash
mkdir -p templates/base/myflavor
$EDITOR templates/base/myflavor/Dockerfile
```

This is where everything heavy lives: apt packages, runtime (`node:22-slim`
/ `python:3.12-slim`), `npm i -g …` or `pip install …`. Typical shape:

```dockerfile
FROM node:22-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git && rm -rf /var/lib/apt/lists/*
RUN npm i -g <your-cli-package>
RUN groupadd -r node || true && useradd -r -g node -m -s /bin/bash node || true
USER node
WORKDIR /work
```

Build once: `multicooker build-base myflavor`.

### 6. Update the schema

In `multicooker/brief_schema.py` add the name to `KNOWN_FLAVORS`.
Otherwise the brief validator will reject briefs that use your flavor.

### 7. Smoke

```bash
multicooker new add-flavor-test --participants a=myflavor
$EDITOR cooks/<date>-add-flavor-test/BRIEF.md  # any mini task
multicooker doctor add-flavor-test
multicooker cook   add-flavor-test
multicooker judge  add-flavor-test  # you'll need at least one
                                    # judge of a different flavor
multicooker report add-flavor-test
```

`doctor` catches most silly mistakes (missing Dockerfile, unknown flavor
in schema, missing base). `cook` fails with a clear exit code if
`entrypoint.sh` doesn't produce RESULT.md within `timeout_s`.

## Reference: what to copy from where

- **Headless / no auth:** `templates/cook/participants/dummy/` (layout
  A, alpine, ~10-line entrypoint).
- **Subscription OAuth + npm-installed CLI:**
  `templates/cook/participants/claude/` (layout B, base = node:22-slim + npm).
- **Standalone binary via install script:** `agy` (layout B,
  base = debian-slim + `curl … | bash`) — also the example for a CLI
  whose creds live in the OS keyring, bridged to a file by `_snapshot_agy`.
- **Plain-file auth (`~/.<cli>/auth.json`)**: `codex` — the simplest
  example with `_snapshot_codex` in `creds.py`.

## Composite flavors (`triad`)

A *composite* flavor bundles several CLIs in one cell so one model can
drive the others — e.g. `triad` runs **Claude as the lead engineer** with
**Codex and Grok as in-cell reviewers** it calls over Bash. Claude
orchestrates its own build → review → integrate loop; the reviewers never
write to `out/`. Use this shape when you want multi-model review *inside* a
single build rather than the turn-based `consult` loop between builds.

What's different from a single-CLI flavor:

1. **Base image installs all the CLIs** —
   `templates/base/triad/Dockerfile` is the union of the
   `mc-base-{claude,codex,grok}` install steps (npm `@anthropic-ai/claude-code`
   + `@openai/codex`, then the grok install script), all running as `node`.
2. **`creds.py` snapshots every cred set the cell needs.** The `triad`
   branch in `snapshot()` calls `_snapshot_claude_* + _snapshot_codex +
   _snapshot_grok`. They land in distinct subdirs (`.auth/claude`,
   `.auth/codex`, `.auth/grok`) — no collision.
3. **`compose_render._auth_volumes`** returns *all three* RO mounts
   (`/home/node/.claude`, `.codex/auth.json`, `.grok/auth.json`).
   `_usage_volumes` mounts the driver's ledger (claude `projects/`) plus
   codex `sessions/`.
4. **`metrics.collect_usage`** maps the composite to its **driver's**
   collector (`triad → _collect_claude`), so the status line reports the
   lead's tokens. Reviewer spend isn't summed into the headline.
5. **The entrypoint hands the driver a review protocol.**
   `templates/cook/participants/triad/entrypoint.sh` prepends a short "you
   are the lead; here are your reviewer CLIs and how to call them" preamble
   to `PROMPT.txt` before invoking `claude --print`. Judge mode
   (`MULTICOOKER_JUDGE`) skips the preamble and scores plainly.

Everything else (schema, base-image autodiscovery, `add-participant`) is
identical to a normal flavor: `base_images` finds
`templates/base/triad/Dockerfile` automatically; attach it to a cook with
`multicooker add-participant <cook> lead=triad`.

Cost note: a composite cell spends ~N× the tokens (one per model in the
loop) and runs slower — it's the "slow but thorough" lead, not a cheap
competitor. Keep it as the chef/lead, not one of the blind-judged field.

## What NOT to do

- Don't add an API-key fallback as a silent path. If the flavor requires
  an API key — let `_snapshot_<flavor>` fail with an explicit `CredsError`
  ("set FOO env / log in via …"), no silent fallback.
- Don't pile new heavy tools (compilers, datasets) into
  `templates/base/<flavor>/` — the base should stay stable. Keep
  cook-specific deps in the per-cook
  `cooks/<task>/participants/<flavor>/Dockerfile` (it overrides the
  template).
- Don't pin a flavor to a single model. The model is selected via
  `model:` in `brief.yaml` per participant — the entrypoint must
  respect `$MULTICOOKER_MODEL` if the CLI supports it.
