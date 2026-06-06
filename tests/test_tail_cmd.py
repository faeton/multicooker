"""`multicooker tail --no-follow` — dumps prefixed log lines (no docker)."""

from __future__ import annotations

from pathlib import Path

from multicooker.tail_cmd import tail_cmd


def _seed_logs(tmp_path: Path) -> Path:
    cook = tmp_path / "260101-test"
    (cook / "logs" / "a").mkdir(parents=True)
    (cook / "logs" / "a" / "claude.stdout.log").write_text("alice-line-1\nalice-line-2\n")
    (cook / "logs" / "b").mkdir(parents=True)
    (cook / "logs" / "b" / "codex.stdout.log").write_text("bob-line-1\n")
    (cook / "judging" / "_logs" / "judge1").mkdir(parents=True)
    (cook / "judging" / "_logs" / "judge1" / "agy.stdout.log").write_text("judge-line\n")
    return cook


def test_missing_cook_returns_2(tmp_path: Path):
    assert tail_cmd("nope", tmp_path) == 2


def test_tail_all_actors_prefixed(tmp_path: Path, capsys):
    _seed_logs(tmp_path)
    rc = tail_cmd("260101-test", tmp_path, follow=False)
    assert rc == 0
    out = capsys.readouterr().out
    assert "a/stdout | alice-line-1" in out
    assert "a/stdout | alice-line-2" in out
    assert "b/stdout | bob-line-1" in out
    assert "judge1/stdout | judge-line" in out


def test_tail_single_actor_filter(tmp_path: Path, capsys):
    _seed_logs(tmp_path)
    rc = tail_cmd("260101-test", tmp_path, actor="a", follow=False)
    assert rc == 0
    out = capsys.readouterr().out
    assert "a/stdout | alice-line-1" in out
    assert "bob-line-1" not in out
    assert "judge-line" not in out
