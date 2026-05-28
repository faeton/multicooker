"""artifacts.json classification + manifest build (items 7)."""

from __future__ import annotations

from pathlib import Path

from multicooker.artifacts import (
    HOST_ONLY,
    OPERATOR,
    PUBLIC,
    SECRET,
    build_manifest,
    classify,
)


def test_classify_public():
    assert classify("leaderboard.md") == PUBLIC
    assert classify("summary.json") == PUBLIC
    assert classify("work/alice/out/RESULT.md") == PUBLIC
    assert classify("work/alice/out/nested/app.js") == PUBLIC
    assert classify("judging/judge-claude/review.md") == PUBLIC


def test_classify_secret():
    assert classify(".auth/claude/creds.json") == SECRET
    # .auth ANYWHERE is secret — even smuggled under a participant's out/.
    assert classify("work/alice/out/.auth/creds.json") == SECRET


def test_classify_host_only():
    assert classify("judging/_mapping.json") == HOST_ONLY
    assert classify("judging/_inbox/alice/out/x.md") == HOST_ONLY
    assert classify("judging/_judge_input/submissions/A/x.md") == HOST_ONLY
    assert classify("judging/_work-judge-claude/submissions/A/x.md") == HOST_ONLY


def test_classify_operator_defaults():
    # Known operator files and ANY unknown path default to operator, never public.
    assert classify("logs/alice/claude.stdout.log") == OPERATOR
    assert classify("work/alice/trace.json") == OPERATOR
    assert classify("work/alice/PROMPT.txt") == OPERATOR
    assert classify("compose.yaml") == OPERATOR
    assert classify("RUN_RESULT.json") == OPERATOR
    assert classify("status.json") == OPERATOR
    assert classify("judging/_logs/judge-claude/x.log") == OPERATOR
    assert classify("something/totally/new.bin") == OPERATOR
    # A judge subfile that ISN'T review.md stays operator.
    assert classify("judging/judge-claude/scores_deanon.json") == OPERATOR


def test_build_manifest(tmp_path: Path):
    cook = tmp_path / "260101-art"
    (cook / "work" / "alice" / "out").mkdir(parents=True)
    (cook / "work" / "alice" / "out" / "RESULT.md").write_text("hello\n")
    (cook / "work" / "alice").joinpath("trace.json").write_text("{}")
    (cook / ".auth" / "claude").mkdir(parents=True)
    (cook / ".auth" / "claude" / "creds.json").write_text("secret\n")
    (cook / "judging").mkdir()
    (cook / "judging" / "_mapping.json").write_text('{"A":"alice"}')
    (cook / "leaderboard.md").write_text("# board\n")
    # build-junk must be pruned from the walk
    (cook / "work" / "alice" / "out" / "node_modules").mkdir()
    (cook / "work" / "alice" / "out" / "node_modules" / "big.js").write_text("x" * 100)

    manifest = build_manifest(cook)
    by_path = {e["path"]: e for e in manifest["artifacts"]}

    assert by_path["leaderboard.md"]["visibility"] == PUBLIC
    assert by_path["work/alice/out/RESULT.md"]["visibility"] == PUBLIC
    assert by_path["work/alice/out/RESULT.md"]["sha256"]
    assert by_path["work/alice/trace.json"]["visibility"] == OPERATOR
    assert by_path[".auth/claude/creds.json"]["visibility"] == SECRET
    assert by_path["judging/_mapping.json"]["visibility"] == HOST_ONLY
    # node_modules pruned
    assert not any("node_modules" in p for p in by_path)
    # manifest doesn't list itself
    assert "artifacts.json" not in by_path
    assert (cook / "artifacts.json").exists()


def test_manifest_prunes_own_outputs(tmp_path: Path):
    cook = tmp_path / "260101-art"
    (cook / "work" / "a" / "out").mkdir(parents=True)
    (cook / "work" / "a" / "out" / "RESULT.md").write_text("x\n")
    # Derived outputs from a prior archive run must not be re-manifested.
    (cook / "archive").mkdir()
    (cook / "archive" / "leaderboard.md").write_text("old\n")
    (cook / ".archive-staging").mkdir()
    (cook / ".archive-staging" / "junk.md").write_text("junk\n")
    (cook / f"{cook.name}-archive.tar.gz").write_text("tarbytes")
    manifest = build_manifest(cook)
    paths = {e["path"] for e in manifest["artifacts"]}
    assert "work/a/out/RESULT.md" in paths
    assert not any(p.startswith("archive/") for p in paths)
    assert not any(p.startswith(".archive-staging/") for p in paths)
    assert f"{cook.name}-archive.tar.gz" not in paths
    # but a participant's OWN out/archive/ survives (pruned at root only)
    (cook / "work" / "a" / "out" / "archive").mkdir()
    (cook / "work" / "a" / "out" / "archive" / "keep.md").write_text("keep\n")
    paths2 = {e["path"] for e in build_manifest(cook)["artifacts"]}
    assert "work/a/out/archive/keep.md" in paths2


def test_manifest_flags_special_file(tmp_path: Path):
    import os
    cook = tmp_path / "260101-art"
    (cook / "work" / "a" / "out").mkdir(parents=True)
    fifo = cook / "work" / "a" / "out" / "pipe"
    os.mkfifo(fifo)
    manifest = build_manifest(cook)
    by_path = {e["path"]: e for e in manifest["artifacts"]}
    assert by_path["work/a/out/pipe"].get("special") is True
    assert "sha256" not in by_path["work/a/out/pipe"]
    assert "size" not in by_path["work/a/out/pipe"]


def test_manifest_marks_symlink(tmp_path: Path):
    cook = tmp_path / "260101-art"
    (cook / "work" / "a" / "out").mkdir(parents=True)
    real = tmp_path / "outside.txt"
    real.write_text("secret outside\n")
    (cook / "work" / "a" / "out" / "link.md").symlink_to(real)
    manifest = build_manifest(cook)
    by_path = {e["path"]: e for e in manifest["artifacts"]}
    assert by_path["work/a/out/link.md"].get("symlink") is True
    assert "sha256" not in by_path["work/a/out/link.md"]
