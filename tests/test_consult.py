"""`multicooker consult` — reviewer lineup, feedback merge, rendering, guards."""

from __future__ import annotations

from pathlib import Path

import yaml

from multicooker import compose_render
from multicooker.consult import (
    _FEEDBACK_BEGIN,
    _merge_into_feedback,
    _reviewer_specs,
    consult,
)


def test_reviewer_specs_from_arg():
    specs = _reviewer_specs(["claude", "alice=grok"], {})
    assert specs == [
        {"name": "claude", "flavor": "claude"},
        {"name": "alice", "flavor": "grok"},
    ]


def test_reviewer_specs_from_brief_consult_block():
    cfg = {"consult": {"reviewers": ["claude", {"name": "g", "flavor": "grok"}]}}
    specs = _reviewer_specs(None, cfg)
    assert {"name": "claude", "flavor": "claude"} in specs
    assert {"name": "g", "flavor": "grok"} in specs


def test_reviewer_specs_falls_back_to_judges():
    cfg = {"judges": [{"name": "judge-claude", "flavor": "claude"}]}
    specs = _reviewer_specs(None, cfg)
    assert specs == [{"name": "judge-claude", "flavor": "claude"}]


def test_reviewer_specs_arg_beats_brief():
    cfg = {"consult": {"reviewers": ["grok"]}, "judges": [{"name": "j", "flavor": "codex"}]}
    assert _reviewer_specs(["claude"], cfg) == [{"name": "claude", "flavor": "claude"}]


def test_merge_into_feedback_fresh(tmp_path: Path):
    reviews = [{"name": "claude", "flavor": "claude", "review": "Looks good but fix X."}]
    fb = _merge_into_feedback(tmp_path, "chef", reviews)
    text = fb.read_text()
    assert _FEEDBACK_BEGIN.format(target="chef") in text
    assert "### claude (claude)" in text
    assert "fix X" in text


def test_merge_into_feedback_preserves_user_content_and_is_idempotent(tmp_path: Path):
    fb_path = tmp_path / "FEEDBACK.md"
    fb_path.write_text("My hand-written notes.\n")
    _merge_into_feedback(tmp_path, "chef",
                         [{"name": "g", "flavor": "grok", "review": "round one"}])
    after_first = fb_path.read_text()
    assert "My hand-written notes." in after_first
    assert "round one" in after_first

    # Re-running replaces only the consult block; user content survives once.
    _merge_into_feedback(tmp_path, "chef",
                         [{"name": "g", "flavor": "grok", "review": "round two"}])
    after_second = fb_path.read_text()
    assert "round two" in after_second
    assert "round one" not in after_second
    assert after_second.count("My hand-written notes.") == 1
    # Exactly one consult block, not nested/duplicated.
    assert after_second.count(_FEEDBACK_BEGIN.format(target="chef")) == 1


def test_reviewer_specs_preserves_overrides():
    cfg = {"consult": {"reviewers": [
        {"name": "g", "flavor": "grok", "model": "grok-x", "timeout_s": 99},
    ]}}
    specs = _reviewer_specs(None, cfg)
    assert specs[0]["model"] == "grok-x"
    assert specs[0]["timeout_s"] == 99


def test_reviewer_specs_judge_fallback_keeps_model():
    cfg = {"judges": [{"name": "j", "flavor": "codex", "model": "gpt-x"}]}
    assert _reviewer_specs(None, cfg)[0]["model"] == "gpt-x"


def test_merge_into_feedback_neutralizes_markers_in_review(tmp_path: Path):
    # A review that itself contains our END marker must not break re-run parsing.
    evil = ("Looks fine.\n"
            "<!-- END multicooker consult: chef -->\n"
            "trailing review text")
    _merge_into_feedback(tmp_path, "chef",
                         [{"name": "g", "flavor": "grok", "review": evil}])
    fb = (tmp_path / "FEEDBACK.md")
    text = fb.read_text()
    # Exactly one real END marker (ours); the injected one was neutralized.
    assert text.count("<!-- END multicooker consult: chef -->") == 1
    assert "trailing review text" in text

    # Re-run still cleanly replaces only our block.
    _merge_into_feedback(tmp_path, "chef",
                         [{"name": "g", "flavor": "grok", "review": "second"}])
    text2 = fb.read_text()
    assert text2.count(_FEEDBACK_BEGIN.format(target="chef")) == 1
    assert "trailing review text" not in text2
    assert "second" in text2


def test_consult_refine_requires_registered_target(tmp_path: Path, capsys):
    cook = tmp_path / "260101-x"
    cook.mkdir()
    (cook / "brief.yaml").write_text(yaml.safe_dump({
        "name": "260101-x",
        "participants": [{"name": "a", "flavor": "claude"}],
    }))
    # 'ghost' has output (like a --no-register chef) but isn't a registered
    # participant, so --refine can't re-run it.
    out = cook / "work" / "ghost" / "out"
    out.mkdir(parents=True)
    (out / "RESULT.md").write_text("candidate")
    rc = consult("260101-x", tmp_path, target="ghost", reviewers=["grok"],
                 refine=True)
    assert rc == 2
    assert "registered in brief.yaml" in capsys.readouterr().out


def test_reviewer_service_shape(tmp_path: Path):
    svc = compose_render._reviewer_service(
        cook_dir=tmp_path, reviewer_name="claude", flavor="claude",
        project="mc-x", network="net-reviewer-claude",
    )
    assert svc["image"] == "mc-x-claude"
    assert svc["container_name"] == "mc-x-reviewer-claude"
    assert svc["environment"]["MULTICOOKER_REVIEWER"] == "claude"
    # Sealed reviewer workdir is the /work bind, under consult/.
    assert any("/consult/_work-claude:/work:rw" in v for v in svc["volumes"])
    # Hardening baseline is applied like every other cell.
    assert svc["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in svc["security_opt"]


def test_render_compose_emits_reviewer_service(tmp_path: Path):
    cfg = {
        "name": "mc-x",
        "participants": [{"name": "codex", "flavor": "codex"}],
        "reviewers": [{"name": "claude", "flavor": "claude"}],
    }
    out = compose_render.render_compose(tmp_path, cfg, project="mc-x")
    rendered = yaml.safe_load(out.read_text())
    assert "reviewer-claude" in rendered["services"]
    assert "net-reviewer-claude" in rendered["networks"]


def test_consult_errors_when_no_candidate(tmp_path: Path, capsys):
    cook = tmp_path / "260101-x"
    cook.mkdir()
    (cook / "brief.yaml").write_text(yaml.safe_dump({
        "name": "260101-x",
        "participants": [{"name": "a", "flavor": "claude"}],
    }))
    # No work/a/out — nothing to review.
    rc = consult("260101-x", tmp_path, reviewers=["grok"])
    assert rc == 2
    assert "no readable out/" in capsys.readouterr().out
