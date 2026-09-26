from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from .config import Config, ConfigError
from .engine import PatchTrialEngine
from .model import ModelClient, ModelError
from .repository import Repository, RepositoryError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="patchtrial",
        description="Autonomous coding harness that challenges AI patches with counterfeits.",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path(os.getenv("TARGET_REPO", Path.cwd())),
        help="target Git repository (default: TARGET_REPO or current directory)",
    )
    task = parser.add_mutually_exclusive_group()
    task.add_argument("--task", help="software task or issue text")
    task.add_argument("--task-file", type=Path, help="file containing task or issue text")
    parser.add_argument(
        "--test-command",
        default=os.getenv("TEST_COMMAND"),
        help="final verification command (default: TEST_COMMAND or auto-detected)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(os.environ["PATCHTRIAL_REPORT"]) if os.getenv("PATCHTRIAL_REPORT") else None,
        help="proof report output path",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="validate configuration and show repository map"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        task = _read_task(args)
        config = Config.from_env(require_key=not args.dry_run)
        repository = Repository(
            args.repo,
            output_limit=config.max_output_chars,
            timeout=config.command_timeout_seconds,
        )
        test_command = args.test_command or repository.detect_test_command()
        report_path = args.report or (repository.root / "patchtrial-proof.json")

        print("PatchTrial")
        print(f"  repository: {repository.root}")
        print(f"  model:      {config.model}")
        print(f"  endpoint:   {config.base_url}")
        print(f"  tests:      {test_command}")

        if args.dry_run:
            print("\nRepository map:\n" + repository.list_files(limit=100))
            return 0

        engine = PatchTrialEngine(
            config,
            repository,
            ModelClient(config),
            test_command=test_command,
        )
        result = engine.run(task, report_path)
        print(result.report.summary())
        print(f"Proof report: {result.report_path}")
        return 0 if result.report.verdict == "ACCEPTED" else 2
    except (ConfigError, ModelError, RepositoryError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _read_task(args: argparse.Namespace) -> str:
    if args.task:
        return args.task.strip()
    if args.task_file:
        return args.task_file.read_text(encoding="utf-8").strip()
    if os.getenv("TASK_FILE"):
        return Path(os.environ["TASK_FILE"]).read_text(encoding="utf-8").strip()
    if os.getenv("TASK_TEXT"):
        return os.environ["TASK_TEXT"].strip()
    if not sys.stdin.isatty():
        value = sys.stdin.read().strip()
        if value:
            return value
    print("Paste the software task. Finish with Ctrl-D:")
    value = sys.stdin.read().strip()
    if not value:
        raise RepositoryError("a task is required")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
