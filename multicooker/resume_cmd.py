"""`multicooker resume <cook>` — re-run only the retryable cells of the latest round.

A rate-limited or timed-out participant can be retried without re-running the
ones that already succeeded. We target the latest round's result file
(RUN_RESULT.json or REFINE_<N>_RESULT.json), re-run only cells in a retryable
terminal state (or all, with --force), preserve each prior attempt under
attempts/round-<N>/<p>/attempt-<k>/, then MERGE the new results over the prior
result file so the successful participants survive for judge/report.

The exact prompt each cell ran is reused verbatim from work/<p>/PROMPT.txt, so
resume works the same after a plain cook or after a refine round without
reconstructing the refine prompt.
"""

from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

import yaml

from . import base_images, brief_schema, compose_render, compose_runner, state
from .cook import _run_participant, _snapshot_creds_or_die
from .report import _latest_run_result
from .runner_common import copytree_clean


def _project_name(cfg: dict) -> str:
    return f"mc-{cfg['name']}".lower().replace("_", "-")


def _archive_attempt(cook_dir: Path, round_num: int, name: str, *,
                     keep_out: bool) -> Path:
    """Snapshot the prior attempt's out/, trace.json, and logs before rerun.

    run_cell truncates logs and the participant overwrites out/, so we snapshot
    them first. trace.json and logs are always moved aside. out/ depends on the
    round semantics:

    - round 1 (cook): the failed attempt's out/ is discarded — move it away and
      recreate an empty out/ so the retry starts clean (cook prompt writes fresh).
    - refine round (round > 1): the refine prompt tells the cell to improve the
      work already in ./out/, so we COPY out/ into the archive and LEAVE it in
      place; removing it would make the retried cell start from nothing.

    Returns the attempt directory.
    """
    base = cook_dir / "attempts" / f"round-{round_num}" / name
    base.mkdir(parents=True, exist_ok=True)
    k = 1 + sum(1 for d in base.iterdir()
                if d.is_dir() and d.name.startswith("attempt-"))
    dest = base / f"attempt-{k}"
    dest.mkdir()
    wt = cook_dir / "work" / name
    out = wt / "out"
    if out.exists():
        if keep_out:
            copytree_clean(out, dest / "out")
        else:
            shutil.move(str(out), str(dest / "out"))
            (wt / "out").mkdir(parents=True, exist_ok=True)
    else:
        (wt / "out").mkdir(parents=True, exist_ok=True)
    trace = wt / "trace.json"
    if trace.exists():
        shutil.move(str(trace), str(dest / "trace.json"))
    logs = cook_dir / "logs" / name
    if logs.exists():
        shutil.move(str(logs), str(dest / "logs"))
    return dest


