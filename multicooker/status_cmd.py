"""`multicooker status <cook> [--json]` — current state of a cook.

Reads status.json (the live contract file). For cooks created before the
contract existed, synthesizes a best-effort snapshot from the legacy
*_RESULT.json files so an orchestrator still gets structured output.

Exit code policy (doc item 8): nonzero only when the cook directory is
missing/unreadable — never merely because a participant failed.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import metrics, state
from .report import _latest_run_result


def _synthesize_status(cook_dir: Path) -> dict | None:
    """Build a status-shaped dict from legacy result files (no status.json)."""
    round_num, rr = _latest_run_result(cook_dir)
    participants = rr.get("participants") if isinstance(rr, dict) else None
    if not participants:
        return None
    cells = {}
    for p in participants:
        cells[p.get("name", "?")] = {
            "role": "participant",
            "flavor": p.get("flavor"),
            "state": p.get("status"),
            "exit_class": p.get("status"),
            "duration_s": p.get("duration_s"),
        }
    jr_path = cook_dir / "JUDGE_RESULT.json"
    if jr_path.exists():
        try:
            jr = json.loads(jr_path.read_text())
            for j in jr.get("judges", []):
                cells[j.get("name", "?")] = {
                    "role": "judge",
                    "flavor": j.get("flavor"),
                    "state": j.get("status"),
                }
        except (json.JSONDecodeError, OSError):
            pass
    reported = (cook_dir / "summary.json").exists()
    return {
        "schema_version": state.SCHEMA_VERSION,
        "cook": cook_dir.name,
        "phase": "report" if reported else "cook",
        "state": state.REPORTED if reported else state.SEALED,
        "round": round_num,
        "synthesized": True,
        "cells": cells,
    }


def status_cmd(name: str, root: Path, as_json: bool = False) -> int:
    cook_dir = root / name if not Path(name).is_absolute() else Path(name)
    if not cook_dir.exists():
        print(f"error: cook folder {cook_dir} does not exist", flush=True)
        return 2
    st = state.read_status(cook_dir)
    if st is None:
        st = _synthesize_status(cook_dir)
    if st is None:
        print(f"error: no status.json and no result files at {cook_dir}", flush=True)
        return 2

    _attach_live_usage(cook_dir, st)

    if as_json:
        print(json.dumps(st, indent=2))
        return 0

    print(f"cook: {st.get('cook')}  phase={st.get('phase')}  "
          f"state={st.get('state')}  round={st.get('round')}")
    cells = st.get("cells", {})
    for cname, c in cells.items():
        line = f"  {c.get('role', '?'):11} {cname:16} {c.get('state', '?'):14}"
        usage = c.get("usage")
        if usage:
            line += f" {metrics.summarize_usage(usage)}"
        print(line.rstrip())
    totals = st.get("usage_totals")
    if totals:
        print(f"  {'total':11} {'':16} {'':14} {metrics.summarize_usage(totals)}")
    return 0


def _attach_live_usage(cook_dir: Path, st: dict) -> None:
    """Collect each cell's usage live (works mid-run) and add per-cell totals.

    Mutates `st`: every participant/judge cell with recorded tokens gains a
    `usage` dict, and the snapshot gains a `usage_totals` aggregate. Read-only
    against the cook — it only parses the mounted usage dirs.
    """
    cells = st.get("cells", {})
    if not isinstance(cells, dict):
        return
    collected = []
    for name, cell in cells.items():
        if not isinstance(cell, dict):
            continue
        usage = metrics.collect_cell_usage(
            cook_dir, cell.get("role"), name, cell.get("flavor"))
        if usage is not None:
            cell["usage"] = usage
            collected.append(usage)
    totals = metrics.sum_usage(collected)
    if totals is not None:
        st["usage_totals"] = totals
