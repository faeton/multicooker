"""`multicooker resume` — attempt archiving + target selection (no docker)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from multicooker.resume_cmd import _archive_attempt, resume


def _make_cook(tmp_path: Path, participants: list[dict]) -> Path:
    cook = tmp_path / "260101-test"
    cook.mkdir()
    (cook / "brief.yaml").write_text(yaml.safe_dump({
        "name": "260101-test",
        "participants": participants,
    }))
    return cook


def test_archive_attempt_round1_moves_out(tmp_path: Path):
    cook = tmp_path / "260101-test"
    (cook / "work" / "a" / "out").mkdir(parents=True)
    (cook / "work" / "a" / "out" / "RESULT.md").write_text("v1\n")
    (cook / "work" / "a" / "trace.json").write_text("{}")
    (cook / "logs" / "a").mkdir(parents=True)
    (cook / "logs" / "a" / "claude.stdout.log").write_text("log\n")

    dest = _archive_attempt(cook, round_num=1, name="a", keep_out=False)
    assert dest.name == "attempt-1"
    assert (dest / "out" / "RESULT.md").read_text() == "v1\n"
    assert (dest / "trace.json").exists()
    assert (dest / "logs" / "claude.stdout.log").exists()
    # round 1: work/a/out recreated EMPTY; trace + logs moved away.
    assert (cook / "work" / "a" / "out").is_dir()
    assert not (cook / "work" / "a" / "out" / "RESULT.md").exists()
    assert not (cook / "work" / "a" / "trace.json").exists()
    assert not (cook / "logs" / "a").exists()

    # A second archive lands in attempt-2.
    (cook / "work" / "a" / "out" / "RESULT.md").write_text("v2\n")
    dest2 = _archive_attempt(cook, round_num=1, name="a", keep_out=False)
    assert dest2.name == "attempt-2"


def test_archive_attempt_refine_keeps_out(tmp_path: Path):
    """Refine-round resume must preserve work/<p>/out (the prompt edits it)."""
    cook = tmp_path / "260101-test"
    (cook / "work" / "a" / "out").mkdir(parents=True)
    (cook / "work" / "a" / "out" / "RESULT.md").write_text("round2 work\n")

    dest = _archive_attempt(cook, round_num=2, name="a", keep_out=True)
    # archived copy exists AND the live out/ is left intact.
    assert (dest / "out" / "RESULT.md").read_text() == "round2 work\n"
    assert (cook / "work" / "a" / "out" / "RESULT.md").read_text() == "round2 work\n"


def test_missing_cook_returns_2(tmp_path: Path):
    assert resume("nope", tmp_path) == 2


def test_nothing_to_resume_when_all_ok(tmp_path: Path):
    cook = _make_cook(tmp_path, [{"name": "a", "flavor": "claude"}])
    (cook / "RUN_RESULT.json").write_text(json.dumps({
        "round": 1,
        "participants": [{"name": "a", "flavor": "claude", "status": "ok"}],
    }))
    # All OK and no --force → returns 0 without touching docker.
    assert resume("260101-test", tmp_path) == 0
