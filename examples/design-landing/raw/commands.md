# multicooker CLI surface

```bash
# Scaffold a new task ("cook"). Name is auto-prefixed with today's date.
multicooker new my-task --participants claude,codex,agy

# Run all participants in parallel, each in its own docker sandbox.
multicooker cook 260516-my-task

# Score outputs blindly with anti-self-judge enforcement.
multicooker judge 260516-my-task

# Aggregate scores into a leaderboard.
multicooker report 260516-my-task
```

Layout of a cook on disk:

```
cooks/260516-my-task/
├── BRIEF.md              ← what participants must do
├── JUDGE_BRIEF.md        ← how judges score
├── brief.yaml            ← participants, judges, timeouts, rubric
├── raw/                  ← reference materials, mounted read-only
├── out/<participant>/    ← what each participant produced
├── judging/              ← anonymized A/B/C copies + judge transcripts
└── leaderboard.md        ← final summary
```

Iterate on the same task:

```bash
$EDITOR cooks/260516-my-task/FEEDBACK.md
multicooker refine 260516-my-task    # round N+1 atop previous output
multicooker judge  260516-my-task
multicooker report 260516-my-task
```
