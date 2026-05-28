"""`multicooker judge <name>` — score the sealed participant outputs.

Each judge LLM gets a sealed working directory containing:
  - JUDGE_BRIEF.md   (the task, plus rubric + how to score)
  - raw/             (read-only — same reference material participants saw)
  - submissions/<participant-id>/   (each participant's frozen work)

The judge writes ./outbox/scores.json + ./outbox/review.md and exits.

Critical pitfall (learned from arena): if you symlink submissions/raw/etc.
into the judge's work-dir, the CLI's sandbox allowlists won't follow the
symlinks and Read/Bash/Write all silently deny. Use real directories
(copy, then rm-after) to avoid placeholder scores.

Anonymity: participants are renamed to A/B/C/... before judging, so a
claude-judge can't identify the claude-participant. The mapping is
recorded in judging/_mapping.json for reporting.
"""

from __future__ import annotations

import json
import random
import secrets
import shutil
import threading
import time
from pathlib import Path

import yaml

from . import base_images, compose_render, compose_runner, metrics, state
from .cook import _snapshot_creds_or_die
from .judging_policy import judging_policy


JUDGE_PROMPT_TEMPLATE = """\
You are an impartial judge in a multi-LLM bake-off. Several participants
solved the same task independently. You will read each submission and
score them against a rubric.

# Files at your disposal

- `./JUDGE_BRIEF.md` — the original task brief and the scoring rubric.
- `./raw/` — the same reference material the participants had.
- `./submissions/A/`, `./submissions/B/`, ... — the frozen worktrees of
  each participant. Identities are stripped: you do NOT know which LLM
  produced which submission, and you must NOT try to guess.

# What you must produce

Write to `./outbox/`:

1. `scores.json` — JSON object of the form:
   ```
   {
     "A": {"dimensions": {"correctness": 4, "quality": 3, ...}, "total": 35},
     "B": {...},
     ...
   }
   ```
   Use the dimensions and weights from JUDGE_BRIEF.md. Score each
   dimension on the scale that brief specifies (default 0–5).

2. `review.md` — short paragraph per participant explaining the score
   and a final ranking with one-line justification.

# Rules

- Do not modify any submission. They are read-only inputs.
- Do not infer participant identity. If you do, your score is invalid.
- A submission missing required artefacts (per JUDGE_BRIEF.md) gets
  zero on that dimension; do not extrapolate.
- If a submission is broken/empty, say so and score honestly.

Begin.
"""


def _anonymize(participants: list[dict], inbox_root: Path,
               sealed: Path) -> tuple[Path, dict[str, str]]:
    """Build judge-input dir with submissions/A/, B/, ... and a mapping."""
    letters = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    random.shuffle(letters)
    mapping: dict[str, str] = {}
    judge_in = inbox_root / "_judge_input"
    if judge_in.exists():
        shutil.rmtree(judge_in)
    judge_in.mkdir(parents=True)
    sub_dir = judge_in / "submissions"
    sub_dir.mkdir()
    from .runner_common import copytree_clean
    for p, letter in zip(participants, letters):
        name = p["name"]
        src = sealed / name
        if not src.exists():
            continue
        dst = sub_dir / letter
        copytree_clean(src, dst)
        mapping[letter] = name
    return judge_in, mapping


def _setup_judge_workdir(cook_dir: Path, judge_name: str,
                         judge_in: Path,
                         deterministic: bool = False) -> Path:
    """Real-dir judge workdir (no symlinks; arena's symlink-bug avoided).

    deterministic=True (docker mode) uses a fixed name so the compose mount
    can target the same path. host-mode keeps a random suffix so concurrent
    cooks don't collide.
    """
    if deterministic:
        work = cook_dir / "judging" / f"_work-{judge_name}"
        if work.exists():
            shutil.rmtree(work)
    else:
        work = cook_dir / "judging" / f"_work-{judge_name}-{secrets.token_hex(3)}"
    work.mkdir(parents=True, exist_ok=True)
    # Copy JUDGE_BRIEF.md, raw/, submissions/ into work/
    shutil.copy(cook_dir / "JUDGE_BRIEF.md", work / "JUDGE_BRIEF.md")
    raw_src = cook_dir / "raw"
    if raw_src.exists():
        shutil.copytree(raw_src, work / "raw")
    shutil.copytree(judge_in / "submissions", work / "submissions")
    (work / "outbox").mkdir()
    return work


