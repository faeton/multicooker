# Design notes — deferred ideas

This is where considerations for features we're **not building now** live,
so we don't lose the context. When we eventually get to one, we pick up
the trade-offs from here instead of rederiving them from scratch.

The matching entries live in `docs/todo.md` (status and priority); here
it's why-it's-shaped-this-way, what alternatives were considered, and
what breaks on the easy path.

---

## Multi-account creds (profiles)

**Why deferred.** MVP covers 95% of cases: one user — one account per
flavor. Profiles are needed for (a) separating personal/work, (b)
vendor benchmarks under different subscriptions, (c) a dedicated
judging account.

**Current state.** `creds.py` hardcodes the sources:

- claude (macOS): Keychain entry `"Claude Code-credentials"`.
- claude (Linux): `~/.claude/.credentials.json`.
- codex: `~/.codex/auth.json`.
- gemini: `~/.gemini/oauth_creds.json` + `settings.json`.

Snapshot reads the source and drops it into `cooks/<task>/.auth/<flavor>/`.

**Design.**

1. A `profile:` field in brief.yaml on each participant/judge. Default
   `"default"` ⇒ current behavior.
   ```yaml
   participants:
     - name: claude-work
       flavor: claude
       profile: work
     - name: claude-home
       flavor: claude
       profile: personal
   ```
2. Storage: `~/.multicooker/profiles/<profile>/<flavor>/` —
   filesystem, not Keychain. Flat structure, explicit copies.
3. `creds.py:snapshot_for_profile(flavor, profile)` — if
   `profile == "default"`, current logic. Otherwise read
   `~/.multicooker/profiles/<profile>/<flavor>/`.
4. **Login wrapper** — the murkiest part. `multicooker login
   <flavor> --profile <name>` runs the CLI in a one-shot container
   with an empty `HOME`, the user does OAuth interactively, then a
   snapshot of `$HOME/.<cli>/` is copied into
   `~/.multicooker/profiles/<name>/<flavor>/`.
   - **claude — special case.** On macOS it writes to the Keychain, not
     a file. Inside the container it falls back to `~/.claude/.credentials.json`
     (the Linux fallback). That's **what we want** — we explicitly want
     a file artifact. But it means that for profiles the user gets a
     linux-style `claude` login that's not integrated with the system
     Keychain. Worth documenting.
5. `doctor` validates that `~/.multicooker/profiles/<p>/<f>/` exists
   for every referenced profile before cook.

**What breaks on the easy path.** If you just add `profile:` without a
login wrapper, the user has to manually copy `~/.codex/auth.json` into
`~/.multicooker/profiles/work/codex/auth.json` etc. It works, but it's
bad UX. The login wrapper is the bulk of the work.

**Scope.** Two sessions. Splittable:
- session 1: `profile:` field + manual storage + `doctor` checks.
- session 2: `multicooker login --profile`.

---

## Replayable traces — full version

**Lite version is done.** Per-cell `trace.json` + `multicooker rejudge`.
That's enough to re-judge the same snapshot with a new rubric without
re-cooking.

**What's not done (full).** Structured traces of the model's tool calls:
prompt → tool_calls[] → tool_results[] → final output. Needed for:
- replay through **a different** judge without the original CLI;
- diffing traces between models (claude vs codex on the same task);
- ground truth for regression tests on the CLIs themselves.

**Why it's hard.** The current argv (`--print`, `exec`, `-p`) doesn't
produce structured output. Available modes:

- claude: `--output-format stream-json` — produces JSONL with tool
  calls/results.
- codex: `exec` has `--json` (event stream).
- gemini: at the time of writing, no structured mode.

So switching to structured traces either breaks gemini support, or
requires two modes: structured where available, text dump where not.

**Pragmatics.** If we ever do it — start with claude-only
(`--output-format stream-json`) and dump the others as stdout blobs.
Drop `trace.jsonl` next to `out/`.

**Scope.** At least one session for claude. Full multi-flavor — another.
Not happening until a **concrete** use case shows up.

---

## Registry / versioned task specs

**Idea.** `~/.multicooker/registry/<spec-name>@<version>/` — an arena
template (BRIEF.md, JUDGE_BRIEF.md, brief.yaml.template, raw/).
`multicooker new --from-spec <spec>@<v>` materializes it.

**Why.** Standard arenas: `arc-style`, `code-review-pr@1.2`,
`pr-summary@1.0`. Shared between people/projects, versioned, progress
on a given spec is comparable over time.

**Why NOT now.** Current user base is one person; no registry needed. A
flat git-cloned "task-pack" repo is just as good as long as users number
in the single digits. Building a registry before demand exists is
overengineering.

**If we ever do it.**
- Versioning: semver, immutable. Breaking change in brief.yaml schema
  ⇒ major bump.
- Registry ↔ user override conflict: the registry provides a template,
  the cook-specific brief.yaml overrides it.
- Distribution: git-based registry (`multicooker pull <git-url>` →
  local clone). No central server.
- Required raw materials: a spec can declare `raw/` requirements
  (file globs + checksums); `new --from-spec` fails if the local
  folder lacks the required raw files.

**Scope.** One session for minimal pull-from-git, another for
versioning + validation. Trigger: 3+ users asking.

---

## Sandbox-providers / k8s

**Idea.** A `Runner` abstraction (cook + judge) → interface. Default
impl — Docker Compose (as today). Alternative — a k8s pod runner.

**Why.** Team setup; long-running benchmarks (10+ cooks at once); cooks
with heavy compute (need a GPU node).

**Why NOT now.**
- The current single-machine setup scales to dozens of parallel cooks.
  The bottleneck isn't here.
- The k8s impl is large: NetworkPolicy to reproduce bridge-net
  isolation, Secret for creds (and refresh inside the pod — non-trivial
  for OAuth), PVC for `out/`, Job orchestration instead of Compose.
- Subscription creds in k8s — a separate pain. OAuth refresh usually
  writes back to `~/.<cli>/`; in k8s that's a writable EmptyDir on the
  pod, and the refresh is lost when the pod is deleted. You'd need
  either a persistent per-profile PVC, or a dedicated auth sidecar.

**Pragmatics.** Ahead of a k8s impl, refactoring `compose_runner.py`
behind a `Runner` interface (with a single Compose impl) is useful as
internal cleanup. But without a second implementation it has the smell
of overengineering.

**Scope.** At least 2 sessions: refactor + k8s impl. Trigger: a user
with a k8s cluster and a recurring benchmark task.
