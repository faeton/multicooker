"""`multicooker chef <task>` — synthesize prior submissions into one output.

Chef mode is a post-cook track. It takes already sealed participant outputs
from `judging/_inbox/` (or `work/` as a fallback), materializes them under
`chef/<chef>/input/`, then mounts that directory read-only only for the
chef container. The chef writes a synthesized result in `work/<chef>/out/`.

The resulting chef output is sealed like any participant, so the existing
`rejudge` / `report` flow can compare it against the original field.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import base_images, compose_render, compose_runner, metrics, state
from .cook import (
    _print_usage_summary,
    _seal_for_judging,
    _setup_worktree,
    _snapshot_creds_or_die,
    _write_trace,
)
from .new_cook import parse_participant
from .runner_common import RunResult, copytree_clean


CHEF_PROMPT_TEMPLATE = """\
You are the chef in a multi-LLM bake-off. The participant round is over.
Your task is to synthesize one best final result from the sealed submissions.

# Original task

Read `./BRIEF.md` first. Your output must still satisfy that original task
contract unless the chef instructions below explicitly add more requirements.

# Chef inputs

The prior outputs and judge materials are mounted read-only under:

`./chef-input/`

Important paths:

- `submissions/{base}/out/` — baseline submission. Preserve its working
  parts unless you have a concrete reason to replace them.
- `submissions/<donor>/out/` — donor submissions. Pull good ideas from them
  only when they improve the result without breaking the baseline.
- `leaderboard.md` — prior aggregate result, if available.
- `reviews/` — prior judge reviews, if available.
- `MANIFEST.md` — exact list of materialized inputs.

# Base and donors

Base: `{base}`
Donors: {donors}

# What you must produce

Write the synthesized result under `./out/`, following the original BRIEF.md.
Also include `./out/CHEF.md` with:

- what you kept from the base;
- what you transplanted from each donor;
- what you rejected and why;
- commands you ran and what passed/failed;
- remaining risks or stubs.

# Rules

- This is synthesis, not a fresh parallel solution.
- Prefer a buildable, coherent output over a larger but broken one.
- Do not claim verification you did not run.
- Do not access paths outside this worktree.
- When done, exit normally. No extra submit step is needed.

