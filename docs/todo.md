# TODO

What's left to do in multicooker — realistic, prioritized. The main
principle hasn't changed: honest, reproducible behavior first, polish
later. The "Done (history)" section at the bottom is a reference for
what's been knocked out in recent sessions.

## Priority 0 — next session

## Priority 1 — after v0.2 cook

- [x] Tests: parse_participant, add_participant, detect_rate_limit
  (with per-CLI fixtures), `judge._anonymize`, `report` aggregation.
  Integration smoke via subprocess on the dummy flavor (auto-skip if
  docker isn't available). 40 tests, 7-8 seconds.
- [x] Integration smoke without real LLM CLIs: the `dummy` flavor is
  ready (`templates/cook/participants/dummy/`, alpine-based, no auth).
  A single entrypoint covers both participant and judge modes
  (branching on `MULTICOOKER_JUDGE`). The full `new→cook→judge→report`
  loop runs in ~10 seconds with no subscription creds.
- [x] Packaging: `templates/` moved inside `multicooker/templates/`;
  all Path references decoupled from `parents[1]` (used to work only
  from the repo, now works after `pip install`). `.dockerignore` in
  every participant template. Wheel build + smoke install into a
  clean venv verified manually.
- [x] CI: GitHub Actions (`.github/workflows/ci.yml`): ruff (E9+F),
  pytest on 3.10/3.12, wheel build, smoke install. Secret scan not
  added yet (separate item below).
- [x] CI: gitleaks for secret scan (separate job in `.github/workflows/ci.yml`).

## Priority 2 — before publishing

- [x] LICENSE — MIT.
- [x] CONTRIBUTING.md (direction + dev loop + flavor extension).
- [x] SECURITY.md (contact + scope + out-of-scope).
- [x] README rewritten around docker-only first-run:
  `doctor → new → cook → judge → report` + refine loop + multi-flavor.
- [x] HOWTO.md synced: removed mentions of `~/.multicooker/auth.env` /
  API keys / host_runner; added a refine section; the "Host-mode vs
  Docker-mode" section replaced with "Docker-mode (the only one)".
- [x] `docs/security.md` — threat model: what Docker protects, what
  it doesn't, how to handle raw/ and creds.
- [x] `examples/hello-task` is now on the dummy flavor — runs without
  LLM creds; added `JUDGE_BRIEF.md` and `examples/hello-task/README.md`.
- [x] `docs/lifecycle.md` — what each step creates, what's safe to
  delete, what `clean` fixes.
- [x] Git history secret scan (gitleaks) wired into CI.

## Auth + creds

- [ ] Extend `creds.py` for the case where the user has multiple
  Anthropic/Google accounts and needs to pick a profile. Right now
  there's one Keychain entry, one gemini config. Design deferred —
  see `docs/design-notes.md` §"Multi-account creds".
- [x] Document the risk: subscription OAuth files are mounted into the
  container and accessible to the agent inside the sandbox. A
  compromised CLI can read them. That's the cost of headless
  subscription auth. (`docs/security.md` §"OAuth files inside the
  sandbox".)
- [x] Watcher for the `claudeAiOauth` key: regression test on a mock
  blob (`tests/test_creds_claude_shape.py`) — 4 cases: good shape,
  unexpected shape, invalid JSON, missing entry. The shape hasn't
  changed once since v0.1; the test is preventive.

## Participant extensibility

- [x] Support N participants instead of hardcoding 3 in the CLI (done
  — `--participants` parses `NAME=FLAVOR`, `add-participant`).
- [x] Support **different models of the same flavor**: brief.yaml
  takes `model:` per participant/judge; compose-render forwards it
  into the container as `MULTICOOKER_MODEL=...`, and each
  entrypoint.sh adds the matching argv (`--model` for claude and
  gemini, `-c model=...` for codex). No model = the CLI picks for
  itself like before.
- [x] Support **new CLIs** without editing the templates:
  `templates/cook/participants/_custom/{Dockerfile,entrypoint.sh}.example`
  + `docs/add-flavor.md` (10-minute step-by-step guide). `new_cook`
  ignores `_*` directories during scaffolding so the example doesn't
  stick to every new cook.
- [x] Per-participant / per-judge timeout: brief.yaml supports an
  optional `timeout_s:` at the participant or judge level; the global
  `timeout_s` / `judge_timeout_s` remains the default. A dynamic
  default based on brief complexity was rejected — no reliable signal.

## Refine

- [x] The refine contract is described in `docs/orchestration.md`
  §"Refine": what survives a round (`out/` stays in `work/`), what
  gets snapshotted (`rounds/N/<p>/` + `rounds/N/_inbox/`), how
  FEEDBACK.md / FEEDBACK_<flavor>.md get inlined into PROMPT.txt,
  the round counter, what does NOT carry over between rounds.
- [x] `multicooker refine --feedback <path>` — point at a FEEDBACK
  file outside cook_dir (to reuse feedback between cooks). Covered
  by an integration test.
- [x] Ability to refine only a subset of participants
  (`--participants`) — covered by integration test
  `test_refine_participants_subset`.
- [x] `multicooker diff <task> N M [--participants ...]` — unified
  diff between rounds, per participant. Handles added/deleted/
  modified/binary, "no changes" notice. Covered by tests
  (`tests/test_diff_rounds.py`).

## Ideas borrowed from analogues

- [x] Replayable traces (light): per-cell `trace.json`
  (prompt/model/exit/duration/started_at) written into
  `work/<p>/trace.json`. `multicooker rejudge <task>` rebuilds
  `_inbox/` from the current `work/<p>/out/` and re-runs the judges
  without re-cooking. The full structured-trace version (tool calls
  / replay through a different CLI) deferred — see
  `docs/design-notes.md` §"Replayable traces — full version".
- [ ] Registry approach (OpenAI Evals): versioned eval/task specs
  shared as templates. Deferred — see `docs/design-notes.md`
  §"Registry / versioned task specs".
- [x] Deterministic validators (AgentV / Iris) — validate brief.yaml
  before running. Implemented as a hand-rolled validator in
  `multicooker/brief_schema.py` (no extra deps), wired into doctor +
  cook/refine/judge. Covered by 13 tests.
- [ ] Sandbox providers à la OpenHands: Docker by default,
  remote/Kubernetes as an option. Deferred — see
  `docs/design-notes.md` §"Sandbox-providers / k8s".

## Don't

- [ ] Don't bring back host-mode. If something stops working without
  it — fix it in docker-mode.
- [ ] Don't add an API-key fallback as a quiet path. If subscription
  auth isn't available, an explicit `doctor`/`cook` error is better.
- [ ] Don't copy participant stderr/stdout into judge input — it
  breaks anonymization.
- [ ] Don't publish the repo with real `cooks/` and `.auth/`.

---

## Done (history, for reference)

- ✅ Shared base images: `templates/base/<flavor>/Dockerfile` installs
  the heavy bits (node:22-slim + apt + `npm i -g <cli>` + `node` user).
  The cook participant Dockerfile shrunk to `FROM mc-base-<flavor>` +
  entrypoint — the cook image build dropped to ~1s from 2-3 minutes.
  CLI: `multicooker build-base [<flavor>...] [--force]`. cook/refine/
  judge call `base_images.ensure_built()` before compose build, so
  it's transparent to the user.
- ✅ `multicooker doctor` extended: check Dockerfile per flavor (FAIL
  if missing both in `cooks/<task>/participants/<flavor>/` and in
  templates), check `mc-base-<flavor>:latest` presence (WARN by
  default, FAIL under `--strict`).
- ✅ Network isolation between containers within one cook: each
  participant and each judge on its own bridge network
  (`net-participant-<name>` / `net-judge-<name>`). Egress to the
  internet is open intentionally (participants need npm/pypi/docs);
  threat model: sandbox = container, not network. A strict allowlist
  is left as opt-in via per-cook `compose.override.yaml`.
- ✅ `compose_runner.py` — build / up / logs-follow / wait / timeout / rm,
  rate-limit detection (migrated into `runner_common.py`), statuses
  ok/rate_limited/timed_out/non_zero_exit.
- ✅ `compose_render.render_compose()` + `creds.snapshot()` wired into
  `cook.py`, `refine.py`, and `judge.py`.
- ✅ Docker-mode became the only mode; the `--docker` flag is gone.
  Host-mode and `host_runner.py` removed.
- ✅ `runner_common.py` as a separate module (RunResult +
  detect_rate_limit + tail) instead of shared private helpers from
  host_runner.
- ✅ Docker judging: materialization via copies, deterministic
  `_work-<judge>` for predictable mounts, collection of
  `outbox/scores.json` + `review.md`.
- ✅ Friendly auth failure: `_snapshot_creds_or_die` catches
  `CredsError`, prints the cause + remediation, exits with 2 and no
  traceback. Used in cook/judge/refine.
- ✅ `multicooker doctor` — preflight for docker + creds, by cook
  name or by a list of flavors.
- ✅ `multicooker add-participant <task> NAME[=FLAVOR]` — extend an
  existing cook without editing brief.yaml by hand.
- ✅ `--participants NAME=FLAVOR` in `new`/`cook`/`refine` supports
  multiple participants of the same flavor (claude-a, claude-b…).
- ✅ `multicooker refine` — round-N iteration over the previous
  output; snapshot into `rounds/<N>/`, inline shared+personal
  FEEDBACK into PROMPT.txt.
- ✅ `multicooker clean` — `compose down -v --rmi local` for a single
  cook or `--all`; flags `--keep-creds`, `--dry-run`.
- ✅ `.auth/` is added to the per-cook `.gitignore` via
  `creds.snapshot()`.
- ✅ Confirmed the `claudeAiOauth` Keychain JSON format is current
  (cook 260509-steamping-design ran with real creds).
- ✅ `cooks/` globally in .gitignore — creds and LLM outputs never
  land in the index.
