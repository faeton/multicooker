"""Public Python API — a thin, subprocess-based wrapper over the CLI.

The CLI plus the cook-directory file contract (`status.json`, `events.jsonl`,
`summary.json`, `artifacts.json`) remain the primary integration surface — this
module is a convenience for in-process Python callers (e.g. a Zuzoo worker) that
would otherwise shell out and parse JSON by hand.

Each `run_*` call launches `python -m multicooker.cli ...` as a SUBPROCESS, so
the caller shares no threads or module-level state with the run (cook/judge use
daemon threads + fcntl locks; embedding them in a long-lived process would be a
concurrency hazard — see docs/control-plane-readiness.md item 18). After the
subprocess exits, the result is read back from the on-disk contract files.

Notes:
- Pass an ABSOLUTE `root` (or run from the directory containing `cooks/`) — it
  is resolved to absolute and handed to the CLI verbatim so both sides agree.
- Subprocess stdout/stderr inherit the parent's, matching the CLI; orchestrators
  should follow `events.jsonl`/`status.json`, not scrape stdout.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import state
from .artifacts import artifacts_path

# Cook states an orchestrator can treat as "done" (no further phase will run on
# its own). `sealed` is intentionally NOT terminal — it's mid-pipeline, awaiting
# `judge`.
_TERMINAL_STATES = frozenset({state.REPORTED, state.CANCELLED, state.FAILED})


@dataclass
class CookRequest:
    """Inputs for a run. `root` defaults to ./cooks (resolved to absolute).

    `root` accepts a str or Path — it's coerced internally, so the documented
    `CookRequest(name=..., root="/abs/cooks")` works.
    """
    name: str
    root: Path | str = Path("cooks")
    participants: list[str] | None = None
    judges: list[str] | None = None
    profile: str | None = None
    namespace: str | None = None
    force: bool = False  # resume only

    def cook_dir(self) -> Path:
        return _cook_dir(self.name, self.root)


@dataclass
class CookStatus:
    """A point-in-time snapshot parsed from status.json."""
    cook: str
    phase: str | None
    state: str | None
    round: int | None
    cells: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)
    exit_code: int | None = None  # set when produced by a run_* call

    @property
    def is_terminal(self) -> bool:
        return self.state in _TERMINAL_STATES

    @classmethod
    def from_dir(cls, cook_dir: Path, exit_code: int | None = None) -> "CookStatus | None":
        st = state.read_status(cook_dir)
        if st is None:
            return None
        return cls(
            cook=st.get("cook", cook_dir.name),
            phase=st.get("phase"),
            state=st.get("state"),
            round=st.get("round"),
            cells=st.get("cells", {}),
            raw=st,
            exit_code=exit_code,
        )


@dataclass
class CookResult:
    """The canonical final result parsed from summary.json (after `report`)."""
    cook: str
    round: int | None
    ranking: list[dict] = field(default_factory=list)
    per_judge: dict = field(default_factory=dict)
    excluded_pairs: list = field(default_factory=list)
    status: str | None = None
    raw: dict = field(default_factory=dict)
    exit_code: int | None = None

    @classmethod
    def from_dir(cls, cook_dir: Path, exit_code: int | None = None) -> "CookResult | None":
        import json
        p = state.summary_path(cook_dir)
        if not p.exists():
            return None
        try:
            s = json.loads(p.read_text())
        except (OSError, ValueError):
            return None
        return cls(
            cook=s.get("cook", cook_dir.name),
            round=s.get("round"),
            ranking=s.get("ranking", []),
            per_judge=s.get("per_judge", {}),
            excluded_pairs=s.get("excluded_pairs", []),
            status=s.get("status"),
            raw=s,
            exit_code=exit_code,
        )


def _root_abs(root: Path | str) -> Path:
    root = Path(root)  # tolerate str roots from the documented API
    return root if root.is_absolute() else root.resolve()


def _cook_dir(name: str, root: Path | str) -> Path:
    return Path(name) if Path(name).is_absolute() else _root_abs(root) / name


def _cli(args: list[str]) -> int:
    """Run `python -m multicooker.cli <args>` as a subprocess; return exit code."""
    return subprocess.run([sys.executable, "-m", "multicooker.cli", *args]).returncode


def _common_args(req: CookRequest) -> list[str]:
    args = [req.name, "--root", str(_root_abs(req.root))]
    if req.profile:
        args += ["--profile", req.profile]
    if req.namespace:
        args += ["--namespace", req.namespace]
    return args


def _status_or_stub(cook_dir: Path, rc: int) -> "CookStatus":
    """Read status.json after a run; if the subprocess died before writing it,
    return a stub carrying the exit code so the caller can still see rc (rather
    than a bare None that's indistinguishable from 'never started')."""
    st = CookStatus.from_dir(cook_dir, exit_code=rc)
    if st is None:
        st = CookStatus(cook=cook_dir.name, phase=None, state=None,
                        round=None, exit_code=rc)
    return st


def run_cook(req: CookRequest) -> "CookStatus":
    args = ["cook", *_common_args(req)]
    if req.participants:
        args += ["--participants", ",".join(req.participants)]
    rc = _cli(args)
    return _status_or_stub(req.cook_dir(), rc)


def run_judge(req: CookRequest) -> "CookStatus":
    args = ["judge", *_common_args(req)]
    if req.judges:
        args += ["--judges", ",".join(req.judges)]
    rc = _cli(args)
    return _status_or_stub(req.cook_dir(), rc)


def run_report(req: CookRequest) -> "CookResult":
    # report takes no --profile/--namespace; pass only name + root.
    rc = _cli(["report", req.name, "--root", str(_root_abs(req.root))])
    r = CookResult.from_dir(req.cook_dir(), exit_code=rc)
    if r is None:
        # summary.json absent (e.g. report failed before writing it).
        r = CookResult(cook=req.cook_dir().name, round=None,
                       status="missing", exit_code=rc)
    return r


def run_resume(req: CookRequest) -> "CookStatus":
    args = ["resume", *_common_args(req)]
    if req.force:
        args.append("--force")
    rc = _cli(args)
    return _status_or_stub(req.cook_dir(), rc)


def cancel(name: str, root: Path | str = Path("cooks"),
           namespace: str | None = None) -> int:
    args = ["cancel", name, "--root", str(_root_abs(root))]
    if namespace:
        args += ["--namespace", namespace]
    return _cli(args)


def get_status(name: str, root: Path | str = Path("cooks")) -> "CookStatus | None":
    """Read status.json without running anything (live progress polling)."""
    return CookStatus.from_dir(_cook_dir(name, root))


def get_result(name: str, root: Path | str = Path("cooks")) -> "CookResult | None":
    """Read summary.json without running anything."""
    return CookResult.from_dir(_cook_dir(name, root))


def get_artifacts(name: str, root: Path | str = Path("cooks")) -> dict | None:
    """Read artifacts.json without running anything (visibility manifest)."""
    import json
    p = artifacts_path(_cook_dir(name, root))
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None
