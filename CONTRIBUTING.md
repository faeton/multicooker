# Contributing to multivarka

Thanks for your interest. multivarka is a small, opinionated tool —
contributions that match the existing direction are welcome.

## Direction (read before sending PRs)

- **Docker-only.** Host-mode was removed in v0.2 and is not coming
  back. If something only works on the host, fix it in docker-mode.
- **Subscription auth, no API keys.** The whole point is headless
  use of `Claude Pro` / `ChatGPT Plus` / `Gemini Advanced` without
  paying twice. Don't add silent API-key fallbacks.
- **Dangerous CLI flags inside the container are intentional.**
  `--dangerously-skip-permissions`, `--yolo`, `--dangerously-bypass-…`
  exist because the container is the sandbox. Don't try to "fix" them.
- **Per-cook isolation.** Cooks don't see each other; participants in
  one cook don't see each other; judges never see participant logs.
  Anything that erodes this is a regression.

If unsure whether your idea fits, open an issue first.

## Dev loop

```bash
git clone https://github.com/<you>/multivarka
cd multivarka
pip install -e . pytest ruff build

pytest -q                          # 40 tests, ~8s with docker
ruff check multivarka/ tests/ --select=E9,F
```

The integration test (`tests/test_integration_dummy.py`) auto-skips
when docker isn't reachable. With docker up it runs the full
`new → cook → judge → report` cycle on the `dummy` flavor in ~10s
without any LLM credentials.

## Adding a new participant flavor

Step-by-step guide: [`docs/add-flavor.md`](docs/add-flavor.md).
Boilerplate to copy from:
[`templates/cook/participants/_custom/`](multivarka/templates/cook/participants/_custom/)
(Dockerfile.example + entrypoint.sh.example).

TL;DR — minimum touch list:

1. `templates/cook/participants/<flavor>/Dockerfile` — slim layer on
   top of `mv-base-<flavor>` (or self-contained, like `dummy`).
2. `templates/cook/participants/<flavor>/entrypoint.sh` — reads
   `/work/PROMPT.txt`, writes into `/work/out/`. Branches on
   `MULTIVARKA_JUDGE` for judge mode.
3. (optional) `templates/base/<flavor>/Dockerfile` — heavy bits
   (`npm i -g <cli>`, apt deps) so cook builds stay fast.
4. Auth snapshot in `multivarka/creds.py` if the CLI has
   non-trivial credentials on the host (or no-op for headless).
5. Add the flavor to `KNOWN_FLAVORS` in
   `multivarka/brief_schema.py`.

## Style

- Russian or English in commits/issues — both fine. Code/docstrings
  in English.
- Small commits, one logical change per PR.
- No trailing summaries in commit messages — the diff speaks.

## Reporting bugs / security

- Functional bugs → GitHub issues.
- Security issues → see `SECURITY.md`.
