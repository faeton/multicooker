# Task: design several divergent UI concepts for one workflow

## Goal

Design three genuinely different UI concepts for the workflow described
in `./raw/product.md` and `./raw/workflow.md`. The goal is not to pick a
single safe layout; the goal is to explore distinct interaction models
that a product team can compare side by side.

Treat this as a design and product thinking task. The visual and
interaction decisions are the deliverable.

## Inputs

- `./raw/product.md` - product, users, tone, and constraints.
- `./raw/workflow.md` - the workflow the UI must support.
- `./raw/data.md` - sample data, states, or content the concepts should
  render.

## Output

Write these files under `./out/`:

1. `concept-a/index.html`
2. `concept-b/index.html`
3. `concept-c/index.html`
4. `RESULT.md`

Each concept must be a self-contained HTML file that opens from
`file://` with no build step. Inline CSS and JavaScript are allowed.
One or two CDN links for fonts or icons are allowed, but the page must
not depend on remote images.

`RESULT.md` must include:

- one paragraph describing each concept's organizing idea;
- a comparison table across layout paradigm, visual mood, information
  density, interaction model, and tradeoffs;
- what is mocked or incomplete.

## Constraints

- Three concepts, not one concept with three color palettes.
- Concepts must differ on at least two of: layout paradigm, navigation,
  information density, interaction model, visual language, or primary
  metaphor.
- Use the sample data from `./raw/data.md` where possible.
- Each concept should be understandable on a 1280px laptop viewport.
  Mobile responsiveness is a plus if the workflow needs it.
- Keep files self-contained. No build system, no React app, no package
  install.

## Anti-goals

- Do not make a marketing landing page unless the workflow itself is a
  landing page.
- Do not fake product metrics, customer quotes, logos, or capabilities.
- Do not copy a known product UI wholesale.
- Do not submit wireframes with no visual decisions.
- Do not bury the required workflow behind decorative hero content.

## Success criteria

- **concept-spread** - the three concepts are meaningfully different,
  not reskins of the same layout.
- **workflow-fit** - the UI supports the actual user workflow and uses
  the provided data honestly.
- **interaction-quality** - states, controls, navigation, and feedback
  are coherent for the task.
- **visual-craft** - typography, spacing, color, hierarchy, and motion
  feel deliberate and finished.
- **honesty** - `RESULT.md` names tradeoffs, mocked behavior, and
  incomplete pieces without overselling.
