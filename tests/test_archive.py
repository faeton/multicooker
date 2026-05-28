"""`multicooker archive` — only-public copy, never secrets/mappings (item 15)."""

from __future__ import annotations

import tarfile
from pathlib import Path

from multicooker.archive_cmd import archive


def _populate(cook: Path) -> None:
    (cook / "work" / "alice" / "out").mkdir(parents=True)
    (cook / "work" / "alice" / "out" / "RESULT.md").write_text("answer\n")
    (cook / "work" / "alice" / "trace.json").write_text('{"flavor":"claude"}')
    (cook / "logs" / "alice").mkdir(parents=True)
    (cook / "logs" / "alice" / "claude.stdout.log").write_text("Claude thinking\n")
    (cook / ".auth" / "claude").mkdir(parents=True)
    (cook / ".auth" / "claude" / "creds.json").write_text("TOPSECRET\n")
    (cook / "judging").mkdir()
    (cook / "judging" / "_mapping.json").write_text('{"A":"alice"}')
    (cook / "judging" / "judge-x").mkdir()
    (cook / "judging" / "judge-x" / "review.md").write_text("A is good\n")
    (cook / "leaderboard.md").write_text("# board\n")
    (cook / "summary.json").write_text("{}")


def test_archive_dir_public_only(tmp_path: Path):
    cook = tmp_path / "260101-arc"
    _populate(cook)
    assert archive("260101-arc", tmp_path) == 0
    arc = cook / "archive"
    assert (arc / "leaderboard.md").exists()
    assert (arc / "summary.json").exists()
    assert (arc / "work" / "alice" / "out" / "RESULT.md").exists()
    assert (arc / "judging" / "judge-x" / "review.md").exists()
    # secrets / host-only / operator MUST be absent
    assert not (arc / ".auth").exists()
    assert not (arc / "judging" / "_mapping.json").exists()
    assert not (arc / "logs").exists()
    assert not (arc / "work" / "alice" / "trace.json").exists()
    # a filtered manifest ships with the archive
    assert (arc / "artifacts.json").exists()


def test_archive_include_operator(tmp_path: Path):
    cook = tmp_path / "260101-arc"
    _populate(cook)
    assert archive("260101-arc", tmp_path, include_operator=True) == 0
    arc = cook / "archive"
    assert (arc / "logs" / "alice" / "claude.stdout.log").exists()
    assert (arc / "work" / "alice" / "trace.json").exists()
    # still never secrets / host-only
    assert not (arc / ".auth").exists()
    assert not (arc / "judging" / "_mapping.json").exists()


def test_archive_tar(tmp_path: Path):
    cook = tmp_path / "260101-arc"
    _populate(cook)
    assert archive("260101-arc", tmp_path, fmt="tar") == 0
    tarp = cook / "260101-arc-archive.tar.gz"
    assert tarp.exists()
    with tarfile.open(tarp) as tf:
        names = tf.getnames()
    assert any(n.endswith("leaderboard.md") for n in names)
    assert not any(".auth" in n for n in names)
    assert not any("_mapping.json" in n for n in names)


def test_archive_skips_symlink_to_outside_secret(tmp_path: Path):
    cook = tmp_path / "260101-arc"
    _populate(cook)
    secret = tmp_path / "host_secret.txt"
    secret.write_text("DO NOT LEAK\n")
    # participant tries to smuggle a host file out via a symlink in out/
    (cook / "work" / "alice" / "out" / "leak.md").symlink_to(secret)
    assert archive("260101-arc", tmp_path) == 0
    arc = cook / "archive"
    assert not (arc / "work" / "alice" / "out" / "leak.md").exists()


def test_archive_skips_special_file(tmp_path: Path):
    import os
    cook = tmp_path / "260101-arc"
    _populate(cook)
    os.mkfifo(cook / "work" / "alice" / "out" / "pipe")
    assert archive("260101-arc", tmp_path) == 0
    arc = cook / "archive"
    assert (arc / "work" / "alice" / "out" / "RESULT.md").exists()
    assert not (arc / "work" / "alice" / "out" / "pipe").exists()


def test_archive_second_run_does_not_recurse(tmp_path: Path):
    cook = tmp_path / "260101-arc"
    _populate(cook)
    # First archive creates cook/archive/. A second run with --include-operator
    # must not pick up that prior archive/ dir and nest it.
    assert archive("260101-arc", tmp_path, include_operator=True) == 0
    assert archive("260101-arc", tmp_path, include_operator=True) == 0
    arc = cook / "archive"
    assert not (arc / "archive").exists()
    assert not (arc / ".archive-staging").exists()


def test_archive_missing_cook(tmp_path: Path):
    assert archive("nope", tmp_path) == 2
