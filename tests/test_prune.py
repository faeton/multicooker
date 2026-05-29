"""`multicooker prune` — age-based cook removal (item 16, no docker)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from multicooker.prune import _age_days, prune


def _cook(root: Path, name: str, *, age_days: float | None = None) -> Path:
    cook = root / name
    cook.mkdir(parents=True)
    (cook / "brief.yaml").write_text(yaml.safe_dump({"name": name}))
    (cook / "summary.json").write_text("{}")
    (cook / "leaderboard.md").write_text("# board\n")
    (cook / "work").mkdir()
    (cook / "work" / "junk.txt").write_text("x\n")
    if age_days is not None:
        ts = (datetime.now(timezone.utc) - timedelta(days=age_days)).isoformat()
        (cook / "status.json").write_text(json.dumps(
            {"schema_version": 1, "cook": name, "state": "reported",
             "updated_at": ts}))
    return cook


def test_age_days_from_status(tmp_path: Path):
    cook = _cook(tmp_path, "260101-old", age_days=10)
    age = _age_days(cook, datetime.now(timezone.utc))
    assert 9.5 < age < 10.5


def test_dry_run_touches_nothing(tmp_path: Path):
    cook = _cook(tmp_path, "260101-old", age_days=30)
    assert prune(tmp_path, older_than_days=7, dry_run=True) == 0
    assert cook.exists()
    assert (cook / "brief.yaml").exists()


def test_prune_removes_old_cook(tmp_path: Path):
    cook = _cook(tmp_path, "260101-old", age_days=30)
    assert prune(tmp_path, older_than_days=7) == 0
    assert not cook.exists()


def test_prune_skips_young_cook(tmp_path: Path):
    cook = _cook(tmp_path, "260101-young", age_days=1)
    assert prune(tmp_path, older_than_days=7) == 0
    assert cook.exists()


def test_prune_keep_results(tmp_path: Path):
    cook = _cook(tmp_path, "260101-old", age_days=30)
    assert prune(tmp_path, older_than_days=7, keep_results=True) == 0
    assert cook.exists()
    assert (cook / "summary.json").exists()
    assert (cook / "leaderboard.md").exists()
    # everything else is gone
    assert not (cook / "brief.yaml").exists()
    assert not (cook / "work").exists()
    assert not (cook / "status.json").exists()


def test_prune_missing_root(tmp_path: Path):
    assert prune(tmp_path / "nope", older_than_days=7) == 2


def test_prune_no_candidates(tmp_path: Path):
    _cook(tmp_path, "260101-young", age_days=1)
    assert prune(tmp_path, older_than_days=30) == 0
