"""`multicooker cancel <cook>` — stop a running cook and mark it cancelled.

Runs as its own process while `cook`/`refine` may be blocked in thread.join().
It writes a cancel marker, stops the compose project's containers (so the
runner's _wait_for_exit returns promptly), and records the cancelled state.
The runner's atomic state.finalize() honors the marker, so the terminal state
ends up `cancelled` regardless of which process writes last.

Partial outputs (work/, judging/_inbox/) are preserved.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from . import compose_runner, state


def _project_name(cfg: dict) -> str:
    return f"mc-{cfg['name']}".lower().replace("_", "-")


def cancel_cmd(name: str, root: Path) -> int:
    cook_dir = root / name if not Path(name).is_absolute() else Path(name)
    if not cook_dir.exists():
        print(f"error: cook folder {cook_dir} does not exist", flush=True)
        return 2
    brief_yaml = cook_dir / "brief.yaml"
    if not brief_yaml.exists():
        print(f"error: {brief_yaml} missing", flush=True)
        return 2
    cfg = yaml.safe_load(brief_yaml.read_text())

    state.request_cancel(cook_dir)
    state.append_event(cook_dir, "cook.cancel_requested", cook=cook_dir.name)
    print(f"[cancel] marker written for {cook_dir.name}", flush=True)

    project = _project_name(cfg)
    try:
        compose_runner.stop_project(cook_dir, project)
        print(f"[cancel] stopped compose project {project}", flush=True)
    except Exception as e:                                                  # noqa: BLE001
        print(f"[cancel] warning: could not stop {project}: {e}", flush=True)

    # Mark any not-yet-finished cells cancelled in one locked operation (a
    # concurrent runner may also relabel its own cells; both converge).
    state.mark_unfinished_cancelled(cook_dir)

    state.update_status(cook_dir, cook=cook_dir.name, state=state.CANCELLED)
    state.append_event(cook_dir, "cook.cancelled", cook=cook_dir.name)
    print(f"[cancel] {cook_dir.name} cancelled; partial outputs preserved", flush=True)
    return 0
