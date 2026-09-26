from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "benchmarks" / "tasks.json"


def load_tasks() -> list[dict[str, Any]]:
    tasks = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if len(tasks) < 10:
        raise ValueError("benchmark manifest must contain at least ten tasks")
    ids = [task["id"] for task in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("benchmark task ids must be unique")
    return tasks


def prepare(task: dict[str, Any], destination: Path) -> Path:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    for relative, content in task["files"].items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _run(["git", "init", "-q"], destination)
    _run(["git", "config", "user.email", "benchmark@patchtrial.local"], destination)
    _run(["git", "config", "user.name", "PatchTrial Benchmark"], destination)
    _run(["git", "add", "."], destination)
    _run(["git", "commit", "-qm", "benchmark baseline"], destination)
    return destination


def add_hidden_tests(task: dict[str, Any], destination: Path) -> None:
    for relative, content in task["hidden_files"].items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def validate(tasks: list[dict[str, Any]]) -> dict[str, int]:
    checked = 0
    with tempfile.TemporaryDirectory(prefix="patchtrial-benchmarks-") as temp:
        root = Path(temp)
        for task in tasks:
            repository = prepare(task, root / task["id"])
            visible = _shell(task["test_command"], repository)
            if visible.returncode:
                raise RuntimeError(f"{task['id']}: visible tests do not pass\n{visible.stderr}")
            add_hidden_tests(task, repository)
            hidden = _shell(task["test_command"], repository)
            if hidden.returncode == 0:
                raise RuntimeError(f"{task['id']}: starter unexpectedly passes hidden tests")
            checked += 1
    return {"tasks": checked, "python": 5, "javascript": 5, "fault_families": 5}


def run_matrix(
    tasks: list[dict[str, Any]], output: Path, *, variant: str, limit: int | None
) -> int:
    if variant not in {"candidate-only", "patchtrial"}:
        raise ValueError("variant must be candidate-only or patchtrial")
    if not os.getenv("AI_API_KEY"):
        raise RuntimeError("AI_API_KEY is required for benchmark execution")
    selected = tasks[:limit] if limit else tasks
    output.mkdir(parents=True, exist_ok=True)
    provider = os.getenv("AI_PROVIDER", "openai-compatible")
    model = os.getenv("AI_MODEL", "unspecified")
    failures = 0
    with tempfile.TemporaryDirectory(prefix="patchtrial-matrix-") as temp:
        work = Path(temp)
        for index, task in enumerate(selected, 1):
            print(f"[{index}/{len(selected)}] {variant} · {provider}/{model} · {task['id']}")
            repository = prepare(task, work / task["id"])
            report = output / f"{task['id']}.json"
            env = os.environ.copy()
            env["PATCHTRIAL_STOP_AFTER_CANDIDATE"] = "1" if variant == "candidate-only" else "0"
            command = [
                sys.executable,
                "-m",
                "patchtrial.cli",
                "--repo",
                str(repository),
                "--task",
                task["task"],
                "--test-command",
                task["test_command"],
                "--report",
                str(report),
            ]
            completed = subprocess.run(command, cwd=ROOT, env=env, text=True)
            if not report.exists():
                failures += 1
                continue
            add_hidden_tests(task, repository)
            hidden = _shell(task["test_command"], repository)
            payload = json.loads(report.read_text(encoding="utf-8"))
            payload.update(
                {
                    "benchmark_task": task["id"],
                    "language": task["language"],
                    "fault_family": task["fault_family"],
                    "evaluation_variant": variant,
                    "hidden_tests_passed": hidden.returncode == 0,
                    "hidden_test_output": (hidden.stdout + "\n" + hidden.stderr)[-4000:],
                    "harness_exit_code": completed.returncode,
                }
            )
            report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            if hidden.returncode:
                failures += 1
    return failures


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if completed.returncode:
        raise RuntimeError(completed.stderr or "command failed: " + " ".join(args))
    return completed


def _shell(command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    import shlex

    args = shlex.split(command)
    if args and args[0] == "python":
        args[0] = sys.executable
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=60)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare and execute PatchTrial benchmarks")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    sub.add_parser("validate")
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("task")
    prepare_parser.add_argument("destination", type=Path)
    matrix = sub.add_parser("matrix")
    matrix.add_argument("--variant", choices=["candidate-only", "patchtrial"], required=True)
    matrix.add_argument("--output", type=Path, required=True)
    matrix.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    tasks = load_tasks()
    if args.command == "list":
        for task in tasks:
            print(f"{task['id']:<24} {task['language']:<10} {task['fault_family']}")
        return 0
    if args.command == "validate":
        result = validate(tasks)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "prepare":
        task = next((item for item in tasks if item["id"] == args.task), None)
        if task is None:
            parser.error(f"unknown task: {args.task}")
        prepare(task, args.destination)
        print(args.destination.resolve())
        return 0
    return 1 if run_matrix(tasks, args.output, variant=args.variant, limit=args.limit) else 0


if __name__ == "__main__":
    raise SystemExit(main())
