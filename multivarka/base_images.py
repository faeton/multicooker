"""Shared base images for participant/judge containers.

Heavy stuff (node:22-slim + apt + `npm i -g <cli>` + node user setup) lives
in `mv-base-<flavor>:latest`, built once. Per-cook images derive from these
with `FROM mv-base-<flavor>:latest` and only layer in the entrypoint, so
cook builds become near-instant instead of 2-3 minutes per flavor.

Lookup of the Dockerfile context is `<repo>/templates/base/<flavor>/`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / "base"


def image_tag(flavor: str) -> str:
    return f"mv-base-{flavor}:latest"


def template_dir(flavor: str) -> Path:
    return TEMPLATE_DIR / flavor


def is_built(flavor: str) -> bool:
    """True iff `docker image inspect mv-base-<flavor>:latest` succeeds."""
    res = subprocess.run(
        ["docker", "image", "inspect", image_tag(flavor)],
        capture_output=True,
    )
    return res.returncode == 0


def build(flavor: str, force: bool = False) -> None:
    """Build mv-base-<flavor>:latest from templates/base/<flavor>/."""
    ctx = template_dir(flavor)
    if not (ctx / "Dockerfile").exists():
        raise FileNotFoundError(
            f"no base Dockerfile for flavor '{flavor}' at {ctx}"
        )
    if not force and is_built(flavor):
        print(f"[base] {image_tag(flavor)}: already built (use --force to rebuild)",
              flush=True)
        return
    print(f"[base] building {image_tag(flavor)} from {ctx}", flush=True)
    res = subprocess.run(
        ["docker", "build", "-t", image_tag(flavor), str(ctx)],
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"docker build for {image_tag(flavor)} failed (exit {res.returncode})"
        )


def ensure_built(flavors: list[str]) -> None:
    """Build any of the requested base images that aren't already present.

    Called from cook/refine/judge before per-cook image builds, so users
    don't need to think about base images on the happy path.
    """
    for flavor in flavors:
        if not (template_dir(flavor) / "Dockerfile").exists():
            # No base template for this flavor — assume the cook's own
            # Dockerfile is self-contained. Skip.
            continue
        if not is_built(flavor):
            build(flavor)