def _run_judge(cook_dir: Path, project: str, judge_cfg: dict,
               judge_in: Path, mapping: dict[str, str],
               timeout_s: int, results: dict,
               lock: threading.Lock, *, strict: bool = False) -> None:
    jname = judge_cfg["name"]
    flavor = judge_cfg.get("flavor", jname)
    eff_timeout = int(judge_cfg.get("timeout_s", timeout_s))
    print(f"[judge] running {jname} ({flavor}, timeout {eff_timeout}s)...",
          flush=True)
    # Drop a stale scores_deanon.json from a prior run so a now-failing/malformed
    # judge can't have its OLD scores silently aggregated by report.
    stale_deanon = cook_dir / "judging" / jname / "scores_deanon.json"
    if stale_deanon.exists():
        stale_deanon.unlink()
    work = _setup_judge_workdir(cook_dir, jname, judge_in, deterministic=True)
    metrics.reset_usage_dir(cook_dir, "judge", jname, flavor)
    log_dir = cook_dir / "judging" / "_logs" / jname
    (work / "PROMPT.txt").write_text(JUDGE_PROMPT_TEMPLATE)
    service = f"judge-{jname}"
    state.set_cell(cook_dir, jname, role="judge", flavor=flavor,
                   state=state.RUNNING, started_at=state.now_iso())
    state.append_event(cook_dir, "judge.started", phase="judge", actor=jname)
    try:
        res = compose_runner.run_cell(
            cook_dir=cook_dir, project=project, service=service,
            flavor=flavor, log_dir=log_dir, timeout_s=eff_timeout,
        )
    except Exception as e:                                                  # noqa: BLE001
        print(f"[judge] {jname}: failed to launch: {e}", flush=True)
        state.set_cell(cook_dir, jname, state=state.START_FAILED,
                       finished_at=state.now_iso(), exit_class=state.START_FAILED)
        state.append_event(cook_dir, "judge.finished", phase="judge", actor=jname,
                           payload={"ok": False, "status": "start_failed"})
        with lock:
            results[jname] = {
                "name": jname, "flavor": flavor, "ok": False,
                "status": "error", "reason": f"launch failed: {e}",
                "duration_s": 0.0,
            }
        return
    usage = metrics.collect_usage(cook_dir, "judge", jname, flavor)
    outbox = cook_dir / "judging" / jname
    ok = _collect_scores(work, outbox)
    if not ok:
        print(f"[judge] {jname}: did NOT produce scores.json "
              f"(exit={res.exit_code}). See {log_dir}", flush=True)
        with lock:
            result = {
                "name": jname, "flavor": flavor, "ok": False,
                "status": "no_scores", "reason": "no scores.json",
                "exit_code": res.exit_code,
                "duration_s": round(res.duration_s, 1),
                "stdout": str(res.stdout_path),
                "stderr": str(res.stderr_path),
            }
            if usage is not None:
                result["usage"] = usage
            results[jname] = result
        state.set_cell(cook_dir, jname, state=state.NON_ZERO_EXIT,
                       finished_at=state.now_iso(), exit_class="no_scores")
        state.append_event(cook_dir, "judge.finished", phase="judge", actor=jname,
                           payload={"ok": False, "status": "no_scores"})
        return
    try:
        scores = json.loads((outbox / "scores.json").read_text())
    except json.JSONDecodeError as e:
        print(f"[judge] {jname}: scores.json invalid: {e}", flush=True)
        with lock:
            result = {
                "name": jname, "flavor": flavor, "ok": False,
                "status": "invalid_json", "reason": f"invalid json: {e}",
                "exit_code": res.exit_code,
                "duration_s": round(res.duration_s, 1),
                "stdout": str(res.stdout_path),
                "stderr": str(res.stderr_path),
            }
            if usage is not None:
                result["usage"] = usage
            results[jname] = result
        state.set_cell(cook_dir, jname, state=state.NON_ZERO_EXIT,
                       finished_at=state.now_iso(), exit_class="invalid_json")
        state.append_event(cook_dir, "judge.finished", phase="judge", actor=jname,
                           payload={"ok": False, "status": "invalid_json"})
        return
    if strict:
        canonical = _strict_canonical(scores)
        if canonical is None:
            print(f"[judge] {jname}: scores.json fails strict schema "
                  f"(judging.strict_schema). Not aggregating.", flush=True)
            with lock:
                result = {
                    "name": jname, "flavor": flavor, "ok": False,
                    "status": "malformed_schema",
                    "reason": "scores.json does not match strict "
                              "scores[label][dimension]:int schema",
                    "exit_code": res.exit_code,
                    "duration_s": round(res.duration_s, 1),
                    "stdout": str(res.stdout_path),
                    "stderr": str(res.stderr_path),
                }
                if usage is not None:
                    result["usage"] = usage
                results[jname] = result
            state.set_cell(cook_dir, jname, state=state.NON_ZERO_EXIT,
                           finished_at=state.now_iso(), exit_class="malformed_schema")
            state.append_event(cook_dir, "judge.finished", phase="judge", actor=jname,
                               payload={"ok": False, "status": "malformed_schema"})
            return
        scores = canonical
    else:
        scores = _normalize_scores(scores)
    deanon = {mapping.get(k, k): v for k, v in scores.items()}
    (outbox / "scores_deanon.json").write_text(json.dumps(deanon, indent=2))
    print(f"[judge] {jname}: ok, {len(deanon)} participants scored", flush=True)
    with lock:
        result = {
            "name": jname, "flavor": flavor, "ok": True,
            "status": "ok", "count": len(deanon),
            "exit_code": res.exit_code,
            "duration_s": round(res.duration_s, 1),
            "stdout": str(res.stdout_path),
            "stderr": str(res.stderr_path),
        }
        if usage is not None:
            result["usage"] = usage
        results[jname] = result
    state.set_cell(cook_dir, jname, state=state.OK,
                   finished_at=state.now_iso(), exit_class="ok",
                   duration_s=round(res.duration_s, 1))
    state.append_event(cook_dir, "judge.finished", phase="judge", actor=jname,
                       payload={"ok": True, "count": len(deanon)})


