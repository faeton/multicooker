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

from . import base_images, compose_render, compose_runner, metrics
from .cook import _snapshot_creds_or_die


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
    for p, letter in zip(participants, letters):
        name = p["name"]
        src = sealed / name
        if not src.exists():
            continue
        dst = sub_dir / letter
        shutil.copytree(src, dst)
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
               lock: threading.Lock) -> None:
    jname = judge_cfg["name"]
    flavor = judge_cfg.get("flavor", jname)
    eff_timeout = int(judge_cfg.get("timeout_s", timeout_s))
    print(f"[judge] running {jname} ({flavor}, timeout {eff_timeout}s)...",
          flush=True)
    work = _setup_judge_workdir(cook_dir, jname, judge_in, deterministic=True)
    metrics.reset_usage_dir(cook_dir, "judge", jname, flavor)
    log_dir = cook_dir / "judging" / "_logs" / jname
    (work / "PROMPT.txt").write_text(JUDGE_PROMPT_TEMPLATE)
    service = f"judge-{jname}"
    try:
        res = compose_runner.run_cell(
            cook_dir=cook_dir, project=project, service=service,
            flavor=flavor, log_dir=log_dir, timeout_s=eff_timeout,
        )
    except Exception as e:                                                  # noqa: BLE001
        print(f"[judge] {jname}: failed to launch: {e}", flush=True)
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
        return
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


def _normalize_scores(scores: dict) -> dict:
    """Accept either canonical format or common LLM variants, return canonical.

    Canonical: {"<label>": {"dimensions": {"<dim>": int, ...}, "total": int?}}

    Variants handled:
    - Top-level {"scores": {...}} wrapper (when JUDGE_BRIEF.md shows that shape).
    - Flat per-label {"<dim>": int, ...} with no "dimensions" key.
    """
    # Unwrap {"scores": {...}} if it's the sole top-level key.
    if (
        isinstance(scores, dict)
        and len(scores) == 1
        and "scores" in scores
        and isinstance(scores["scores"], dict)
    ):
        scores = scores["scores"]

    normalized: dict[str, dict] = {}
    for label, entry in scores.items():
        if not isinstance(entry, dict):
            continue
        if "dimensions" in entry and isinstance(entry["dimensions"], dict):
            normalized[label] = entry
            continue
        # Flat: lift int-valued keys into a "dimensions" block.
        total = entry.get("total")
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
          judges_override: list[str] | None = None) -> int:
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

    timeout_s = int(cfg.get("judge_timeout_s", 15 * 60))

    project = f"mc-{cfg['name']}".lower().replace("_", "-")
    flavors_needed = sorted({j.get("flavor", j["name"]) for j in judges_cfg})
    print("[judge] snapshotting creds...", flush=True)
    rc = _snapshot_creds_or_die(cook_dir, flavors_needed)
    if rc is not None:
        return rc
    compose_render.render_compose(cook_dir, cfg)

    try:
        base_images.ensure_built(flavors_needed)
    except Exception as e:                                                   # noqa: BLE001
        print(f"[judge] base image build failed: {e}", flush=True)
        return 2

    # Anti-self-judging warnings (anonymization mitigates; this only warns).
    for j in judges_cfg:
        jname = j["name"]
        flavor = j.get("flavor", jname)
        same_flavor_participants = [p["name"] for p in participants
                                    if p.get("flavor", p["name"]) == flavor]
        if same_flavor_participants:
            print(f"[judge] WARN: {jname} ({flavor}) is same flavor as "
                  f"participants {same_flavor_participants}. Anonymization is on, "
                  f"but for full anti-bias add a different-flavor judge.",
                  flush=True)

    # Build all judge images upfront so threaded runs don't serialize on docker build.
    services = [f"judge-{j['name']}" for j in judges_cfg]
    try:
        compose_runner.build_images(cook_dir, project, services)
    except Exception as e:                                                  # noqa: BLE001
        print(f"[judge] build failed: {e}", flush=True)
        return 2

    # Run judges in parallel, 2-sec stagger like cook (auth refresh storms).
    results: dict[str, dict] = {}
    lock = threading.Lock()
    threads: list[threading.Thread] = []
    for j in judges_cfg:
        t = threading.Thread(
            target=_run_judge,
            args=(cook_dir, project, j, judge_in, mapping, timeout_s, results, lock),
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
    summary.write_text(json.dumps({
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "judges": [results[j["name"]] for j in judges_cfg if j["name"] in results],
    }, indent=2))
    print(f"[judge] summary at {summary}", flush=True)

    any_score = any(r.get("ok") for r in results.values())
    if not any_score:
        print("[judge] no judges produced scores; nothing to report", flush=True)
        return 1
    print(f"[judge] done. next: multicooker report {name}", flush=True)
    return 0
