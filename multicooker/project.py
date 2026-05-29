"""Single source of truth for compose project naming + namespace resolution.

Every command that talks to docker must compute the SAME compose project name
for a given cook — otherwise `docker compose -p <name>` diverges and a later
`cancel`/`clean` can't find the containers `cook` created. The name is
`mc-<namespace>-<cook>` (or `mc-<cook>` when no namespace is set).

Namespace lets two orchestrators run cooks with the same suffix without
colliding on compose projects, images, or networks. It comes from `--namespace`
(CLI) or the `MULTICOOKER_NAMESPACE` env var, with the CLI winning.

`render_compose` writes the resolved name into `compose.yaml` `name:`. Commands
that DON'T re-render (cancel/clean) should prefer reading it back via
`project_from_compose()` so they stay consistent with whatever namespace the
cook actually ran under, rather than re-deriving from a (possibly different)
current env.
"""

from __future__ import annotations

import os
from pathlib import Path


def resolve_namespace(cli_namespace: str | None = None) -> str | None:
    """CLI flag wins over MULTICOOKER_NAMESPACE env; empty/whitespace -> None.

    An EXPLICIT empty/whitespace `--namespace ""` is treated as "no namespace"
    and wins over the env (it was passed, so it overrides); only an unset
    (None) CLI value falls back to the env var.
    """
    if cli_namespace is not None:
        return cli_namespace.strip() or None
    ns = (os.environ.get("MULTICOOKER_NAMESPACE") or "").strip()
    return ns or None


def _slug(s: str) -> str:
    return s.lower().replace("_", "-")


def project_name(cook_name: str, namespace: str | None = None) -> str:
    """`mc-<namespace>-<cook>`, or `mc-<cook>` when no namespace."""
    ns = (namespace or "").strip()
    return _slug(f"mc-{ns}-{cook_name}") if ns else _slug(f"mc-{cook_name}")


def project_from_compose(cook_dir: Path, *, fallback_name: str | None = None,
                         namespace: str | None = None) -> str:
    """Prefer the project name persisted in compose.yaml `name:`; else recompute.

    Non-render commands (cancel/clean) use this so they target the project the
    cook was actually launched under, regardless of the current env.
    """
    compose = cook_dir / "compose.yaml"
    if compose.exists():
        try:
            import yaml
            cfg = yaml.safe_load(compose.read_text())
            if isinstance(cfg, dict) and cfg.get("name"):
                return str(cfg["name"])
        except Exception:                                                   # noqa: BLE001
            pass
    return project_name(fallback_name or cook_dir.name, namespace)


def effective_project(cook_dir: Path, cook_name: str,
                      cli_namespace: str | None = None) -> str:
    """Resolve the compose project a render command (cook/judge/refine/resume)
    should use — making the namespace STICKY across phases.

    - An EXPLICIT --namespace/env value always wins (lets a user deliberately
      re-namespace), producing mc-<ns>-<cook>.
    - With NO explicit namespace, reuse the name the cook already ran under
      (compose.yaml `name:`). Otherwise a judge/refine/resume invoked without
      the flag would silently rewrite a namespaced cook back to mc-<cook> and
      orphan the original containers/images.
    - First render (no compose.yaml yet) falls back to the bare mc-<cook>.

    Both the command's `docker compose -p` string and the rendered compose
    `name:` must come from here so they never diverge.
    """
    ns = resolve_namespace(cli_namespace)
    if ns is not None:
        return project_name(cook_name, ns)
    return project_from_compose(cook_dir, fallback_name=cook_name)
