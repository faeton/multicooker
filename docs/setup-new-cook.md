# Setup: new cook

Step by step — how to bring up a new task in multicooker. All
commands run from the repo root `~/Sites/multicooker/`.

## 0. Prerequisites

- Docker Desktop / Orbstack / Colima is running.
- The flow from `docs/auth.md` has been done once (creds for all
  flavors are available in containers).
- `pip install -e .` has been run in the repo.

## 1. Scaffold the folder

```bash
multicooker new my-task
```

Creates `cooks/my-task/` by copying `templates/cook/`:

```
cooks/my-task/
├── BRIEF.md             # you write the task here
├── brief.yaml           # participants, timeouts, rubric
├── JUDGE_BRIEF.md       # instructions for the judge + rubric
├── raw/                 # you drop reference materials here
├── participants/        # Dockerfile per flavor (inherited from templates/)
│   ├── claude/Dockerfile
│   ├── codex/Dockerfile
│   ├── agy/Dockerfile
│   └── grok/Dockerfile
└── judge/               # judge Dockerfile (per flavor)
```

`work/` and `judging/` are created at `cook` / `judge` time.

## 2. BRIEF.md

The template hints at the structure. At minimum:

- **Goal** (1 paragraph) — what we're doing.
- **Inputs** — `BRIEF.md` itself, `raw/` (RO), optionally
  `raw/CONTEXT.md`.
- **Output** — what should land in `/work/out/` (always a
  `RESULT.md`, plus artifacts if needed).
- **Constraints** — timeout, no network except the API.
- **Success criteria** — rubric. The same dimensions must appear
  in `JUDGE_BRIEF.md`.

Ambiguity in the task statement — fine, that's where participants
diverge. Ambiguity in the success criteria — a bug.

## 3. brief.yaml

```yaml
name: my-task
timeout_s: 1800            # per participant
judge_timeout_s: 900       # per judge

participants:
  - {name: claude, flavor: claude}
  - {name: codex,  flavor: codex}
  - {name: agy,    flavor: agy}

judges:
  - {name: claude-judge, flavor: claude}
  - {name: agy-judge, flavor: agy}

rubric:
  scale: [0, 5]
  dimensions:
    - {id: correctness,  weight: 40}
    - {id: quality,      weight: 25}
    - {id: honesty,      weight: 20}
    - {id: completeness, weight: 15}
```

Anti-self-judge: if a judge is the same `flavor` as one of the
participants, multicooker prints a WARN. Want it strict — add a
third flavor to the judges and remove the matching one.

## 4. JUDGE_BRIEF.md

Same rubric as in `brief.yaml`, with a description of each
dimension and the schema for `scores.json`. If you edit the
rubric — edit both files.

## 5. raw/

Drop PDFs, CSVs, samples, other people's repos. All of it is
mounted read-only into `/work/raw/` for every participant. Never
put secrets here — the participant can read them.

## 6. Custom tools in the container

If the task needs `tshark`, `pandas`, a Go compiler, etc. — edit
**the Dockerfile inside this cook**, not `templates/cook/`.
Reason: cooks are independent, new tasks shouldn't bloat the
template.

## 7. Launch

```bash
multicooker cook   my-task     # brings up N containers in parallel
multicooker judge  my-task     # anonymizes and runs the judges
multicooker report my-task     # writes cooks/my-task/leaderboard.md
```

Between `cook` and `judge` you can peek at
`cooks/my-task/work/<p>/out/` — what participants produced before
anonymization.

## 8. What not to do

- Don't edit `cooks/my-task/work/<p>/` after `cook` — that's no
  longer the participant's result. Want to give a hint — update
  `BRIEF.md` / `raw/` and re-run cook.
- Don't put artifacts outside `cooks/<task>/`. Cross-cook
  comparison is a future feature, it doesn't exist now.
- Don't hand the judge a participant's `stderr.log` — it'll catch
  phrases like "Claude is thinking" and the whole point of
  anonymization is gone.
