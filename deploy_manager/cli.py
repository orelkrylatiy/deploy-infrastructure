from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .config import ConfigError, load_config, validate_slug, validate_release_id
from .engine import DeployError, deploy, init_project, list_releases, read_logs, rollback, status
from .logging_utils import get_logger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="deploy-manager", description="Release-based deployment manager.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    for command, help_text in (
        ("init", "Create the managed directory structure."),
        ("status", "Show current release and service state."),
        ("releases", "List known releases."),
        ("rollback", "Switch to the previous successful release."),
    ):
        item = sub.add_parser(command, help=help_text)
        item.add_argument("project")

    deploy_parser = sub.add_parser("deploy", help="Deploy an uploaded artifact or source tree.")
    deploy_parser.add_argument("project")
    deploy_parser.add_argument("--release-id", required=True)

    logs_parser = sub.add_parser("logs", help="Show recent deployment logs.")
    logs_parser.add_argument("project")
    logs_parser.add_argument("--lines", type=int, default=100)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        validate_slug(args.project)
        config = load_config(args.project)
        logger = get_logger(args.project)
        if args.command == "init":
            init_project(config)
            print(f"Initialized {args.project} at {config.root}")
        elif args.command == "deploy":
            validate_release_id(args.release_id)
            deploy(config, args.release_id, logger)
            print(f"Deployment successful: {args.project} ({args.release_id})")
        elif args.command == "rollback":
            target = rollback(config, logger)
            print(f"Rollback successful: {args.project} -> {target}")
        elif args.command == "status":
            print(json.dumps(status(config), indent=2))
        elif args.command == "releases":
            print(json.dumps(list_releases(config), indent=2))
        elif args.command == "logs":
            if not 1 <= args.lines <= 2000:
                parser.error("--lines must be between 1 and 2000")
            print(read_logs(args.project, args.lines))
        return 0
    except (ConfigError, DeployError, RuntimeError, OSError, ValueError) as exc:
        print(f"deploy-manager: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
