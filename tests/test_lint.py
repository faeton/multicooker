"""`multicooker lint` — cross-file rubric/JUDGE_BRIEF consistency."""

from __future__ import annotations

from pathlib import Path

import yaml

from multicooker.lint import lint, lint_consistency, lint_or_die


def _cook(tmp_path: Path, *, rubric_dims, judges, judge_brief: str | None) -> Path:
    cook = tmp_path / "260101-lint"
    cook.mkdir()
    cfg = {
        "name": "260101-lint",
        "participants": [{"name": "a", "flavor": "claude"}],
        "judges": judges,
    }
    if rubric_dims is not None:
        n = len(rubric_dims)
        weights = [100 // n] * n
        weights[-1] += 100 - sum(weights)  # make them sum to exactly 100
        cfg["rubric"] = {"scale": [0, 5],
                         "dimensions": [{"id": d, "weight": w}
                                        for d, w in zip(rubric_dims, weights)]}
    (cook / "brief.yaml").write_text(yaml.safe_dump(cfg))
    if judge_brief is not None:
        (cook / "JUDGE_BRIEF.md").write_text(judge_brief)
    return cook


def test_clean_when_all_dims_covered(tmp_path: Path):
    cook = _cook(tmp_path, rubric_dims=["correctness", "quality"],
                 judges=[{"name": "jc", "flavor": "codex"}],
                 judge_brief="Score correctness and quality.\n")
    cfg = yaml.safe_load((cook / "brief.yaml").read_text())
    assert lint_consistency(cook, cfg) == []


def test_missing_dimension_id_flagged(tmp_path: Path):
    cook = _cook(tmp_path, rubric_dims=["correctness", "quality"],
                 judges=[{"name": "jc", "flavor": "codex"}],
                 judge_brief="Score correctness only.\n")
    cfg = yaml.safe_load((cook / "brief.yaml").read_text())
    errors = lint_consistency(cook, cfg)
    assert len(errors) == 1
    assert "quality" in errors[0]


def test_missing_judge_brief_flagged_when_rubric_and_judges(tmp_path: Path):
    cook = _cook(tmp_path, rubric_dims=["correctness"],
                 judges=[{"name": "jc", "flavor": "codex"}],
                 judge_brief=None)
    cfg = yaml.safe_load((cook / "brief.yaml").read_text())
    errors = lint_consistency(cook, cfg)
    assert len(errors) == 1
    assert "JUDGE_BRIEF.md missing" in errors[0]


def test_no_judges_skips_coverage(tmp_path: Path):
    cook = _cook(tmp_path, rubric_dims=["correctness"], judges=[],
                 judge_brief=None)
    cfg = yaml.safe_load((cook / "brief.yaml").read_text())
    assert lint_consistency(cook, cfg) == []


def test_no_rubric_skips_coverage(tmp_path: Path):
    cook = _cook(tmp_path, rubric_dims=None,
                 judges=[{"name": "jc", "flavor": "codex"}],
                 judge_brief=None)
    cfg = yaml.safe_load((cook / "brief.yaml").read_text())
    assert lint_consistency(cook, cfg) == []


def test_lint_or_die_returns_2_on_error(tmp_path: Path):
    cook = _cook(tmp_path, rubric_dims=["correctness"],
                 judges=[{"name": "jc", "flavor": "codex"}],
                 judge_brief="nothing relevant\n")
    cfg = yaml.safe_load((cook / "brief.yaml").read_text())
    assert lint_or_die(cook, cfg) == 2


def test_lint_or_die_returns_none_when_clean(tmp_path: Path):
    cook = _cook(tmp_path, rubric_dims=["correctness"],
                 judges=[{"name": "jc", "flavor": "codex"}],
                 judge_brief="Judge correctness.\n")
    cfg = yaml.safe_load((cook / "brief.yaml").read_text())
    assert lint_or_die(cook, cfg) is None


def test_lint_cli_ok(tmp_path: Path):
    _cook(tmp_path, rubric_dims=["correctness"],
          judges=[{"name": "jc", "flavor": "codex"}],
          judge_brief="Judge correctness.\n")
    assert lint("260101-lint", tmp_path) == 0


def test_lint_cli_reports_issue(tmp_path: Path):
    _cook(tmp_path, rubric_dims=["correctness"],
          judges=[{"name": "jc", "flavor": "codex"}],
          judge_brief="unrelated\n")
    assert lint("260101-lint", tmp_path) == 1


def test_lint_cli_missing_brief(tmp_path: Path):
    assert lint("nope", tmp_path) == 2


def test_lint_cli_malformed_rubric_does_not_crash(tmp_path: Path):
    # A non-mapping rubric is a schema error — lint must report it (exit 1),
    # not crash in lint_consistency's rubric.get().
    cook = tmp_path / "260101-lint"
    cook.mkdir()
    (cook / "brief.yaml").write_text(yaml.safe_dump({
        "name": "260101-lint",
        "participants": [{"name": "a", "flavor": "claude"}],
        "judges": [{"name": "jc", "flavor": "codex"}],
        "rubric": "nope",
    }))
    assert lint("260101-lint", tmp_path) == 1


def test_lint_consistency_tolerates_non_mapping_rubric(tmp_path: Path):
    cook = tmp_path / "260101-lint"
    cook.mkdir()
    assert lint_consistency(cook, {"rubric": "nope",
                                   "judges": [{"name": "j", "flavor": "codex"}]}) == []
