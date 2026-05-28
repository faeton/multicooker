# Pitfalls: gotchas from reproxy/arena

This is a port of lessons learned from reproxy-arena overnight
runs. We've caught every one of these bugs once already — save
your time, don't catch them again.

## #1. Symlinks inside a CLI sandbox allowlist — don't work

CLI sandboxes (`claude --add-dir <dir>`, `codex --sandbox
workspace-write`) only allow reads/writes inside the named
directory. **If there's a symlink inside the directory pointing
outside — the path resolves to "outside" and Read/Write/Bash will
silently refuse.** No errors, just an empty result.

In arena-judge this manifested as: the judge got `./inbox` and
`./outbox` as symlinks — 97% of scores came out as placeholders.

**Rule:** in CLI sandboxes mount **only real paths**, no
symlinks. If you need to "show" a file — copy it (`cp`), don't
symlink. This matters especially in `judge`: materials in the
judge's work-dir are always copies.

## #2. Variadic argv flags eat the positional prompt

```bash
# BROKEN:
claude --add-dir /work --print "prompt"
# claude treats "prompt" as one more path for --add-dir,
# stdin is empty, output is 0 bytes.

# CORRECT:
claude --print "prompt" --add-dir /work
```

Same happens with codex and gemini — check argv order against
`reproxy/arena/coding-sandbox/host_runner.py:CLI_COMMANDS`.
That's the reference.

## #3. exit-code = 0 ≠ all good

All three CLIs (claude, codex, gemini) return 0 even when they've
hit a rate-limit, because they "successfully reported the limit".
If you go by exit-code, you'll mark a rate-limited cell as
successful.

**Rule:** always parse stderr for known-bad patterns. The
patterns are in `multicooker/host_runner.py:_RL_PATTERNS`, legacy
from arena.

## #4. Codex quota once every ~5 hours

OpenAI ChatGPT Plus quota typically resets every ~5 hours. Codex
often dies mid-cook, the other participants must not be blocked.

**Rule:** rate-limit on one participant = `deferred` flag for
that slot, the others keep going. No inline sleeps. Resume is a
separate flow (`multicooker resume <task>`, in TODO for v0.2).

## #5. Don't trust the leaderboard of the first run

reproxy-arena overnight #1 showed gemini > codex > claude. After
fixing the argv bug and judge symlinks, the order changed. If
the smoke test isn't green — the leaderboard means nothing.

**Rule:** before trusting results, confirm:
- do all three CLIs basically work (`out/RESULT.md` is
  non-empty);
- did the judge write `scores.json` with real numbers, not
  placeholders;
- is the A↔flavor mapping randomized per-run, not cached.

## #6. macOS sleep kills API connections

Lid closed → `caffeinate -dimsu` sometimes doesn't help
(clamshell mode without external power) → connections to
Anthropic API drop. Symptom: a participant exited early with
some transient error.

**Rule:** wall-clock vs monotonic skew > 60s = the laptop slept.
One retry. Logic is in arena `host_runner.py`. For cook in a
container this works differently (Docker should reconnect after
wake on its own), but a wall-clock detector won't hurt.

## #7. Artifacts eat disk

reproxy-arena: 4.3 GB in two nights. In multicooker an artifact
= only `cooks/<task>/`, no round snapshots, the limit is lower.
But the habit of cleaning old cooks is useful:

```bash
find cooks/ -maxdepth 1 -type d -mtime +30 -name '[!_]*' -print
# review → delete → rebuild leaderboard if needed
```

## #8. Stagger when starting parallel CLIs

If you bring up three CLIs simultaneously — they all hit auth
refresh at the same time. Keychain (for claude on the host) or
OAuth refresh endpoints (for codex/gemini) under load can return
a transient error.

**Rule:** 2-second stagger between launches. Inherited from
`multicooker/host_runner.py:run_all`.

## #9. Don't write markdown instructions in place of a prompt

If you stick "don't do X" into `BRIEF.md` — the participant will
read it but won't necessarily honor it. **If something is
critical for scoring — it goes into the prompt, not into a
file.** In multicooker the container prompt = "Read
/work/BRIEF.md and complete the task" + optionally hard rules.
Append hard rules to `Dockerfile.cmd` or to the wrapper, not to
`BRIEF.md`.

## #10. Rubrics drift between BRIEF and JUDGE_BRIEF

The most common "scores are random" — the rubric in
`JUDGE_BRIEF.md` is out of sync with what's promised in
`BRIEF.md`. Check: after editing one, open the other and make
sure the dimensions match by id, weight, and scale. `multicooker lint`
now catches the id-coverage half of this (and `cook`/`refine` refuse to
run when a rubric dimension id is missing from `JUDGE_BRIEF.md`), but
weight/scale wording still needs a human eye. **Upgrade note:** because
this gate is new, an older cook whose `JUDGE_BRIEF.md` already drifted
will start failing on the next `cook`/`refine` — run `multicooker lint
<task>` to see exactly which dimension ids to add.

## #11. Participant's stderr contains its flavor's fingerprints

`claude` writes "Claude is thinking..." etc. to stderr. If those
logs reach the judge — anonymization is blown. **Rule:** into
`judging/_inbox/<p>/` we copy **only `out/`** plus a sanitized
`meta.json` (`exit_class` + `round`, never flavor/model/name). We
do **not** copy `logs/`, `PROMPT.txt`, `trace.json`, or `usage/` —
those name the flavor and the judge tree is built straight from
`_inbox/<p>/`.

## #12. `outputs.required` paths must survive the seal

Required-output validation runs against `work/<p>/out/`, but judges only
ever see the *sealed* copy, and `copytree_clean` strips `.gitignore`
basenames and build-dir names (`node_modules`, `dist`, `build`, `target`,
…) on the way into `judging/_inbox/<p>/out/`. So a required path whose
basename collides with that ignore list (e.g. `required: build/index.html`)
can pass validation yet vanish from the submission the judge scores.
**Rule:** keep required outputs plain top-level files like `RESULT.md` /
`PROPOSAL.md`; don't point them at build-artifact directories.
