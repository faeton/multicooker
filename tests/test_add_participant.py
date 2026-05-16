"""Tests for add_participant — extending an existing cook's brief.yaml.

Covered: happy path, idempotency (refuse duplicate names), missing brief,
missing cook dir, work/<name>/ pre-creation.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from multicooker.add_participant import add_participant


def _make_cook(tmp_path: Path, participants: list[dict]) -> Path:
    cook = tmp_path / "260101-test"
    cook.mkdir()
    (cook / "brief.yaml").write_text(yaml.safe_dump({
        "name": "260101-test",
        "participants": participants,
    }))
    return cook


def test_adds_new_participant(tmp_path: Path):
    _make_cook(tmp_path, [{"name": "claude", "flavor": "claude"}])
    rc = add_participant("260101-test", tmp_path, "codex")
    assert rc == 0
    cfg = yaml.safe_load((tmp_path / "260101-test" / "brief.yaml").read_text())
    names = [p["name"] for p in cfg["participants"]]
    assert names == ["claude", "codex"]
    assert (tmp_path / "260101-test" / "work" / "codex").is_dir()


def test_supports_name_equals_flavor(tmp_path: Path):
    _make_cook(tmp_path, [{"name": "claude", "flavor": "claude"}])
    rc = add_participant("260101-test", tmp_path, "claude-b=claude")
    assert rc == 0
    cfg = yaml.safe_load((tmp_path / "260101-test" / "brief.yaml").read_text())
    entry = next(p for p in cfg["participants"] if p["name"] == "claude-b")
    assert entry["flavor"] == "claude"


def test_refuses_duplicate_name(tmp_path: Path):
    _make_cook(tmp_path, [{"name": "claude", "flavor": "claude"}])
    rc = add_participant("260101-test", tmp_path, "claude")
    assert rc != 0
    # brief.yaml unchanged
    cfg = yaml.safe_load((tmp_path / "260101-test" / "brief.yaml").read_text())
    assert len(cfg["participants"]) == 1


def test_missing_cook_dir(tmp_path: Path):
    rc = add_participant("does-not-exist", tmp_path, "claude")
    assert rc != 0


def test_missing_brief_yaml(tmp_path: Path):
    cook = tmp_path / "broken"
    cook.mkdir()
    rc = add_participant("broken", tmp_path, "claude")
    assert rc != 0


def test_idempotent_after_failure(tmp_path: Path, capsys):
    """A failed add must not leave half-written state."""
    _make_cook(tmp_path, [{"name": "claude", "flavor": "claude"}])
    rc = add_participant("260101-test", tmp_path, "claude")  # dup
    assert rc != 0
    # brief.yaml still has one participant; no work/claude duplicated.
    cfg = yaml.safe_load((tmp_path / "260101-test" / "brief.yaml").read_text())
    assert [p["name"] for p in cfg["participants"]] == ["claude"]
