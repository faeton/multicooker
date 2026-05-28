"""`multicooker cancel` — marker + cancelled state + cell relabel (no docker).

The compose stop call fails gracefully when docker is absent/unknown project,
so these run without a daemon.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from multicooker import state
from multicooker.cancel_cmd import cancel_cmd


def _make_cook(tmp_path: Path) -> Path:
    cook = tmp_path / "260101-test"
    cook.mkdir()
    (cook / "brief.yaml").write_text(yaml.safe_dump({
        "name": "260101-test",
        "participants": [{"name": "a", "flavor": "claude"}],
    }))
    return cook


def test_missing_cook_returns_2(tmp_path: Path):
    assert cancel_cmd("nope", tmp_path) == 2


def test_cancel_sets_state_and_marker(tmp_path: Path):
    cook = _make_cook(tmp_path)
    state.init_status(cook, cook="260101-test", phase="cook", state=state.COOKING,
                      cells={"a": {"role": "participant", "state": state.RUNNING}})
    rc = cancel_cmd("260101-test", tmp_path)
    assert rc == 0
    assert state.is_cancelled(cook)
    st = state.read_status(cook)
    assert st["state"] == state.CANCELLED
    assert st["cells"]["a"]["state"] == state.CELL_CANCELLED
    events = (cook / "events.jsonl").read_text()
    assert "cook.cancel_requested" in events
    assert "cook.cancelled" in events


def test_cancel_leaves_finished_cells_untouched(tmp_path: Path):
    cook = _make_cook(tmp_path)
    state.init_status(cook, cook="260101-test", phase="cook", state=state.COOKING,
                      cells={
                          "a": {"role": "participant", "state": state.OK},
                          "b": {"role": "participant", "state": state.RUNNING},
                      })
    cancel_cmd("260101-test", tmp_path)
    cells = state.read_status(cook)["cells"]
    assert cells["a"]["state"] == state.OK  # already done → not relabeled
    assert cells["b"]["state"] == state.CELL_CANCELLED
