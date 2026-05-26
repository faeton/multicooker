# Changelog

Notable changes to multicooker. Newest first.

## Unreleased

### Added
- **`grok` flavor.** xAI's CLI is now a first-class participant /
  judge alongside `claude` / `codex` / `gemini`. Uses
  `~/.grok/auth.json` (OAuth oidc, ~6h token), single-file RO
  bind-mount into the container, codex-style headless invocation
  (`grok -p "$PROMPT" --always-approve`). Pinned to
  `GROK_VERSION=0.1.220` in the base Dockerfile; override via
  `--build-arg`. Models: `grok-build` (default), `grok-build-latest`.
  See `docs/auth.md` for the cred layout.
