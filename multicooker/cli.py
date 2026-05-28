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
from .status_cmd import status_cmd
from .cancel_cmd import cancel_cmd
from .resume_cmd import resume
from .tail_cmd import tail_cmd
from .lint import lint as lint_cook
from .artifacts import artifacts_cmd
from .archive_cmd import archive
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
    pd.add_argument("--capacity", action="store_true",
                    help="Also check host capacity against per-cell mem_limits "
                         "(reads `docker info` from the active docker context)")
    pd.add_argument("--profile", choices=["auto", "large", "medium", "small"],
                    default=None,
                    help="Profile to use when planning capacity (default: auto-detect)")
    pd.add_argument("--concurrent-cooks", type=int, default=1,
                    help="How many cooks may run in parallel on this host (default: 1)")
    pd.add_argument("--reserve-mib", type=int, default=2048,
                    help="MiB to leave for OS + other host services (default: 2048)")

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

    profile_help = (
        "Resource profile for the docker context: auto (default, detects from "
        "host RAM via `docker info`), large (no mem/cpu caps), medium "
        "(2g/1cpu per cell), small (1g/0.5cpu). Overrides MULTICOOKER_PROFILE "
        "env and brief.yaml resources.profile."
    )
    profile_choices = ["auto", "large", "medium", "small"]

    # cook
    pc = sub.add_parser("cook", help="Launch all participants in parallel")
    pc.add_argument("name", help="Cook folder name (under cooks/ unless absolute)")
    pc.add_argument("--root", default="cooks")
    pc.add_argument("--participants", default=None,
                    help="Override which participants to run (comma-separated NAMES from brief.yaml)")
    pc.add_argument("--profile", choices=profile_choices, default=None,
                    help=profile_help)

    # judge
    pj = sub.add_parser("judge", help="Score all participant outputs with LLM judges")
    pj.add_argument("name")
    pj.add_argument("--root", default="cooks")
    pj.add_argument("--judges", default=None,
                    help="Override judges (comma-separated, e.g. claude,gemini)")
    pj.add_argument("--profile", choices=profile_choices, default=None,
                    help=profile_help)

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
    prf.add_argument("--profile", choices=profile_choices, default=None,
                     help=profile_help)

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
    prj.add_argument("--profile", choices=profile_choices, default=None,
                     help=profile_help)

    # report
    pr = sub.add_parser("report", help="Build leaderboard.md from judge scores")
    pr.add_argument("name")
    pr.add_argument("--root", default="cooks")

    # lint
    pli = sub.add_parser("lint",
                         help="Check brief.yaml + JUDGE_BRIEF.md consistency "
                              "(rubric dimension coverage, schema)")
    pli.add_argument("name", help="Cook folder name")
    pli.add_argument("--root", default="cooks")

    # artifacts
    par = sub.add_parser("artifacts",
                         help="Build/show artifacts.json (visibility-tagged file manifest)")
    par.add_argument("name", help="Cook folder name")
    par.add_argument("--root", default="cooks")
    par.add_argument("--json", action="store_true", dest="as_json",
                     help="Emit the manifest as JSON")

    # archive
    pac = sub.add_parser("archive",
                         help="Copy only publishable artifacts into a shareable "
                              "dir/tarball (never .auth or judge mappings)")
    pac.add_argument("name", help="Cook folder name")
    pac.add_argument("--root", default="cooks")
    pac.add_argument("--out", default=None,
                     help="Output path (default: cooks/<task>/archive or .tar.gz)")
    pac.add_argument("--include-operator", action="store_true",
                     help="Also include operator files (logs, traces, results)")
    pac.add_argument("--format", choices=["dir", "tar"], default="dir",
                     dest="fmt", help="Output as a directory (default) or .tar.gz")

    # status
    pst = sub.add_parser("status",
                         help="Show a cook's current state (reads status.json)")
    pst.add_argument("name", help="Cook folder name")
    pst.add_argument("--root", default="cooks")
    pst.add_argument("--json", action="store_true", dest="as_json",
                     help="Emit the raw status.json snapshot as JSON")

    # cancel
    pcn = sub.add_parser("cancel",
                         help="Stop a running cook and mark it cancelled "
                              "(preserves partial outputs)")
    pcn.add_argument("name", help="Cook folder name")
    pcn.add_argument("--root", default="cooks")

    # resume
    prs = sub.add_parser("resume",
                         help="Re-run only the retryable cells of the latest round")
    prs.add_argument("name", help="Cook folder name")
    prs.add_argument("--root", default="cooks")
    prs.add_argument("--force", action="store_true",
                     help="Also rerun cells that already succeeded")
    prs.add_argument("--profile", choices=profile_choices, default=None,
                     help=profile_help)

    # tail
    pt = sub.add_parser("tail",
                        help="Stream a cook's cell logs, prefixed by actor")
    pt.add_argument("name", help="Cook folder name")
    pt.add_argument("actor", nargs="?", default=None,
                    help="Only this participant/judge (default: all)")
    pt.add_argument("--root", default="cooks")
    pt.add_argument("--no-follow", action="store_false", dest="follow",
                    help="Print existing log content and exit (don't follow)")

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
            capacity=args.capacity,
            profile_override=args.profile,
            concurrent_cooks=args.concurrent_cooks,
            reserve_mib=args.reserve_mib,
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
            profile_override=args.profile,
        )
    if args.cmd == "judge":
        return judge_cook(
            name=args.name, root=Path(args.root),
            judges_override=_csv(args.judges),
            profile_override=args.profile,
        )
    if args.cmd == "refine":
        return refine(
            name=args.name, root=Path(args.root),
            participants_override=_csv(args.participants),
            feedback_path=Path(args.feedback) if args.feedback else None,
            profile_override=args.profile,
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
            profile_override=args.profile,
        )
    if args.cmd == "report":
        return report(name=args.name, root=Path(args.root))
    if args.cmd == "lint":
        return lint_cook(name=args.name, root=Path(args.root))
    if args.cmd == "artifacts":
        return artifacts_cmd(name=args.name, root=Path(args.root), as_json=args.as_json)
    if args.cmd == "archive":
        return archive(name=args.name, root=Path(args.root), out=args.out,
                       include_operator=args.include_operator, fmt=args.fmt)
    if args.cmd == "status":
        return status_cmd(name=args.name, root=Path(args.root), as_json=args.as_json)
    if args.cmd == "cancel":
        return cancel_cmd(name=args.name, root=Path(args.root))
    if args.cmd == "resume":
        return resume(name=args.name, root=Path(args.root),
                      force=args.force, profile_override=args.profile)
    if args.cmd == "tail":
        return tail_cmd(name=args.name, root=Path(args.root),
                        actor=args.actor, follow=args.follow)
    if args.cmd == "clean":
        return clean(
            name=args.name, root=Path(args.root),
            all_cooks=args.all_cooks, dry_run=args.dry_run,
            keep_creds=args.keep_creds,
        )
    return 2


if __name__ == "__main__":
    sys.exit(main())
