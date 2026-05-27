# Orchestration: what's inside cook / judge

Inspired by reproxy/arena. Each cook gets its own docker compose
project so networks and volumes stay isolated between tasks.

## Picture

```
              cooks/<task>/  (compose project: mc-<task>)
               │
   ┌───────────┬──────┴────┬───────────┬───────────┬───────────┐
   ▼           ▼           ▼           ▼           ▼           ▼
┌──────┐   ┌──────┐    ┌──────┐    ┌──────┐    ┌──────┐    ┌──────┐
│claude│   │codex │    │gemini│    │ grok │    │judge1│    │judge2│
└──┬───┘   └──┬───┘    └──┬───┘    └──┬───┘    └──┬───┘    └──┬───┘
   │          │           │           │           │           │
   ▼          ▼           ▼           ▼           ▼           ▼
 net-      net-         net-        net-       net-        net-
 part-     part-        part-       part-      judge-      judge-
 claude    codex        gemini      grok       <name>      <name>
   │          │           │           │           │           │
   └──────────┴───────────┴───────────┴───────────┴───────────┘
                          │
                          ▼  egress to internet is open
                     (npm / pypi / github / LLM API)
```

## Networks

Each participant and each judge sits on its own bridge network
(`net-participant-<name>` / `net-judge-<name>`). This gives two
properties:

- Containers within one cook **can't see each other**: they're on
  different networks, names and IPs don't resolve. A participant
  can't peek at someone else's `/work/out/` over the network, a
  judge can't ping participants.
- **Egress to internet is open.** Participants legitimately need
  npm / pypi / github / docs / LLM API to solve the task. A strict
  allowlist breaks real cases (packages, datasets, documentation),
  so the default is open egress, and the sandbox guarantee rests on
  the container (cgroup, namespaces, RO bind-mounts), not the
  network.

If a specific cook needs a strict allowlist (sensitive raw, audit
mode), it's added via a local `compose.override.yaml` — that's a
cook-level decision, not the default.

## Participant container

Image: `cooks/<task>/participants/<flavor>/Dockerfile`. Base
template — `templates/cook/participants/<flavor>/Dockerfile`.

Mounts (read-only except `out/`):

| host                                   | container             | mode |
|----------------------------------------|-----------------------|------|
| `cooks/<task>/BRIEF.md`                | `/work/BRIEF.md`      | ro   |
| `cooks/<task>/raw/`                    | `/work/raw/`          | ro   |
| `cooks/<task>/work/<name>/out/`        | `/work/out/`          | rw   |
| (auth) see `docs/auth.md`              | `/root/.codex` etc.   | ro/rw|

No other host paths. In particular **no symlinks** inside `/work/`
pointing outside — they'll resolve to a path outside the CLI's
sandbox and Read/Write/Bash will silently refuse (bug #1 from
reproxy/arena).

CMD is fixed per flavor. **Container = sandbox**, so we use
dangerous-skip flags (without them CLIs in non-interactive mode
hang on approval prompts):

```bash
# claude
claude --print "$PROMPT" --dangerously-skip-permissions --add-dir /work

# codex
codex exec --cd /work --skip-git-repo-check \
      --dangerously-bypass-approvals-and-sandbox "$PROMPT"

# gemini
gemini --yolo -p "$PROMPT"

# grok
grok -p "$PROMPT" --always-approve
```

The prompt ALWAYS goes **before** `--add-dir` (claude), otherwise
the variadic flag eats the positional prompt (bug #2 from
reproxy/arena). The canonical argv reference —
`reproxy/arena/coding-sandbox/host_runner.py:CLI_COMMANDS`.

These flags are safe precisely because:
- the container is isolated from the host (cgroup, network
  namespace, no bind-mounts outside `/work` and creds);
- the participant is on its own bridge network, can't see other
  participants or judges over the network;
- `out/` is the only rw bind-mount, nothing to corrupt there
  except the participant's own result.

## Judge container

After `cook`, multicooker assembles `judging/_judge_input/`:

- copies (NOT symlinks) `BRIEF.md`, `JUDGE_BRIEF.md`, `raw/`;
- copies `work/<participant>/out/` into `submissions/<letter>/`,
  where letter = A/B/C from a random permutation `_mapping.json`;
