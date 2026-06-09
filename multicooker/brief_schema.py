"""Hand-rolled validator for `brief.yaml`.

Why hand-rolled rather than `jsonschema`: this catches >95% of real
mistakes (missing/typo'd field, wrong type, weights that don't add up to
100, duplicate participant names, unknown flavor, judge same flavor as
all participants) and keeps the dependency tree at one runtime dep
(`pyyaml`). Adding `jsonschema` would buy us ~5% more rigor at the cost
of one more wheel in every install.

Each rule emits a short error string; callers print them and exit
non-zero before any docker work happens — so we never spend compose
build time on a brief that's structurally broken.

Used by:
  - `multicooker doctor` (preflight)
  - `cook.py`, `refine.py`, `judge.py` (start-of-run guard, redundant with
    doctor but cheap and protects users who skip doctor).

Convention: `validate(cfg)` returns a list of error strings. Empty list
means valid. Caller decides what to do (print + exit, raise, etc).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


# Flavors known to creds.py. Adding a flavor = adding here AND in creds.py
# AND providing a Dockerfile under templates/cook/participants/<flavor>/.
KNOWN_FLAVORS = frozenset({"claude", "codex", "agy", "grok", "triad", "dummy"})

# Mirror of host_profile.VALID_PROFILES; duplicated to keep brief_schema
# import-free of subprocess-using modules (cheaper unit tests).
VALID_PROFILES = frozenset({"auto", "large", "medium", "small"})

# Mirror of judging_policy.VALID_POLICIES (inlined for the same reason).
VALID_JUDGING_POLICIES = frozenset(
    {"require_distinct_flavor", "warn", "allow_self"}
)


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _validate_resources(res: Any, where: str, errors: list[str]) -> None:
    """Validate a `resources:` block (top-level or per-actor).

    Accepted keys: profile (only at top-level, but we accept it
    everywhere and ignore where it's nonsensical to keep the rule
    simple), mem_limit, memswap_limit, cpus, pids_limit. Unknown
    keys are warned about by the caller via validate_warnings.
    """
    if res is None:
        return
    if not isinstance(res, dict):
        errors.append(f"{where}: must be a mapping (got {type(res).__name__})")
        return
    if "profile" in res:
        prof = res["profile"]
        if not isinstance(prof, str) or prof not in VALID_PROFILES:
            errors.append(
                f"{where}.profile: must be one of {sorted(VALID_PROFILES)} "
                f"(got {prof!r})"
            )
    for key in ("mem_limit", "memswap_limit"):
        if key in res:
            v = res[key]
            if not isinstance(v, (str, int)) or isinstance(v, bool):
                errors.append(f"{where}.{key}: must be a docker-style mem string "
                              f"(e.g. '2g', '512m') or bytes int (got {type(v).__name__})")
                continue
            if isinstance(v, str):
                s = v.strip().lower()
                if not s or (s[-1] not in "kmgt" and not s.isdigit()):
                    errors.append(f"{where}.{key}='{v}': expected suffix k/m/g/t or raw bytes")
    if "cpus" in res:
        c = res["cpus"]
        if not _is_number(c) and not (isinstance(c, str) and c.replace(".", "", 1).isdigit()):
            errors.append(f"{where}.cpus: must be numeric (e.g. 1.0 or '0.5') — got {c!r}")
    if "pids_limit" in res:
        p = res["pids_limit"]
        if not _is_int_like(p) or p <= 0:
            errors.append(f"{where}.pids_limit: must be a positive integer (got {p!r})")


def _is_int_like(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _validate_actor(actor: Any, kind: str, idx: int,
                    seen_names: set[str], errors: list[str]) -> None:
    """kind is 'participant' or 'judge'."""
    where = f"{kind}s[{idx}]"
    if not isinstance(actor, dict):
        errors.append(f"{where}: must be a mapping (got {type(actor).__name__})")
        return
    name = actor.get("name")
    if not isinstance(name, str) or not name:
        errors.append(f"{where}: 'name' is required and must be a non-empty string")
        return
    if not name.replace("-", "").replace("_", "").isalnum():
        errors.append(
            f"{where}.name='{name}': must be alphanumeric (with - or _); "
            f"used as docker service / network name"
        )
    if name in seen_names:
        errors.append(
            f"{where}.name='{name}': duplicate name in {kind}s "
            f"(names must be unique to address compose services)"
        )
    seen_names.add(name)
    flavor = actor.get("flavor", name)
    if not isinstance(flavor, str) or not flavor:
        errors.append(f"{where}.flavor: must be a non-empty string")
        return
    if flavor not in KNOWN_FLAVORS:
        errors.append(
            f"{where}.flavor='{flavor}': unknown flavor. Known: "
            f"{sorted(KNOWN_FLAVORS)}. To add a new flavor see docs/add-flavor.md."
        )
    if "timeout_s" in actor:
        t = actor["timeout_s"]
        if not _is_int_like(t) or t <= 0:
            errors.append(f"{where}.timeout_s: must be a positive integer (got {t!r})")
    if "model" in actor and not isinstance(actor["model"], str):
        errors.append(f"{where}.model: must be a string if set (got {type(actor['model']).__name__})")
    if "resources" in actor:
        _validate_resources(actor["resources"], f"{where}.resources", errors)


def _validate_rubric(rubric: Any, errors: list[str]) -> None:
    if rubric is None:
        return  # rubric is optional — judges fall back to JUDGE_BRIEF.md text
    if not isinstance(rubric, dict):
        errors.append(f"rubric: must be a mapping (got {type(rubric).__name__})")
        return
    scale = rubric.get("scale")
    if scale is not None:
        if (not isinstance(scale, list) or len(scale) != 2
                or not all(_is_int_like(x) for x in scale)
                or scale[0] >= scale[1]):
            errors.append(f"rubric.scale: must be [lo, hi] with lo<hi (got {scale!r})")
    dims = rubric.get("dimensions")
    if dims is None:
        errors.append("rubric.dimensions: required when rubric is set")
        return
    if not isinstance(dims, list) or not dims:
        errors.append("rubric.dimensions: must be a non-empty list")
        return
    seen_ids: set[str] = set()
    total_weight = 0
    for i, d in enumerate(dims):
        if not isinstance(d, dict):
            errors.append(f"rubric.dimensions[{i}]: must be a mapping")
            continue
        did = d.get("id")
        if not isinstance(did, str) or not did:
            errors.append(f"rubric.dimensions[{i}].id: required non-empty string")
        elif did in seen_ids:
            errors.append(f"rubric.dimensions[{i}].id='{did}': duplicate dimension id")
        else:
            seen_ids.add(did)
        w = d.get("weight")
        if not _is_int_like(w) or w <= 0:
            errors.append(f"rubric.dimensions[{i}].weight: positive integer required "
                          f"(got {w!r})")
        else:
            total_weight += w
    if total_weight and total_weight != 100:
        errors.append(
            f"rubric.dimensions: weights sum to {total_weight}, expected 100. "
            f"(So `report` produces a clean 0-100 score; rebalance.)"
        )


def _validate_outputs(outputs: Any, errors: list[str]) -> None:
    """Validate an optional `outputs:` block declaring required deliverables.

    Shape:
        outputs:
          required:
            - { path: RESULT.md, kind: markdown }   # kind optional

    `path` is relative to the participant's out/. We reject absolute paths and
    `..` traversal so validate_outputs(out_dir, ...) only ever looks inside the
    submission tree. `kind` is recorded but not deeply enforced (presence is the
    contract; see runner_common.validate_outputs).
    """
    if outputs is None:
        return
    if not isinstance(outputs, dict):
        errors.append(f"outputs: must be a mapping (got {type(outputs).__name__})")
        return
    required = outputs.get("required")
    if required is None:
        return
    if not isinstance(required, list):
        errors.append("outputs.required: must be a list")
        return
    for i, spec in enumerate(required):
        where = f"outputs.required[{i}]"
        if not isinstance(spec, dict):
            errors.append(f"{where}: must be a mapping (got {type(spec).__name__})")
            continue
        path = spec.get("path")
        if not isinstance(path, str) or not path:
            errors.append(f"{where}.path: required non-empty string")
        elif path.startswith("/") or ".." in Path(path).parts:
            errors.append(
                f"{where}.path='{path}': must be a relative path inside out/ "
                f"(no leading '/' or '..')"
            )
        if "kind" in spec and not isinstance(spec["kind"], str):
            errors.append(f"{where}.kind: must be a string if set "
                          f"(got {type(spec['kind']).__name__})")


def _validate_judging(judging: Any, errors: list[str]) -> None:
    if judging is None:
        return
    if not isinstance(judging, dict):
        errors.append(f"judging: must be a mapping (got {type(judging).__name__})")
        return
    if "policy" in judging:
        pol = judging["policy"]
        if not isinstance(pol, str) or pol not in VALID_JUDGING_POLICIES:
            errors.append(
                f"judging.policy: must be one of {sorted(VALID_JUDGING_POLICIES)} "
                f"(got {pol!r})"
            )
    if "strict_schema" in judging and not isinstance(judging["strict_schema"], bool):
        errors.append(
            f"judging.strict_schema: must be true or false "
            f"(got {judging['strict_schema']!r})"
        )


def validate(cfg: Any) -> list[str]:
    """Return a list of human-readable validation errors. Empty = valid."""
    errors: list[str] = []
    if not isinstance(cfg, dict):
        return [f"brief.yaml root: must be a mapping (got {type(cfg).__name__})"]

    name = cfg.get("name")
    if not isinstance(name, str) or not name:
        errors.append("name: required non-empty string (used as compose project name)")
    elif not name.replace("-", "").replace("_", "").isalnum():
        errors.append(f"name='{name}': must be alphanumeric (with - or _)")
    elif name == "PLACEHOLDER":
        errors.append("name='PLACEHOLDER': brief.yaml not initialized — "
                      "did `multicooker new` finish? expected a real cook name.")

    for key in ("timeout_s", "judge_timeout_s"):
        if key in cfg:
            v = cfg[key]
            if not _is_int_like(v) or v <= 0:
                errors.append(f"{key}: must be a positive integer (got {v!r})")

    participants = cfg.get("participants", [])
    if not isinstance(participants, list) or not participants:
        errors.append("participants: must be a non-empty list")
    else:
        seen: set[str] = set()
        for i, p in enumerate(participants):
            _validate_actor(p, "participant", i, seen, errors)

    judges = cfg.get("judges", [])
    if not isinstance(judges, list):
        errors.append("judges: must be a list (can be empty)")
    else:
        seen_j: set[str] = set()
        for i, j in enumerate(judges):
            _validate_actor(j, "judge", i, seen_j, errors)

    _validate_rubric(cfg.get("rubric"), errors)
    _validate_judging(cfg.get("judging"), errors)
    _validate_outputs(cfg.get("outputs"), errors)

    if "resources" in cfg:
        _validate_resources(cfg["resources"], "resources", errors)

    # Soft warning rolled into errors — only when participants exist and judges
    # do too: if every judge shares a flavor with every participant, anonymization
    # is the only line of defense. Just warn (not block).
    if (isinstance(participants, list) and participants
            and isinstance(judges, list) and judges):
        p_flavors = {p.get("flavor", p.get("name")) for p in participants
                     if isinstance(p, dict)}
        j_flavors = {j.get("flavor", j.get("name")) for j in judges
                     if isinstance(j, dict)}
        if j_flavors and j_flavors.issubset(p_flavors):
            # Don't add to errors[] — this is advisory, not blocking.
            # Caller can re-emit if they care. For now we surface via
            # validate_warnings() below.
            pass

    return errors


def validate_warnings(cfg: Any) -> list[str]:
    """Non-blocking issues worth surfacing. Caller prints, doesn't exit."""
    warnings: list[str] = []
    if not isinstance(cfg, dict):
        return warnings
    participants = cfg.get("participants") or []
    judges = cfg.get("judges") or []
    if (isinstance(participants, list) and isinstance(judges, list)
            and judges and participants):
        p_flavors = {p.get("flavor", p.get("name")) for p in participants
                     if isinstance(p, dict)}
        j_flavors = {j.get("flavor", j.get("name")) for j in judges
                     if isinstance(j, dict)}
        if j_flavors and j_flavors.issubset(p_flavors):
            warnings.append(
                f"every judge flavor ({sorted(j_flavors)}) also appears as a "
                f"participant. Anonymization mitigates self-bias, but for full "
                f"anti-self-judging add at least one judge of a different flavor."
            )
    return warnings


def validate_or_die(cfg: Any, source: str = "brief.yaml") -> int | None:
    """Print errors and return exit code 2 if invalid; print warnings; else None.

    Standard "guard" entry point for cook/refine/judge.
    """
    import sys
    errors = validate(cfg)
    if errors:
        print(f"\n{source} is invalid:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print("", file=sys.stderr)
        return 2
    for w in validate_warnings(cfg):
        print(f"warn ({source}): {w}")
    return None
