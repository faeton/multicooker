"""`multicooker report <name>` — aggregate judge scores into leaderboard.md
plus a machine-readable summary.json.

leaderboard.md stays the human report. summary.json is the canonical machine
contract an external orchestrator reads instead of parsing markdown: ranking,
run statuses/durations/usage for the *latest* round, per-judge breakdown,
excluded self-flavor pairs, and artifact pointers.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from . import metrics, state
from .judging_policy import excluded_pairs, judging_policy


def _fmt_duration(value) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.1f}s"
    return "?"


def _tokens_of(entry: dict):
    usage = entry.get("usage") if isinstance(entry, dict) else None
    if not isinstance(usage, dict):
        return None
    total = usage.get("total_tokens")
    return int(total) if isinstance(total, (int, float)) else None


def _cost_of(entry: dict):
    usage = entry.get("usage") if isinstance(entry, dict) else None
    if not isinstance(usage, dict):
        return None
    cost = usage.get("cost_usd")
    return float(cost) if isinstance(cost, (int, float)) else None


def _usage_totals(rr_by_name: dict, jr: dict) -> dict | None:
    """Token totals split participants/judges/all, or None when nothing recorded.

    Each sub-key is only present when that group had usage, and the whole block
    is dropped when neither did — so summary.json never carries null totals.
    """
    participants = metrics.sum_usage(e.get("usage") for e in rr_by_name.values())
    judges = metrics.sum_usage(e.get("usage") for e in jr.get("judges", []))
    grand = metrics.sum_usage([participants, judges])
    if grand is None:
        return None
    block = {"all": grand}
    if participants is not None:
        block["participants"] = participants
    if judges is not None:
        block["judges"] = judges
    return block


def _fmt_tokens(entry: dict) -> str:
    t = _tokens_of(entry)
    return f"{t:,}" if t is not None else "?"


def _fmt_cost(entry: dict) -> str:
    c = _cost_of(entry)
    return f"${c:.4f}" if c is not None else "?"


def _compute_score(dims: dict, rubric: dict | None) -> float | None:
    """Weighted percentage from per-dimension scores and rubric weights.

    Always derived here, ignoring whatever 'total' the judge wrote — judges
    have historically differed on scale (sum-of-dims vs weighted-divided-by-5)
    and that mismatch silently produced nonsense leaderboards. Returns a 0–100
    percentage where 100 = max score in every weighted dimension.

    If `rubric` is absent or has no dimensions, falls back to equal weights
    across whatever dimensions the judge actually scored.
    """
    if not dims:
        return None
    rubric = rubric or {}
    scale = rubric.get("scale", [0, 5]) if isinstance(rubric, dict) else [0, 5]
    scale_max = scale[1] if isinstance(scale, list) and len(scale) >= 2 else 5
    rubric_dims = (rubric.get("dimensions") or []) if isinstance(rubric, dict) else []
    if not rubric_dims:
        rubric_dims = [{"id": k, "weight": 1} for k in dims]
    weighted_sum = 0.0
    total_weight = 0.0
    for rd in rubric_dims:
        dim_id = rd.get("id")
        if dim_id is None:
            continue
        weight = rd.get("weight", 1)
        score = dims.get(dim_id)
        if not isinstance(score, (int, float)):
            continue
        weighted_sum += score * weight
        total_weight += weight
    if total_weight == 0 or scale_max == 0:
        return None
    return (weighted_sum / (total_weight * scale_max)) * 100.0


def _load_json(path: Path):
    import json
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _latest_run_result(cook_dir: Path) -> tuple[int, dict]:
    """Return (round, run_result) for the latest completed round.

    Refine writes REFINE_<N>_RESULT.json; the original cook writes
    RUN_RESULT.json (round 1). We pick the highest refine round present, else
    fall back to RUN_RESULT.json. Reading the per-round file (not always
    RUN_RESULT.json) is what keeps leaderboard metadata fresh after refine.
    """
    refine_rounds = []
    for f in cook_dir.glob("REFINE_*_RESULT.json"):
        m = re.match(r"REFINE_(\d+)_RESULT\.json$", f.name)
        if m:
            refine_rounds.append(int(m.group(1)))
    if refine_rounds:
        n = max(refine_rounds)
        rr = _load_json(cook_dir / f"REFINE_{n}_RESULT.json")
        # The highest refine file exists (we just globbed it). If it's
        # unreadable (corrupt/half-written), report that round honestly with
        # empty metrics rather than silently falling back to round 1.
        return n, rr if rr is not None else {"participants": []}
    rr = _load_json(cook_dir / "RUN_RESULT.json") or {"participants": []}
    return rr.get("round", 1), rr


def report(name: str, root: Path) -> int:
    cook_dir = root / name if not Path(name).is_absolute() else Path(name)
    cfg = yaml.safe_load((cook_dir / "brief.yaml").read_text())
    participants_cfg = cfg.get("participants", [])
    participants = [p["name"] for p in participants_cfg]
    flavor_of = {p["name"]: p.get("flavor", p["name"]) for p in participants_cfg}
    judges_cfg = cfg.get("judges", [])
    brief_judge_names = {j["name"] for j in judges_cfg}
    rubric = cfg.get("rubric") or {}
    policy = judging_policy(cfg)
    excluded = excluded_pairs(participants_cfg, judges_cfg, policy)

    judging = cook_dir / "judging"
    if not judging.exists():
        print(f"error: no judging output at {judging}", flush=True)
        return 2

    # Collect scores_deanon.json per judge — but only for judges that are still
    # in brief.yaml. A judge removed/renamed between rounds leaves a stale
    # outbox folder that would otherwise poison the aggregate.
    judges_used: list[str] = []
    per_judge: dict[str, dict] = {}
    for d in sorted(judging.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        # Drop stale judge folders (removed/renamed between rounds) — but only
        # when the brief actually lists judges to filter against.
        if brief_judge_names and d.name not in brief_judge_names:
            continue
        sd = d / "scores_deanon.json"
        if not sd.exists():
            continue
        scores = _load_json(sd)
        if scores is None:
            continue
        per_judge[d.name] = scores
        judges_used.append(d.name)

    if not per_judge:
        print("error: no judge produced scores", flush=True)
        # Still emit a contract summary.json so an orchestrator reading it
        # unconditionally sees a valid-but-unjudged cook instead of a missing
        # file. Empty ranking signals "no scores yet".
        round_num, rr = _latest_run_result(cook_dir)
        jr = _load_json(cook_dir / "JUDGE_RESULT.json") or {}
        rr_by_name = {p["name"]: p for p in rr.get("participants", [])}
        no_scores_summary = {
            "schema_version": 1,
            "cook": cook_dir.name,
            "round": round_num,
            "generated_at": state.now_iso(),
            "anti_self_judge_policy": policy,
            "judges_used": [],
            "ranking": [],
            "per_judge": {},
            "judge_run": jr.get("judges", []),
            "excluded_pairs": [],
            "artifacts": {},
            "status": "no_scores",
        }
        usage_totals = _usage_totals(rr_by_name, jr)
        if usage_totals is not None:
            no_scores_summary["usage_totals"] = usage_totals
        state.write_json_atomic(state.summary_path(cook_dir), no_scores_summary)
        return 1

    # Aggregate: per participant, mean normalized score across judges, dropping
    # excluded self-flavor (judge, participant) pairs under the strict policy.
    excluded_recorded: list[dict] = []
    agg: dict[str, dict] = {p: {"scores": [], "by_judge": {}} for p in participants}
    for jn, scores in per_judge.items():
        for p, entry in scores.items():
            if p not in agg:
                continue
            if (jn, p) in excluded:
                excluded_recorded.append({"judge": jn, "participant": p,
                                          "flavor": flavor_of.get(p)})
                continue
            dims = entry.get("dimensions") if isinstance(entry, dict) else None
            score = _compute_score(dims, rubric) if dims else None
            if score is not None:
                agg[p]["scores"].append(score)
            agg[p]["by_judge"][jn] = entry

    # Mean across judges.
    ranking = []
    for p, data in agg.items():
        scores = data["scores"]
        mean = sum(scores) / len(scores) if scores else 0.0
        ranking.append((p, mean, len(scores)))
    ranking.sort(key=lambda x: x[1], reverse=True)

    # Latest-round run results + judge run metrics.
    round_num, rr = _latest_run_result(cook_dir)
    rr_by_name = {p["name"]: p for p in rr.get("participants", [])}
    jr = _load_json(cook_dir / "JUDGE_RESULT.json") or {"judges": []}

    out = ["# Leaderboard — `" + str(cook_dir.name) + "`", ""]
    out.append(f"Judges: {', '.join(judges_used)}")
    out.append(f"Round: {round_num} · anti-self-judge policy: {policy}")
    out.append("")
    out.append("Score = weighted % from `brief.yaml` rubric (0–100, 100 = max in every dimension).")
    out.append("")
    out.append("| Rank | Participant | Mean % | # judges | Run status | Duration | Tokens | Cost |")
    out.append("|------|-------------|--------|----------|------------|----------|--------|------|")
    for i, (p, mean, n) in enumerate(ranking, 1):
        run_entry = rr_by_name.get(p, {})
        status = run_entry.get("status", "?")
        out.append(
            f"| {i} | {p} | {mean:.1f} | {n} | {status} | "
            f"{_fmt_duration(run_entry.get('duration_s'))} | "
            f"{_fmt_tokens(run_entry)} | {_fmt_cost(run_entry)} |"
        )
    # Sum over every participant that ran (rr_by_name), matching summary.json —
    # not just the ranked subset, so the Total reflects true token spend.
    part_totals = metrics.sum_usage(e.get("usage") for e in rr_by_name.values())
    if part_totals is not None:
        wrap = {"usage": part_totals}
        out.append(
            f"| | **Total** | | | | | **{_fmt_tokens(wrap)}** | "
            f"**{_fmt_cost(wrap)}** |"
        )
    if excluded_recorded:
        out.append("")
        out.append("Excluded (same-flavor judge/submission pairs, per policy "
                   "`require_distinct_flavor`):")
        for ex in excluded_recorded:
            out.append(f"- {ex['judge']} → {ex['participant']}")
    if jr.get("judges"):
        out.append("")
        out.append("## Judge run metrics")
        out.append("")
        out.append("| Judge | Status | Duration | Tokens | Cost |")
        out.append("|-------|--------|----------|--------|------|")
        for entry in jr.get("judges", []):
            out.append(
                f"| {entry.get('name', '?')} | {entry.get('status', '?')} | "
                f"{_fmt_duration(entry.get('duration_s'))} | "
                f"{_fmt_tokens(entry)} | {_fmt_cost(entry)} |"
            )
        judge_totals = metrics.sum_usage(
            e.get("usage") for e in jr.get("judges", []))
        if judge_totals is not None:
            wrap = {"usage": judge_totals}
            out.append(
                f"| **Total** | | | **{_fmt_tokens(wrap)}** | "
                f"**{_fmt_cost(wrap)}** |"
            )
    out.append("")
    out.append("## Per-judge breakdown")
    out.append("")
    for jn, scores in per_judge.items():
        out.append(f"### {jn}")
        out.append("")
        for p, entry in scores.items():
            dims = entry.get("dimensions", {}) if isinstance(entry, dict) else {}
            score = _compute_score(dims, rubric) if dims else None
            score_str = f"{score:.1f}%" if score is not None else "?"
            excl = " (excluded: same flavor)" if (jn, p) in excluded else ""
            dim_str = ", ".join(f"{k}={v}" for k, v in dims.items())
            out.append(f"- **{p}** — {score_str}{excl}; {dim_str}")
        out.append("")
        review = (cook_dir / "judging" / jn / "review.md")
        if review.exists():
            out.append("Review:")
            out.append("")
            out.append(review.read_text().strip())
            out.append("")

    leaderboard = cook_dir / "leaderboard.md"
    leaderboard.write_text("\n".join(out))

    _write_summary(cook_dir, round_num=round_num, policy=policy,
                   judges_used=judges_used, ranking=ranking,
                   rr_by_name=rr_by_name, flavor_of=flavor_of,
                   per_judge=per_judge, rubric=rubric,
                   excluded=excluded, excluded_recorded=excluded_recorded,
                   jr=jr)

    from . import artifacts
    artifacts.build_manifest(cook_dir)

    state.append_event(cook_dir, "report.written", cook=cook_dir.name, phase="report",
                       payload={"round": round_num})
    state.update_status(cook_dir, cook=cook_dir.name, phase="report",
                        state=state.REPORTED, round=round_num)

    print(f"[report] written: {leaderboard}")
    print(f"[report] summary: {state.summary_path(cook_dir)}")
    print(f"[report] artifacts: {artifacts.artifacts_path(cook_dir)}")
    print()
    print("\n".join(out[:20]))
    return 0


def _write_summary(cook_dir: Path, *, round_num: int, policy: str,
                   judges_used: list[str], ranking: list,
                   rr_by_name: dict, flavor_of: dict,
                   per_judge: dict, rubric: dict,
                   excluded: set, excluded_recorded: list, jr: dict) -> None:
    ranking_out = []
    for i, (p, mean, n) in enumerate(ranking, 1):
        run_entry = rr_by_name.get(p, {})
        ranking_out.append({
            "rank": i,
            "participant": p,
            "flavor": flavor_of.get(p),
            "mean_pct": round(mean, 2),
            "num_judges": n,
            "run_status": run_entry.get("status"),
            "duration_s": run_entry.get("duration_s"),
            "tokens": _tokens_of(run_entry),
            "cost_usd": _cost_of(run_entry),
        })

    per_judge_out: dict = {}
    for jn, scores in per_judge.items():
        per_judge_out[jn] = {}
        for p, entry in scores.items():
            dims = entry.get("dimensions", {}) if isinstance(entry, dict) else {}
            sc = _compute_score(dims, rubric) if dims else None
            per_judge_out[jn][p] = {
                "dimensions": dims,
                "score_pct": round(sc, 2) if sc is not None else None,
                "excluded": (jn, p) in excluded,
            }

    summary = {
        "schema_version": 1,
        "cook": cook_dir.name,
        "round": round_num,
        "generated_at": state.now_iso(),
        "anti_self_judge_policy": policy,
        "judges_used": judges_used,
        "ranking": ranking_out,
        "per_judge": per_judge_out,
        "judge_run": jr.get("judges", []),
        "excluded_pairs": excluded_recorded,
        "artifacts": {"leaderboard": "leaderboard.md", "manifest": "artifacts.json"},
    }
    usage_totals = _usage_totals(rr_by_name, jr)
    if usage_totals is not None:
        summary["usage_totals"] = usage_totals
    state.write_json_atomic(state.summary_path(cook_dir), summary)
