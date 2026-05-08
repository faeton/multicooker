"""multivarka command-line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .new_cook import new_cook
from .cook import cook
from .judge import judge as judge_cook
from .report import report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="multivarka",
        description="Run several LLM agents on the same task in parallel sandboxes.",
    )
    p.add_argument("--version", action="version", version=f"multivarka {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    # new
    pn = sub.add_parser("new", help="Scaffold a new cook (task) folder")
    pn.add_argument("name", help="Folder name under cooks/ (e.g. my-task)")
    pn.add_argument("--root", default="cooks", help="Parent folder (default: cooks/)")
    pn.add_argument("--participants", default="claude,codex,gemini",
                    help="Comma-separated list (default: claude,codex,gemini)")

    # cook
    pc = sub.add_parser("cook", help="Launch all participants in parallel")
    pc.add_argument("name", help="Cook folder name (under cooks/ unless absolute)")
    pc.add_argument("--root", default="cooks")
    pc.add_argument("--docker", action="store_true",
                    help="Use docker-mode (requires per-participant Dockerfile + API keys)")
    pc.add_argument("--participants", default=None,
                    help="Override which participants to run (comma-separated)")

    # judge
    pj = sub.add_parser("judge", help="Score all participant outputs with LLM judges")
    pj.add_argument("name")
    pj.add_argument("--root", default="cooks")
    pj.add_argument("--judges", default=None,
                    help="Override judges (comma-separated, e.g. claude,gemini)")

    # report
    pr = sub.add_parser("report", help="Build leaderboard.md from judge scores")
    pr.add_argument("name")
    pr.add_argument("--root", default="cooks")

    args = p.parse_args(argv)

    if args.cmd == "new":
        return new_cook(
            name=args.name, root=Path(args.root),
            participants=args.participants.split(","),
        )
    if args.cmd == "cook":
        return cook(
            name=args.name, root=Path(args.root),
            use_docker=args.docker,
            participants_override=args.participants.split(",") if args.participants else None,
        )
    if args.cmd == "judge":
        return judge_cook(
            name=args.name, root=Path(args.root),
            judges_override=args.judges.split(",") if args.judges else None,
        )
    if args.cmd == "report":
        return report(name=args.name, root=Path(args.root))
    return 2


if __name__ == "__main__":
    sys.exit(main())
