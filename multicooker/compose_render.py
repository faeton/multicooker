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

import yaml


def render_compose(cook_dir: Path, cfg: dict) -> Path:
    """Write cook_dir/compose.yaml. Returns the path."""
    name = cfg["name"]
    project = f"mc-{name}".lower().replace("_", "-")

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
        )

    compose = {
        "name": project,
        "networks": networks,
        "services": services,
    }

    out = cook_dir / "compose.yaml"
    out.write_text(yaml.safe_dump(compose, sort_keys=False))
    return out


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


def _participant_service(cook_dir: Path, participant_name: str,
                         flavor: str, project: str, network: str,
                         model: str | None = None) -> dict:
    cd = cook_dir.resolve()
    image = f"{project}-{flavor}"
    env = {
        "MULTICOOKER_FLAVOR": flavor,
        "MULTICOOKER_PARTICIPANT": participant_name,
    }
    if model:
        env["MULTICOOKER_MODEL"] = model
    return {
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
        ],
        # `up` will run the entrypoint baked into the image.
        # Don't restart on failure — we want a definitive exit.
        "restart": "no",
    }


def _judge_service(cook_dir: Path, judge_name: str, flavor: str,
                   project: str, network: str,
                   model: str | None = None) -> dict:
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
    return {
        "image": image,
        "build": build,
        "container_name": f"{project}-judge-{judge_name}",
        "working_dir": "/work",
        "environment": env,
        "networks": [network],
        "volumes": [
            f"{cd}/judging/_work-{judge_name}:/work:rw",
            *_auth_volumes(flavor, cook_dir),
        ],
        "restart": "no",
    }
