"""`multicooker refine <task>` — run another round on top of previous output.

Iteration mode (vs cook's bake-off mode). Each participant sees:
  - their own previous round's `./out/` (in place, RW — they edit/replace)
  - inline shared FEEDBACK.md and per-participant FEEDBACK_<flavor>.md content
    embedded in PROMPT.txt
  - same BRIEF.md and raw/ as before

Previous round's outputs are snapshotted to cooks/<task>/rounds/<N>/<p>/
before the run, so history is never lost. The just-run round becomes
work/<p>/out/ (and the next sealed _inbox).

Docker-only — host-mode is legacy.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import base_images, compose_render, compose_runner
from .cook import _seal_for_judging, _snapshot_creds_or_die, _write_trace
from .runner_common import RunResult


REFINE_PROMPT_HEADER = """\
You are a participant in a multi-LLM bake-off. **This is a refinement round
(round {round_num}).** You already produced round {prev_round}; that work
is still present at `./out/`. Read it first, then improve it based on the
feedback below.

# What you can read
- `./BRIEF.md` — the original task brief (read-only, unchanged).
- `./raw/` — the same reference material as before (read-only).
- `./out/` — **your previous round's output**, writable. Edit, replace, extend.

# Rules
- This is iteration, not a fresh start. Keep what worked; fix what didn't.
- The feedback below is the user's direct review — treat as authoritative.
- If feedback asks for a feature you didn't have, add it.
- If your previous output had something the feedback contradicts, change it.
- Keep the same artefact shape (`./out/RESULT.md` + the files the brief asks for).
- In `./out/RESULT.md`, add a "Round {round_num} changes" section: what you
  changed, what you kept, and why.

# Shared feedback (applies to all participants)

{shared_feedback}
"""

REFINE_PROMPT_PERSONAL = """\
# Personal feedback (addressed specifically to you)

{personal_feedback}
"""

REFINE_PROMPT_FOOTER = """\
---

Below is the original BRIEF.md (unchanged from round 1, included for reference):

---

# BRIEF.md

{brief}

