# Security policy

## Scope

multivarka runs LLM agents (`claude`, `codex`, `gemini`) inside Docker
containers with `--dangerously-skip-permissions` / `--yolo` /
`--dangerously-bypass-…` flags. These flags **are intentional** — the
container is the sandbox. The threat model is documented in
[`docs/security.md`](docs/security.md). Read it before reporting.

## Reporting a vulnerability

If you believe you've found a security issue, please **don't** open a
public GitHub issue. Email **faeton@gmail.com** with:

- a description of the issue;
- a minimal reproducer if possible;
- the multivarka commit / version you tested.

I'll acknowledge within 7 days. Please give me 30 days to ship a fix
before public disclosure unless the issue is being actively exploited.

## Out of scope

The following are **known and intentional** — please don't report them:

- LLM CLIs run with permission-bypass flags inside containers.
- Containers have open egress to the public internet (npm, pypi,
  GitHub, model APIs). Cross-participant isolation is via separate
  bridge networks; sandboxing is via the container, not the network.
- Subscription OAuth files are bind-mounted RO into containers. A
  compromised CLI binary would have access to its own creds. This is
  the unavoidable cost of headless subscription auth.
- `cooks/` is gitignored; if you commit it on purpose, that's on you.

## What's in scope

- Anything that lets one participant read another participant's
  `out/` or logs in the same cook.
- Anything that lets a judge see the `A↔flavor` mapping or
  participant logs.
- Anything that lets a container reach files on the host outside
  the documented bind mounts.
- Credential leaks from `.auth/` to places other than the intended
  per-flavor RO mount.
