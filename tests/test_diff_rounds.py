"""Smoke for `multicooker diff <task> N M`.

Builds a fake cook directory shaped like a real one (brief.yaml +
rounds/1/<p>/ + rounds/2/<p>/) and verifies diff_rounds() detects
modified / added / deleted / identical files correctly.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from multicooker.diff_rounds import diff_rounds


def _make_cook(tmp_path: Path) -> Path:
    cook = tmp_path / "cook"
    cook.mkdir()
    (cook / "brief.yaml").write_text(textwrap.dedent("""
        name: t
        participants:
          - {name: a, flavor: dummy}
          - {name: b, flavor: dummy}
    """).lstrip())
    # round 1
    (cook / "rounds" / "1" / "a").mkdir(parents=True)
    (cook / "rounds" / "1" / "a" / "RESULT.md").write_text("hello\nworld\n")
    (cook / "rounds" / "1" / "a" / "to-delete.txt").write_text("gone soon\n")
    (cook / "rounds" / "1" / "b").mkdir(parents=True)
    (cook / "rounds" / "1" / "b" / "RESULT.md").write_text("identical\n")
    # round 2
    (cook / "rounds" / "2" / "a").mkdir(parents=True)
    (cook / "rounds" / "2" / "a" / "RESULT.md").write_text("hello\nbrave\nworld\n")
    (cook / "rounds" / "2" / "a" / "added.txt").write_text("new\n")
    (cook / "rounds" / "2" / "b").mkdir(parents=True)
    (cook / "rounds" / "2" / "b" / "RESULT.md").write_text("identical\n")
    return cook


def test_diff_detects_changes_and_identicals(tmp_path: Path, capsys) -> None:
    _make_cook(tmp_path)
    rc = diff_rounds("cook", tmp_path, n=1, m=2)
    assert rc == 0  # >0 changes => exit 0
    out = capsys.readouterr().out
    assert "a: round 1 → round 2" in out
    assert "RESULT.md" in out
    assert "+brave" in out
    assert "added.txt" in out
    assert "to-delete.txt" in out
    # b had no changes between rounds → "no changes" notice
    assert "b: round 1 → round 2" in out
    assert "(no changes between r1 and r2)" in out


def test_diff_returns_1_when_no_changes_anywhere(tmp_path: Path) -> None:
    cook = tmp_path / "cook"
    cook.mkdir()
    (cook / "brief.yaml").write_text("name: t\nparticipants: [{name: a, flavor: dummy}]\n")
    for r in (1, 2):
        d = cook / "rounds" / str(r) / "a"
        d.mkdir(parents=True)
        (d / "RESULT.md").write_text("same\n")
    assert diff_rounds("cook", tmp_path, n=1, m=2) == 1


def test_diff_missing_round_is_skipped_not_crash(tmp_path: Path, capsys) -> None:
    cook = tmp_path / "cook"
    cook.mkdir()
    (cook / "brief.yaml").write_text("name: t\nparticipants: [{name: a, flavor: dummy}]\n")
    (cook / "rounds" / "1" / "a").mkdir(parents=True)
    (cook / "rounds" / "1" / "a" / "RESULT.md").write_text("only round 1\n")
    rc = diff_rounds("cook", tmp_path, n=1, m=2)
    out = capsys.readouterr().out
    assert "round 2 not found" in out
    assert rc == 1  # nothing changed because m doesn't exist
