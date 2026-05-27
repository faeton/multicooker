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


def report(name: str, root: Path) -> int:
    cook_dir = root / name if not Path(name).is_absolute() else Path(name)
    cfg = yaml.safe_load((cook_dir / "brief.yaml").read_text())
    participants = [p["name"] for p in cfg.get("participants", [])]

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

    # Aggregate: per participant, sum totals across judges, count judges.
    agg: dict[str, dict] = {p: {"totals": [], "by_judge": {}} for p in participants}
    for jn, scores in per_judge.items():
        for p, entry in scores.items():
            if p not in agg:
                agg[p] = {"totals": [], "by_judge": {}}
            total = entry.get("total")
            if total is None and "dimensions" in entry:
                total = sum(entry["dimensions"].values())
            if total is not None:
                agg[p]["totals"].append(total)
            agg[p]["by_judge"][jn] = entry

    # Mean across judges.
    ranking = []
    for p, data in agg.items():
        totals = data["totals"]
        mean = sum(totals) / len(totals) if totals else 0.0
        ranking.append((p, mean, len(totals)))
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
    out.append("| Rank | Participant | Mean score | # judges | Run status | Duration | Tokens | Cost |")
    out.append("|------|-------------|------------|----------|------------|----------|--------|------|")
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
            dims = entry.get("dimensions", {})
            total = entry.get("total") or sum(dims.values()) if dims else "?"
            dim_str = ", ".join(f"{k}={v}" for k, v in dims.items())
            out.append(f"- **{p}** — total {total}; {dim_str}")
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
