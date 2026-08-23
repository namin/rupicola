from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from . import __version__
from .diagnose import diagnose, format_human
from .project import ProjectError, find_project_root
from .runs import RunStore, RunStoreError, default_runs_root
from .solve import format_show_human, format_solve_human, load_run, solve_with_patch


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rupicola-llm",
        description="Diagnose Rupicola proofs and check isolated candidate patches.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    diagnose_parser = subparsers.add_parser(
        "diagnose", help="replay a proof and classify residual compiler goals"
    )
    diagnose_parser.add_argument("file", type=Path, help="Rocq source containing the proof")
    diagnose_parser.add_argument("--theorem", required=True, help="the theorem to replay")
    diagnose_parser.add_argument(
        "--line",
        type=int,
        help="replay through the last complete phrase ending on or before this line",
    )
    diagnose_parser.add_argument(
        "--project-root", type=Path, help="override automatic _CoqProject discovery"
    )
    diagnose_parser.add_argument(
        "--timeout", type=float, default=120.0, help="seconds allowed per Rocq response"
    )
    diagnose_parser.add_argument(
        "--json", action="store_true", help="emit the versioned machine-readable record"
    )

    solve_parser = subparsers.add_parser(
        "solve", help="validate a candidate patch in an isolated workspace"
    )
    solve_parser.add_argument("file", type=Path, help="Rocq source containing the proof")
    solve_parser.add_argument("--theorem", required=True, help="the theorem to solve")
    solve_parser.add_argument(
        "--candidate-patch",
        required=True,
        type=Path,
        help="unified diff proposed by a deterministic or model provider",
    )
    solve_parser.add_argument(
        "--scope", choices=("local", "project"), default="local"
    )
    solve_parser.add_argument("--project-root", type=Path)
    solve_parser.add_argument("--runs-root", type=Path, help=argparse.SUPPRESS)
    solve_parser.add_argument("--timeout", type=float, default=120.0)
    solve_parser.add_argument("--rationale", help="proposal rationale recorded with the run")
    solve_parser.add_argument("--json", action="store_true")

    show_parser = subparsers.add_parser("show", help="show a persisted solve run")
    show_parser.add_argument("run_id")
    show_parser.add_argument("--project-root", type=Path)
    show_parser.add_argument("--runs-root", type=Path, help=argparse.SUPPRESS)
    show_parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "diagnose":
        result, exit_code = diagnose(
            args.file,
            args.theorem,
            through_line=args.line,
            project_root=args.project_root,
            timeout_seconds=args.timeout,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(format_human(result))
        return exit_code
    if args.command == "solve":
        result, exit_code = solve_with_patch(
            args.file,
            args.theorem,
            args.candidate_patch,
            scope=args.scope,
            project_root=args.project_root,
            runs_root=args.runs_root,
            timeout_seconds=args.timeout,
            rationale=args.rationale,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(format_solve_human(result))
        return exit_code
    if args.command == "show":
        try:
            if args.runs_root is not None:
                runs_root = args.runs_root
            else:
                root = (
                    args.project_root.expanduser().resolve()
                    if args.project_root is not None
                    else find_project_root(Path.cwd())
                )
                runs_root = default_runs_root(root)
            result = load_run(RunStore(runs_root), args.run_id)
        except (ProjectError, RunStoreError) as error:
            result = {"schema_version": "0.1", "status": "error", "message": str(error)}
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(f"rupicola-llm show: {error}")
            return 2
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(format_show_human(result))
        return 0
    raise AssertionError(f"unhandled command {args.command}")


if __name__ == "__main__":
    sys.exit(main())
