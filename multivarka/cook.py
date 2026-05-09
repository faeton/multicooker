"""`multivarka cook <name>` — launch all participants in parallel.

Each participant runs in `cooks/<name>/work/<participant>/`. That folder is
their writable worktree. They get:
  - BRIEF.md  (read-only symlink to ../../BRIEF.md      ; host-mode)
              (read-only bind-mount of ../../BRIEF.md   ; docker-mode)
  - raw/      (read-only symlink / bind-mount)
  - their own writable space; whatever they write under work/<p>/out/ is
    treated as their submission

After all participants finish (or rate-limit/timeout), a sealed copy of
each work tree is placed under `cooks/<name>/judging/_inbox/` for judges.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .host_runner import run, RunResult
from . import compose_render, compose_runner, creds


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


def _setup_worktree(cook_dir: Path, participant: str) -> Path:
    """Create work/<participant>/ with symlinks to ../BRIEF.md and ../raw."""
    wt = cook_dir / "work" / participant
    wt.mkdir(parents=True, exist_ok=True)
    (wt / "out").mkdir(exist_ok=True)

    # Symlinks (relative) so the participant sees ./BRIEF.md and ./raw.
    brief_link = wt / "BRIEF.md"
    raw_link = wt / "raw"
    if brief_link.is_symlink() or brief_link.exists():
        brief_link.unlink()
    if raw_link.is_symlink() or raw_link.exists():
        if raw_link.is_dir() and not raw_link.is_symlink():
            shutil.rmtree(raw_link)
        else:
            raw_link.unlink()
    brief_link.symlink_to(Path("..") / ".." / "BRIEF.md")
    raw_link.symlink_to(Path("..") / ".." / "raw")
    return wt


def _seal_for_judging(cook_dir: Path, participant: str) -> None:
    """Copy work/<p>/ into judging/_inbox/<p>/ as a frozen artefact."""
    src = cook_dir / "work" / participant
    dst = cook_dir / "judging" / "_inbox" / participant
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)
    # Don't copy the symlinks — the judge has its own view of BRIEF and raw.
    for item in src.iterdir():
        if item.is_symlink():
            continue
        if item.is_dir():
            shutil.copytree(item, dst / item.name)
        else:
            shutil.copy2(item, dst / item.name)


def _run_participant(cook_dir: Path, participant: dict, results: dict,
                     timeout_s: int, prompt_text: str, lock: threading.Lock) -> None:
    name = participant["name"]
    flavor = participant.get("flavor", name)
    wt = _setup_worktree(cook_dir, name)
    log_dir = cook_dir / "logs" / name
    print(f"[cook] {name} ({flavor}): starting in {wt}", flush=True)
    try:
        res: RunResult = run(
            flavor=flavor, worktree=wt, prompt_text=prompt_text,
            log_dir=log_dir, timeout_s=timeout_s, wait_for_reset=False,
        )
    except Exception as e:                                                  # noqa: BLE001
        with lock:
            results[name] = {
                "name": name, "flavor": flavor, "status": "error",
                "error": str(e), "duration_s": 0.0,
            }
        print(f"[cook] {name}: FAILED to launch: {e}", flush=True)
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
    _seal_for_judging(cook_dir, name)
    print(f"[cook] {name}: {status} (exit={res.exit_code}, {res.duration_s:.1f}s)", flush=True)


def _setup_worktree_docker(cook_dir: Path, participant: str,
                           prompt_text: str) -> Path:
    """Prepare cook_dir/work/<p>/out/ and PROMPT.txt; bind-mounts handle the rest."""
    wt = cook_dir / "work" / participant
    wt.mkdir(parents=True, exist_ok=True)
    (wt / "out").mkdir(exist_ok=True)
    # PROMPT.txt is bind-mounted RO into the container at /work/PROMPT.txt.
    (wt / "PROMPT.txt").write_text(prompt_text)
    # Tear down stale host-mode symlinks so the bind-mounts don't see them.
    for stale in (wt / "BRIEF.md", wt / "raw"):
        if stale.is_symlink():
            stale.unlink()
    return wt


def _run_participant_docker(cook_dir: Path, project: str, participant: dict,
                            results: dict, timeout_s: int, prompt_text: str,
                            lock: threading.Lock) -> None:
    name = participant["name"]
    flavor = participant.get("flavor", name)
    service = f"participant-{name}"
    _setup_worktree_docker(cook_dir, name, prompt_text)
    log_dir = cook_dir / "logs" / name
    print(f"[cook] {name} ({flavor}): launching service {service}", flush=True)
    try:
        res: RunResult = compose_runner.run_cell(
            cook_dir=cook_dir, project=project, service=service,
            flavor=flavor, log_dir=log_dir, timeout_s=timeout_s,
        )
    except Exception as e:                                                  # noqa: BLE001
        with lock:
            results[name] = {
                "name": name, "flavor": flavor, "status": "error",
                "error": str(e), "duration_s": 0.0,
            }
        print(f"[cook] {name}: FAILED to launch: {e}", flush=True)
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
    _seal_for_judging(cook_dir, name)
    print(f"[cook] {name}: {status} (exit={res.exit_code}, {res.duration_s:.1f}s)", flush=True)


def _cook_docker(cook_dir: Path, cfg: dict, participants: list[dict],
                 timeout_s: int, prompt_text: str,
                 results: dict, lock: threading.Lock) -> int:
    project = f"mv-{cfg['name']}".lower().replace("_", "-")
    flavors_needed = sorted({p.get("flavor", p["name"]) for p in participants})

    print(f"[cook] docker mode: project={project} flavors={flavors_needed}", flush=True)

    # 1. Snapshot creds (Keychain → cooks/<task>/.auth/, etc).
    print("[cook] snapshotting creds...", flush=True)
    creds.snapshot(cook_dir, flavors_needed)

    # 2. Render compose.yaml from brief.yaml.
    compose_render.render_compose(cook_dir, cfg)

    # 3. Set up per-participant worktrees (PROMPT.txt etc.) BEFORE build —
    #    docker compose will refuse to mount missing files.
    for p in participants:
        _setup_worktree_docker(cook_dir, p["name"], prompt_text)

    # 4. Build participant images.
    services = [f"participant-{p['name']}" for p in participants]
    try:
        compose_runner.build_images(cook_dir, project, services)
    except Exception as e:                                                  # noqa: BLE001
        print(f"[cook] build failed: {e}", flush=True)
        return 2

    # 5. Run each participant in parallel (each as its own thread; compose_runner
    #    blocks per-cell). 2-sec stagger so auth refresh storms don't sync.
    threads = []
    for p in participants:
        t = threading.Thread(
            target=_run_participant_docker,
            args=(cook_dir, project, p, results, timeout_s, prompt_text, lock),
            daemon=True,
        )
        t.start()
        threads.append(t)
        time.sleep(2)
    for t in threads:
        t.join()

    # 6. Final teardown — remove any orphaned containers/networks.
    try:
        compose_runner.teardown(cook_dir, project)
    except Exception as e:                                                  # noqa: BLE001
        print(f"[cook] teardown warning: {e}", flush=True)

    # 7. Summary file (host-mode does this too — keep it consistent).
    summary = cook_dir / "RUN_RESULT.json"
    summary.write_text(json.dumps({
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "participants": [results[p["name"]] for p in participants if p["name"] in results],
    }, indent=2))
    print(f"\n[cook] done. summary at {summary}")
    print(f"[cook] sealed work trees at {cook_dir}/judging/_inbox/")
    print(f"[cook] next: multivarka judge {cfg['name']}")
    any_ok = any(r["status"] == "ok" for r in results.values())
    return 0 if any_ok else 1


def cook(name: str, root: Path, use_docker: bool = False,
         participants_override: list[str] | None = None) -> int:
    cook_dir = root / name if not Path(name).is_absolute() else Path(name)
    if not cook_dir.exists():
        print(f"error: cook folder {cook_dir} does not exist; "
              f"run `multivarka new {name}` first", flush=True)
        return 2

    brief_yaml = cook_dir / "brief.yaml"
    if not brief_yaml.exists():
        print(f"error: {brief_yaml} missing", flush=True)
        return 2
    cfg = yaml.safe_load(brief_yaml.read_text())

    participants = cfg.get("participants", [])
    if participants_override:
        wanted = set(participants_override)
        participants = [p for p in participants if p["name"] in wanted]
    if not participants:
        print("error: no participants selected", flush=True)
        return 2

    timeout_s = int(cfg.get("timeout_s", 30 * 60))

    # Stamp run metadata.
    run_meta = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "participants": [p["name"] for p in participants],
        "timeout_s": timeout_s,
        "host": os.uname().nodename,
        "mode": "docker" if use_docker else "host",
    }
    (cook_dir / "RUN.json").write_text(json.dumps(run_meta, indent=2))

    # Read brief into the prompt — participant CLIs work better with the brief
    # inlined in the prompt than relying on them to read BRIEF.md, even though
    # we also symlink/mount it.
    brief_text = (cook_dir / "BRIEF.md").read_text()
    prompt_text = PROMPT_TEMPLATE + "\n\n---\n\n# BRIEF.md\n\n" + brief_text

    results: dict[str, dict] = {}
    lock = threading.Lock()

    if use_docker:
        return _cook_docker(cook_dir, cfg, participants, timeout_s,
                            prompt_text, results, lock)

    threads = []
    for p in participants:
        t = threading.Thread(target=_run_participant,
                             args=(cook_dir, p, results, timeout_s, prompt_text, lock),
                             daemon=True)
        t.start()
        threads.append(t)
        # Stagger the launches by a couple seconds so the CLIs don't all hit
        # auth refresh at the exact same instant.
        time.sleep(2)

    for t in threads:
        t.join()

    summary = cook_dir / "RUN_RESULT.json"
    summary.write_text(json.dumps({
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "participants": [results[p["name"]] for p in participants if p["name"] in results],
    }, indent=2))

    print()
    print(f"[cook] done. summary at {summary}")
    print(f"[cook] sealed work trees at {cook_dir}/judging/_inbox/")
    print(f"[cook] next: multivarka judge {name}")
    # Exit 0 if at least one participant produced something usable.
    any_ok = any(r["status"] == "ok" for r in results.values())
    return 0 if any_ok else 1
