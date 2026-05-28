"""Anti-self-judge policy: should a judge score a same-flavor submission?

A claude judge scoring the claude participant is the self-bias the bake-off
exists to avoid. Anonymization (A/B/C labels) mitigates it, but the doc's
control-plane contract wants this to be an enforceable policy, not just a
printed warning.

Policy lives in brief.yaml:

    judging:
      policy: require_distinct_flavor   # | warn | allow_self

- ``require_distinct_flavor`` — drop every (judge, participant) score where the
  judge's flavor equals the participant's flavor before aggregation.
- ``warn`` (default) — keep the scores, print an advisory. This preserves the
  historical behavior so existing single-flavor cooks (e.g. examples/) don't
  silently lose all their scores.
- ``allow_self`` — keep the scores, no warning.

Default is ``warn`` deliberately: making strict the default would break any
cook whose only judge shares a flavor with the participants.
"""

from __future__ import annotations

REQUIRE_DISTINCT = "require_distinct_flavor"
WARN = "warn"
ALLOW_SELF = "allow_self"
VALID_POLICIES = frozenset({REQUIRE_DISTINCT, WARN, ALLOW_SELF})

DEFAULT_POLICY = WARN


def judging_policy(cfg: dict) -> str:
    """Return the anti-self-judge policy from brief.yaml, defaulting to WARN."""
    judging = cfg.get("judging") if isinstance(cfg, dict) else None
    if isinstance(judging, dict):
        pol = judging.get("policy")
        if isinstance(pol, str) and pol in VALID_POLICIES:
            return pol
    return DEFAULT_POLICY


def _flavor_of(actor: dict) -> str:
    return actor.get("flavor", actor.get("name"))


def self_flavor_pairs(participants: list, judges: list) -> list[tuple[str, str]]:
    """All (judge_name, participant_name) pairs that share a flavor."""
    pairs: list[tuple[str, str]] = []
    for j in judges:
        if not isinstance(j, dict):
            continue
        jf = _flavor_of(j)
        for p in participants:
            if not isinstance(p, dict):
                continue
            if _flavor_of(p) == jf:
                pairs.append((j["name"], p["name"]))
    return pairs


def excluded_pairs(participants: list, judges: list, policy: str) -> set[tuple[str, str]]:
    """(judge_name, participant_name) pairs to drop from aggregation.

    Non-empty only under ``require_distinct_flavor``; warn/allow_self keep
    everything.
    """
    if policy != REQUIRE_DISTINCT:
        return set()
    return set(self_flavor_pairs(participants, judges))
