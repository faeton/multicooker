# design-landing — same brief, three landings

A design task: each participant (`claude`, `codex`, `gemini`) gets
the same brief — "design a landing page for `multicooker`" — and
each produces its own `out/index.html`. Two judges score the
results blindly against a 5-dimension visual rubric.

The interesting thing about design tasks here isn't picking a
winner; it's seeing **how the same brief collapses into three very
different aesthetic decisions** when each model interprets it. One
model tends toward dense, technical layouts; another toward
generous whitespace and big type; another toward dark-mode
defaults. The rubric is calibrated to not punish any one
direction — internal consistency matters more than which direction
the design picks.

## What you need

- `claude`, `codex`, `gemini` CLIs installed and logged in (or
  comment out flavors you don't have in `brief.yaml`).
- Docker Desktop / colima running.
- A few minutes — design tasks have a 10-minute per-participant
  timeout, but most finish well under that.

## Run

```bash
# Copy this example into your cooks/ as a real cook
multicooker new landing --participants claude,codex,gemini
TASK=$(ls -d cooks/*-landing | tail -1)
cp examples/design-landing/BRIEF.md       "$TASK/"
cp examples/design-landing/JUDGE_BRIEF.md "$TASK/"
cp examples/design-landing/brief.yaml     "$TASK/"
cp examples/design-landing/raw/*          "$TASK/raw/"

# Cook → judge → report
multicooker cook   "$(basename "$TASK")"
multicooker judge  "$(basename "$TASK")"
multicooker report "$(basename "$TASK")"

# Open each result in your browser
open "$TASK"/out/*/index.html
cat  "$TASK"/leaderboard.md
```

## What to look at

When you open the three `index.html` files side-by-side in your
browser, look for:

- **Color palette decisions.** Did the model commit to one accent
  and use neutrals carefully, or did it sprinkle six colors?
- **Typography.** System stack? Custom Google Font? Big-display
  hero vs uniform body type?
- **Layout primitives.** Hero + features grid vs single-column
  scroll vs side-by-side panes.
- **How it described `multicooker`.** Did the copy stick to the
  inputs in `raw/`, or did it invent features?
- **Polish details.** Spacing rhythm, hover states, code-block
  styling, footer treatment.

Then read `leaderboard.md` and each judge's `review.md` — and
notice whether the judges agreed with your eye. They often
disagree with each other on design tasks, which is itself useful
data.

## Iterate

The most useful pattern with design cooks is feedback rounds:

```bash
# Open the leaderboard and the three designs, decide what you want
# to push the models toward — more density, less density, a
# different mood, accessibility fixes, whatever.
$EDITOR "$TASK/FEEDBACK.md"

# Per-participant feedback if one design is close but needs nudging
$EDITOR "$TASK/FEEDBACK_claude.md"

multicooker refine "$(basename "$TASK")"
multicooker judge  "$(basename "$TASK")"
multicooker report "$(basename "$TASK")"
```

Each round goes into `rounds/<N>/` so you can A/B previous rounds
against the latest. `multicooker diff <task>` shows what moved
between two rounds at file level — useful for spotting which model
took the feedback to heart vs which model just rephrased.

## Adapt this for your own design task

Most of what's here is reusable. To repurpose:

1. Rewrite `BRIEF.md` for your subject (a different product, a
   different artifact — logo SVG, README header, dashboard mockup,
   email template). Keep the structure: goal / inputs / output /
   constraints / anti-goals / success criteria.
2. Drop your reference material into `raw/` — brand notes, content
   inventory, competitor screenshots (as `.md` descriptions), etc.
3. Tweak the rubric dimensions in `brief.yaml` and `JUDGE_BRIEF.md`
   to match what you actually care about. Visual hierarchy and
   typography are usually keepers; swap in dimension like
   `brand-fit`, `accessibility`, `density`, or `motion-restraint`
   depending on the artifact.
4. If your output isn't HTML — say it's an SVG or a Markdown email
   template — update the `output` section of `BRIEF.md` and the
   "how to evaluate" guidance in `JUDGE_BRIEF.md`.
