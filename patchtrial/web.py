from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import tempfile
import time
import uuid
from urllib.parse import urlparse

from .config import Config, ConfigError
from .engine import PatchTrialEngine
from .model import ModelClient, ModelError
from .repository import Repository, RepositoryError


SUPPORTED_PROVIDERS = {
    "deepseek",
    "qwen",
    "openrouter",
    "groq",
    "gemini",
    "custom",
}


@dataclass
class Job:
    id: str
    status: str = "queued"
    events: list[str] = field(default_factory=list)
    result: dict | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)

    def public(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "events": list(self.events),
            "result": self.result,
            "error": self.error,
        }


class JobStore:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.runtime_config: Config | None = None

    def configure(self, payload: dict) -> Config:
        api_key = str(payload.get("api_key", "")).strip()
        base_url = str(payload.get("base_url", "")).strip().rstrip("/")
        model = str(payload.get("model", "")).strip()
        provider = str(payload.get("provider", "custom")).strip().lower()
        if not api_key or not base_url or not model:
            raise ValueError("API key, base URL, and model are required")
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError("Unsupported model provider")
        if provider == "openrouter" and not api_key.startswith("sk-or-"):
            raise ValueError(
                "OpenRouter keys begin with 'sk-or-'. Create and copy a key from "
                "OpenRouter; do not reuse a Gemini or DeepSeek key."
            )
        if not base_url.startswith("https://"):
            raise ValueError("Base URL must use HTTPS")
        self.runtime_config = Config(
            api_key=api_key,
            base_url=base_url,
            model=model,
            provider=provider,
        )
        return self.runtime_config

    def config(self, *, require_key: bool = True) -> Config:
        return self.runtime_config or Config.from_env(require_key=require_key)

    def create(self, payload: dict) -> Job:
        repo = str(payload.get("repo", "")).strip()
        task = str(payload.get("task", "")).strip()
        if not repo or not task:
            raise ValueError("Repository path and task are required")
        job = Job(id=uuid.uuid4().hex[:12])
        with self.lock:
            self.jobs[job.id] = job
        thread = threading.Thread(target=self._run, args=(job, payload), daemon=True)
        thread.start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self.lock:
            return self.jobs.get(job_id)

    def _run(self, job: Job, payload: dict) -> None:
        job.status = "running"
        repository: Repository | None = None
        try:
            config = self.config()
            repository = Repository(
                Path(str(payload["repo"])),
                output_limit=config.max_output_chars,
                timeout=config.command_timeout_seconds,
            )
            test_command = str(payload.get("test_command", "")).strip()
            if not test_command:
                test_command = repository.detect_test_command()
            report_dir = Path(tempfile.gettempdir()) / "patchtrial-proofs"
            report_dir.mkdir(parents=True, exist_ok=True)
            report_path = report_dir / f"{job.id}.json"
            engine = PatchTrialEngine(
                config,
                repository,
                ModelClient(config),
                test_command=test_command,
                event=job.events.append,
            )
            run = engine.run(str(payload["task"]).strip(), report_path)
            proof = json.loads(report_path.read_text(encoding="utf-8"))
            restored = False
            if run.report.verdict != "ACCEPTED":
                repository.restore_clean()
                restored = True
            job.result = {
                "proof": proof,
                "diff": run.candidate_diff,
                "report_path": str(report_path),
                "repository_restored": restored,
            }
            job.status = "complete"
        except (ConfigError, ModelError, RepositoryError, OSError, ValueError) as exc:
            restoration = ""
            if repository is not None:
                try:
                    restoration = "; repository restored to its clean starting state"
                    repository.restore_clean()
                except RepositoryError as restore_exc:
                    restoration = f"; WARNING: automatic restoration failed: {restore_exc}"
            job.error = str(exc) + restoration
            job.status = "failed"


class DashboardHandler(SimpleHTTPRequestHandler):
    store: JobStore

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            config = self.store.config(require_key=False)
            self._json(200, {
                "ready": bool(config.api_key),
                "provider": config.provider,
                "model": config.model,
                "base_url": config.base_url,
                "message": "Ready for live runs" if config.api_key else "Configure a model to enable live runs",
            })
            return
        if parsed.path.startswith("/api/jobs/"):
            job = self.store.get(parsed.path.rsplit("/", 1)[-1])
            self._json(200, job.public()) if job else self._json(404, {"error": "Job not found"})
            return
        super().do_GET()

    def do_POST(self):
        route = urlparse(self.path).path
        if route not in {"/api/jobs", "/api/config"}:
            self._json(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise ValueError("Invalid request size")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Request body must be an object")
            if route == "/api/config":
                config = self.store.configure(payload)
                self._json(200, {
                    "ready": True,
                    "provider": config.provider,
                    "model": config.model,
                    "base_url": config.base_url,
                })
            else:
                job = self.store.create(payload)
                self._json(202, job.public())
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})

    def _json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local PatchTrial dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    static = Path(__file__).resolve().parent.parent / "dashboard" / "dist"
    handler = lambda *hargs, **kwargs: DashboardHandler(*hargs, directory=str(static), **kwargs)
    DashboardHandler.store = JobStore()
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"PatchTrial dashboard: http://{args.host}:{args.port}")
    print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
