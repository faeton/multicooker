"""Render cooks/<task>/compose.yaml from brief.yaml + cook_dir layout.

v1 design choices (intentionally minimal — see docs/implementation-status.md):

- Single bridge network per cook (`mv-<task>`). Egress to internet allowed.
  Participants share the same network; they don't actively talk to each
  other, but full inter-container DNS isolation is a TODO. The trust model
  is "container is sandbox" — participants can't escape to the host.
- No allowlist proxy. Plain bridge. Add via compose.override.yaml if a
  task is sensitive.
- Auth: bind-mount RO from cooks/<task>/.auth/<flavor>/ (built by creds.py).
- Per-flavor entrypoint reads /work/PROMPT.txt and invokes the CLI with
  canonical sandbox argv. The PROMPT.txt is also bind-mounted RO.

Image naming: `mv-<task>-<flavor>` to keep cooks isolated from each other.
"""

from __future__ import annotations

from pathlib import Path

import yaml


def render_compose(cook_dir: Path, cfg: dict) -> Path:
    """Write cook_dir/compose.yaml. Returns the path."""
    name = cfg["name"]
    project = f"mv-{name}".lower().replace("_", "-")

    services: dict = {}

    # Participants
    for p in cfg.get("participants", []):
        pname = p["name"]
        flavor = p.get("flavor", pname)
        services[f"participant-{pname}"] = _participant_service(
            cook_dir=cook_dir,
            participant_name=pname,
            flavor=flavor,
            project=project,
        )

    # Judges (only emit if judging input has been materialized; cook.py
    # writes compose.yaml first and judge.py re-renders before its run).
    for j in cfg.get("judges", []):
        jname = j["name"]
        flavor = j.get("flavor", jname)
        services[f"judge-{jname}"] = _judge_service(
            cook_dir=cook_dir,
            judge_name=jname,
            flavor=flavor,
            project=project,
        )

    compose = {
        "name": project,
        "networks": {
            "default": {
                "driver": "bridge",
            },
        },
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
    if flavor == "gemini":
        # gemini needs settings.json + oauth_creds.json + a few small id files,
        # plus it writes a project registry to .gemini/projects.json at startup.
        # Mount the whole .gemini snapshot RW; creds are re-snapshotted each cook
        # so transient writes don't leak into the host's ~/.gemini.
        return [f"{auth}/gemini/:/home/node/.gemini/:rw"]
    raise ValueError(f"unknown flavor: {flavor}")


def _participant_service(cook_dir: Path, participant_name: str,
                         flavor: str, project: str) -> dict:
    cd = cook_dir.resolve()
    image = f"{project}-{flavor}"
    return {
        "image": image,
        "build": {
            "context": str(cd / "participants" / flavor),
            "dockerfile": "Dockerfile",
        },
        "container_name": f"{project}-participant-{participant_name}",
        "working_dir": "/work",
        "environment": {
            "MULTIVARKA_FLAVOR": flavor,
            "MULTIVARKA_PARTICIPANT": participant_name,
        },
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
                   project: str) -> dict:
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
    return {
        "image": image,
        "build": build,
        "container_name": f"{project}-judge-{judge_name}",
        "working_dir": "/work",
        "environment": {
            "MULTIVARKA_FLAVOR": flavor,
            "MULTIVARKA_JUDGE": judge_name,
        },
        "volumes": [
            f"{cd}/judging/_work-{judge_name}:/work:rw",
            *_auth_volumes(flavor, cook_dir),
        ],
        "restart": "no",
    }