def _strict_canonical(scores) -> dict | None:
    """Return scores unchanged iff they match the strict canonical schema:

        {"<label>": {"dimensions": {"<dim>": int, ...}, "total"?: int}}

    `int` means a real integer (bool excluded), per the documented contract.
    Returns None on any deviation. Unlike `_normalize_scores`, this performs NO
    repair — strict mode wants malformed output flagged, not silently fixed.
    """
    if not isinstance(scores, dict) or not scores:
        return None
    for entry in scores.values():
        if not isinstance(entry, dict):
            return None
        dims = entry.get("dimensions")
        if not isinstance(dims, dict) or not dims:
            return None
        for v in dims.values():
            if not isinstance(v, int) or isinstance(v, bool):
                return None
        if "total" in entry and (not isinstance(entry["total"], int)
                                 or isinstance(entry["total"], bool)):
            return None
    return scores


def _normalize_scores(scores: dict) -> dict:
    """Accept either canonical format or common LLM variants, return canonical.

    Canonical: {"<label>": {"dimensions": {"<dim>": int, ...}, "total": int?}}

    Variants handled:
    - Top-level {"scores": {...}} wrapper (when JUDGE_BRIEF.md shows that shape).
    - Flat per-label {"<dim>": int, ...} with no "dimensions" key.
    """
    totals = scores.get("totals") if isinstance(scores, dict) else None

    # Unwrap {"scores": {...}}. Judges often include sibling metadata such as
    # {"totals": {...}} even when the brief asks for strict scores-only JSON.
    if (
        isinstance(scores, dict)
        and "scores" in scores
        and isinstance(scores["scores"], dict)
    ):
        scores = scores["scores"]

    normalized: dict[str, dict] = {}
    for label, entry in scores.items():
        if not isinstance(entry, dict):
            continue
        if "dimensions" in entry and isinstance(entry["dimensions"], dict):
            if (
                isinstance(totals, dict)
                and "total" not in entry
                and isinstance(totals.get(label), (int, float))
            ):
                entry = {**entry, "total": totals[label]}
            normalized[label] = entry
            continue
        # Flat: lift int-valued keys into a "dimensions" block.
        total = entry.get("total")
        if (
            total is None
            and isinstance(totals, dict)
            and isinstance(totals.get(label), (int, float))
        ):
            total = totals[label]
        dims = {k: v for k, v in entry.items()
                if k != "total" and isinstance(v, (int, float))}
        out: dict = {"dimensions": dims}
        if total is not None:
            out["total"] = total
        normalized[label] = out
    return normalized


def _collect_scores(work: Path, judge_outbox: Path) -> bool:
    src_outbox = work / "outbox"
    if not src_outbox.exists():
        return False
    judge_outbox.mkdir(parents=True, exist_ok=True)
    for item in src_outbox.iterdir():
        dst = judge_outbox / item.name
        if dst.exists():
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        if item.is_dir():
            shutil.copytree(item, dst)
        else:
            shutil.copy2(item, dst)
    return (judge_outbox / "scores.json").exists()


