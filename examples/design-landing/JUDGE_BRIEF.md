# Judge brief: design-landing

You are judging landing-page submissions from anonymous participants
`A`, `B`, `C`, … against the rubric below. You only see anonymized
labels — do not try to guess which model wrote which submission.

Each submission lives in `./submissions/<letter>/out/index.html`.
Read the HTML and the inline CSS as a designer would: imagine the
page rendered, then judge the **design decisions**, not the code
style.

## Rubric

| Dimension | Weight | What you're scoring (0–5) |
|---|---|---|
| visual-hierarchy | 25 | When the page loads, does the eye land on the project name → value prop → CTA in that order? Or is everything the same visual weight? |
| typography | 20 | Are font families, sizes, and line-heights chosen deliberately? Or is it browser-default Times-New-Roman / unstyled `<h1>`? Custom fonts via Google Fonts / system stacks both count as deliberate. |
| color-discipline | 20 | Is there a clear palette (one accent, considered neutrals, intentional contrast) or a random rainbow? Monochrome is fine if it's intentional. |
| content-fit | 20 | Does the copy describe `multicooker` accurately (using the inputs in `./raw/`)? Or does it invent features, fake metrics, or describe a generic SaaS? |
| polish | 15 | Spacing rhythm, alignment, hover states, small touches. Does the page feel finished or thrown together? |

## What to write

To `./outbox/scores.json`, **strict JSON** in this shape:

```json
{
  "scores": {
    "A": { "visual-hierarchy": 4, "typography": 5, "color-discipline": 3, "content-fit": 5, "polish": 4 },
    "B": { "visual-hierarchy": 3, "typography": 3, "color-discipline": 4, "content-fit": 4, "polish": 3 }
  }
}
```

To `./outbox/review.md`, a short paragraph per submission. Be
concrete: quote the actual color values, font choices, or copy
phrases you're reacting to. Avoid vague praise ("looks nice");
prefer specific observations ("uses `#0F172A` for body text on
`#FAFAFA` background, generous 1.7 line-height — comfortable to
read").

## Rules

- Score every submission you receive, even if `index.html` is
  malformed (give 0s for what's missing and say so).
- Use only the rubric dimensions above; don't invent new ones.
- No mention of `claude` / `codex` / `gemini` / `grok` / specific
  model names — the labels are `A`, `B`, `C`, …
- Don't penalize different aesthetic choices against each other.
  A minimal monochrome page and a vibrant accent-color page can
  both score well if internally consistent.
