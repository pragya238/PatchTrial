from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile


IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "dist", "build",
    "target", "coverage", ".next", ".cache", "__pycache__",
}

ALLOWED_COMMANDS = {
    "python", "python3", "pytest", "ruff", "mypy", "npm", "pnpm", "yarn",
    "node", "go", "cargo", "make", "gradle", "./gradlew", "mvn",
}


class RepositoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class Repository:
    def __init__(self, root: Path, *, output_limit: int = 16_000, timeout: int = 180):
        self.root = root.resolve()
        self.output_limit = output_limit
        self.timeout = timeout
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
        if not patch.strip() or "diff --git" not in patch:
            raise RepositoryError("patch must be a non-empty git unified diff")
        with tempfile.NamedTemporaryFile("w", suffix=".patch", encoding="utf-8") as handle:
            handle.write(patch)
            handle.flush()
            check = ["git", "apply", "--check"]
            apply = ["git", "apply", "--whitespace=nowarn"]
            if reverse:
                check.append("--reverse")
                apply.append("--reverse")
            check.append(handle.name)
            apply.append(handle.name)
            checked = self._run(check, enforce_allowlist=False)
            if not checked.ok:
                return checked
            return self._run(apply, enforce_allowlist=False)

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
        candidates = [
            ("pyproject.toml", "python -m unittest discover -v"),
            ("pytest.ini", "pytest -q"),
            ("package.json", "npm test -- --runInBand"),
            ("go.mod", "go test ./..."),
            ("Cargo.toml", "cargo test"),
            ("pom.xml", "mvn test"),
            ("build.gradle", "./gradlew test"),
            ("Makefile", "make test"),
        ]
        for filename, command in candidates:
            if (self.root / filename).exists():
                if filename == "pyproject.toml" and (self.root / "tests").exists():
                    return "python -m unittest discover -s tests -v"
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
            return CommandResult(shlex.join(args), completed.returncode, stdout, stderr)
        except subprocess.TimeoutExpired as exc:
            stdout = _truncate(_as_text(exc.stdout), self.output_limit)
            stderr = _truncate(_as_text(exc.stderr), self.output_limit)
            return CommandResult(shlex.join(args), 124, stdout, f"{stderr}\nCommand timed out")


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