Begin.
"""


def _next_round_num(cook_dir: Path) -> int:
    """Return N where the run we are *about to do* will be round N.

    rounds/ holds snapshots of completed rounds. If rounds/ has {1,2}, then
    work/<p>/out/ is currently round 3 (just finished), and the run we are
    about to do is round 4. If rounds/ is empty/missing, work/ holds round 1
    (the original cook), and we are about to run round 2.
    """
    rounds_dir = cook_dir / "rounds"
    if not rounds_dir.exists():
        return 2
    nums = sorted(int(d.name) for d in rounds_dir.iterdir()
                  if d.is_dir() and d.name.isdigit())
    if not nums:
        return 2
    return nums[-1] + 2  # snapshot the live one as max+1, then run max+2


def _snapshot_previous(cook_dir: Path, participants: list[dict],
                       prev_round_num: int) -> Path:
    """Copy current work/<p>/out/ → rounds/<prev_round_num>/<p>/."""
    snap_root = cook_dir / "rounds" / str(prev_round_num)
    snap_root.mkdir(parents=True, exist_ok=True)
    for p in participants:
        name = p["name"]
        src = cook_dir / "work" / name / "out"
        dst = snap_root / name
        if dst.exists():
            shutil.rmtree(dst)
        if src.exists():
            shutil.copytree(src, dst)
    # Also snapshot the sealed judging inbox if present (so judging history
    # for that round is preserved alongside the raw work).
    inbox = cook_dir / "judging" / "_inbox"
    if inbox.exists():
        dst = snap_root / "_inbox"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(inbox, dst)
    return snap_root


def _build_prompt(cook_dir: Path, participant: dict, round_num: int,
                  shared_fb: str, brief: str) -> str:
    flavor = participant.get("flavor", participant["name"])
    parts = [REFINE_PROMPT_HEADER.format(
        round_num=round_num, prev_round=round_num - 1,
        shared_feedback=shared_fb.strip() or "(none provided)",
    )]
    personal_path = cook_dir / f"FEEDBACK_{flavor}.md"
    if personal_path.exists():
        parts.append(REFINE_PROMPT_PERSONAL.format(
            personal_feedback=personal_path.read_text().strip()
        ))
    parts.append(REFINE_PROMPT_FOOTER.format(brief=brief))
    return "\n".join(parts)


def _setup_worktree_refine(cook_dir: Path, participant: str,
                           prompt_text: str) -> None:
    """Write PROMPT.txt; leave out/ in place (it's the previous round's work)."""
    wt = cook_dir / "work" / participant
    wt.mkdir(parents=True, exist_ok=True)
    (wt / "out").mkdir(exist_ok=True)
    (wt / "PROMPT.txt").write_text(prompt_text)
    for stale in (wt / "BRIEF.md", wt / "raw"):
        if stale.is_symlink():
            stale.unlink()


def _run_one(cook_dir: Path, project: str, participant: dict,
             prompt_text: str, timeout_s: int, results: dict,
             round_num: int,
             lock: threading.Lock) -> None:
    name = participant["name"]
    flavor = participant.get("flavor", name)
    service = f"participant-{name}"
    eff_timeout = int(participant.get("timeout_s", timeout_s))
    _setup_worktree_refine(cook_dir, name, prompt_text)
    log_dir = cook_dir / "logs" / name
    started_at = datetime.now(timezone.utc).isoformat()
    print(f"[refine] {name} ({flavor}): launching service {service} "
          f"(timeout {eff_timeout}s)", flush=True)
    try:
        res: RunResult = compose_runner.run_cell(
            cook_dir=cook_dir, project=project, service=service,
            flavor=flavor, log_dir=log_dir, timeout_s=eff_timeout,
        )
    except Exception as e:                                                  # noqa: BLE001
        with lock:
            results[name] = {
                "name": name, "flavor": flavor, "status": "error",
                "error": str(e), "duration_s": 0.0,
            }
        _write_trace(cook_dir, participant, mode="refine", round_num=round_num,
                     started_at=started_at, res=None, status="error", error=str(e))
        print(f"[refine] {name}: FAILED to launch: {e}", flush=True)
        return
    status = (
        "rate_limited" if res.rate_limited
        else "timed_out" if res.timed_out
        else "ok" if res.exit_code == 0
        else "non_zero_exit"
    )
    with lock:
        results[name] = {
            "name": name, "flavor": flavor, "status": status,
            "exit_code": res.exit_code,
            "duration_s": round(res.duration_s, 1),
            "rate_limit_evidence": res.rate_limit_evidence,
            "retry_after_s": res.retry_after_s,
            "stdout": str(res.stdout_path),
            "stderr": str(res.stderr_path),
        }
    _write_trace(cook_dir, participant, mode="refine", round_num=round_num,
                 started_at=started_at, res=res, status=status)
    _seal_for_judging(cook_dir, name)
    print(f"[refine] {name}: {status} (exit={res.exit_code}, {res.duration_s:.1f}s)",
          flush=True)


def refine(name: str, root: Path,
           participants_override: list[str] | None = None,
           feedback_path: Path | None = None) -> int:
    cook_dir = root / name if not Path(name).is_absolute() else Path(name)
    if not cook_dir.exists():
        print(f"error: cook folder {cook_dir} does not exist", flush=True)
        return 2
    cfg = yaml.safe_load((cook_dir / "brief.yaml").read_text())

    from . import brief_schema
    rc = brief_schema.validate_or_die(cfg, source=str(cook_dir / "brief.yaml"))
    if rc is not None:
        return rc

    participants = cfg.get("participants", [])
    if participants_override:
        wanted = set(participants_override)
        participants = [p for p in participants if p["name"] in wanted]
    if not participants:
        print("error: no participants selected", flush=True)
        return 2

    timeout_s = int(cfg.get("timeout_s", 30 * 60))

    # Round-N math.
    round_num = _next_round_num(cook_dir)
    prev_round = round_num - 1

    if feedback_path is not None:
        fb_path = feedback_path if feedback_path.is_absolute() else Path.cwd() / feedback_path
        if not fb_path.exists():
            print(f"error: --feedback path {fb_path} not found", flush=True)
            return 2
        print(f"[refine] using shared feedback from {fb_path}", flush=True)
        shared_fb = fb_path.read_text()
    else:
        fb_path = cook_dir / "FEEDBACK.md"
        if not fb_path.exists():
            print(f"warn: {fb_path} missing — running with empty shared feedback",
                  flush=True)
            shared_fb = ""
        else:
            shared_fb = fb_path.read_text()

    brief_text = (cook_dir / "BRIEF.md").read_text()

    # 1. Snapshot previous round before we touch anything.
    snap = _snapshot_previous(cook_dir, participants, prev_round)
    print(f"[refine] snapshotted round {prev_round} → {snap}", flush=True)

    # Stamp metadata.
    (cook_dir / f"REFINE_{round_num}.json").write_text(json.dumps({
        "started_at": datetime.now(timezone.utc).isoformat(),
        "round_num": round_num,
        "prev_round": prev_round,
        "participants": [p["name"] for p in participants],
        "timeout_s": timeout_s,
        "snapshot": str(snap),
    }, indent=2))

    project = f"mc-{cfg['name']}".lower().replace("_", "-")
    flavors_needed = sorted({p.get("flavor", p["name"]) for p in participants})

    print(f"[refine] round {round_num}: project={project} flavors={flavors_needed}",
          flush=True)
    print("[refine] snapshotting creds...", flush=True)
    rc = _snapshot_creds_or_die(cook_dir, flavors_needed)
    if rc is not None:
        return rc

    # 2. Compose render (judges section may be re-rendered later by `judge`,
    #    but we still need participant services to exist.)
    compose_render.render_compose(cook_dir, cfg)

    # 3. Per-participant prompts.
    prompts = {p["name"]: _build_prompt(cook_dir, p, round_num, shared_fb, brief_text)
               for p in participants}
    for p in participants:
        _setup_worktree_refine(cook_dir, p["name"], prompts[p["name"]])

    # 4. Build images (cached if Dockerfiles unchanged).
    try:
        base_images.ensure_built(flavors_needed)
    except Exception as e:                                                  # noqa: BLE001
        print(f"[refine] base image build failed: {e}", flush=True)
        return 2

    services = [f"participant-{p['name']}" for p in participants]
    try:
        compose_runner.build_images(cook_dir, project, services)
    except Exception as e:                                                  # noqa: BLE001
        print(f"[refine] build failed: {e}", flush=True)
        return 2

    # 5. Run participants in parallel.
    results: dict[str, dict] = {}
    lock = threading.Lock()
    threads: list[threading.Thread] = []
    for p in participants:
        t = threading.Thread(
            target=_run_one,
            args=(cook_dir, project, p, prompts[p["name"]], timeout_s, results, round_num, lock),
            daemon=True,
        )
        t.start()
        threads.append(t)
        time.sleep(2)
    for t in threads:
        t.join()

    try:
        compose_runner.teardown(cook_dir, project)
    except Exception as e:                                                  # noqa: BLE001
        print(f"[refine] teardown warning: {e}", flush=True)

    summary = cook_dir / f"REFINE_{round_num}_RESULT.json"
    summary.write_text(json.dumps({
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "round_num": round_num,
        "participants": [results[p["name"]] for p in participants
                         if p["name"] in results],
    }, indent=2))
    print(f"\n[refine] done. round {round_num} summary at {summary}")
    print(f"[refine] sealed work trees at {cook_dir}/judging/_inbox/")
    print(f"[refine] previous round preserved at {snap}")
    print(f"[refine] next: multicooker judge {name} --docker")

    any_ok = any(r["status"] == "ok" for r in results.values())
    return 0 if any_ok else 1
