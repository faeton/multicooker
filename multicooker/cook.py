"""`multicooker cook <name>` — launch all participants in parallel containers.

Each participant runs in its own docker container, in
`cooks/<name>/work/<participant>/`. That folder is bind-mounted as their
writable worktree. They get:
  - BRIEF.md  (read-only bind-mount of ../../BRIEF.md)
  - raw/      (read-only bind-mount)
  - PROMPT.txt (read-only bind-mount of /work/<p>/PROMPT.txt)
  - out/      (read-write bind-mount; their submission ends up here)
  - their flavor's auth snapshot (read-only, from .auth/<flavor>/)

After all participants finish (or rate-limit/timeout), a sealed copy of
each work tree is placed under `cooks/<name>/judging/_inbox/` for judges.

Docker is the only mode. There is no host-mode anymore — the CLAUDE.md
HARD rule (everything in docker) is now enforced in code, not docs.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import base_images, compose_render, compose_runner, creds, metrics, state
from .runner_common import RunResult, classify_cell


PROMPT_TEMPLATE = """\
You are a participant in a multi-LLM bake-off. You are working in your own
isolated worktree. Other participants are solving the same task in their
own worktrees in parallel; you cannot see or interfere with them.

# Task brief

The full task description is at `./BRIEF.md`. Read it first.

# What you can read

- `./BRIEF.md` — the task brief (read-only)
- `./raw/` — reference material the user has provided (read-only)
- `./` — anything you put here, you can read

# What you must produce

Read BRIEF.md for the contract. Typically you must write:
- `./out/RESULT.md`  — your answer / proposal / summary
- `./out/<artifacts>` — any files the brief asks for

# Rules

- Do not attempt to access any path outside this worktree.
- Do not contact other participants. They are running in parallel.
- If the brief is ambiguous, make your best judgement and document it
  in RESULT.md under a "Assumptions" section. The judges reward
  honest reasoning over hidden guesses.
- When done, just exit. No need to "submit".

