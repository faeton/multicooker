# hello-task — sanitized smoke example

A trivial task (write a haiku about reproxy) on the `dummy` flavor, with
no subscription creds. Runs locally in ~10 seconds and exists for two
reasons:

1. To show the shape of a cook (BRIEF.md / JUDGE_BRIEF.md / brief.yaml /
   raw/) on a minimal but meaningful example.
2. To provide a ready-made smoke scenario that doesn't need LLM access.

## Run

```bash
# Copy the example into your cooks/ as a regular cook:
multicooker new hello-smoke --participants a=dummy,b=dummy,c=dummy
cp examples/hello-task/BRIEF.md       cooks/$(date +%y%m%d)-hello-smoke/
cp examples/hello-task/JUDGE_BRIEF.md cooks/$(date +%y%m%d)-hello-smoke/
cp examples/hello-task/raw/about.md   cooks/$(date +%y%m%d)-hello-smoke/raw/

multicooker cook   $(date +%y%m%d)-hello-smoke
multicooker judge  $(date +%y%m%d)-hello-smoke
multicooker report $(date +%y%m%d)-hello-smoke
```

The `dummy` flavor:

- participant copies `PROMPT.txt` → `out/RESULT.md` (no model calls);
- judge assigns fixed scores and writes a review with `A/B/C` labels.

Want to try it on real agents? Change `flavor: dummy` in `brief.yaml` to
`claude`/`codex`/`gemini` — otherwise the example is shaped exactly like
a "real" cook.