Begin.
"""


_LEADERBOARD_ROW_RE = re.compile(r"^\|\s*1\s*\|\s*([^|]+?)\s*\|")


def _participant_names(cfg: dict) -> list[str]:
    return [p["name"] for p in cfg.get("participants", [])]


def _pick_default_base(cook_dir: Path, cfg: dict, chef_name: str) -> str | None:
    leaderboard = cook_dir / "leaderboard.md"
    participants = [n for n in _participant_names(cfg) if n != chef_name]
    participant_set = set(participants)
    if leaderboard.exists():
        for line in leaderboard.read_text(errors="replace").splitlines():
            m = _LEADERBOARD_ROW_RE.match(line)
            if not m:
                continue
            candidate = m.group(1).strip()
            if candidate in participant_set:
                return candidate
    return participants[0] if participants else None


def _trace_mode(cook_dir: Path, participant: str) -> str | None:
    trace = cook_dir / "work" / participant / "trace.json"
    if not trace.exists():
        return None
    try:
        data = json.loads(trace.read_text())
    except json.JSONDecodeError:
        return None
    mode = data.get("mode")
    return mode if isinstance(mode, str) else None


def _resolve_source_root(cook_dir: Path, participant: str, source: str) -> Path | None:
    candidates: list[Path] = []
    if source in {"auto", "inbox"}:
        candidates.append(cook_dir / "judging" / "_inbox" / participant)
    if source in {"auto", "work"}:
        candidates.append(cook_dir / "work" / participant)
    for candidate in candidates:
        if (candidate / "out").exists():
            return candidate
    return None


def _copy_submission(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    copytree_clean(src / "out", dst / "out")
    for name in ("trace.json", "PROMPT.txt"):
        item = src / name
        if item.exists() and item.is_file():
            shutil.copy2(item, dst / name)


def _materialize_inputs(
    cook_dir: Path,
    chef_name: str,
    base: str,
    donors: list[str],
    source: str,
) -> Path:
    root = cook_dir / "chef" / chef_name / "input"
    if root.exists():
        shutil.rmtree(root)
    subs = root / "submissions"
    reviews = root / "reviews"
    reviews.mkdir(parents=True, exist_ok=True)

    selected = [base, *[d for d in donors if d != base]]
    copied: list[str] = []
    missing: list[str] = []
    for participant in selected:
        src = _resolve_source_root(cook_dir, participant, source)
        if src is None:
            missing.append(participant)
            continue
        _copy_submission(src, subs / participant)
        copied.append(participant)

    leaderboard = cook_dir / "leaderboard.md"
    if leaderboard.exists():
        shutil.copy2(leaderboard, root / "leaderboard.md")

    judging = cook_dir / "judging"
    if judging.exists():
        for judge_dir in sorted(judging.iterdir()):
            if not judge_dir.is_dir() or judge_dir.name.startswith("_"):
                continue
            review = judge_dir / "review.md"
            if review.exists():
                shutil.copy2(review, reviews / f"{judge_dir.name}.md")
            scores = judge_dir / "scores_deanon.json"
            if scores.exists():
                shutil.copy2(scores, reviews / f"{judge_dir.name}.scores_deanon.json")

    manifest = [
        f"# Chef Input Manifest: {chef_name}",
        "",
        f"- base: `{base}`",
        f"- donors: {', '.join(f'`{d}`' for d in donors) if donors else '(none)'}",
        f"- source: `{source}`",
        f"- copied submissions: {', '.join(f'`{p}`' for p in copied) if copied else '(none)'}",
        f"- missing submissions: {', '.join(f'`{p}`' for p in missing) if missing else '(none)'}",
        "",
        "Submissions are copied from sealed `judging/_inbox/<participant>/out/`",
        "when available, otherwise from live `work/<participant>/out/` in",
        "`--source auto` mode.",
    ]
    (root / "MANIFEST.md").write_text("\n".join(manifest) + "\n")

    if base not in copied:
        raise RuntimeError(f"base submission '{base}' has no readable out/ in source '{source}'")
    return root


def _register_chef(cook_dir: Path, cfg: dict, chef_name: str, flavor: str,
                   model: str | None) -> dict:
    participants = cfg.setdefault("participants", [])
    for p in participants:
        if p["name"] != chef_name:
            continue
        if p.get("flavor", p["name"]) != flavor:
            raise RuntimeError(
                f"participant '{chef_name}' already exists with flavor "
                f"'{p.get('flavor', p['name'])}', not '{flavor}'"
            )
        if model:
            p["model"] = model
            brief_yaml = cook_dir / "brief.yaml"
            brief_yaml.write_text(yaml.safe_dump(cfg, sort_keys=False))
        return p

    entry = {"name": chef_name, "flavor": flavor}
    if model:
        entry["model"] = model
    participants.append(entry)
    brief_yaml = cook_dir / "brief.yaml"
    brief_yaml.write_text(yaml.safe_dump(cfg, sort_keys=False))
    return entry


def chef(
    name: str,
    root: Path,
    chef_spec: str,
    base: str | None = None,
    donors: list[str] | None = None,
    source: str = "auto",
    no_register: bool = False,
    force: bool = False,
    timeout_s: int | None = None,
    profile_override: str | None = None,
    model: str | None = None,
) -> int:
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

    try:
        chef_name, flavor = parse_participant(chef_spec)
    except ValueError as e:
        print(f"error: {e}", flush=True)
        return 2

    if source not in {"auto", "inbox", "work"}:
        print("error: --source must be one of: auto, inbox, work", flush=True)
        return 2

    base = base or _pick_default_base(cook_dir, cfg, chef_name)
    if base is None:
        print("error: could not infer --base; pass one explicitly", flush=True)
        return 2

    existing_names = [n for n in _participant_names(cfg) if n != chef_name]
    if donors is None:
        donors = [n for n in existing_names if n != base]
    donors = [d for d in donors if d and d != chef_name]

    existing_participants = set(_participant_names(cfg))
    if chef_name in existing_participants and _trace_mode(cook_dir, chef_name) != "chef":
        print(
            f"error: '{chef_name}' is an existing non-chef participant; "
            "choose a new --chef name",
            flush=True,
        )
        return 2
    if (
        (cook_dir / "work" / chef_name / "out").exists()
        and _trace_mode(cook_dir, chef_name) == "chef"
        and not force
    ):
        print(
            f"error: chef output for '{chef_name}' already exists; "
            "rerun with --force to overwrite it",
            flush=True,
        )
        return 2

    try:
        input_root = _materialize_inputs(
            cook_dir=cook_dir,
            chef_name=chef_name,
            base=base,
            donors=donors,
            source=source,
        )
    except RuntimeError as e:
        print(f"error: {e}", flush=True)
        return 2

    participant = {"name": chef_name, "flavor": flavor}
    if model:
        participant["model"] = model
    if not no_register:
        try:
            participant = _register_chef(cook_dir, cfg, chef_name, flavor, model)
        except RuntimeError as e:
            print(f"error: {e}", flush=True)
            return 2
    else:
        cfg = dict(cfg)
        cfg["participants"] = [participant]

    eff_timeout = int(timeout_s or participant.get("timeout_s") or cfg.get("timeout_s", 30 * 60))
    participant["timeout_s"] = eff_timeout
    participant["_chef_input"] = str(input_root)

    project = f"mc-{cfg['name']}".lower().replace("_", "-")
    prompt = CHEF_PROMPT_TEMPLATE.format(
        chef_name=chef_name,
        base=base,
        donors=", ".join(f"`{d}`" for d in donors) if donors else "(none)",
    )
    brief_text = (cook_dir / "BRIEF.md").read_text()
    prompt_text = prompt + "\n\n---\n\n# BRIEF.md\n\n" + brief_text

    run_meta = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "chef": chef_name,
        "flavor": flavor,
        "base": base,
        "donors": donors,
        "source": source,
        "input_root": str(input_root),
        "timeout_s": eff_timeout,
        "host": os.uname().nodename,
        "mode": "docker",
    }
    (cook_dir / f"CHEF_{chef_name}.json").write_text(json.dumps(run_meta, indent=2))

    print(f"[chef] project={project} chef={chef_name} ({flavor}) base={base}", flush=True)
    print(f"[chef] inputs materialized at {input_root}", flush=True)
    print("[chef] snapshotting creds...", flush=True)
    rc = _snapshot_creds_or_die(cook_dir, [flavor])
    if rc is not None:
        return rc

    compose_render.render_compose(cook_dir, cfg, profile_override=profile_override)
    _setup_worktree(cook_dir, chef_name, prompt_text)

    try:
        base_images.ensure_built([flavor])
    except Exception as e:                                                   # noqa: BLE001
        print(f"[chef] base image build failed: {e}", flush=True)
        return 2

    service = f"participant-{chef_name}"
    try:
        compose_runner.build_images(cook_dir, project, [service])
    except Exception as e:                                                   # noqa: BLE001
        print(f"[chef] build failed: {e}", flush=True)
        return 2

    metrics.reset_usage_dir(cook_dir, "participant", chef_name, flavor)
    log_dir = cook_dir / "logs" / chef_name
    started_at = datetime.now(timezone.utc).isoformat()
    # Merge a chef cell into the cook's status.json (created if absent) so
    # `multicooker status` surfaces the chef run with live token stats. We only
    # touch the cell — the top-level phase/state stay as the cook left them.
    state.set_cell(cook_dir, chef_name, role="participant", flavor=flavor,
                   state=state.RUNNING, started_at=started_at)
    print(f"[chef] launching {service} (timeout {eff_timeout}s)", flush=True)
    try:
        res: RunResult = compose_runner.run_cell(
            cook_dir=cook_dir,
            project=project,
            service=service,
            flavor=flavor,
            log_dir=log_dir,
            timeout_s=eff_timeout,
        )
    except Exception as e:                                                   # noqa: BLE001
        _write_trace(cook_dir, participant, mode="chef", round_num=None,
                     started_at=started_at, res=None, status="error", error=str(e))
        state.set_cell(cook_dir, chef_name, state=state.START_FAILED,
                       finished_at=state.now_iso(), exit_class=state.START_FAILED)
        print(f"[chef] {chef_name}: FAILED to launch: {e}", flush=True)
        return 1

    status = (
        "rate_limited" if res.rate_limited
        else "timed_out" if res.timed_out
        else "ok" if res.exit_code == 0
        else "non_zero_exit"
    )
    usage = metrics.collect_usage(cook_dir, "participant", chef_name, flavor)
    _write_trace(cook_dir, participant, mode="chef", round_num=None,
                 started_at=started_at, res=res, status=status, usage=usage)
    state.set_cell(cook_dir, chef_name, state=status, finished_at=state.now_iso(),
                   exit_class=status, duration_s=round(res.duration_s, 1))
    _seal_for_judging(cook_dir, chef_name)

    result = {
        **run_meta,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "exit_code": res.exit_code,
        "duration_s": round(res.duration_s, 1),
        "rate_limit_evidence": res.rate_limit_evidence,
        "retry_after_s": res.retry_after_s,
        "stdout": str(res.stdout_path),
        "stderr": str(res.stderr_path),
    }
    if usage is not None:
        result["usage"] = usage
    (cook_dir / f"CHEF_{chef_name}_RESULT.json").write_text(json.dumps(result, indent=2))

    try:
        compose_runner.teardown(cook_dir, project)
    except Exception as e:                                                   # noqa: BLE001
        print(f"[chef] teardown warning: {e}", flush=True)

    print(f"[chef] {chef_name}: {status} (exit={res.exit_code}, {res.duration_s:.1f}s)")
    _print_usage_summary("chef", [{"name": chef_name, "usage": usage}])
    print(f"[chef] sealed chef work tree at {cook_dir}/judging/_inbox/{chef_name}/")
    print(f"[chef] next: multicooker rejudge {name}")
    return 0 if status == "ok" else 1