Begin.
"""


def _seal_for_judging(cook_dir: Path, participant: str, *,
                      exit_class: str | None = None,
                      round_num: int | None = None) -> None:
    """Copy ONLY work/<p>/out/ into judging/_inbox/<p>/out/, plus a sanitized
    meta.json.

    Deliberately does NOT copy PROMPT.txt, trace.json, usage/, or logs: those
    carry the participant's flavor, model, and name, and judge.py copytrees
    _inbox/<p>/ straight into the blind submissions/<letter>/. Copying the
    whole work tree (the old behavior) leaked identity into judge input.

    The meta.json that IS judge-visible is curated: exit_class + round only,
    never flavor/model/name. When exit_class/round aren't passed (e.g.
    rejudge, which only has a participant name), they're read host-side from
    work/<p>/trace.json — trace.json itself is never sealed.
    """
    from .runner_common import copytree_clean
    src = cook_dir / "work" / participant
    dst = cook_dir / "judging" / "_inbox" / participant
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)
    out_src = src / "out"
    if out_src.exists():
        copytree_clean(out_src, dst / "out")
    else:
        (dst / "out").mkdir(parents=True, exist_ok=True)
    if exit_class is None or round_num is None:
        trace = src / "trace.json"
        if trace.exists():
            try:
                t = json.loads(trace.read_text())
                if exit_class is None:
                    exit_class = t.get("status")
                if round_num is None:
                    round_num = t.get("round_num")
            except (json.JSONDecodeError, OSError):
                pass
    meta: dict = {"schema_version": 1}
    if exit_class is not None:
        meta["exit_class"] = exit_class
    if round_num is not None:
        meta["round"] = round_num
    (dst / "meta.json").write_text(json.dumps(meta, indent=2))


def _setup_worktree(cook_dir: Path, participant: str, prompt_text: str) -> Path:
    """Prepare cook_dir/work/<p>/out/ and PROMPT.txt; bind-mounts handle the rest."""
    wt = cook_dir / "work" / participant
    wt.mkdir(parents=True, exist_ok=True)
    (wt / "out").mkdir(exist_ok=True)
    # Write PROMPT.txt + fsync so the file is durably on disk before compose
    # bind-mounts it. On native Linux docker, mounting a single file that
    # isn't visible to the daemon yet can silently materialize as an empty
    # directory inside the container (and entrypoints exit on missing file).
    prompt_path = wt / "PROMPT.txt"
    with open(prompt_path, "w") as f:
        f.write(prompt_text)
        f.flush()
        os.fsync(f.fileno())
    # Tear down stale legacy host-mode symlinks so the bind-mounts don't see them.
    for stale in (wt / "BRIEF.md", wt / "raw"):
        if stale.is_symlink():
            stale.unlink()
    return wt


def _write_trace(cook_dir: Path, participant: dict, mode: str,
                 round_num: int | None, started_at: str,
                 res: RunResult | None, status: str,
                 error: str | None = None,
                 usage: dict | None = None) -> None:
    """Per-cell trace.json next to work/<p>/. Cheap structured artifact for
    rejudge / debugging without re-running the LLM. Overwrites previous
    round's trace — round-N traces also live in rounds/<N>/<p>/trace.json
    via the existing snapshot path (refine snapshots out/, trace.json sits
    in work/<p>/, not in out/, so it does NOT get auto-snapshotted; see
    docs/design-notes.md if we ever decide to keep them per-round)."""
    name = participant["name"]
    trace_path = cook_dir / "work" / name / "trace.json"
    trace = {
        "name": name,
        "flavor": participant.get("flavor", name),
        "model": participant.get("model"),
        "mode": mode,
        "round_num": round_num,
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
    }
    if error is not None:
        trace["error"] = error
    if res is not None:
        trace.update({
            "exit_code": res.exit_code,
            "duration_s": round(res.duration_s, 1),
            "rate_limited": res.rate_limited,
            "rate_limit_evidence": res.rate_limit_evidence,
            "retry_after_s": res.retry_after_s,
            "timed_out": res.timed_out,
            "stdout_path": str(res.stdout_path),
            "stderr_path": str(res.stderr_path),
        })
    if usage is not None:
        trace["usage"] = usage
    trace_path.write_text(json.dumps(trace, indent=2))


def _run_participant(cook_dir: Path, project: str, participant: dict,
                     results: dict, timeout_s: int, prompt_text: str,
                     lock: threading.Lock, *, round_num: int = 1,
                     phase: str = "cook", mode: str = "cook") -> None:
    name = participant["name"]
    flavor = participant.get("flavor", name)
    service = f"participant-{name}"
    eff_timeout = int(participant.get("timeout_s", timeout_s))
    _setup_worktree(cook_dir, name, prompt_text)
    metrics.reset_usage_dir(cook_dir, "participant", name, flavor)
    log_dir = cook_dir / "logs" / name
    started_at = datetime.now(timezone.utc).isoformat()
    state.set_cell(cook_dir, name, role="participant", flavor=flavor,
                   state=state.RUNNING, started_at=started_at)
    state.append_event(cook_dir, "cell.started", phase=phase, actor=name,
                       payload={"flavor": flavor, "round": round_num})
    print(f"[{phase}] {name} ({flavor}): launching service {service} "
          f"(timeout {eff_timeout}s)", flush=True)
    try:
        res: RunResult = compose_runner.run_cell(
            cook_dir=cook_dir, project=project, service=service,
            flavor=flavor, log_dir=log_dir, timeout_s=eff_timeout,
        )
    except Exception as e:                                                  # noqa: BLE001
        with lock:
            results[name] = {
                "name": name, "flavor": flavor, "status": "start_failed",
                "error": str(e), "duration_s": 0.0,
            }
        _write_trace(cook_dir, participant, mode=mode, round_num=round_num,
                     started_at=started_at, res=None, status="start_failed", error=str(e))
        state.set_cell(cook_dir, name, state=state.START_FAILED,
                       finished_at=state.now_iso(), exit_class=state.START_FAILED)
        state.append_event(cook_dir, "cell.exited", phase=phase, actor=name,
                           payload={"exit_class": state.START_FAILED, "error": str(e)})
        print(f"[{phase}] {name}: FAILED to launch: {e}", flush=True)
        return

    status = classify_cell(res)
    # If a cancel was requested mid-run, the container was stopped externally;
    # don't mislabel that 137/125 exit as a genuine non_zero_exit.
    if state.is_cancelled(cook_dir) and status != "ok":
        status = state.CELL_CANCELLED
    usage = metrics.collect_usage(cook_dir, "participant", name, flavor)
    with lock:
        result = {
            "name": name, "flavor": flavor, "status": status,
            "exit_code": res.exit_code,
            "duration_s": round(res.duration_s, 1),
            "rate_limit_evidence": res.rate_limit_evidence,
            "retry_after_s": res.retry_after_s,
            "stdout": str(res.stdout_path),
            "stderr": str(res.stderr_path),
        }
        if usage is not None:
            result["usage"] = usage
        results[name] = result
    _write_trace(cook_dir, participant, mode=mode, round_num=round_num,
                 started_at=started_at, res=res, status=status, usage=usage)
    _seal_for_judging(cook_dir, name, exit_class=status, round_num=round_num)
    state.set_cell(cook_dir, name, state=status, finished_at=state.now_iso(),
                   exit_class=status, duration_s=round(res.duration_s, 1))
    if res.rate_limited:
        state.append_event(cook_dir, "cell.rate_limited", phase=phase, actor=name,
                           payload={"retry_after_s": res.retry_after_s})
    state.append_event(cook_dir, "cell.exited", phase=phase, actor=name,
                       payload={"exit_class": status, "duration_s": round(res.duration_s, 1)})
    print(f"[{phase}] {name}: {status} (exit={res.exit_code}, {res.duration_s:.1f}s)", flush=True)


def _snapshot_creds_or_die(cook_dir: Path, flavors: list[str]) -> int | None:
    """Try to snapshot creds. On failure, print a friendly message and return
    a non-None exit code so the caller can `return` it."""
    try:
        creds.snapshot(cook_dir, flavors)
    except creds.CredsError as e:
        print("\n[cook] cannot start: subscription auth not ready.", file=sys.stderr)
        print(f"\n{e}\n", file=sys.stderr)
        print("Run `multicooker doctor` to see exactly what's missing, then "
              "log in to the affected CLI(s) on the host and re-run.",
              file=sys.stderr)
        return 2
    return None


def cook(name: str, root: Path,
         participants_override: list[str] | None = None,
         profile_override: str | None = None) -> int:
    cook_dir = root / name if not Path(name).is_absolute() else Path(name)
    if not cook_dir.exists():
        print(f"error: cook folder {cook_dir} does not exist; "
              f"run `multicooker new {name}` first", flush=True)
        return 2

    brief_yaml = cook_dir / "brief.yaml"
    if not brief_yaml.exists():
        print(f"error: {brief_yaml} missing", flush=True)
        return 2
    cfg = yaml.safe_load(brief_yaml.read_text())

    from . import brief_schema
    rc = brief_schema.validate_or_die(cfg, source=str(brief_yaml))
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
    project = f"mc-{cfg['name']}".lower().replace("_", "-")
    flavors_needed = sorted({p.get("flavor", p["name"]) for p in participants})

    # Stamp run metadata.
    run_meta = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "participants": [p["name"] for p in participants],
        "timeout_s": timeout_s,
        "host": os.uname().nodename,
        "mode": "docker",
    }
    state.write_json_atomic(cook_dir / "RUN.json", run_meta)

    # Initialize the machine-readable contract: status.json + events.jsonl.
    init_cells = {
        p["name"]: {"role": "participant",
                    "flavor": p.get("flavor", p["name"]),
                    "state": state.PENDING}
        for p in participants
    }
    state.clear_cancel(cook_dir)  # drop any stale marker from a prior run
    state.init_status(cook_dir, cook=cook_dir.name, phase="cook",
                      state=state.CREATED, cells=init_cells, round_num=1)
    state.append_event(cook_dir, "cook.created", cook=cook_dir.name, phase="cook",
                       payload={"participants": [p["name"] for p in participants]})
    state.append_event(cook_dir, "phase.started", cook=cook_dir.name, phase="cook")

    brief_text = (cook_dir / "BRIEF.md").read_text()
    prompt_text = PROMPT_TEMPLATE + "\n\n---\n\n# BRIEF.md\n\n" + brief_text

    print(f"[cook] project={project} flavors={flavors_needed}", flush=True)
    print("[cook] snapshotting creds...", flush=True)
    state.update_status(cook_dir, state=state.PREFLIGHTING)
    rc = _snapshot_creds_or_die(cook_dir, flavors_needed)
    if rc is not None:
        state.finalize(cook_dir, state.FAILED)
        state.append_event(cook_dir, "cook.failed", phase="cook",
                           payload={"reason": "creds snapshot failed"})
        return rc

    compose_render.render_compose(cook_dir, cfg, profile_override=profile_override)

    # Worktrees BEFORE build — compose refuses to mount missing files.
    for p in participants:
        _setup_worktree(cook_dir, p["name"], prompt_text)

    state.update_status(cook_dir, state=state.BUILDING)
    state.append_event(cook_dir, "image.build.started", phase="cook")
    try:
        base_images.ensure_built(flavors_needed)
    except Exception as e:                                                   # noqa: BLE001
        print(f"[cook] base image build failed: {e}", flush=True)
        state.finalize(cook_dir, state.FAILED)
        state.append_event(cook_dir, "cook.failed", phase="cook",
                           payload={"reason": f"base image build failed: {e}"})
        return 2

    services = [f"participant-{p['name']}" for p in participants]
    try:
        compose_runner.build_images(cook_dir, project, services)
    except Exception as e:                                                  # noqa: BLE001
        print(f"[cook] build failed: {e}", flush=True)
        state.finalize(cook_dir, state.FAILED)
        state.append_event(cook_dir, "cook.failed", phase="cook",
                           payload={"reason": f"build failed: {e}"})
        return 2
    state.append_event(cook_dir, "image.build.finished", phase="cook")
    state.update_status(cook_dir, state=state.COOKING)

    results: dict[str, dict] = {}
    lock = threading.Lock()

    threads: list[threading.Thread] = []
    for p in participants:
        t = threading.Thread(
            target=_run_participant,
            args=(cook_dir, project, p, results, timeout_s, prompt_text, lock),
            daemon=True,
        )
        t.start()
        threads.append(t)
        # 2-sec stagger so auth refresh storms don't sync.
        time.sleep(2)
    for t in threads:
        t.join()

    try:
        compose_runner.teardown(cook_dir, project)
    except Exception as e:                                                  # noqa: BLE001
        print(f"[cook] teardown warning: {e}", flush=True)

    summary = cook_dir / "RUN_RESULT.json"
    state.write_json_atomic(summary, {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "round": 1,
        "participants": [results[p["name"]] for p in participants if p["name"] in results],
    })
    # finalize honors a cancel marker written by a concurrent `cancel` process
    # (atomically, so sealed never clobbers cancelled).
    final_state = state.finalize(cook_dir, state.SEALED)
    if final_state == state.CANCELLED:
        state.append_event(cook_dir, "cook.cancelled", cook=cook_dir.name, phase="cook")
        print(f"\n[cook] cancelled. partial results at {summary}")
        return 130
    state.append_event(cook_dir, "seal.finished", phase="cook")
    print(f"\n[cook] done. summary at {summary}")
    print(f"[cook] sealed work trees at {cook_dir}/judging/_inbox/")
    print(f"[cook] next: multicooker judge {name}")

    any_ok = any(r["status"] == "ok" for r in results.values())
    return 0 if any_ok else 1
