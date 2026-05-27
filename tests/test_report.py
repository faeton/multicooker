"""Tests for report.report — leaderboard aggregation.

A judge can write a kaput scores.json (broken JSON, missing keys, single
participant). The report must survive and produce a sane leaderboard
or fail loudly with rc != 0 — never silently mis-aggregate.

Covered:
- happy path: two judges, two participants, mean across judges
- missing scores from one judge
- invalid JSON in one judge's scores
- empty judging dir → rc != 0
- no rubric in brief.yaml: equal-weight fallback over judge-provided dims
- explicit rubric in brief.yaml: weighted normalization to 0-100
- judge-supplied `total` is ignored — score is always recomputed from dims
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from multicooker.report import report


def _make_cook(tmp_path: Path, participants: list[str]) -> Path:
    cook = tmp_path / "260101-test"
    cook.mkdir()
    (cook / "brief.yaml").write_text(yaml.safe_dump({
        "name": "260101-test",
        "participants": [{"name": p, "flavor": p} for p in participants],
    }))
    (cook / "judging").mkdir()
    return cook


def _put_judge(cook: Path, judge_name: str,
               scores: dict, broken: bool = False) -> None:
    jd = cook / "judging" / judge_name
    jd.mkdir()
    body = "{not json" if broken else json.dumps(scores)
    (jd / "scores_deanon.json").write_text(body)


def test_happy_path_two_judges(tmp_path: Path, capsys):
    # No rubric → equal-weight fallback on the dims judges actually wrote.
    cook = _make_cook(tmp_path, ["a", "b"])
    _put_judge(cook, "judge1", {
        "a": {"dimensions": {"correctness": 4}},
        "b": {"dimensions": {"correctness": 2}},
    })
    _put_judge(cook, "judge2", {
        "a": {"dimensions": {"correctness": 3}},
        "b": {"dimensions": {"correctness": 4}},
    })
    rc = report("260101-test", tmp_path)
    assert rc == 0
    md = (cook / "leaderboard.md").read_text()
    # a mean = (4/5*100 + 3/5*100)/2 = 70.0
    # b mean = (2/5*100 + 4/5*100)/2 = 60.0
    a_idx = md.find("| a |")
    b_idx = md.find("| b |")
    assert a_idx > 0 and b_idx > 0
    assert a_idx < b_idx
    assert "70.0" in md
    assert "60.0" in md


def test_missing_scores_from_one_judge(tmp_path: Path):
    cook = _make_cook(tmp_path, ["a", "b"])
    _put_judge(cook, "judge1", {
        "a": {"dimensions": {"correctness": 4}},
    })
    # judge2 has no scores file at all.
    (cook / "judging" / "judge2").mkdir()
    rc = report("260101-test", tmp_path)
    assert rc == 0
    md = (cook / "leaderboard.md").read_text()
    # b had no judge → mean 0.0, # judges 0.
    assert "| b | 0.0 | 0 |" in md
    # a single judge gave correctness=4 → 80%
    assert "| a | 80.0 | 1 |" in md


def test_invalid_json_skipped(tmp_path: Path):
    cook = _make_cook(tmp_path, ["a"])
    _put_judge(cook, "judge1", {}, broken=True)
    _put_judge(cook, "judge2", {"a": {"dimensions": {"correctness": 5}}})
    rc = report("260101-test", tmp_path)
    assert rc == 0
    md = (cook / "leaderboard.md").read_text()
    # correctness=5 / max 5 → 100.0%
    assert "| a | 100.0 | 1 |" in md
    judges_line = next(line for line in md.splitlines() if line.startswith("Judges:"))
    assert "judge1" not in judges_line
    assert "judge2" in judges_line


def test_no_judges_at_all(tmp_path: Path):
    cook = _make_cook(tmp_path, ["a"])
    rc = report("260101-test", tmp_path)
    assert rc == 1
    assert not (cook / "leaderboard.md").exists()


def test_judge_supplied_total_is_ignored(tmp_path: Path):
    """Judges have historically written `total` on different scales (raw sum
    vs weighted-normalized). Report must ignore `total` and always recompute
    from `dimensions` so mismatched scales don't poison the leaderboard."""
    cook = _make_cook(tmp_path, ["a"])
    _put_judge(cook, "j1", {
        # Judge wrote a wildly wrong total — should be ignored.
        "a": {"dimensions": {"correctness": 3, "quality": 4}, "total": 999.0},
    })
    rc = report("260101-test", tmp_path)
    assert rc == 0
    md = (cook / "leaderboard.md").read_text()
    # Equal-weight fallback (no rubric): (3+4)/(2*5)*100 = 70.0
    assert "| a | 70.0 | 1 |" in md
    assert "999" not in md


