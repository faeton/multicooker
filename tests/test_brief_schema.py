"""Coverage for the hand-rolled brief.yaml validator.

We assert the spirit (each rule fires when violated and stays quiet on the
happy path) rather than exact wording — error strings are user-facing and
will get tweaked over time.
"""

from __future__ import annotations

from multivarka.brief_schema import KNOWN_FLAVORS, validate, validate_warnings


def _good() -> dict:
    return {
        "name": "smoke",
        "timeout_s": 600,
        "judge_timeout_s": 300,
        "participants": [
            {"name": "a", "flavor": "claude"},
            {"name": "b", "flavor": "codex"},
        ],
        "judges": [
            {"name": "j", "flavor": "gemini"},
        ],
        "rubric": {
            "scale": [0, 5],
            "dimensions": [
                {"id": "correctness", "weight": 60},
                {"id": "quality", "weight": 40},
            ],
        },
    }


def test_happy_path_clean() -> None:
    assert validate(_good()) == []


def test_root_must_be_mapping() -> None:
    assert validate(["nope"])
    assert validate("string")


def test_name_required() -> None:
    cfg = _good()
    del cfg["name"]
    errs = validate(cfg)
    assert any("name" in e for e in errs)


def test_name_placeholder_caught() -> None:
    cfg = _good()
    cfg["name"] = "PLACEHOLDER"
    assert any("PLACEHOLDER" in e for e in validate(cfg))


def test_unknown_flavor_caught() -> None:
    cfg = _good()
    cfg["participants"][0]["flavor"] = "imaginary"
    errs = validate(cfg)
    assert any("imaginary" in e and "unknown flavor" in e for e in errs)


def test_known_flavors_complete() -> None:
    # If someone adds a new flavor to creds.py, schema must follow.
    assert KNOWN_FLAVORS == {"claude", "codex", "gemini", "dummy"}


def test_duplicate_participant_name() -> None:
    cfg = _good()
    cfg["participants"].append({"name": "a", "flavor": "gemini"})
    assert any("duplicate" in e for e in validate(cfg))


def test_weights_must_sum_to_100() -> None:
    cfg = _good()
    cfg["rubric"]["dimensions"] = [
        {"id": "x", "weight": 30},
        {"id": "y", "weight": 30},
    ]
    assert any("100" in e for e in validate(cfg))


def test_per_actor_timeout_must_be_positive_int() -> None:
    cfg = _good()
    cfg["participants"][0]["timeout_s"] = -5
    assert any("timeout_s" in e for e in validate(cfg))
    cfg["participants"][0]["timeout_s"] = "fast"
    assert any("timeout_s" in e for e in validate(cfg))


def test_empty_participants_rejected() -> None:
    cfg = _good()
    cfg["participants"] = []
    assert any("participants" in e for e in validate(cfg))


def test_warning_on_judges_subset_of_participants() -> None:
    cfg = _good()
    cfg["participants"] = [{"name": "a", "flavor": "gemini"}]
    cfg["judges"] = [{"name": "j", "flavor": "gemini"}]
    assert validate(cfg) == []
    warnings = validate_warnings(cfg)
    assert any("anti-self-judging" in w or "anonymization" in w.lower()
               for w in warnings)


def test_rubric_optional() -> None:
    cfg = _good()
    del cfg["rubric"]
    assert validate(cfg) == []


def test_service_name_must_be_safe() -> None:
    cfg = _good()
    cfg["participants"][0]["name"] = "has spaces"
    errs = validate(cfg)
    assert any("alphanumeric" in e for e in errs)
