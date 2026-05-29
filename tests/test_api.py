"""Public Python API (item 18) — read-only accessors + run wiring (no docker)."""

from __future__ import annotations

import json
from pathlib import Path

from multicooker import api
from multicooker.api import (
    CookRequest,
    CookResult,
    CookStatus,
    get_artifacts,
    get_result,
    get_status,
    run_cook,
)


def _write_status(cook: Path, **kw) -> None:
    cook.mkdir(parents=True, exist_ok=True)
    base = {"schema_version": 1, "cook": cook.name, "phase": "cook",
            "state": "cooking", "round": 1, "cells": {}}
    base.update(kw)
    (cook / "status.json").write_text(json.dumps(base))


def test_cookstatus_from_dir(tmp_path: Path):
    cook = tmp_path / "260101-t"
    _write_status(cook, state="reported", cells={"a": {"state": "ok"}})
    st = CookStatus.from_dir(cook)
    assert st is not None
    assert st.cook == "260101-t"
    assert st.state == "reported"
    assert st.is_terminal is True
    assert st.cells["a"]["state"] == "ok"


def test_cookstatus_terminal_flags(tmp_path: Path):
    cook = tmp_path / "260101-t"
    for s, term in [("cooking", False), ("sealed", False), ("judging", False),
                    ("reported", True), ("cancelled", True), ("failed", True)]:
        _write_status(cook, state=s)
        assert CookStatus.from_dir(cook).is_terminal is term, s


def test_get_status_absent(tmp_path: Path):
    assert get_status("nope", tmp_path) is None


def test_cookresult_from_dir(tmp_path: Path):
    cook = tmp_path / "260101-t"
    cook.mkdir()
    (cook / "summary.json").write_text(json.dumps({
        "cook": "260101-t", "round": 2,
        "ranking": [{"rank": 1, "participant": "a", "mean_pct": 80.0}],
        "per_judge": {"j": {}}, "excluded_pairs": [], "status": None,
    }))
    r = get_result("260101-t", tmp_path)
    assert isinstance(r, CookResult)
    assert r.round == 2
    assert r.ranking[0]["participant"] == "a"


def test_get_artifacts(tmp_path: Path):
    cook = tmp_path / "260101-t"
    cook.mkdir()
    (cook / "artifacts.json").write_text(json.dumps(
        {"schema_version": 1, "artifacts": [{"path": "leaderboard.md",
                                             "visibility": "public"}]}))
    m = get_artifacts("260101-t", tmp_path)
    assert m["artifacts"][0]["visibility"] == "public"
    assert get_artifacts("missing", tmp_path) is None


def test_cook_request_cook_dir(tmp_path: Path):
    req = CookRequest(name="260101-t", root=tmp_path)
    assert req.cook_dir() == tmp_path / "260101-t"


def test_run_cook_builds_args_and_reads_status(tmp_path: Path, monkeypatch):
    captured = {}

    def fake_cli(args):
        captured["args"] = args
        # Simulate the CLI: write a terminal status.json for the cook.
        _write_status(tmp_path / "260101-t", state="sealed")
        return 0

    monkeypatch.setattr(api, "_cli", fake_cli)
    req = CookRequest(name="260101-t", root=tmp_path,
                      participants=["a", "b"], namespace="zuzoo",
                      profile="small")
    st = run_cook(req)
    assert st is not None and st.state == "sealed" and st.exit_code == 0
    args = captured["args"]
    assert args[0] == "cook"
    assert "260101-t" in args
    assert "--participants" in args and "a,b" in args
    assert "--namespace" in args and "zuzoo" in args
    assert "--profile" in args and "small" in args
    # root is passed as an absolute path
    ri = args.index("--root")
    assert Path(args[ri + 1]).is_absolute()


def test_run_cook_propagates_exit_code(tmp_path: Path, monkeypatch):
    def fake_cli(args):
        _write_status(tmp_path / "260101-t", state="failed")
        return 1
    monkeypatch.setattr(api, "_cli", fake_cli)
    st = run_cook(CookRequest(name="260101-t", root=tmp_path))
    assert st.exit_code == 1 and st.state == "failed"


def test_run_cook_stub_when_no_status(tmp_path: Path, monkeypatch):
    # Subprocess dies before writing status.json → caller still gets exit_code,
    # not a bare None.
    monkeypatch.setattr(api, "_cli", lambda args: 2)
    st = run_cook(CookRequest(name="260101-t", root=tmp_path))
    assert st is not None
    assert st.exit_code == 2
    assert st.state is None
    assert st.cook == "260101-t"


def test_run_report_stub_when_no_summary(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(api, "_cli", lambda args: 1)
    r = api.run_report(CookRequest(name="260101-t", root=tmp_path))
    assert r.exit_code == 1
    assert r.status == "missing"


def test_str_root_is_accepted(tmp_path: Path):
    # The README documents string roots — they must not crash.
    cook = tmp_path / "260101-t"
    _write_status(cook, state="reported")
    req = CookRequest(name="260101-t", root=str(tmp_path))
    assert req.cook_dir() == cook
    assert get_status("260101-t", str(tmp_path)).state == "reported"