def test_explicit_rubric_uses_weighted_normalization(tmp_path: Path):
    """When brief.yaml has a rubric with weights, scores are weighted."""
    cook = _make_cook(tmp_path, ["a"])
    (cook / "brief.yaml").write_text(yaml.safe_dump({
        "name": "260101-test",
        "participants": [{"name": "a", "flavor": "a"}],
        "rubric": {
            "scale": [0, 5],
            "dimensions": [
                {"id": "correctness", "weight": 80},
                {"id": "polish", "weight": 20},
            ],
        },
    }))
    _put_judge(cook, "j1", {
        "a": {"dimensions": {"correctness": 5, "polish": 1}},
    })
    rc = report("260101-test", tmp_path)
    assert rc == 0
    md = (cook / "leaderboard.md").read_text()
    # weighted: (5*80 + 1*20) / (100 * 5) * 100 = 420/500*100 = 84.0
    assert "| a | 84.0 | 1 |" in md


def test_report_includes_run_metrics(tmp_path: Path):
    cook = _make_cook(tmp_path, ["a"])
    _put_judge(cook, "j1", {"a": {"dimensions": {"correctness": 3}}})
    (cook / "RUN_RESULT.json").write_text(json.dumps({
        "participants": [{
            "name": "a",
            "status": "ok",
            "duration_s": 12.3,
            "usage": {"total_tokens": 1234, "cost_usd": 0.0123},
        }]
    }))
    (cook / "JUDGE_RESULT.json").write_text(json.dumps({
        "judges": [{
            "name": "j1",
            "status": "ok",
            "duration_s": 4.5,
            "usage": {"total_tokens": 77},
        }]
    }))

    rc = report("260101-test", tmp_path)

    assert rc == 0
    md = (cook / "leaderboard.md").read_text()
    # correctness=3/5 → 60.0%
    assert "| a | 60.0 | 1 | ok | 12.3s | 1,234 | $0.0123 |" in md
    assert "## Judge run metrics" in md
    assert "| j1 | ok | 4.5s | 77 | ? |" in md


def test_underscore_dirs_ignored(tmp_path: Path):
    """report iterates judging/ but should skip _inbox, _logs, _mapping etc."""
    cook = _make_cook(tmp_path, ["a"])
    _put_judge(cook, "real-judge", {"a": {"dimensions": {"correctness": 5}}})
    # Underscore dirs that the cook produces — must not be parsed as judges.
    (cook / "judging" / "_inbox").mkdir()
    (cook / "judging" / "_logs").mkdir()
    (cook / "judging" / "_mapping.json").write_text("{}")
    rc = report("260101-test", tmp_path)
    assert rc == 0
    md = (cook / "leaderboard.md").read_text()
    judges_line = next(line for line in md.splitlines() if line.startswith("Judges:"))
    assert "_inbox" not in judges_line
    assert "_logs" not in judges_line


def test_report_ignores_unknown_score_keys(tmp_path: Path):
    cook = _make_cook(tmp_path, ["a"])
    _put_judge(cook, "j1", {
        "a": {"dimensions": {"correctness": 5}},
        "scores": {"dimensions": {}},
        "totals": {"dimensions": {"A": 100}},
    })

    rc = report("260101-test", tmp_path)

    assert rc == 0
    md = (cook / "leaderboard.md").read_text()
    assert "| a | 100.0 | 1 |" in md
    assert "| scores |" not in md
    assert "| totals |" not in md
