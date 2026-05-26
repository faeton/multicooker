"""multicooker command-line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .new_cook import new_cook
from .add_participant import add_participant
from .cook import cook
from .judge import judge as judge_cook
from .report import report
from .clean import clean
from .refine import refine
from .rejudge import rejudge
from .doctor import doctor
from .diff_rounds import diff_rounds
from . import base_images


def _csv(s: str | None) -> list[str] | None:
    return [x.strip() for x in s.split(",") if x.strip()] if s else None


def _resolve_root(root_arg: str) -> Path:
    """Resolve --root to an absolute path so the CLI works from any cwd.

    Try cwd first, then walk up looking for a directory of that name
    (handles invocation from a subdirectory of the repo), then fall back
    to a path resolved relative to the multicooker source location
    (handles invocation from anywhere on the machine). Absolute paths
    pass through untouched.
    """
    root_path = Path(root_arg)
    if root_path.is_absolute():
        return root_path
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / root_path
        if candidate.is_dir():
            return candidate.resolve()
    # Fall back to the multicooker source root (parent of this package).
    pkg_root = Path(__file__).resolve().parent.parent
    candidate = pkg_root / root_path
    if candidate.is_dir():
        return candidate
    # Not found anywhere; return cwd-relative so the downstream error
    # message names the path the user asked for.
    return (cwd / root_path).resolve()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="multicooker",
        description="Run several LLM agents on the same task in parallel docker sandboxes.",
    )
    p.add_argument("--version", action="version", version=f"multicooker {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    # doctor
    pd = sub.add_parser("doctor",
                        help="Preflight: check docker + creds for a cook (or default flavors)")
    pd.add_argument("name", nargs="?", default=None,
                    help="Cook folder name (optional; if given, checks the flavors it uses)")
    pd.add_argument("--root", default="cooks")
    pd.add_argument("--participants", default=None,
                    help="Override flavors to check (comma-separated)")
    pd.add_argument("--strict", action="store_true",
                    help="Treat warnings (missing base image) as failures (exit=1)")

    # build-base
    pbb = sub.add_parser("build-base",
                         help="Build shared mc-base-<flavor> images "
                              "(node:22-slim + npm i -g <cli>)")
    pbb.add_argument("flavors", nargs="*",
                     help="Flavors to build (default: all under templates/base/)")
    pbb.add_argument("--force", action="store_true",
                     help="Rebuild even if the image already exists")

    # new
    pn = sub.add_parser("new", help="Scaffold a new cook (task) folder")
    pn.add_argument("name", help="Folder name under cooks/ (e.g. my-task)")
    pn.add_argument("--root", default="cooks", help="Parent folder (default: cooks/)")
    pn.add_argument("--participants", default="claude,codex,gemini,grok",
                    help="Comma-separated list (default: claude,codex,gemini,grok). "
                         "Each entry is a flavor; for multiple participants of "
                         "the same flavor use NAME=FLAVOR (e.g. claude-a=claude,claude-b=claude).")

    # add-participant (extend an existing cook)
    pap = sub.add_parser("add-participant",
                         help="Add another participant to an existing cook")
    pap.add_argument("name", help="Cook folder name")
    pap.add_argument("participant",
                     help="NEW_NAME or NEW_NAME=FLAVOR (flavor defaults to NEW_NAME)")
    pap.add_argument("--root", default="cooks")

    # cook
    pc = sub.add_parser("cook", help="Launch all participants in parallel")
    pc.add_argument("name", help="Cook folder name (under cooks/ unless absolute)")
    pc.add_argument("--root", default="cooks")
    pc.add_argument("--participants", default=None,
                    help="Override which participants to run (comma-separated NAMES from brief.yaml)")

    # judge
    pj = sub.add_parser("judge", help="Score all participant outputs with LLM judges")
    pj.add_argument("name")
    pj.add_argument("--root", default="cooks")
    pj.add_argument("--judges", default=None,
                    help="Override judges (comma-separated, e.g. claude,gemini)")

    # refine
    prf = sub.add_parser("refine",
                         help="Run another round on top of previous output, with feedback")
    prf.add_argument("name")
    prf.add_argument("--root", default="cooks")
    prf.add_argument("--participants", default=None,
                     help="Override which participants to refine (comma-separated)")
    prf.add_argument("--feedback", default=None, metavar="PATH",
                     help="Use this file as shared feedback instead of "
                          "cooks/<task>/FEEDBACK.md (handy for reusing feedback "
                          "across cooks).")

    # diff
    pdf = sub.add_parser("diff",
                         help="Show file-level diff between two refine rounds "
                              "(sanity check that refine moved the needle)")
    pdf.add_argument("name", help="Cook folder name")
    pdf.add_argument("n", type=int, help="Round N (older)")
    pdf.add_argument("m", type=int, help="Round M (newer; use the live round if it isn't snapshotted yet)")
    pdf.add_argument("--root", default="cooks")
    pdf.add_argument("--participants", default=None,
                     help="Comma-separated participants to diff (default: all)")

    # rejudge
    prj = sub.add_parser("rejudge",
                         help="Re-seal _inbox/ from current work/ and run judges "
                              "again (no participant re-run; useful after "
                              "editing JUDGE_BRIEF.md or hand-fixing out/)")
    prj.add_argument("name")
    prj.add_argument("--root", default="cooks")
    prj.add_argument("--judges", default=None,
                     help="Override judges (comma-separated)")

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
    if hasattr(args, "root"):
        args.root = str(_resolve_root(args.root))

    if args.cmd == "doctor":
        return doctor(
            name=args.name, root=Path(args.root),
            participants_override=_csv(args.participants),
            strict=args.strict,
        )
    if args.cmd == "build-base":
        flavors = args.flavors or sorted(
            d.name for d in base_images.TEMPLATE_DIR.iterdir()
            if d.is_dir() and (d / "Dockerfile").exists()
        )
        for flavor in flavors:
            try:
                base_images.build(flavor, force=args.force)
            except Exception as e:                                            # noqa: BLE001
                print(f"build-base {flavor}: {e}", file=sys.stderr)
                return 1
        return 0
    if args.cmd == "new":
        return new_cook(
            name=args.name, root=Path(args.root),
            participants=_csv(args.participants) or [],
        )
    if args.cmd == "add-participant":
        return add_participant(
            name=args.name, root=Path(args.root),
            spec=args.participant,
        )
    if args.cmd == "cook":
        return cook(
            name=args.name, root=Path(args.root),
            participants_override=_csv(args.participants),
        )
    if args.cmd == "judge":
        return judge_cook(
            name=args.name, root=Path(args.root),
            judges_override=_csv(args.judges),
        )
    if args.cmd == "refine":
        return refine(
            name=args.name, root=Path(args.root),
            participants_override=_csv(args.participants),
            feedback_path=Path(args.feedback) if args.feedback else None,
        )
    if args.cmd == "diff":
        return diff_rounds(
            name=args.name, root=Path(args.root),
            n=args.n, m=args.m,
            participants_override=_csv(args.participants),
        )
    if args.cmd == "rejudge":
        return rejudge(
            name=args.name, root=Path(args.root),
            judges_override=_csv(args.judges),
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
