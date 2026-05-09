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
from .clean import clean
from .refine import refine


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
    pj.add_argument("--docker", action="store_true",
                    help="Run judges in containers (matches `cook --docker`).")
    pj.add_argument("--judges", default=None,
                    help="Override judges (comma-separated, e.g. claude,gemini)")

    # refine
    prf = sub.add_parser("refine",
                         help="Run another round on top of previous output, with feedback")
    prf.add_argument("name")
    prf.add_argument("--root", default="cooks")
    prf.add_argument("--participants", default=None,
                     help="Override which participants to refine (comma-separated)")

    # report
    pr = sub.add_parser("report", help="Build leaderboard.md from judge scores")
    pr.add_argument("name")
    pr.add_argument("--root", default="cooks")

    # clean
    pcl = sub.add_parser("clean",
                         help="Tear down docker containers/networks/images for a cook")
    pcl.add_argument("name", nargs="?", default=None,
                     help="Cook to clean (omit if using --all)")
    pcl.add_argument("--root", default="cooks")
    pcl.add_argument("--all", action="store_true", dest="all_cooks",
                     help="Clean every cook under <root>/")
    pcl.add_argument("--dry-run", action="store_true",
                     help="Show what would be removed; touch nothing")
    pcl.add_argument("--keep-creds", action="store_true",
                     help="Don't remove cooks/<task>/.auth/")

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
            use_docker=args.docker,
            judges_override=args.judges.split(",") if args.judges else None,
        )
    if args.cmd == "refine":
        return refine(
            name=args.name, root=Path(args.root),
            use_docker=True,
            participants_override=args.participants.split(",") if args.participants else None,
        )
    if args.cmd == "report":
        return report(name=args.name, root=Path(args.root))
    if args.cmd == "clean":
        return clean(
            name=args.name, root=Path(args.root),
            all_cooks=args.all_cooks, dry_run=args.dry_run,
            keep_creds=args.keep_creds,
        )
    return 2


if __name__ == "__main__":
    sys.exit(main())
