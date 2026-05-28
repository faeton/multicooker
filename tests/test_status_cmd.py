"""`multicooker status` — reads status.json, synthesizes for legacy cooks."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from multicooker import state
from multicooker.status_cmd import status_cmd


def _make_cook(tmp_path: Path) -> Path:
    cook = tmp_path / "260101-test"
    cook.mkdir()
    (cook / "brief.yaml").write_text(yaml.safe_dump({
        "name": "260101-test",
        "participants": [{"name": "a", "flavor": "claude"}],
    }))
    return cook


def test_missing_cook_returns_2(tmp_path: Path):
    assert status_cmd("nope", tmp_path) == 2


def test_reads_status_json(tmp_path: Path, capsys):
    cook = _make_cook(tmp_path)
    state.init_status(cook, cook="260101-test", phase="cook",
                      state=state.COOKING,
                      cells={"a": {"role": "participant", "state": state.RUNNING}})
    rc = status_cmd("260101-test", tmp_path, as_json=True)
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == state.COOKING
    assert out["cells"]["a"]["state"] == state.RUNNING


def test_synthesizes_from_legacy_results(tmp_path: Path, capsys):
    cook = _make_cook(tmp_path)
    (cook / "RUN_RESULT.json").write_text(json.dumps({
        "round": 1,
        "participants": [
            {"name": "a", "flavor": "claude", "status": "ok", "duration_s": 1.0},
        ],
    }))
    rc = status_cmd("260101-test", tmp_path, as_json=True)
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["synthesized"] is True
    assert out["cells"]["a"]["state"] == "ok"
    assert out["round"] == 1


def test_running_participant_failure_is_not_nonzero(tmp_path: Path):
    """A failed participant must not make `status` exit nonzero."""
    cook = _make_cook(tmp_path)
    state.init_status(cook, cook="260101-test", phase="cook", state=state.SEALED,
                      cells={"a": {"role": "participant", "state": state.NON_ZERO_EXIT}})
    assert status_cmd("260101-test", tmp_path, as_json=True) == 0
