"""`multivarka new <name>` — scaffold a new cook folder from templates/."""

from __future__ import annotations

import re
import shutil
from datetime import date
from pathlib import Path

import yaml


PKG_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = PKG_ROOT / "templates" / "cook"

_DATE_PREFIX_RE = re.compile(r"^\d{6}-")


def parse_participant(spec: str) -> tuple[str, str]:
    """Parse `name` or `name=flavor` into (name, flavor).

    Bare `claude` → name=claude, flavor=claude.
    `claude-a=claude` → name=claude-a, flavor=claude (multiple claude
    participants in one cook, distinguished by name).
    """
    spec = spec.strip()
    if "=" in spec:
        name, flavor = spec.split("=", 1)
        name, flavor = name.strip(), flavor.strip()
        if not name or not flavor:
            raise ValueError(f"bad participant spec '{spec}': use NAME=FLAVOR")
        return name, flavor
    return spec, spec


def _flavor_template_exists(flavor: str) -> bool:
    return (TEMPLATE_DIR / "participants" / flavor / "Dockerfile").exists()


def new_cook(name: str, root: Path, participants: list[str]) -> int:
    if not TEMPLATE_DIR.exists():
        print(f"error: template dir not found at {TEMPLATE_DIR}", flush=True)
        return 2
    if not _DATE_PREFIX_RE.match(name):
        name = f"{date.today():%y%m%d}-{name}"
    target = root / name
    if target.exists():
        print(f"error: {target} already exists; pick another name", flush=True)
        return 2

    parsed: list[tuple[str, str]] = []
    for spec in participants:
        try:
            parsed.append(parse_participant(spec))
        except ValueError as e:
            print(f"error: {e}", flush=True)
            return 2

    # Warn if a flavor has no Dockerfile in templates — the cook will fail at
    # build time. We still allow it: user might add the Dockerfile manually
    # after `new`, or shape templates differently. Just be loud.
    seen_flavors = {f for _, f in parsed}
    missing = [f for f in seen_flavors if not _flavor_template_exists(f)]
    if missing:
        print(f"warn: no Dockerfile template for flavor(s): {missing}", flush=True)
        print(f"      add templates/cook/participants/<flavor>/{{Dockerfile,entrypoint.sh}} "
              f"before running cook.")

    # Disallow duplicate participant names (flavors can repeat).
    names = [n for n, _ in parsed]
    if len(set(names)) != len(names):
        print(f"error: duplicate participant name in {names}", flush=True)
        return 2

    root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(TEMPLATE_DIR, target)

    brief_yaml = target / "brief.yaml"
    cfg = yaml.safe_load(brief_yaml.read_text())
    cfg["participants"] = [{"name": n, "flavor": f} for n, f in parsed]
    cfg["name"] = name
    brief_yaml.write_text(yaml.safe_dump(cfg, sort_keys=False))

    # Pre-create participant work folders.
    for n, _ in parsed:
        (target / "work" / n).mkdir(parents=True, exist_ok=True)

    print(f"created cook: {target}")
    print(f"participants: {', '.join(f'{n} ({f})' for n, f in parsed)}")
    print()
    print("next steps:")
    print(f"  1. $EDITOR {target}/BRIEF.md          # describe the task")
    print(f"  2. cp <ref-files> {target}/raw/      # any reference material")
    print(f"  3. $EDITOR {target}/brief.yaml       # tweak timeout, participants, judges")
    print(f"  4. multivarka doctor {name}          # check creds/docker before cooking")
    print(f"  5. multivarka cook {name}            # launch all participants")
    return 0
