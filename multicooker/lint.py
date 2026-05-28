"""`multicooker lint <cook>` — cross-file consistency checks for a cook.

`brief_schema.validate()` covers the structural validity of `brief.yaml` in
isolation. Linting adds the checks that span files — the ones that make a cook
silently misbehave rather than fail loudly:

  - every rubric dimension id in `brief.yaml` must appear in `JUDGE_BRIEF.md`,
    otherwise judges improvise dimensions and scores become noisy (see CLAUDE.md
    "Ambiguity in Success criteria is not [fine]").

`lint_consistency()` returns ONLY the cross-file errors (no schema duplication)
so it can be folded into `cook`/`refine` start-guards (which already call
`brief_schema.validate_or_die`) and into `doctor`. The standalone `lint` command
runs both layers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from . import brief_schema


def lint_consistency(cook_dir: Path, cfg: dict) -> list[str]:
    """Cross-file checks between brief.yaml and JUDGE_BRIEF.md. [] = clean."""
    errors: list[str] = []
    rubric = cfg.get("rubric")
    if not isinstance(rubric, dict):
        rubric = {}  # malformed rubric is brief_schema's job to report, not ours
    dims = rubric.get("dimensions") or []
    judges = cfg.get("judges") or []
    dim_ids = [d.get("id") for d in dims
               if isinstance(d, dict) and isinstance(d.get("id"), str)]

    # Rubric→JUDGE_BRIEF coverage only matters when there's a rubric to mirror
    # AND judges that will read it. A rubric-less or judge-less cook is fine.
    if dim_ids and judges:
        jb = cook_dir / "JUDGE_BRIEF.md"
        if not jb.exists():
            errors.append(
                f"JUDGE_BRIEF.md missing, but brief.yaml defines a rubric with "
                f"{len(dim_ids)} dimension(s) and {len(judges)} judge(s) — judges "
                f"need the rubric mirrored there."
            )
        else:
            text = jb.read_text()
            absent = [d for d in dim_ids if d not in text]
            if absent:
                errors.append(
                    f"JUDGE_BRIEF.md is missing rubric dimension id(s): {absent}. "
                    f"Every brief.yaml rubric dimension id must appear in "
                    f"JUDGE_BRIEF.md so judges score the same axes."
                )
    return errors


def lint_or_die(cook_dir: Path, cfg: dict) -> int | None:
    """Start-guard for cook/refine: print cross-file errors, return 2 if any.

    Schema validity is assumed already checked by the caller's
    brief_schema.validate_or_die — this layer only adds the cross-file checks.
    """
    errors = lint_consistency(cook_dir, cfg)
    if errors:
        print(f"\n{cook_dir.name}: rubric lint failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print("Fix JUDGE_BRIEF.md (or run `multicooker lint` for details), "
              "then re-run.", file=sys.stderr)
        return 2
    return None


def lint(name: str, root: Path) -> int:
    """`multicooker lint <cook>` — schema + cross-file checks. 0 ok, 1 issues."""
    cook_dir = root / name if not Path(name).is_absolute() else Path(name)
    brief_yaml = cook_dir / "brief.yaml"
    if not brief_yaml.exists():
        print(f"error: {brief_yaml} missing", file=sys.stderr)
        return 2
    cfg = yaml.safe_load(brief_yaml.read_text())
    errors = brief_schema.validate(cfg)
    # Only run cross-file checks once the brief is structurally valid — a
    # malformed rubric/judges block is brief_schema's to report (mirrors how
    # cook/doctor return on schema errors before linting).
    if not errors and isinstance(cfg, dict):
        errors = lint_consistency(cook_dir, cfg)
    if errors:
        print(f"{brief_yaml}: {len(errors)} issue(s):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"lint: {cook_dir.name} ok")
    return 0