def resume(name: str, root: Path, force: bool = False,
           profile_override: str | None = None) -> int:
    cook_dir = root / name if not Path(name).is_absolute() else Path(name)
    if not cook_dir.exists():
        print(f"error: cook folder {cook_dir} does not exist", flush=True)
        return 2
    brief_yaml = cook_dir / "brief.yaml"
    if not brief_yaml.exists():
        print(f"error: {brief_yaml} missing", flush=True)
        return 2
    cfg = yaml.safe_load(brief_yaml.read_text())
    rc = brief_schema.validate_or_die(cfg, source=str(brief_yaml))
    if rc is not None:
        return rc

    round_num, rr = _latest_run_result(cook_dir)
    prior = {p["name"]: p for p in rr.get("participants", [])}
    pcfg = {p["name"]: p for p in cfg.get("participants", [])}

    if force:
        targets = [n for n in prior if n in pcfg]
    else:
        targets = [n for n, e in prior.items()
                   if n in pcfg
                   and e.get("status") in state.RETRYABLE_CELL_STATES]
    if not targets:
        extra = ""
        if not force:
            skipped = sorted({e.get("status") for e in prior.values()
                              if e.get("status") not in state.RETRYABLE_CELL_STATES
                              and e.get("status") not in (None, "ok")})
            if skipped:
                extra = (f"; cells in state {skipped} are not auto-retryable — "
                         f"use --force to rerun them (and any OK cells)")
            else:
                extra = "; use --force to rerun OK cells"
        print(f"[resume] nothing to resume (round {round_num}: no retryable "
              f"cells{extra})", flush=True)
        return 0

    # Reuse each cell's exact prompt from the last run (cook or refine).
    prompts: dict[str, str] = {}
    for n in targets:
        ptxt = cook_dir / "work" / n / "PROMPT.txt"
        if not ptxt.exists():
            print(f"error: no work/{n}/PROMPT.txt; run `multicooker cook {name}` "
                  f"before resume", flush=True)
            return 2
        prompts[n] = ptxt.read_text()

    timeout_s = int(cfg.get("timeout_s", 30 * 60))
    project = _project_name(cfg)
    flavors_needed = sorted({pcfg[n].get("flavor", n) for n in targets})

    state.clear_cancel(cook_dir)
    state.update_status(cook_dir, cook=cook_dir.name, phase="resume",
                        state=state.PREFLIGHTING, round=round_num)
    state.append_event(cook_dir, "phase.started", cook=cook_dir.name, phase="resume",
                       payload={"round": round_num, "targets": targets})
    print(f"[resume] round {round_num}: retrying {targets}", flush=True)

    rc = _snapshot_creds_or_die(cook_dir, flavors_needed)
    if rc is not None:
        state.finalize(cook_dir, state.FAILED)
        return rc

    compose_render.render_compose(cook_dir, cfg, profile_override=profile_override)

    keep_out = round_num != 1  # refine rounds edit ./out/ in place
    for n in targets:
        _archive_attempt(cook_dir, round_num, n, keep_out=keep_out)
        state.reset_cell(cook_dir, n, role="participant",
                         flavor=pcfg[n].get("flavor", n))

    state.update_status(cook_dir, state=state.BUILDING)
    try:
        base_images.ensure_built(flavors_needed)
    except Exception as e:                                                   # noqa: BLE001
        print(f"[resume] base image build failed: {e}", flush=True)
        state.finalize(cook_dir, state.FAILED)
        return 2
    services = [f"participant-{n}" for n in targets]
    try:
        compose_runner.build_images(cook_dir, project, services)
    except Exception as e:                                                  # noqa: BLE001
        print(f"[resume] build failed: {e}", flush=True)
        state.finalize(cook_dir, state.FAILED)
        return 2

    state.update_status(cook_dir, state=state.COOKING)
    results: dict[str, dict] = {}
    lock = threading.Lock()
    required_outputs = (cfg.get("outputs") or {}).get("required")
    threads: list[threading.Thread] = []
    for n in targets:
        t = threading.Thread(
            target=_run_participant,
            args=(cook_dir, project, pcfg[n], results, timeout_s, prompts[n], lock),
            kwargs={"round_num": round_num, "phase": "resume", "mode": "resume",
                    "required_outputs": required_outputs},
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
        print(f"[resume] teardown warning: {e}", flush=True)

    # Merge: replace retried entries, keep the rest (OK participants survive).
    merged = dict(prior)
    for n in targets:
        if n in results:
            merged[n] = results[n]
    result_file = (cook_dir / "RUN_RESULT.json" if round_num == 1
                   else cook_dir / f"REFINE_{round_num}_RESULT.json")
    payload: dict = {
        "finished_at": state.now_iso(),
        "round": round_num,
        "participants": list(merged.values()),
    }
    if round_num != 1:
        payload["round_num"] = round_num
    state.write_json_atomic(result_file, payload)

    final = state.finalize(cook_dir, state.SEALED)
    if final == state.CANCELLED:
        state.append_event(cook_dir, "cook.cancelled", cook=cook_dir.name, phase="resume")
        print(f"\n[resume] cancelled. partial results at {result_file}", flush=True)
        return 130
    state.append_event(cook_dir, "seal.finished", phase="resume",
                       payload={"round": round_num})
    print(f"\n[resume] done. merged results at {result_file}", flush=True)
    print(f"[resume] next: multicooker judge {name}", flush=True)

    any_ok = any(r.get("status") == "ok" for r in results.values())
    return 0 if any_ok else 1
