# multicooker — notes for Claude

multicooker is an arena for LLMs: one task, several participants
(`claude` / `codex` / `gemini`) solve it in parallel **each in its
own docker container** with subscription auth, then judges (also
LLMs in containers) compare and score the results. The architecture
is inherited from `~/Sites/reproxy/arena/` (branch `archive/arena`)
— compose orchestration, anti-self-judge, anonymization, rate-limit
handling.

## Hard rules

1. **Everything in docker.** This is not "a future migration" — it's
   the design: the container is itself an OS-level sandbox, and
   that's exactly why participants are launched with
   **dangerously-skip / bypass / yolo** flags. Without them the CLIs
   hang on approval prompts in non-interactive mode. Inside the
   isolated container those flags are safe — they can't reach the
   host.
2. **No API keys.** Subscription credentials (`Claude Pro`,
   `ChatGPT Plus`, `Gemini Advanced`) are passed into the container
   from the host: bind-mount files for codex/gemini, a named volume
   with one-time `claude /login` for claude. See `docs/auth.md`.
3. **New task = new folder `cooks/<name>/`** via
   `multicooker new <name>` — copies the skeleton from
   `templates/cook/`. The name is auto-prefixed with today's date:
   `multicooker new foo` → `cooks/260509-foo/` (if a `YYMMDD-`
   prefix is already there, it's not duplicated). All subsequent
   commands use the full name with the date: `multicooker cook
   260509-foo`. Never edit someone else's cooks, never write
   artifacts outside `cooks/<name>/`.
4. **Parallelism.** All participants start at the same time (with a
   2-second stagger for auth refresh), independently of each other.
   One being rate-limited doesn't block the others.

## Permission flags in containers (important)

Canonical argv per flavor (see
`reproxy/arena/coding-sandbox/host_runner.py` for the canonical
ordering — getting the order wrong breaks the CLI):

```bash
# claude  (prompt ALWAYS before --add-dir, otherwise the variadic --add-dir eats it)
claude --print "<prompt>" --dangerously-skip-permissions --add-dir /work

# codex
codex exec --cd /work --skip-git-repo-check \
      --dangerously-bypass-approvals-and-sandbox "<prompt>"

# gemini
gemini --yolo -p "<prompt>"
```

These dangerous flags are a **deliberate and mandatory** condition,
not a workaround. They guarantee:

- the participant won't hang on "may I write to ./out/RESULT.md? [y/N]";
- but at the same time it can't reach the host, because the
  container *is* the sandbox.

Network isolation between containers: each participant and each
judge is on its own bridge network (`net-participant-<name>` /
`net-judge-<name>`). Containers in the same cook don't see each
other via DNS/IP, so a participant can't peek at another's `out/`.
Egress to the internet is open: participants legitimately reach
out to npm/pypi/docs/github to solve the task. The container is
the sandbox, not the network.

## Canonical flow

```bash
multicooker new <task>                 # → cooks/<task>/ from templates/cook/
$EDITOR cooks/<task>/BRIEF.md          # WHAT participants must do
$EDITOR cooks/<task>/brief.yaml        # WHO, timeouts, rubric
$EDITOR cooks/<task>/JUDGE_BRIEF.md    # HOW to judge (rubric == brief.yaml)
cp <refs>... cooks/<task>/raw/         # references (RO mount)

multicooker cook   <task>              # parallel run in containers
multicooker judge  <task>              # anonymized judging in containers
multicooker report <task>              # → cooks/<task>/leaderboard.md
```

## When asked to "make a new arena for X"

1. `multicooker new <task>`.
2. Rewrite `BRIEF.md`: goal, inputs (will arrive in `/work/raw/`
   RO), what must be in `/work/out/`, success criteria.
   Ambiguity in the problem statement — ok (that's where
   participants diverge); ambiguity in the success criteria — not
   ok.
3. Keep the rubric in sync between `brief.yaml`
   (`rubric.dimensions`) and `JUDGE_BRIEF.md` (the table + JSON
   schema for `scores.json`).
4. Reference materials → `raw/`.
5. If the task needs custom tools in the container (`tshark`,
   `pandas`, a Go compiler) — add them to the Dockerfile of **this
   cook**, not the template. Cooks are independent.
6. `multicooker cook <task>` → `judge` → `report`.

Before an overnight run — skim `docs/pitfalls.md`.

## Isolation (as in reproxy/arena)

- Each participant — its own container on its own bridge network
  `net-participant-<name>`. Sees: `/work/BRIEF.md` (RO),
  `/work/raw/` (RO), `/work/out/` (RW), its own creds. **Doesn't
  see**: other participants (they're on other networks),
  `judging/`, the `A↔flavor` mapping, the rest of the repo.
- Egress to the internet is open. Deliberate: participants need
  access to LLM API + npm/pypi/github/docs. Sandbox guarantee is
  the container, not the network. If a specific cook needs a hard
  allowlist, do it via a local `compose.override.yaml`.
- Judge — a separate container on its own `net-judge-<name>`, no
  access to participants. Receives **copies** (not symlinks) of
  `BRIEF.md` / `JUDGE_BRIEF.md` / `raw/` / the anonymized
  `submissions/{A,B,C}/`. Symlinks into the CLI's sandbox
  allowlist don't work — bug #1 from reproxy/arena.
- `_mapping.json` (A→claude, B→codex, ...) lives **only** on the
  host, never goes into containers.

Details — `docs/orchestration.md`.

## Further reading

- `README.md` — TL;DR for the user.
- `HOWTO.md` — long description of mechanics and lessons learned.
  Still mentions host-mode (legacy v0.1 fallback) — ignore that,
  the target mode is docker.
- `docs/setup-new-cook.md` — step by step: how to make a new cook.
- `docs/orchestration.md` — compose layout, networks, mounts, argv
  per flavor, what runs in which container.
- `docs/auth.md` — subscription-based auth in containers without
  API keys.
- `docs/pitfalls.md` — gotchas inherited from reproxy/arena.
- `docs/implementation-status.md` — what already works in code,
  what still needs to be written (if `multicooker cook --docker`
  is failing with "not implemented" — this is the place).