def judge(name: str, root: Path,
          judges_override: list[str] | None = None,
          profile_override: str | None = None) -> int:
    cook_dir = root / name if not Path(name).is_absolute() else Path(name)
    cfg = yaml.safe_load((cook_dir / "brief.yaml").read_text())

    from . import brief_schema
    rc = brief_schema.validate_or_die(cfg, source=str(cook_dir / "brief.yaml"))
    if rc is not None:
        return rc

    participants = cfg.get("participants", [])
    judges_cfg = cfg.get("judges", [{"name": "claude", "flavor": "claude"}])
    if judges_override:
        wanted = set(judges_override)
        judges_cfg = [j for j in judges_cfg if j["name"] in wanted]
    if not judges_cfg:
        print("error: no judges configured", flush=True)
        return 2

    sealed = cook_dir / "judging" / "_inbox"
    if not sealed.exists():
        print(f"error: no sealed inbox at {sealed}; run `multicooker cook {name}` first",
              flush=True)
        return 2

    judge_in, mapping = _anonymize(participants, cook_dir / "judging", sealed)
    (cook_dir / "judging" / "_mapping.json").write_text(
        json.dumps(mapping, indent=2)
    )
    print(f"[judge] anonymized: {mapping}", flush=True)

    state.update_status(cook_dir, cook=cook_dir.name, phase="judge",
                        state=state.JUDGING)
    state.append_event(cook_dir, "phase.started", cook=cook_dir.name, phase="judge")

    timeout_s = int(cfg.get("judge_timeout_s", 15 * 60))

    project = f"mc-{cfg['name']}".lower().replace("_", "-")
    flavors_needed = sorted({j.get("flavor", j["name"]) for j in judges_cfg})
    print("[judge] snapshotting creds...", flush=True)
    rc = _snapshot_creds_or_die(cook_dir, flavors_needed)
    if rc is not None:
        return rc
    compose_render.render_compose(cook_dir, cfg, profile_override=profile_override)

    try:
        base_images.ensure_built(flavors_needed)
    except Exception as e:                                                   # noqa: BLE001
        print(f"[judge] base image build failed: {e}", flush=True)
        return 2

    # Anti-self-judge policy. Anonymization mitigates self-bias; this decides
    # whether same-flavor scores are dropped from aggregation (report applies
    # the exclusion). See judging_policy.py.
    policy = judging_policy(cfg)
    for j in judges_cfg:
        jname = j["name"]
        flavor = j.get("flavor", jname)
        same_flavor_participants = [p["name"] for p in participants
                                    if p.get("flavor", p["name"]) == flavor]
        if not same_flavor_participants:
            continue
        if policy == "require_distinct_flavor":
            print(f"[judge] policy=require_distinct_flavor: {jname} ({flavor}) "
                  f"scores for same-flavor {same_flavor_participants} will be "
                  f"EXCLUDED from the leaderboard.", flush=True)
        elif policy == "warn":
            print(f"[judge] WARN: {jname} ({flavor}) is same flavor as "
                  f"participants {same_flavor_participants}. Anonymization is on, "
                  f"but for full anti-bias add a different-flavor judge or set "
                  f"judging.policy: require_distinct_flavor.", flush=True)

    # Build all judge images upfront so threaded runs don't serialize on docker build.
    services = [f"judge-{j['name']}" for j in judges_cfg]
    try:
        compose_runner.build_images(cook_dir, project, services)
    except Exception as e:                                                  # noqa: BLE001
        print(f"[judge] build failed: {e}", flush=True)
        return 2

    # Run judges in parallel, 2-sec stagger like cook (auth refresh storms).
    results: dict[str, dict] = {
        j["name"]: {
            "name": j["name"],
            "flavor": j.get("flavor", j["name"]),
            "ok": False,
            "status": "missing",
            "duration_s": 0.0,
        }
        for j in judges_cfg
    }
    lock = threading.Lock()
    strict = bool((cfg.get("judging") or {}).get("strict_schema", False))
    if strict:
        print("[judge] judging.strict_schema=true: malformed scores.json will be "
              "flagged, not repaired.", flush=True)
    threads: list[threading.Thread] = []
    for j in judges_cfg:
        t = threading.Thread(
            target=_run_judge,
            args=(cook_dir, project, j, judge_in, mapping, timeout_s, results, lock),
            kwargs={"strict": strict},
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
        print(f"[judge] teardown warning: {e}", flush=True)

    summary = cook_dir / "JUDGE_RESULT.json"
    state.write_json_atomic(summary, {
        "finished_at": state.now_iso(),
        "policy": policy,
        "judges": [results[j["name"]] for j in judges_cfg if j["name"] in results],
    })
    print(f"[judge] summary at {summary}", flush=True)

    any_score = any(r.get("ok") for r in results.values())
    if not any_score:
        print("[judge] no judges produced scores; nothing to report", flush=True)
        return 1
    print(f"[judge] done. next: multicooker report {name}", flush=True)
    return 0
