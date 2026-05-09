"""`multivarka clean <task>` — tear down a cook's docker artifacts.

Removes:
  - containers belonging to compose project mv-<task>
  - networks named after the project
  - images locally built for the project (mv-<task>-{flavor})
  - cooks/<task>/.auth/ (creds snapshot — re-snapshotted on next cook)

Does NOT remove:
  - cooks/<task>/work/, logs/, judging/, RUN*.json (your actual results)
  - the cook folder itself (use `rm -rf cooks/<task>` if you want that)
  - base images pulled from registries (node:22-slim et al.)

`--all` walks cooks/ and cleans every subdir that has a compose.yaml.
`--dry-run` prints what would happen without touching anything.
`--keep-creds` skips removing .auth/.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _project_name(task_name: str) -> str:
    return f"mv-{task_name}".lower().replace("_", "-")


def _compose_down(cook_dir: Path, project: str, dry_run: bool) -> None:
    cmd = [
        "docker", "compose", "-p", project,
        "-f", str(cook_dir / "compose.yaml"),
        "down", "-v", "--rmi", "local", "--remove-orphans",
    ]
    print(f"  {'[dry-run] ' if dry_run else ''}{' '.join(cmd)}")
    if dry_run:
        return
    subprocess.run(cmd, check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _rm_auth(cook_dir: Path, dry_run: bool) -> None:
    auth = cook_dir / ".auth"
    if not auth.exists():
        return
    print(f"  {'[dry-run] ' if dry_run else ''}rm -rf {auth}")
    if dry_run:
        return
    shutil.rmtree(auth, ignore_errors=True)


def _clean_one(cook_dir: Path, dry_run: bool, keep_creds: bool) -> int:
    if not cook_dir.exists():
        print(f"clean: cook {cook_dir} does not exist", flush=True)
        return 2
    compose_yaml = cook_dir / "compose.yaml"
    if not compose_yaml.exists():
        print(f"clean: {compose_yaml} not present (cook never ran in docker-mode); "
              f"only .auth/ will be removed if present", flush=True)
    else:
        # Read project name from compose.yaml's `name:` field if present, otherwise
        # derive from directory name.
        try:
            import yaml
            cfg = yaml.safe_load(compose_yaml.read_text())
            project = cfg.get("name") or _project_name(cook_dir.name)
        except Exception:                                                   # noqa: BLE001
            project = _project_name(cook_dir.name)
        print(f"[clean] {cook_dir.name} (project={project})")
        _compose_down(cook_dir, project, dry_run)
    if not keep_creds:
        _rm_auth(cook_dir, dry_run)
    return 0


def clean(name: str | None, root: Path, all_cooks: bool,
          dry_run: bool, keep_creds: bool) -> int:
    if all_cooks:
        if not root.exists():
            print(f"clean: {root} does not exist", flush=True)
            return 2
        rc = 0
        for d in sorted(root.iterdir()):
            if d.is_dir() and (d / "brief.yaml").exists():
                rc = _clean_one(d, dry_run, keep_creds) or rc
        return rc
    if not name:
        print("clean: pass <task> or --all", flush=True)
        return 2
    cook_dir = root / name if not Path(name).is_absolute() else Path(name)
    return _clean_one(cook_dir, dry_run, keep_creds)
