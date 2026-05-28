"""Required-output validation → artifact_missing (no docker)."""

from __future__ import annotations

from pathlib import Path

from multicooker.runner_common import apply_required_outputs, validate_outputs


def _out(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    out.mkdir()
    return out


def test_validate_outputs_present(tmp_path: Path):
    out = _out(tmp_path)
    (out / "RESULT.md").write_text("hello\n")
    assert validate_outputs(out, [{"path": "RESULT.md"}]) == []


def test_validate_outputs_missing(tmp_path: Path):
    out = _out(tmp_path)
    assert validate_outputs(out, [{"path": "RESULT.md"}]) == ["RESULT.md"]


def test_validate_outputs_empty_file_is_missing(tmp_path: Path):
    out = _out(tmp_path)
    (out / "RESULT.md").write_text("")  # zero bytes isn't a deliverable
    assert validate_outputs(out, [{"path": "RESULT.md"}]) == ["RESULT.md"]


def test_validate_outputs_symlink_is_missing(tmp_path: Path):
    out = _out(tmp_path)
    real = tmp_path / "real.md"
    real.write_text("content\n")
    (out / "RESULT.md").symlink_to(real)
    assert validate_outputs(out, [{"path": "RESULT.md"}]) == ["RESULT.md"]


def test_validate_outputs_nested_path(tmp_path: Path):
    out = _out(tmp_path)
    (out / "docs").mkdir()
    (out / "docs" / "PROPOSAL.md").write_text("x\n")
    assert validate_outputs(out, [{"path": "docs/PROPOSAL.md"}]) == []
    assert validate_outputs(out, [{"path": "docs/MISSING.md"}]) == ["docs/MISSING.md"]


def test_apply_only_downgrades_ok(tmp_path: Path):
    out = _out(tmp_path)  # nothing written
    req = [{"path": "RESULT.md"}]
    # ok with missing file → artifact_missing
    assert apply_required_outputs("ok", out, req) == ("artifact_missing", ["RESULT.md"])
    # a real failure state is more specific and must NOT be masked
    assert apply_required_outputs("timed_out", out, req) == ("timed_out", [])
    assert apply_required_outputs("non_zero_exit", out, req) == ("non_zero_exit", [])


def test_apply_noop_without_required(tmp_path: Path):
    out = _out(tmp_path)
    assert apply_required_outputs("ok", out, None) == ("ok", [])
    assert apply_required_outputs("ok", out, []) == ("ok", [])


def test_apply_ok_when_present(tmp_path: Path):
    out = _out(tmp_path)
    (out / "RESULT.md").write_text("done\n")
    assert apply_required_outputs("ok", out, [{"path": "RESULT.md"}]) == ("ok", [])
