"""Render cooks/<task>/compose.yaml from brief.yaml + cook_dir layout.

Network model:

- One bridge network per participant (`mc-<task>-net-<participant>`) and
  one per judge. Each service joins only its own network, so containers
  inside the same cook cannot resolve or reach each other — a participant
  can't peek at another's `/work/out/` over the network, and a judge
  can't see participants. Egress to the internet stays open: participants
  may legitimately need npm/pypi/github/docs to do their task. The
  sandbox guarantee is the container itself, not the network.
- Auth: bind-mount RO from cooks/<task>/.auth/<flavor>/ (built by creds.py).
- Per-flavor entrypoint reads /work/PROMPT.txt and invokes the CLI with
  canonical sandbox argv. The PROMPT.txt is also bind-mounted RO.

Image naming: `mc-<task>-<flavor>` to keep cooks isolated from each other.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from . import host_profile, metrics


def render_compose(cook_dir: Path, cfg: dict,
                   profile_override: str | None = None) -> Path:
    """Write cook_dir/compose.yaml. Returns the path.

    `profile_override` comes from the CLI (--profile auto|large|medium|small).
    brief.yaml `resources.profile` and the MULTICOOKER_PROFILE env var
    are also honored via `host_profile.resolve_profile`.
    """
    name = cfg["name"]
    project = f"mc-{name}".lower().replace("_", "-")

    top_resources = cfg.get("resources") or {}
    cfg_profile = top_resources.get("profile")
    profile = host_profile.resolve_profile(
        cli_override=profile_override, cfg_override=cfg_profile,
    )

    services: dict = {}
    networks: dict = {}

    # Participants — each on its own bridge so they can't see each other.
    for p in cfg.get("participants", []):
        pname = p["name"]
        flavor = p.get("flavor", pname)
        net = f"net-participant-{pname}"
        networks[net] = {"driver": "bridge"}
        services[f"participant-{pname}"] = _participant_service(
            cook_dir=cook_dir,
            participant_name=pname,
            flavor=flavor,
            project=project,
            network=net,
            model=p.get("model"),
            limits=_resolve_limits(
                actor=p, top_resources=top_resources, profile=profile,
            ),
        )

    # Judges (only emit if judging input has been materialized; cook.py
    # writes compose.yaml first and judge.py re-renders before its run).
    for j in cfg.get("judges", []):
        jname = j["name"]
        flavor = j.get("flavor", jname)
        net = f"net-judge-{jname}"
        networks[net] = {"driver": "bridge"}
        services[f"judge-{jname}"] = _judge_service(
            cook_dir=cook_dir,
            judge_name=jname,
            flavor=flavor,
            project=project,
            network=net,
            model=j.get("model"),
            limits=_resolve_limits(
                actor=j, top_resources=top_resources, profile=profile,
            ),
        )

    compose = {
        "name": project,
        "networks": networks,
        "services": services,
    }

    out = cook_dir / "compose.yaml"
    out.write_text(yaml.safe_dump(compose, sort_keys=False))
    return out


def _resolve_limits(actor: dict, top_resources: dict,
                    profile: dict) -> dict[str, Any]:
    """Per-cell limits: profile defaults overridden by brief.yaml.

    Resolution (weakest → strongest):
      1. profile defaults (host_profile.PROFILES[tier])
      2. brief.yaml top-level `resources:` (apart from `profile`)
      3. brief.yaml per-actor `resources:`

    Returns a dict with possibly-None keys:
      mem_limit, memswap_limit, cpus, pids_limit

    Convention: if mem_limit is set and memswap_limit isn't, mirror
    mem_limit into memswap_limit. Without this, docker defaults
    memswap to 2×mem, which means a cell can quietly drain the host's
    swap — exactly what we want to prevent on a shared VPS.
    """
    actor_res = actor.get("resources") or {}

    def pick(key: str) -> Any:
        if key in actor_res:
            return actor_res[key]
        if key in top_resources and key != "profile":
            return top_resources[key]
        return profile.get(key)

    mem = pick("mem_limit")
    memswap = pick("memswap_limit")
    if mem is not None and memswap is None:
        memswap = mem
    cpus = pick("cpus")

    # pids_limit override is allowed but rare; fall back to the cheap
    # safety default if neither layer set it.
    pids = (actor_res.get("pids_limit")
            or top_resources.get("pids_limit")
            or host_profile.DEFAULT_PIDS_LIMIT)

    return {
        "mem_limit": mem,
        "memswap_limit": memswap,
        "cpus": str(cpus) if cpus is not None else None,
        "pids_limit": pids,
    }


def _apply_limits(service: dict, limits: dict[str, Any]) -> None:
    """Mutate `service` to add resource limits + cheap safeties.

    Always emits: pids_limit, oom_score_adj, logging caps, ulimit nofile.
    Conditionally emits: mem_limit, memswap_limit, cpus (only when the
    profile/override set them — `large` profile leaves them None so dev
    laptops aren't artificially throttled).
    """
    if limits["mem_limit"] is not None:
        service["mem_limit"] = limits["mem_limit"]
    if limits["memswap_limit"] is not None:
        service["memswap_limit"] = limits["memswap_limit"]
    if limits["cpus"] is not None:
        service["cpus"] = limits["cpus"]
    service["pids_limit"] = limits["pids_limit"]
    service["oom_score_adj"] = host_profile.DEFAULT_OOM_SCORE_ADJ
    soft, hard = host_profile.DEFAULT_NOFILE
    service["ulimits"] = {"nofile": {"soft": soft, "hard": hard}}
    service["logging"] = {
        "driver": "json-file",
        "options": dict(host_profile.DEFAULT_LOG_OPTS),
    }


def _auth_volumes(flavor: str, cook_dir: Path) -> list[str]:
    """Bind-mount the right cred file(s) per flavor.

    Paths are absolute on the host (compose resolves relative paths against
    its own dir, which is the cook_dir, but absolute is more robust against
    `docker compose -f` invocations).
    """
    auth = (cook_dir / ".auth").resolve()
    # Containers run as the `node` user (uid=1000); claude refuses
    # --dangerously-skip-permissions under root. So creds go in /home/node.
    if flavor == "claude":
        return [f"{auth}/claude/:/home/node/.claude/:ro"]
    if flavor == "codex":
        return [f"{auth}/codex/auth.json:/home/node/.codex/auth.json:ro"]
    if flavor == "grok":
        # Single-file RO bind (codex pattern). Rest of /home/node/.grok/
        # (bin/, bundled/, etc.) stays as the image baked it. Token refresh
        # writes during a cook won't persist back to the snapshot, but cooks
        # finish well within the ~6h token lifetime.
        return [f"{auth}/grok/auth.json:/home/node/.grok/auth.json:ro"]
    if flavor == "gemini":
        # gemini needs settings.json + oauth_creds.json + a few small id files,
        # plus it writes a project registry to .gemini/projects.json at startup.
        # Mount the whole .gemini snapshot RW; creds are re-snapshotted each cook
        # so transient writes don't leak into the host's ~/.gemini.
        return [f"{auth}/gemini/:/home/node/.gemini/:rw"]
    if flavor == "dummy":
        # Smoke-test flavor — no creds, no auth mount.
        return []
    raise ValueError(f"unknown flavor: {flavor}")


def _usage_volumes(flavor: str, cook_dir: Path, cell_kind: str, name: str) -> list[str]:
    """Writable mounts for CLI usage ledgers, kept inside the cook folder."""
    root = metrics.prepare_usage_dir(cook_dir, cell_kind, name, flavor).resolve()
    if flavor == "claude":
        # This deliberately overlays a writable projects/ submount under the
        # read-only ~/.claude auth mount so session ledgers stay cook-local.
        return [f"{root}/projects:/home/node/.claude/projects:rw"]
    if flavor == "codex":
        return [f"{root}/sessions:/home/node/.codex/sessions:rw"]
    if flavor == "gemini":
        return [
            f"{root}/tmp:/home/node/.gemini/tmp:rw",
            f"{root}/history:/home/node/.gemini/history:rw",
        ]
    return []


def _participant_service(cook_dir: Path, participant_name: str,
                         flavor: str, project: str, network: str,
                         model: str | None = None,
                         limits: dict | None = None) -> dict:
    cd = cook_dir.resolve()
    image = f"{project}-{flavor}"
    env = {
        "MULTICOOKER_FLAVOR": flavor,
        "MULTICOOKER_PARTICIPANT": participant_name,
    }
    if model:
        env["MULTICOOKER_MODEL"] = model
    service = {
        "image": image,
        "build": {
            "context": str(cd / "participants" / flavor),
            "dockerfile": "Dockerfile",
        },
        "container_name": f"{project}-participant-{participant_name}",
        "working_dir": "/work",
        "environment": env,
        "networks": [network],
        "volumes": [
            f"{cd}/BRIEF.md:/work/BRIEF.md:ro",
            f"{cd}/raw:/work/raw:ro",
            f"{cd}/work/{participant_name}/PROMPT.txt:/work/PROMPT.txt:ro",
            f"{cd}/work/{participant_name}/out:/work/out:rw",
            *_auth_volumes(flavor, cook_dir),
            *_usage_volumes(flavor, cook_dir, "participant", participant_name),
        ],
        # `up` will run the entrypoint baked into the image.
        # Don't restart on failure — we want a definitive exit.
        "restart": "no",
    }
    if limits is not None:
        _apply_limits(service, limits)
    return service


def _judge_service(cook_dir: Path, judge_name: str, flavor: str,
                   project: str, network: str,
                   model: str | None = None,
                   limits: dict | None = None) -> dict:
    cd = cook_dir.resolve()
    image = f"{project}-{flavor}-judge"
    judge_ctx = cd / "judge" / flavor
    # If the cook didn't override the judge image, use the participant image.
    use_participant_image = not (judge_ctx / "Dockerfile").exists()
    if use_participant_image:
        image = f"{project}-{flavor}"
        build = {
            "context": str(cd / "participants" / flavor),
            "dockerfile": "Dockerfile",
        }
    else:
        build = {"context": str(judge_ctx), "dockerfile": "Dockerfile"}
    env = {
        "MULTICOOKER_FLAVOR": flavor,
        "MULTICOOKER_JUDGE": judge_name,
    }
    if model:
        env["MULTICOOKER_MODEL"] = model
    service = {
        "image": image,
        "build": build,
        "container_name": f"{project}-judge-{judge_name}",
        "working_dir": "/work",
        "environment": env,
        "networks": [network],
        "volumes": [
            f"{cd}/judging/_work-{judge_name}:/work:rw",
            *_auth_volumes(flavor, cook_dir),
            *_usage_volumes(flavor, cook_dir, "judge", judge_name),
        ],
        "restart": "no",
    }
    if limits is not None:
        _apply_limits(service, limits)
    return service
