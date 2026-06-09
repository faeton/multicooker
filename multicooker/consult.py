"""`multicooker consult <task>` — get a second opinion on one candidate.

A consult spawns one isolated *reviewer* cell per requested flavor (its own
container, own bridge network, own RO subscription creds — same isolation as a
judge). Each reviewer reads ONE candidate's output and writes a `review.md`
critique; it does not score and does not rewrite the solution. The reviews are
archived under `consult/<target>/` and merged into the cook's `FEEDBACK.md`, so
a follow-up `multicooker refine` (or `chef --consult --refine`) can act on them.

This is the host-orchestrated "give the chef the opportunity to consult"
design: the chef never holds multiple flavors' creds itself — the host runs the
reviewers as separate cells and feeds their critiques back. See the reviewer
service in compose_render.py and the judge cell it mirrors.
"""

from __future__ import annotations

import re
import shutil
import threading
import time
from pathlib import Path

import yaml

from . import base_images, compose_render, compose_runner, metrics, state
from .chef import _pick_default_base, _resolve_source_root
from .cook import _grant_container_write, _print_usage_summary, _snapshot_creds_or_die
from .new_cook import parse_participant


REVIEWER_PROMPT_TEMPLATE = """\
You are an independent reviewer giving a second opinion on ONE candidate
solution in a multi-LLM bake-off. You did not write it and you must not
rewrite it — your job is a sharp, honest critique another agent will act on.

# Files at your disposal

- `./BRIEF.md` — the original task brief the candidate had to satisfy.
- `./raw/` — the same reference material the author had (read-only).
- `./candidate/` — the candidate's output (its `out/` directory). Read-only
  input; do NOT modify it.
- `./context/` — optional prior leaderboard / reviews, if available.

# What you must produce

Write `./outbox/review.md` with, in this order:

1. **Verdict** — one paragraph: does this satisfy the brief? Ship / fix / rework.
2. **Strengths** — concrete, with file/line or quote references.
3. **Problems** — concrete and specific (bugs, missing requirements, risky
   claims, broken builds). Quote the candidate; no vague generalities.
4. **Prioritized fixes** — a short numbered list, most important first, each
   one actionable enough that the author could apply it directly.

# Rules

- Critique, don't rewrite. Do not edit files under `./candidate/`.
- Be specific. "Improve error handling" is useless; name the call site.
- If the candidate is empty or broken, say so plainly and stop.
- Do not access paths outside this worktree.

Begin.
"""

_FEEDBACK_BEGIN = "<!-- BEGIN multicooker consult: {target} -->"
_FEEDBACK_END = "<!-- END multicooker consult: {target} -->"
# Reviews are LLM output and can themselves contain HTML comments. Strip any
# string that looks like one of our own block markers before embedding, so the
# only real markers in FEEDBACK.md are the ones we write — otherwise a re-run's
# split() on the marker would slice in the wrong place and corrupt the file.
_MARKER_RE = re.compile(
    r"<!--\s*(?:BEGIN|END)\s+multicooker consult:.*?-->", re.IGNORECASE | re.DOTALL)


def _strip_markers(text: str) -> str:
    return _MARKER_RE.sub("(consult marker removed)", text)


