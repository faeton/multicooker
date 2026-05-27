"""`multicooker rejudge <task>` — re-run judges on the current work/<p>/out/.

Distinct from `judge` only in that it re-seals `judging/_inbox/` from the
current `work/<p>/out/` first, and clears stale judge outboxes. Useful
when:

  - you tweaked `JUDGE_BRIEF.md` (rubric, weights) and want fresh scores
    without burning a new cook;
  - you hand-edited a participant's `out/` and want it judged as-is;
  - one judge timed out / rate-limited last time and you swapped it.

`judge` itself is idempotent — it reuses `_inbox/` if it exists — but
it does NOT re-seal from `work/`. So if `out/` has drifted, plain
`judge` would score the stale snapshot. `rejudge` is the explicit
"reseal + judge" path.

Anonymization mapping is regenerated (fresh A/B/C permutation). That's
the anti-bias guarantee — we never preserve it across runs.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .cook import _seal_for_judging
from .judge import judge as judge_cook


def rejudge(name: str, root: Path,
            judges_override: list[str] | None = None,
            profile_override: str | None = None) -> int:
    cook_dir = root / name if not Path(name).is_absolute() else Path(name)
    if not cook_dir.exists():
        print(f"error: cook folder {cook_dir} does not exist", flush=True)
        return 2

    work_root = cook_dir / "work"
    if not work_root.exists():
        print(f"error: no work/ at {work_root}; run `multicooker cook {name}` first",
              flush=True)
        return 2

    participants = sorted(p.name for p in work_root.iterdir()
                          if p.is_dir() and (p / "out").exists())
    if not participants:
        print(f"error: no participants with out/ found in {work_root}", flush=True)
        return 2
    print(f"[rejudge] re-sealing {len(participants)} participants from work/ → "
          f"judging/_inbox/: {participants}", flush=True)
    for p in participants:
        _seal_for_judging(cook_dir, p)

    # Clean stale judge outboxes so old scores.json doesn't get re-aggregated
    # by `report` if the new run skips a judge (e.g. via --judges).
    judging_root = cook_dir / "judging"
    for child in judging_root.iterdir():
        if child.is_dir() and not child.name.startswith("_"):
            shutil.rmtree(child)

    return judge_cook(name=name, root=root, judges_override=judges_override,
                      profile_override=profile_override)
