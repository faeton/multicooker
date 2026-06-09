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


def test_status_attaches_live_token_usage(tmp_path: Path, capsys):
    """status collects per-cell usage live from the mounted usage dirs."""
    cook = _make_cook(tmp_path)
    state.init_status(cook, cook="260101-test", phase="cook",
                      state=state.COOKING,
                      cells={"a": {"role": "participant", "flavor": "claude",
                                   "state": state.RUNNING}})
    usage_file = (cook / "work" / "a" / "usage" / "claude" / "projects"
                  / "p" / "s.jsonl")
    usage_file.parent.mkdir(parents=True, exist_ok=True)
    usage_file.write_text(json.dumps({
        "message": {"model": "claude-sonnet",
                    "usage": {"input_tokens": 100, "output_tokens": 20}},
    }) + "\n")

    rc = status_cmd("260101-test", tmp_path, as_json=True)
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["cells"]["a"]["usage"]["total_tokens"] == 120
    assert out["usage_totals"]["total_tokens"] == 120


def test_status_text_shows_tokens(tmp_path: Path, capsys):
    cook = _make_cook(tmp_path)
    state.init_status(cook, cook="260101-test", phase="cook",
                      state=state.COOKING,
                      cells={"a": {"role": "participant", "flavor": "claude",
                                   "state": state.RUNNING}})
    usage_file = (cook / "work" / "a" / "usage" / "claude" / "projects"
                  / "p" / "s.jsonl")
    usage_file.parent.mkdir(parents=True, exist_ok=True)
    usage_file.write_text(json.dumps({
        "message": {"usage": {"input_tokens": 100, "output_tokens": 20}},
    }) + "\n")

    rc = status_cmd("260101-test", tmp_path, as_json=False)
    assert rc == 0
    text = capsys.readouterr().out
    assert "120 tok" in text
    assert "total" in text


def test_status_no_usage_omits_totals(tmp_path: Path, capsys):
    cook = _make_cook(tmp_path)
    state.init_status(cook, cook="260101-test", phase="cook",
                      state=state.COOKING,
                      cells={"a": {"role": "participant", "flavor": "claude",
                                   "state": state.RUNNING}})
    rc = status_cmd("260101-test", tmp_path, as_json=True)
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "usage" not in out["cells"]["a"]
    assert "usage_totals" not in out