def _target_flavor_from_trace(cook_dir: Path, target: str) -> str | None:
    """Best-effort target flavor for the self-review warning when the target
    isn't in brief.yaml (e.g. a --no-register chef leaves only a trace)."""
    import json
    trace = cook_dir / "work" / target / "trace.json"
    if not trace.exists():
        return None
    try:
        data = json.loads(trace.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    flavor = data.get("flavor")
    return flavor if isinstance(flavor, str) and flavor else None


def _reviewer_specs(reviewers: list[str] | None, cfg: dict) -> list[dict]:
    """Resolve the reviewer lineup from the CLI arg, brief.yaml, or judges.

    Each spec is {name, flavor[, model]}. Bare flavors (e.g. "grok") become
    name=flavor; explicit "alice=claude" is honored for multiple same-flavor
    reviewers.
    """
    if reviewers:
        specs = []
        for spec in reviewers:
            rname, flavor = parse_participant(spec)
            specs.append({"name": rname, "flavor": flavor})
        return specs
    consult_cfg = cfg.get("consult") or {}
    configured = consult_cfg.get("reviewers")
    if configured:
        out = []
        for r in configured:
            if isinstance(r, str):
                rname, flavor = parse_participant(r)
                out.append({"name": rname, "flavor": flavor})
            elif isinstance(r, dict) and r.get("name"):
                # Carry through per-reviewer overrides (model/timeout_s/resources)
                # so _run_reviewer and _reviewer_service honor them.
                out.append({**r, "flavor": r.get("flavor", r["name"])})
        if out:
            return out
    # Fall back to the judge lineup — judges are already a cross-flavor panel.
    # Keep their overrides too (a judge with a pinned model reviews with it).
    return [{**j, "flavor": j.get("flavor", j["name"])}
            for j in cfg.get("judges", [])]


def _setup_reviewer_workdir(cook_dir: Path, reviewer_name: str,
                            candidate_src: Path) -> Path:
    """Real-dir reviewer workdir (no symlinks; same constraint as judges)."""
    work = cook_dir / "consult" / f"_work-{reviewer_name}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    shutil.copy(cook_dir / "BRIEF.md", work / "BRIEF.md")
    raw_src = cook_dir / "raw"
    if raw_src.exists():
        shutil.copytree(raw_src, work / "raw")
    from .runner_common import copytree_clean
    copytree_clean(candidate_src / "out", work / "candidate")
    # Optional context: the prior leaderboard, useful for "is this better".
    context = work / "context"
    context.mkdir()
    leaderboard = cook_dir / "leaderboard.md"
    if leaderboard.exists():
        shutil.copy2(leaderboard, context / "leaderboard.md")
    outbox = work / "outbox"
    outbox.mkdir()
    _grant_container_write(outbox)
    (work / "PROMPT.txt").write_text(REVIEWER_PROMPT_TEMPLATE)
    return work


def _run_reviewer(cook_dir: Path, project: str, reviewer: dict, target: str,
                  candidate_src: Path, timeout_s: int, results: dict,
                  lock: threading.Lock) -> None:
    rname = reviewer["name"]
    flavor = reviewer.get("flavor", rname)
    eff_timeout = int(reviewer.get("timeout_s", timeout_s))
    print(f"[consult] reviewer {rname} ({flavor}) on '{target}' "
          f"(timeout {eff_timeout}s)...", flush=True)
    work = _setup_reviewer_workdir(cook_dir, rname, candidate_src)
    metrics.reset_usage_dir(cook_dir, "reviewer", rname, flavor)
    log_dir = cook_dir / "consult" / "_logs" / rname
    service = f"reviewer-{rname}"
    try:
        res = compose_runner.run_cell(
            cook_dir=cook_dir, project=project, service=service,
            flavor=flavor, log_dir=log_dir, timeout_s=eff_timeout,
        )
    except Exception as e:                                                  # noqa: BLE001
        print(f"[consult] {rname}: failed to launch: {e}", flush=True)
        with lock:
            results[rname] = {"name": rname, "flavor": flavor, "ok": False,
                              "status": "start_failed", "reason": str(e)}
        return
    usage = metrics.collect_usage(cook_dir, "reviewer", rname, flavor)
    review_src = work / "outbox" / "review.md"
    archive_dir = cook_dir / "consult" / target
    archive_dir.mkdir(parents=True, exist_ok=True)
    ok = review_src.exists() and review_src.read_text(errors="replace").strip() != ""
    if not ok:
        print(f"[consult] {rname}: produced no review.md (exit={res.exit_code}). "
              f"See {log_dir}", flush=True)
        with lock:
            result = {"name": rname, "flavor": flavor, "ok": False,
                      "status": "no_review", "exit_code": res.exit_code,
                      "duration_s": round(res.duration_s, 1)}
            if usage is not None:
                result["usage"] = usage
            results[rname] = result
        return
    text = review_src.read_text(errors="replace").strip()
    shutil.copy2(review_src, archive_dir / f"{rname}.md")
    print(f"[consult] {rname}: ok ({res.duration_s:.1f}s)", flush=True)
    with lock:
        result = {"name": rname, "flavor": flavor, "ok": True, "status": "ok",
                  "exit_code": res.exit_code, "duration_s": round(res.duration_s, 1),
                  "review": text}
        if usage is not None:
            result["usage"] = usage
        results[rname] = result


def _merge_into_feedback(cook_dir: Path, target: str,
                         reviews: list[dict]) -> Path:
    """Idempotently fold the reviews into FEEDBACK.md.

    The consult block is delimited by HTML comment markers and re-runs replace
    only that block, preserving any hand-written feedback the user keeps below.
    """
    begin = _FEEDBACK_BEGIN.format(target=target)
    end = _FEEDBACK_END.format(target=target)
    lines = [begin, f"## Consult reviews for `{target}`", ""]
    for r in reviews:
        lines.append(f"### {r['name']} ({r['flavor']})")
        lines.append("")
        lines.append(_strip_markers(r["review"].strip()))
        lines.append("")
    lines.append(end)
    block = "\n".join(lines)

    fb_path = cook_dir / "FEEDBACK.md"
    existing = fb_path.read_text() if fb_path.exists() else ""
    if begin in existing and end in existing:
        pre = existing.split(begin, 1)[0].rstrip()
        post = existing.split(end, 1)[1].lstrip()
        rest = "\n\n".join(part for part in (pre, post) if part)
    else:
        rest = existing.strip()
    merged = block if not rest else f"{block}\n\n{rest}\n"
    if not merged.endswith("\n"):
        merged += "\n"
    fb_path.write_text(merged)
    return fb_path


def consult(name: str, root: Path,
            target: str | None = None,
            reviewers: list[str] | None = None,
            refine: bool = False,
            profile_override: str | None = None,
            namespace: str | None = None) -> int:
    cook_dir = root / name if not Path(name).is_absolute() else Path(name)
    if not cook_dir.exists():
        print(f"error: cook folder {cook_dir} does not exist", flush=True)
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

    # Resolve target: explicit, else the leaderboard winner / first participant.
    if target is None:
        target = _pick_default_base(cook_dir, cfg, chef_name="")
    if not target:
        print("error: no target to review; pass --target <participant>", flush=True)
        return 2
    candidate_src = _resolve_source_root(cook_dir, target, "auto")
    if candidate_src is None:
        print(f"error: no readable out/ for target '{target}' "
              f"(looked in judging/_inbox and work)", flush=True)
        return 2

    specs = _reviewer_specs(reviewers, cfg)
    if not specs:
        print("error: no reviewers; pass --reviewers <flavors> or add a "
              "consult.reviewers / judges block to brief.yaml", flush=True)
        return 2

    participant_names = {p["name"] for p in cfg.get("participants", [])}
    # --refine re-runs the target via `refine`, which only knows brief.yaml
    # participants. A target absent from there (e.g. a `--no-register` chef)
    # can't be refined — fail loudly up front rather than after writing reviews.
    if refine and target not in participant_names:
        print(f"error: --refine needs target '{target}' registered in "
              f"brief.yaml participants; it isn't (a --no-register chef can't "
              f"auto-refine). Re-run the chef without --no-register, or run "
              f"consult without --refine and refine manually.", flush=True)
        return 2

    # Anti-self: warn when a reviewer shares the target's flavor (self-review).
    target_flavor = next((p.get("flavor", p["name"])
                          for p in cfg.get("participants", [])
                          if p["name"] == target), None) or _target_flavor_from_trace(
                          cook_dir, target)
    for s in specs:
        if target_flavor and s["flavor"] == target_flavor:
            print(f"[consult] WARN: reviewer {s['name']} ({s['flavor']}) is the "
                  f"same flavor as target '{target}'. For a true second opinion, "
                  f"prefer a different-flavor reviewer.", flush=True)

    timeout_s = int((cfg.get("consult") or {}).get("timeout_s",
                    cfg.get("judge_timeout_s", 15 * 60)))

    from .project import effective_project
    project = effective_project(cook_dir, cfg["name"], namespace)
    flavors_needed = sorted({s["flavor"] for s in specs})
    print(f"[consult] target={target} reviewers="
          f"{[s['name'] for s in specs]} flavors={flavors_needed}", flush=True)
    print("[consult] snapshotting creds...", flush=True)
    rc = _snapshot_creds_or_die(cook_dir, flavors_needed)
    if rc is not None:
        return rc

    # Inject reviewers so render_compose emits reviewer-<name> services. This is
    # an in-memory overlay; brief.yaml is not modified.
    render_cfg = {**cfg, "reviewers": specs}
    compose_render.render_compose(cook_dir, render_cfg,
                                  profile_override=profile_override, project=project)

    try:
        base_images.ensure_built(flavors_needed)
    except Exception as e:                                                  # noqa: BLE001
        print(f"[consult] base image build failed: {e}", flush=True)
        return 2

    services = [f"reviewer-{s['name']}" for s in specs]
    try:
        compose_runner.build_images(cook_dir, project, services)
    except Exception as e:                                                  # noqa: BLE001
        print(f"[consult] build failed: {e}", flush=True)
        return 2

    results: dict[str, dict] = {}
    lock = threading.Lock()
    threads: list[threading.Thread] = []
    for s in specs:
        t = threading.Thread(
            target=_run_reviewer,
            args=(cook_dir, project, s, target, candidate_src, timeout_s,
                  results, lock),
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
        print(f"[consult] teardown warning: {e}", flush=True)

    ordered = [results[s["name"]] for s in specs if s["name"] in results]
    state.write_json_atomic(cook_dir / "consult" / target / "CONSULT_RESULT.json", {
        "finished_at": state.now_iso(),
        "target": target,
        "reviewers": ordered,
    })

    ok_reviews = [r for r in ordered if r.get("ok")]
    if not ok_reviews:
        print("[consult] no reviewer produced a review; nothing to merge", flush=True)
        _print_usage_summary("consult", ordered)
        return 1

    fb_path = _merge_into_feedback(cook_dir, target, ok_reviews)
    print(f"[consult] {len(ok_reviews)}/{len(specs)} reviews → {fb_path}", flush=True)
    print(f"[consult] archived per-reviewer notes at {cook_dir}/consult/{target}/",
          flush=True)
    _print_usage_summary("consult", ordered)

    if refine:
        print(f"[consult] --refine: running a refine pass on '{target}'...",
              flush=True)
        from .refine import refine as run_refine
        return run_refine(name, root, participants_override=[target],
                          profile_override=profile_override, namespace=namespace)

    print(f"[consult] next: multicooker refine {name} "
          f"--participants {target}  (or re-run with --refine)", flush=True)
    return 0
