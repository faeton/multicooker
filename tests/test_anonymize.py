"""Tests for judge._anonymize.

Anonymization is the only thing standing between participant flavor names
(claude/codex/gemini) and the judge LLM. If a flavor name leaks into the
judge's input directory, the judge can guess identity and bias scores.

Covered:
- mapping covers exactly the participants present in the sealed inbox
- submission directory names are letters (A/B/C/...), not flavor names
- file contents from each participant are preserved (no data loss)
- missing sealed dir for a participant is skipped, not crashed
"""

from __future__ import annotations

from pathlib import Path

from multicooker.judge import _anonymize, _normalize_scores


def _make_sealed(tmp_path: Path, participants: list[str]) -> Path:
    sealed = tmp_path / "judging" / "_inbox"
    sealed.mkdir(parents=True)
    for p in participants:
        d = sealed / p
        (d / "out").mkdir(parents=True)
        (d / "out" / "RESULT.md").write_text(f"hello from {p}")
    return sealed


def test_mapping_covers_all_participants(tmp_path: Path):
    sealed = _make_sealed(tmp_path, ["claude", "codex", "gemini"])
    parts = [{"name": n, "flavor": n} for n in ["claude", "codex", "gemini"]]
    judge_in, mapping = _anonymize(parts, tmp_path / "judging", sealed)
    assert set(mapping.values()) == {"claude", "codex", "gemini"}
    assert all(letter.isupper() and len(letter) == 1 for letter in mapping)


def test_submission_dirs_are_letters_not_flavors(tmp_path: Path):
    sealed = _make_sealed(tmp_path, ["claude", "codex"])
    parts = [{"name": n, "flavor": n} for n in ["claude", "codex"]]
    judge_in, _ = _anonymize(parts, tmp_path / "judging", sealed)
    sub_names = sorted(d.name for d in (judge_in / "submissions").iterdir())
    for name in sub_names:
        assert name not in {"claude", "codex", "gemini", "dummy"}, \
            f"flavor name leaked into submissions: {name}"
    # All entries should be single uppercase letters.
    for name in sub_names:
        assert name.isupper() and len(name) == 1


def test_no_flavor_name_in_paths_or_filenames(tmp_path: Path):
    sealed = _make_sealed(tmp_path, ["claude", "codex", "gemini"])
    parts = [{"name": n, "flavor": n} for n in ["claude", "codex", "gemini"]]
    judge_in, _ = _anonymize(parts, tmp_path / "judging", sealed)
    leaks = []
    for path in judge_in.rglob("*"):
        rel = str(path.relative_to(judge_in))
        for needle in ("claude", "codex", "gemini"):
            if needle in rel:
                leaks.append(rel)
    assert leaks == [], f"flavor name leaked into paths: {leaks}"


def test_file_contents_preserved(tmp_path: Path):
    sealed = _make_sealed(tmp_path, ["claude", "codex"])
    parts = [{"name": n, "flavor": n} for n in ["claude", "codex"]]
    judge_in, mapping = _anonymize(parts, tmp_path / "judging", sealed)
    # For each letter, find its source participant and verify the RESULT.md.
    for letter, source in mapping.items():
        result = (judge_in / "submissions" / letter / "out" / "RESULT.md").read_text()
        assert result == f"hello from {source}"


def test_missing_sealed_participant_is_skipped(tmp_path: Path):
    sealed = _make_sealed(tmp_path, ["claude"])  # only claude on disk
    parts = [{"name": n, "flavor": n} for n in ["claude", "codex"]]  # but config has both
    judge_in, mapping = _anonymize(parts, tmp_path / "judging", sealed)
    # Only the participant whose sealed dir exists ends up in mapping.
    assert list(mapping.values()) == ["claude"]
    sub_count = len(list((judge_in / "submissions").iterdir()))
    assert sub_count == 1


def test_judge_input_dir_is_recreated(tmp_path: Path):
    """Re-running anonymize wipes a stale _judge_input/."""
    sealed = _make_sealed(tmp_path, ["claude"])
    parts = [{"name": "claude", "flavor": "claude"}]
    judge_in_root = tmp_path / "judging"
    # First run.
    judge_in, _ = _anonymize(parts, judge_in_root, sealed)
    (judge_in / "stale.txt").write_text("leftover")
    # Second run.
    judge_in2, _ = _anonymize(parts, judge_in_root, sealed)
    assert not (judge_in2 / "stale.txt").exists()


def test_normalize_scores_unwraps_scores_with_totals():
    scores = _normalize_scores({
        "scores": {
            "K": {"buildability": 0, "architecture-fit": 3},
            "M": {"buildability": 5, "architecture-fit": 5},
        },
        "totals": {
            "K": 34,
            "M": 92,
        },
    })

    assert scores == {
        "K": {
            "dimensions": {"buildability": 0, "architecture-fit": 3},
            "total": 34,
        },
        "M": {
            "dimensions": {"buildability": 5, "architecture-fit": 5},
            "total": 92,
        },
    }
