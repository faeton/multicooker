"""`multivarka new <name>` — scaffold a new cook folder from templates/."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml


PKG_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = PKG_ROOT / "templates" / "cook"


def new_cook(name: str, root: Path, participants: list[str]) -> int:
    if not TEMPLATE_DIR.exists():
        print(f"error: template dir not found at {TEMPLATE_DIR}", flush=True)
        return 2
    target = root / name
    if target.exists():
        print(f"error: {target} already exists; pick another name", flush=True)
        return 2

    root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(TEMPLATE_DIR, target)

    # Patch brief.yaml with the requested participants list.
    brief_yaml = target / "brief.yaml"
    cfg = yaml.safe_load(brief_yaml.read_text())
    cfg["participants"] = [{"name": p, "flavor": p} for p in participants]
    cfg["name"] = name
    brief_yaml.write_text(yaml.safe_dump(cfg, sort_keys=False))

    # Pre-create participant work folders so user can drop preseed material.
    for p in participants:
        (target / "work" / p).mkdir(parents=True, exist_ok=True)

    print(f"created cook: {target}")
    print()
    print("next steps:")
    print(f"  1. $EDITOR {target}/BRIEF.md          # describe the task")
    print(f"  2. cp <ref-files> {target}/raw/      # any reference material")
    print(f"  3. $EDITOR {target}/brief.yaml       # tweak timeout, participants")
    print(f"  4. multivarka cook {name}            # launch all participants")
    return 0