- the build sits on the host, mounted RO into the judge container.

The judge container gets:

| host                                             | container                | mode |
|--------------------------------------------------|--------------------------|------|
| `cooks/<task>/judging/_judge_input/`             | `/work/`                 | ro   |
| `cooks/<task>/judging/<judge-name>/outbox/`      | `/work/outbox/`          | rw   |
| (auth)                                            | …                        |      |

The judge writes `outbox/scores.json` and `outbox/review.md`.
Format hints live in `JUDGE_BRIEF.md`. The anonymous
`letter→flavor` map sits **only** on the host in `_mapping.json`,
never piped into the container.

## Cell lifecycle

For each `(participant, scenario_or_task)` cell:

1. `docker compose -p mc-<task> up -d <participant>`. Healthcheck
   waits for the CLI to be ready.
2. `docker exec` launches the CLI with a fixed prompt that reads
   `/work/BRIEF.md` + `/work/raw/`, writes to `/work/out/`.
3. Wall-clock cap (`brief.yaml: timeout_s`) kills a hung
   container.
4. On exit: `docker logs` → `cooks/<task>/logs/<participant>/`,
   `out/` is already on the host via bind-mount.
5. `docker compose down -v` for this participant.

Parallelism: all participants come up simultaneously (with a
2-second stagger so Keychain/OAuth don't catch a cold from
simultaneous refreshes — legacy from arena).

## Refine: round N+1 on top of round N

`multicooker refine <task>` — iteration: participants get their
**previous** `out/` as the starting state plus feedback, not a
blank slate. This is a different mode from cook (bake-off from
scratch), and artifacts sit alongside.

### What survives a round, what gets snapshotted

State of round N before launching round N+1:

```
cooks/<task>/
├── work/<p>/out/              ← live output of round N (RW bind-mount)
├── judging/_inbox/<p>/out/    ← sealed copy of round N for judging
└── rounds/                    ← (created on first refine)
```

Before launching round N+1, `refine` does one atomic step:

1. **Snapshot round N** → `rounds/<N>/<p>/` (copytree, not
   symlink). Plus `rounds/<N>/_inbox/` — a sealed copy of the
   judge input so judging history is reproducible too.
2. **Doesn't touch** `work/<p>/out/` — it stays in the RW
   bind-mount for the container, and in round N+1 the participant
   sees its round-N result in place, like "a draft to revise".
3. After round N+1 finishes: `_seal_for_judging()` rebuilds
   `judging/_inbox/` on top (the old inbox now lives only in
   `rounds/<N>/_inbox/`).

