"""report → summary.json + anti-self-judge exclusion + latest-round metrics."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from multicooker.report import report


def _make_cook(tmp_path: Path, cfg_extra: dict) -> Path:
    cook = tmp_path / "260101-test"
    cook.mkdir()
    cfg = {
        "name": "260101-test",
        "participants": [
            {"name": "alice", "flavor": "claude"},
            {"name": "bob", "flavor": "codex"},
        ],
        "judges": [
            {"name": "judge-claude", "flavor": "claude"},
            {"name": "judge-gemini", "flavor": "gemini"},
        ],
        "rubric": {"scale": [0, 5],
                   "dimensions": [{"id": "correctness", "weight": 100}]},
    }
    cfg.update(cfg_extra)
    (cook / "brief.yaml").write_text(yaml.safe_dump(cfg))
    (cook / "judging").mkdir()
    return cook


def _put_judge(cook: Path, judge_name: str, scores: dict) -> None:
    jd = cook / "judging" / judge_name
    jd.mkdir()
    (jd / "scores_deanon.json").write_text(json.dumps(scores))


def test_summary_written_with_ranking(tmp_path: Path):
    cook = _make_cook(tmp_path, {})
    _put_judge(cook, "judge-claude", {
        "alice": {"dimensions": {"correctness": 5}},
        "bob": {"dimensions": {"correctness": 3}},
    })
    _put_judge(cook, "judge-gemini", {
        "alice": {"dimensions": {"correctness": 4}},
        "bob": {"dimensions": {"correctness": 4}},
    })
    (cook / "RUN_RESULT.json").write_text(json.dumps({
        "round": 1,
        "participants": [
            {"name": "alice", "flavor": "claude", "status": "ok", "duration_s": 1.0},
            {"name": "bob", "flavor": "codex", "status": "ok", "duration_s": 2.0},
        ],
    }))

    rc = report("260101-test", tmp_path)
    assert rc == 0
    summary = json.loads((cook / "summary.json").read_text())
    assert summary["cook"] == "260101-test"
    assert summary["round"] == 1
    assert summary["anti_self_judge_policy"] == "warn"
    # Default warn → no exclusions; both judges count for both participants.
    assert summary["excluded_pairs"] == []
    ranks = {r["participant"]: r for r in summary["ranking"]}
    assert ranks["alice"]["num_judges"] == 2
    assert ranks["alice"]["run_status"] == "ok"
    assert ranks["alice"]["rank"] == 1  # alice mean (90) > bob (70)


def test_strict_policy_excludes_self_flavor(tmp_path: Path):
    cook = _make_cook(tmp_path, {"judging": {"policy": "require_distinct_flavor"}})
    # judge-claude is same flavor as alice → its alice score must be dropped.
    _put_judge(cook, "judge-claude", {
        "alice": {"dimensions": {"correctness": 5}},
        "bob": {"dimensions": {"correctness": 1}},
    })
    _put_judge(cook, "judge-gemini", {
        "alice": {"dimensions": {"correctness": 2}},
        "bob": {"dimensions": {"correctness": 2}},
    })
    rc = report("260101-test", tmp_path)
    assert rc == 0
    summary = json.loads((cook / "summary.json").read_text())
    assert {"judge": "judge-claude", "participant": "alice", "flavor": "claude"} \
        in summary["excluded_pairs"]
    ranks = {r["participant"]: r for r in summary["ranking"]}
    # alice scored only by judge-gemini (claude judge excluded).
    assert ranks["alice"]["num_judges"] == 1
    # bob scored by both (neither judge shares codex flavor).
    assert ranks["bob"]["num_judges"] == 2


def test_latest_round_metrics_from_refine(tmp_path: Path):
    cook = _make_cook(tmp_path, {})
    _put_judge(cook, "judge-gemini", {
        "alice": {"dimensions": {"correctness": 5}},
        "bob": {"dimensions": {"correctness": 3}},
    })
    # Round 1 cook result (stale durations).
    (cook / "RUN_RESULT.json").write_text(json.dumps({
        "round": 1,
        "participants": [
            {"name": "alice", "flavor": "claude", "status": "ok", "duration_s": 1.0},
        ],
    }))
    # Round 2 refine result (the current truth).
    (cook / "REFINE_2_RESULT.json").write_text(json.dumps({
        "round": 2,
        "participants": [
            {"name": "alice", "flavor": "claude", "status": "ok", "duration_s": 9.9},
        ],
    }))
    rc = report("260101-test", tmp_path)
    assert rc == 0
    summary = json.loads((cook / "summary.json").read_text())
    assert summary["round"] == 2
    ranks = {r["participant"]: r for r in summary["ranking"]}
    assert ranks["alice"]["duration_s"] == 9.9


def test_no_scores_still_writes_summary(tmp_path: Path):
    cook = _make_cook(tmp_path, {})
    # judging/ exists (from _make_cook) but no judge produced scores.
    rc = report("260101-test", tmp_path)
    assert rc == 1
    summary = json.loads((cook / "summary.json").read_text())
    assert summary["status"] == "no_scores"
    assert summary["ranking"] == []
    assert summary["judges_used"] == []


def test_stale_judge_folder_ignored(tmp_path: Path):
    cook = _make_cook(tmp_path, {})
    _put_judge(cook, "judge-gemini", {
        "alice": {"dimensions": {"correctness": 4}},
        "bob": {"dimensions": {"correctness": 4}},
    })
    # A judge folder NOT in brief.yaml (removed/renamed between rounds).
    _put_judge(cook, "ghost-judge", {
        "alice": {"dimensions": {"correctness": 0}},
        "bob": {"dimensions": {"correctness": 0}},
    })
    rc = report("260101-test", tmp_path)
    assert rc == 0
    summary = json.loads((cook / "summary.json").read_text())
    assert summary["judges_used"] == ["judge-gemini"]
