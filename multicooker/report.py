"""`multicooker report <name>` — aggregate judge scores into leaderboard.md."""

from __future__ import annotations

import json
from pathlib import Path

import yaml


def _fmt_duration(value) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.1f}s"
    return "?"


def _fmt_tokens(entry: dict) -> str:
    usage = entry.get("usage") if isinstance(entry, dict) else None
    if not isinstance(usage, dict):
        return "?"
    total = usage.get("total_tokens")
    if not isinstance(total, (int, float)):
        return "?"
    return f"{int(total):,}"


def _fmt_cost(entry: dict) -> str:
    usage = entry.get("usage") if isinstance(entry, dict) else None
    if not isinstance(usage, dict):
        return "?"
    cost = usage.get("cost_usd")
    if not isinstance(cost, (int, float)):
        return "?"
    return f"${cost:.4f}"


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


def report(name: str, root: Path) -> int:
    cook_dir = root / name if not Path(name).is_absolute() else Path(name)
    cfg = yaml.safe_load((cook_dir / "brief.yaml").read_text())
    participants = [p["name"] for p in cfg.get("participants", [])]
    rubric = cfg.get("rubric") or {}

    judging = cook_dir / "judging"
    if not judging.exists():
        print(f"error: no judging output at {judging}", flush=True)
        return 2

    # Collect all scores_deanon.json from each judge folder.
    judges_used: list[str] = []
    per_judge: dict[str, dict] = {}
    for d in sorted(judging.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        sd = d / "scores_deanon.json"
        if not sd.exists():
            continue
        try:
            per_judge[d.name] = json.loads(sd.read_text())
            judges_used.append(d.name)
        except json.JSONDecodeError:
            continue

    if not per_judge:
        print("error: no judge produced scores", flush=True)
        return 1

    # Aggregate: per participant, mean normalized score across judges.
    agg: dict[str, dict] = {p: {"scores": [], "by_judge": {}} for p in participants}
    for jn, scores in per_judge.items():
        for p, entry in scores.items():
            if p not in agg:
                agg[p] = {"scores": [], "by_judge": {}}
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

    # Run results
    rr_path = cook_dir / "RUN_RESULT.json"
    rr = json.loads(rr_path.read_text()) if rr_path.exists() else {"participants": []}
    rr_by_name = {p["name"]: p for p in rr.get("participants", [])}
    jr_path = cook_dir / "JUDGE_RESULT.json"
    jr = json.loads(jr_path.read_text()) if jr_path.exists() else {"judges": []}

    out = ["# Leaderboard — `" + str(cook_dir.name) + "`", ""]
    out.append(f"Judges: {', '.join(judges_used)}")
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
            dim_str = ", ".join(f"{k}={v}" for k, v in dims.items())
            out.append(f"- **{p}** — {score_str}; {dim_str}")
        out.append("")
        review = (cook_dir / "judging" / jn / "review.md")
        if review.exists():
            out.append("Review:")
            out.append("")
            out.append(review.read_text().strip())
            out.append("")

    leaderboard = cook_dir / "leaderboard.md"
    leaderboard.write_text("\n".join(out))
    print(f"[report] written: {leaderboard}")
    print()
    print("\n".join(out[:20]))
    return 0
