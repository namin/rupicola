from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from . import __version__
from .agent import solve_with_agent
from .agent_protocol import AgentProtocolError, ScriptedProvider
from .bedrock import (
    AwsCliConverseTransport,
    BedrockError,
    BedrockProvider,
    resolve_aws_region,
)
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
        "solve", help="run a bounded provider or validate an isolated candidate"
    )
    solve_parser.add_argument("file", type=Path, help="Rocq source containing the proof")
    solve_parser.add_argument("--theorem", required=True, help="the theorem to solve")
    proposal_source = solve_parser.add_mutually_exclusive_group(required=True)
    proposal_source.add_argument(
        "--candidate-patch",
        type=Path,
        help="unified diff proposed by a deterministic or model provider",
    )
    proposal_source.add_argument(
        "--agent-script",
        type=Path,
        help="deterministic JSON action script for the bounded agent controller",
    )
    proposal_source.add_argument(
        "--provider",
        choices=("bedrock",),
        help="remote model provider for the bounded agent controller",
    )
    solve_parser.add_argument(
        "--scope", choices=("local", "project"), default="local"
    )
    solve_parser.add_argument("--project-root", type=Path)
    solve_parser.add_argument("--runs-root", type=Path, help=argparse.SUPPRESS)
    solve_parser.add_argument("--timeout", type=float, default=120.0)
    solve_parser.add_argument("--rationale", help="proposal rationale recorded with the run")
    solve_parser.add_argument("--max-actions", type=int, default=24)
    solve_parser.add_argument("--max-checks", type=int, default=3)
    solve_parser.add_argument("--max-retrievals", type=int, default=8)
    solve_parser.add_argument("--wall-seconds", type=float, default=900.0)
    solve_parser.add_argument("--model-id", help="Bedrock model or inference-profile ID")
    solve_parser.add_argument("--aws-region", help="AWS region; defaults to profile config")
    solve_parser.add_argument("--aws-profile", default="default")
    solve_parser.add_argument(
        "--allow-remote-source",
        action="store_true",
        help="confirm disclosure of proof context and requested source to the provider",
    )
    solve_parser.add_argument(
        "--provider-timeout",
        type=float,
        default=180.0,
        help="seconds allowed per remote provider response",
    )
    solve_parser.add_argument(
        "--bedrock-max-tokens",
        type=int,
        default=8192,
        help="maximum output tokens per Bedrock response",
    )
    solve_parser.add_argument(
        "--bedrock-temperature",
        type=float,
        help="optional temperature for models that support it",
    )
    solve_parser.add_argument(
        "--bedrock-no-strict-tools",
        action="store_false",
        dest="bedrock_strict_tools",
        default=True,
        help="disable Bedrock-side strict schemas; local validation remains enabled",
    )
    solve_parser.add_argument(
        "--bedrock-auto-tool",
        action="store_false",
        dest="bedrock_force_tool",
        default=True,
        help="let the model choose whether to call a tool",
    )
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
        if args.provider == "bedrock":
            if not args.allow_remote_source:
                result = {
                    "schema_version": "0.1",
                    "status": "error",
                    "message": (
                        "Bedrock receives proof context and requested source; "
                        "rerun with --allow-remote-source to confirm disclosure"
                    ),
                }
                exit_code = 2
            elif args.model_id is None:
                result = {
                    "schema_version": "0.1",
                    "status": "error",
                    "message": "--model-id is required with --provider bedrock",
                }
                exit_code = 2
            else:
                try:
                    region = resolve_aws_region(
                        args.aws_region,
                        profile=args.aws_profile,
                    )
                    transport = AwsCliConverseTransport(
                        region=region,
                        profile=args.aws_profile,
                        timeout_seconds=args.provider_timeout,
                    )
                    provider = BedrockProvider(
                        transport,
                        model_id=args.model_id,
                        region=region,
                        profile=args.aws_profile,
                        allow_remote_source=True,
                        max_tokens=args.bedrock_max_tokens,
                        temperature=args.bedrock_temperature,
                        strict_tools=args.bedrock_strict_tools,
                        force_tool=args.bedrock_force_tool,
                    )
                except BedrockError as error:
                    result = {
                        "schema_version": "0.1",
                        "status": "error",
                        "message": str(error),
                    }
                    exit_code = 2
                else:
                    result, exit_code = solve_with_agent(
                        args.file,
                        args.theorem,
                        provider,
                        scope=args.scope,
                        project_root=args.project_root,
                        runs_root=args.runs_root,
                        timeout_seconds=args.timeout,
                        max_actions=args.max_actions,
                        max_checks=args.max_checks,
                        max_retrievals=args.max_retrievals,
                        wall_seconds=args.wall_seconds,
                    )
        elif args.agent_script is not None:
            try:
                provider = ScriptedProvider.load(args.agent_script)
            except AgentProtocolError as error:
                result = {
                    "schema_version": "0.1",
                    "status": "error",
                    "message": str(error),
                }
                exit_code = 2
            else:
                result, exit_code = solve_with_agent(
                    args.file,
                    args.theorem,
                    provider,
                    scope=args.scope,
                    project_root=args.project_root,
                    runs_root=args.runs_root,
                    timeout_seconds=args.timeout,
                    max_actions=args.max_actions,
                    max_checks=args.max_checks,
                    max_retrievals=args.max_retrievals,
                    wall_seconds=args.wall_seconds,
                )
        else:
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
