# Task: design a landing page for `multicooker`

## Goal

Design a single-page landing for the `multicooker` project — a tool
that runs several LLM agents on the same task in parallel docker
sandboxes and has other LLMs score the results.

The page should make it obvious within five seconds what the project
is and why someone would want it. Treat this as a design task, not a
coding task: the visual decisions are the deliverable.

## Inputs

- `./raw/product.md` — what multicooker does and who it's for.
- `./raw/commands.md` — the CLI surface, in case you want to show a
  code snippet.

## Output

`./out/index.html` — a single self-contained file (inline `<style>`
is fine; one or two `<link>` tags to a CDN for fonts / icons is fine
too). It must open correctly when double-clicked, without a build
step.

The page should include, in some order:

1. A hero section that names the project and explains the value in
   one sentence.
2. A short "how it works" — three steps or three blocks, your call.
3. At least one code block showing real CLI usage.
4. A footer with a link to https://github.com/faeton/multicooker.

## Constraints

- One HTML file. No webpack, no React, no build pipeline.
- External CSS frameworks via CDN are allowed but not required. If
  you reach for Tailwind/Bootstrap/etc., the design choices still
  need to be yours, not the framework's defaults.
- No images you can't generate inline (SVG is welcome; `<img src>`
  to a remote URL is not).
- The page must be readable on a 1280px-wide laptop screen. Mobile
  responsive is a plus, not a requirement.

## Anti-goals

- Don't write a full marketing site. One scrollable page.
- Don't lift entire layouts from existing projects you've seen.
  Pastiche is fine; copy-paste is not.
- Don't fake metrics, testimonials, or company logos.

## Success criteria

- **visual-hierarchy** — does the eye land on the right thing first?
- **typography** — are font choices and sizes deliberate and
  readable, or default-browser sad?
- **color-discipline** — is the palette intentional (one accent,
  considered neutrals) or random?
- **content-fit** — does the copy actually describe `multicooker`
  accurately, using the inputs provided?
- **polish** — spacing, alignment, hover states, small touches that
  show care.
