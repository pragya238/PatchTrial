from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
import json


IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "dist", "build",
    "target", "coverage", ".next", ".cache", "__pycache__",
}

ALLOWED_COMMANDS = {
    "python", "python3", "pytest", "ruff", "mypy", "npm", "pnpm", "yarn",
    "node", "go", "cargo", "make", "gradle", "./gradlew", "mvn", "tox", "nox",
    "bun", "deno", "dotnet", "uv",
}


class RepositoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class Repository:
    def __init__(self, root: Path, *, output_limit: int = 16_000, timeout: int = 180):
        self.root = root.resolve()
        self.output_limit = output_limit
        self.timeout = timeout
        self.command_log: list[dict] = []
        if not self.root.is_dir():
            raise RepositoryError(f"repository does not exist: {self.root}")

    def _resolve(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if path != self.root and self.root not in path.parents:
            raise RepositoryError("path escapes repository root")
        return path

    def list_files(self, pattern: str = "*", limit: int = 400) -> str:
        found: list[str] = []
        for path in sorted(self.root.rglob("*")):
            if any(part in IGNORED_DIRS for part in path.relative_to(self.root).parts):
                continue
            if path.is_file():
                relative = path.relative_to(self.root).as_posix()
                if fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(path.name, pattern):
                    found.append(relative)
                    if len(found) >= limit:
                        found.append(f"... truncated at {limit} files")
                        break
        return "\n".join(found)

    def read_file(self, path: str, start_line: int = 1, end_line: int = 400) -> str:
        if start_line < 1 or end_line < start_line:
            raise RepositoryError("invalid line range")
        target = self._resolve(path)
        if not target.is_file():
            raise RepositoryError(f"file not found: {path}")
        data = target.read_text(encoding="utf-8", errors="replace").splitlines()
        selected = data[start_line - 1 : min(end_line, start_line + 799)]
        return "\n".join(f"{number:>5} | {line}" for number, line in enumerate(selected, start_line))

    def search_code(self, query: str, path: str = ".", limit: int = 100) -> str:
        if not query or len(query) > 300:
            raise RepositoryError("search query must contain 1-300 characters")
        target = self._resolve(path)
        args = ["git", "grep", "-n", "--no-color", "-F", query, "--"]
        if target != self.root:
            args.append(target.relative_to(self.root).as_posix())
        result = self._run(args, enforce_allowlist=False)
        lines = result.stdout.splitlines()[:limit]
        if result.returncode not in (0, 1):
            raise RepositoryError(result.stderr or "search failed")
        return "\n".join(lines) or "No matches"

    def apply_patch(self, patch: str, *, reverse: bool = False) -> CommandResult:
        patch = _normalize_patch(patch)
        if not patch or "diff --git" not in patch:
            raise RepositoryError("patch must be a non-empty git unified diff")
        with tempfile.NamedTemporaryFile("w", suffix=".patch", encoding="utf-8") as handle:
            handle.write(patch)
            handle.flush()
            check = ["git", "apply", "--check", "--recount"]
            apply = ["git", "apply", "--recount", "--whitespace=nowarn"]
            if reverse:
                check.append("--reverse")
                apply.append("--reverse")
            check.append(handle.name)
            apply.append(handle.name)
            checked = self._run(check, enforce_allowlist=False)
            if not checked.ok:
                return checked
            return self._run(apply, enforce_allowlist=False)

    def replace_text(self, path: str, old: str, new: str) -> str:
        if not old:
            raise RepositoryError("old text must not be empty")
        if old == new:
            raise RepositoryError("old and new text are identical")
        target = self._resolve(path)
        if not target.is_file():
            raise RepositoryError(f"file not found: {path}")
        content = target.read_text(encoding="utf-8")
        count = content.count(old)
        if count != 1:
            raise RepositoryError(
                f"old text must match exactly once in {path}; found {count} matches. "
                "Re-read the file and use a larger exact snippet."
            )
        target.write_text(content.replace(old, new, 1), encoding="utf-8")
        return f"Replaced one exact occurrence in {path}"

    def create_file(self, path: str, content: str) -> str:
        target = self._resolve(path)
        if target.exists():
            raise RepositoryError(f"file already exists: {path}; use replace_text")
        if "\x00" in content:
            raise RepositoryError("binary file content is not supported")
        if len(content) > 1_000_000:
            raise RepositoryError("new file exceeds 1,000,000 characters")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Created {path} ({len(content)} characters)"

    def restore_clean(self) -> str:
        current = self.diff()
        if current.strip():
            restored = self.apply_patch(current, reverse=True)
            if not restored.ok:
                raise RepositoryError(restored.stderr or "could not restore clean baseline")
        remaining = self.status().strip()
        if remaining:
            raise RepositoryError(f"repository restoration left changes:\n{remaining}")
        return "Repository restored to its clean starting state"

    def diff(self) -> str:
        result = self._run(["git", "diff", "--no-ext-diff", "--binary"], enforce_allowlist=False)
        if not result.ok:
            raise RepositoryError(result.stderr or "could not inspect diff")
        parts = [result.stdout]
        untracked = self._run(
            ["git", "ls-files", "--others", "--exclude-standard"], enforce_allowlist=False
        )
        if not untracked.ok:
            raise RepositoryError(untracked.stderr or "could not inspect untracked files")
        for relative in untracked.stdout.splitlines():
            if any(part in IGNORED_DIRS for part in Path(relative).parts):
                continue
            target = self._resolve(relative)
            if not target.is_file():
                continue
            added = self._run(
                ["git", "diff", "--no-index", "--binary", "--", "/dev/null", relative],
                enforce_allowlist=False,
            )
            if added.returncode not in (0, 1):
                raise RepositoryError(added.stderr or f"could not diff {relative}")
            parts.append(added.stdout)
        return "".join(parts)

    def status(self) -> str:
        return self._run(["git", "status", "--short"], enforce_allowlist=False).stdout

    def head_commit(self) -> str:
        result = self._run(["git", "rev-parse", "HEAD"], enforce_allowlist=False)
        if not result.ok:
            raise RepositoryError(result.stderr or "could not read baseline commit")
        return result.stdout.strip()

    def run_command(self, command: str) -> CommandResult:
        try:
            args = shlex.split(command)
        except ValueError as exc:
            raise RepositoryError(f"invalid command: {exc}") from exc
        if not args:
            raise RepositoryError("empty command")
        if args[0] == "python":
            args[0] = sys.executable
        return self._run(args, enforce_allowlist=True)

    def detect_test_command(self) -> str:
        pyproject = self.root / "pyproject.toml"
        if pyproject.exists():
            content = pyproject.read_text(encoding="utf-8", errors="replace").lower()
            if "pytest" in content or (self.root / "pytest.ini").exists() or (self.root / "conftest.py").exists():
                return "python -m pytest -q"
            if (self.root / "tests").exists():
                return "python -m unittest discover -s tests -v"
        package = self.root / "package.json"
        if package.exists():
            try:
                scripts = json.loads(package.read_text(encoding="utf-8")).get("scripts", {})
            except (json.JSONDecodeError, OSError):
                scripts = {}
            if scripts.get("test"):
                if (self.root / "pnpm-lock.yaml").exists():
                    return "pnpm test"
                if (self.root / "yarn.lock").exists():
                    return "yarn test"
                if (self.root / "bun.lockb").exists() or (self.root / "bun.lock").exists():
                    return "bun test"
                return "npm test"
        candidates = [
            ("pytest.ini", "python -m pytest -q"),
            ("tox.ini", "tox"),
            ("noxfile.py", "nox"),
            ("go.mod", "go test ./..."),
            ("Cargo.toml", "cargo test"),
            ("pom.xml", "mvn test"),
            ("build.gradle", "./gradlew test"),
            ("Makefile", "make test"),
        ]
        for filename, command in candidates:
            if (self.root / filename).exists():
                return command
        raise RepositoryError("could not detect a test command; provide one with --test-command")

    def _run(self, args: list[str], *, enforce_allowlist: bool) -> CommandResult:
        executable = args[0]
        allowed_name = "python" if executable == sys.executable else executable
        if enforce_allowlist and allowed_name not in ALLOWED_COMMANDS:
            if not executable.startswith("./"):
                raise RepositoryError(f"command is not allowlisted: {executable}")
            local_executable = self._resolve(executable)
            if not local_executable.is_file() or not os.access(local_executable, os.X_OK):
                raise RepositoryError(f"local command is not executable: {executable}")
        environment = os.environ.copy()
        environment.pop("AI_API_KEY", None)
        started = time.monotonic()
        try:
            completed = subprocess.run(
                args,
                cwd=self.root,
                text=True,
                capture_output=True,
                timeout=self.timeout,
                env=environment,
            )
            stdout = _truncate(completed.stdout, self.output_limit)
            stderr = _truncate(completed.stderr, self.output_limit)
            result = CommandResult(
                shlex.join(args), completed.returncode, stdout, stderr,
                round(time.monotonic() - started, 4),
            )
            if enforce_allowlist:
                self.command_log.append({
                    "command": result.command,
                    "returncode": result.returncode,
                    "duration_seconds": result.duration_seconds,
                    "stdout_tail": result.stdout[-2000:],
                    "stderr_tail": result.stderr[-2000:],
                })
            return result
        except subprocess.TimeoutExpired as exc:
            stdout = _truncate(_as_text(exc.stdout), self.output_limit)
            stderr = _truncate(_as_text(exc.stderr), self.output_limit)
            result = CommandResult(
                shlex.join(args), 124, stdout, f"{stderr}\nCommand timed out",
                round(time.monotonic() - started, 4),
            )
            if enforce_allowlist:
                self.command_log.append({
                    "command": result.command,
                    "returncode": 124,
                    "duration_seconds": result.duration_seconds,
                    "stdout_tail": result.stdout[-2000:],
                    "stderr_tail": result.stderr[-2000:],
                })
            return result


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    half = max(1, limit // 2)
    return f"{value[:half]}\n... output truncated ...\n{value[-half:]}"


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _normalize_patch(value: str) -> str:
    patch = value.strip()
    start = patch.find("diff --git ")
    if start < 0:
        return patch
    patch = patch[start:]
    if patch.endswith("```"):
        patch = patch[:-3].rstrip()
    return patch + "\n"
