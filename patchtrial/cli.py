from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlparse

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
        default=os.getenv("TARGET_REPO"),
        help="target Git repository path or HTTPS Git URL (default: TARGET_REPO)",
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
    repository: Repository | None = None
    try:
        task = _read_task(args)
        config = Config.from_env(require_key=not args.dry_run)
        repo_path, cloned = _resolve_repository(args.repo)
        repository = Repository(
            repo_path,
            output_limit=config.max_output_chars,
            timeout=config.command_timeout_seconds,
        )
        test_command = args.test_command or repository.detect_test_command()
        report_path = args.report or _default_report_path(repository.root)

        print("PatchTrial")
        print(f"  repository: {repository.root}")
        print(f"  model:      {config.model}")
        print(f"  endpoint:   {config.base_url}")
        print(f"  tests:      {test_command}")
        if cloned:
            print(f"  workspace:  {repository.root} (cloned from {args.repo})")

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
        if result.report.verdict != "ACCEPTED":
            repository.restore_clean()
            print("Repository restored because the evidence was not sufficient for acceptance.")
        print(result.report.summary())
        print(f"Proof report: {result.report_path}")
        return 0 if result.report.verdict in {"ACCEPTED", "BASELINE_CANDIDATE_PASSED"} else 2
    except (ConfigError, ModelError, RepositoryError, OSError) as exc:
        if repository is not None and repository.status().strip():
            try:
                repository.restore_clean()
            except RepositoryError as restore_exc:
                print(f"WARNING: automatic restoration failed: {restore_exc}", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _resolve_repository(value: str | None) -> tuple[Path, bool]:
    if not value:
        if sys.stdin.isatty():
            value = input("Target repository path or HTTPS Git URL: ").strip()
        if not value:
            raise RepositoryError(
                "target repository is required; set TARGET_REPO or pass --repo PATH_OR_URL"
            )
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        if parsed.scheme != "https" or not parsed.netloc:
            raise RepositoryError("remote repositories must use a valid HTTPS URL")
        workspace = Path(tempfile.mkdtemp(prefix="patchtrial-target-")) / "repository"
        completed = subprocess.run(
            ["git", "clone", "--depth", "1", value, str(workspace)],
            text=True,
            capture_output=True,
            timeout=180,
        )
        if completed.returncode:
            raise RepositoryError(completed.stderr or "could not clone target repository")
        return workspace, True
    return Path(value).expanduser(), False


def _default_report_path(repository: Path) -> Path:
    root = Path(tempfile.gettempdir()) / "patchtrial-proofs"
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return root / f"{repository.name}-{timestamp}.json"


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