Principle: **`work/` is always "the current round", `rounds/<N>/`
is immutable history**. `out/` is never deleted — it just
evolves. If round N+1 broke the result, you can roll back by
copying `rounds/<N>/<p>/` back into `work/<p>/out/` (multicooker
doesn't do this automatically — deliberate user decision).

### FEEDBACK.md and FEEDBACK_<flavor>.md

Refine reads two files **from the cook root** (not from `work/`):

| file                       | purpose                                      |
|----------------------------|----------------------------------------------|
| `FEEDBACK.md`              | shared feedback, visible to all participants |
| `FEEDBACK_<flavor>.md`     | personal feedback for a specific flavor      |

Both are inlined into round N+1's `PROMPT.txt` — under separate
headers ("Shared feedback" and "Personal feedback"). FEEDBACK
files are NOT mounted into the container on their own — only via
the contents of `PROMPT.txt`. This is deliberate: the participant
sees exactly the text we addressed to it, and won't "accidentally"
get feedback written for another flavor.

`FEEDBACK.md` is optional — if missing, refine starts with a
warning and an empty shared block. `FEEDBACK_<flavor>.md` is also
optional — absent ⇒ no personal block is added.

`multicooker refine --feedback <path>` overrides the shared
feedback source with an arbitrary file (outside cook_dir).
Useful when the same feedback applies to several cooks, or
feedback lives in a shared "issue tracker" repo separate from
the arenas. Personal feedback is always read from
`cook_dir/FEEDBACK_<flavor>.md` (per-cook).

One FEEDBACK lives **as many rounds as you don't overwrite it**.
Between rounds, `refine` doesn't clear FEEDBACK files. Want fresh
feedback for round N+2 — rewrite `FEEDBACK.md` by hand before
launching.

### Round counter

`rounds/` defines numbering: if it contains `{1,2}`, then `work/`
holds round 3 (just finished), and the next refine is round 4.
If `rounds/` is empty/absent, `work/` = round 1 (the original
cook), refine = round 2.

Round metadata: `REFINE_<N>.json` (start) and
`REFINE_<N>_RESULT.json` (per-participant statuses). Deleting
them is undesirable — `report` may rely on them for progress
history (see `docs/lifecycle.md`).

### What does NOT carry over between rounds

- `judging/<judge-name>/` (scores) — each round is re-judged
  from scratch via `multicooker judge`. History of past scores
  lives in `rounds/<N>/_inbox/` and in `judging/_logs/`.
- `_mapping.json` — regenerated for each judging (new random
  A/B/C permutation, so the judge doesn't get trained).

## Resource limits and profiles

The same `brief.yaml` runs on a 100 GiB dev laptop and on an 11 GiB
shared VPS. Limits are picked from the **active docker context**
(whatever `docker info` reports) — switch context with `docker context
use <name>` or `DOCKER_HOST=ssh://host` and the same cook automatically
adapts.

Profiles:

| profile | trigger             | per-cell `mem_limit` | per-cell `cpus` |
|---------|---------------------|----------------------|-----------------|
| `large` | host has ≥32 GiB    | not emitted          | not emitted     |
| `medium`| 8–32 GiB            | `2g`                 | `1.0`           |
| `small` | <8 GiB              | `1g`                 | `0.5`           |
| `auto`  | default — detects   | depends on host      | depends on host |

`large` deliberately emits no `mem_limit` / `cpus` so a dev laptop
doesn't get artificially throttled — agents can take whatever the
host has.

**Cheap safeties always emitted** (independent of profile, because they
cost nothing and prevent specific failure modes):

- `pids_limit: 512` — fork-bomb in a participant doesn't take down the IDE
- `oom_score_adj: 500` — under global OOM a participant cell dies before
  matomo/bugsink (which sit at the default `0`)
- `memswap_limit = mem_limit` (when `mem_limit` is set) — without this
  docker defaults `memswap` to `2×mem`, so one runaway cell could quietly
  drain the host's swap
- `logging: json-file max-size=10m max-file=3` — docker journal stays bounded
- `ulimits.nofile: 4096:8192` — FD leak doesn't propagate

**Override precedence** (weakest to strongest):

1. auto-detect from `docker info`
2. `MULTICOOKER_PROFILE=large|medium|small` env var
3. `--profile` CLI flag (`cook`/`refine`/`judge`/`rejudge`)
4. `brief.yaml` top-level `resources.profile`
5. `brief.yaml` per-participant / per-judge `resources:` block:

   ```yaml
   participants:
     - name: claude
       flavor: claude
       resources:
         mem_limit: 4g       # this participant needs more
         cpus: 2.0
   ```

**Capacity preflight**:

```bash
multicooker doctor <cook> --capacity \
    --concurrent-cooks 1 --reserve-mib 2048
```

Reads `docker info` from the active context, sums per-cell limits over
the heaviest phase (cook **or** judge — they run sequentially, so peak
is `max(N_p, N_j)`, not the sum), multiplies by `--concurrent-cooks`,
compares against `MemTotal − reserve_mib`. Fails (exit 1) if the cook
doesn't fit; suggests a smaller profile or fewer cells. For remote
hosts, set `DOCKER_HOST=ssh://on1` before the call — no SSH transport
inside multicooker.

## What we do NOT carry over from arena

- Middlebox / observer / origin containers aren't here — our
  tasks aren't network-related, no SNI to observe. If a specific
  cook needs network monitoring, add an observer to its local
  `compose.override.yaml`.
- Variants (cold/warm) — not yet. If needed, the natural place
  is separate `participants` in brief.yaml with different
  `model:` or env vars.
