"""`multivarka add-participant <task> <spec>` — add a new participant to a cook.

Spec is the same shape as `multivarka new --participants`:
  - `cursor`            → name=cursor, flavor=cursor
  - `claude-b=claude`   → name=claude-b, flavor=claude (second claude in the cook)

Idempotent: refuses to overwrite an existing participant name. Updates
brief.yaml and pre-creates work/<name>/ for symmetry with `new`.

Doesn't run anything. Doesn't render compose. The next `cook` / `refine` /
`judge` will pick up the new entry from brief.yaml.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .new_cook import parse_participant, _flavor_template_exists


def add_participant(name: str, root: Path, spec: str) -> int:
    cook_dir = root / name if not Path(name).is_absolute() else Path(name)
    if not cook_dir.exists():
        print(f"error: cook {cook_dir} does not exist", flush=True)
        return 2
    brief_yaml = cook_dir / "brief.yaml"
    if not brief_yaml.exists():
        print(f"error: {brief_yaml} missing", flush=True)
        return 2
    try:
        new_name, new_flavor = parse_participant(spec)
    except ValueError as e:
        print(f"error: {e}", flush=True)
        return 2

    cfg = yaml.safe_load(brief_yaml.read_text())
    existing = cfg.get("participants", []) or []
    if any(p.get("name") == new_name for p in existing):
        print(f"error: participant '{new_name}' already in {brief_yaml}", flush=True)
        return 2

    if not _flavor_template_exists(new_flavor):
        print(f"warn: no Dockerfile template for flavor '{new_flavor}' "
              f"(templates/cook/participants/{new_flavor}/Dockerfile). "
              f"Add it before running cook.", flush=True)

    existing.append({"name": new_name, "flavor": new_flavor})
    cfg["participants"] = existing
    brief_yaml.write_text(yaml.safe_dump(cfg, sort_keys=False))

    (cook_dir / "work" / new_name).mkdir(parents=True, exist_ok=True)

    print(f"added participant: {new_name} (flavor: {new_flavor}) → {brief_yaml}")
    print(f"next: multivarka doctor {name} && multivarka cook {name}")
    return 0
