from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from . import __version__
from .diagnose import diagnose, format_human


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rupicola-llm",
        description="Read-only diagnostics for incomplete Rupicola derivations.",
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
    raise AssertionError(f"unhandled command {args.command}")


if __name__ == "__main__":
    sys.exit(main())

