from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from .config import Config
from .repository import Repository, RepositoryError


def inspect(repo_path: Path) -> dict:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str):
        checks.append({"name": name, "ok": ok, "detail": detail})

    add("Python", True, "Standard-library runtime available")
    add("Git", shutil.which("git") is not None, shutil.which("git") or "git not found")
    config = Config.from_env(require_key=False)
    add("API key", bool(config.api_key), "AI_API_KEY is set" if config.api_key else "AI_API_KEY is missing")
    add("Model", bool(config.model), config.model)
    add("Endpoint", config.base_url.startswith(("http://", "https://")), config.base_url)

    try:
        repository = Repository(repo_path)
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=repository.root,
            capture_output=True,
            text=True,
        ).returncode == 0
        add("Target repository", inside, str(repository.root))
        status = repository.status().strip() if inside else "not a Git repository"
        add("Clean baseline", inside and not status, status or "clean")
        try:
            command = repository.detect_test_command()
            add("Test command", True, command)
        except RepositoryError as exc:
            add("Test command", False, str(exc))
    except RepositoryError as exc:
        add("Target repository", False, str(exc))

    return {"ready": all(item["ok"] for item in checks), "checks": checks}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check PatchTrial evaluation readiness")
    parser.add_argument("--repo", type=Path, default=Path(os.getenv("TARGET_REPO", Path.cwd())))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = inspect(args.repo)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("PatchTrial preflight\n")
        for item in result["checks"]:
            print(f"  {'PASS' if item['ok'] else 'FAIL':4}  {item['name']}: {item['detail']}")
        print(f"\n{'READY' if result['ready'] else 'NOT READY'}")
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
