from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from typing import Any
from urllib import error, request

from .config import Config


OPENROUTER_FREE_ALIAS = "openrouter/free"


class ModelError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelResponse:
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ModelClient:
    """Minimal OpenAI-compatible client usable with DeepSeek and Qwen gateways."""

    def __init__(self, config: Config):
        self.config = config
        self._openrouter_routes: list[str] | None = None
        self._model_catalog: list[dict[str, Any]] | None = None

    def list_models(self) -> list[dict[str, Any]]:
        if self._model_catalog is not None:
            return self._model_catalog
        endpoint = _model_discovery_endpoint(self.config)
        req = request.Request(
            endpoint,
            method="GET",
            headers={"Authorization": f"Bearer {self.config.api_key}"},
        )
        try:
            with request.urlopen(req, timeout=min(self.config.timeout_seconds, 30)) as response:
                result = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = _redact_secret(
                exc.read().decode("utf-8", errors="replace")[:2000],
                self.config.api_key,
            )
            raise ModelError(f"model discovery returned HTTP {exc.code}: {detail}") from exc
        except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ModelError(f"model discovery failed: {exc}") from exc
        models = result.get("data")
        if not isinstance(models, list):
            qwen_models = (result.get("output") or {}).get("models")
            if isinstance(qwen_models, list):
                models = [
                    {
                        **item,
                        "id": item.get("model"),
                        "supported_parameters": [
                            "response_format"
                            for feature in (item.get("features") or [])
                            if feature == "structured-outputs"
                        ],
                    }
                    for item in qwen_models
                    if isinstance(item, dict)
                ]
        if not isinstance(models, list):
            raise ModelError("model discovery returned an invalid response")
        self._model_catalog = [
            item for item in models if isinstance(item, dict) and item.get("id")
        ]
        return self._model_catalog

    def _discover_openrouter_free_routes(self) -> list[str]:
        if self._openrouter_routes is not None:
            return self._openrouter_routes
        free: list[tuple[bool, int, str]] = []
        for item in self.list_models():
            pricing = item.get("pricing") or {}
            try:
                is_free = float(pricing.get("prompt", 1)) == 0 and float(
                    pricing.get("completion", 1)
                ) == 0
            except (TypeError, ValueError):
                is_free = False
            output = ((item.get("architecture") or {}).get("output_modalities") or [])
            if not is_free or (output and "text" not in output):
                continue
            supported = item.get("supported_parameters") or []
            free.append(
                (
                    "response_format" in supported,
                    int(item.get("context_length") or 0),
                    str(item["id"]),
                )
            )
        free.sort(reverse=True)
        self._openrouter_routes = [model_id for _, _, model_id in free[:4]]
        if not self._openrouter_routes:
            raise ModelError(
                "OpenRouter reported no currently available free text models. "
                "Choose a specific model or try again after its catalog updates."
            )
        return self._openrouter_routes

    def complete(self, messages: list[dict[str, str]]) -> ModelResponse:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "stream": False,
        }
        if self.config.provider == "openrouter":
            if self.config.model == OPENROUTER_FREE_ALIAS:
                routes = self._discover_openrouter_free_routes()
                payload["model"] = routes[0]
                payload["models"] = routes[1:]
            # JSON mode is requested only when every selected route advertises
            # support. This avoids excluding an otherwise healthy fallback.
            selected = [payload["model"], *(payload.get("models") or [])]
            catalog = {str(item["id"]): item for item in self.list_models()}
            if selected and all(
                "response_format" in (catalog.get(model_id, {}).get("supported_parameters") or [])
                for model_id in selected
            ):
                payload["response_format"] = {"type": "json_object"}
                payload["provider"] = {"require_parameters": True}
        body = json.dumps(payload).encode("utf-8")
        endpoint = f"{self.config.base_url}/chat/completions"
        req = request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
        )

        last_error: Exception | None = None
        for attempt in range(self.config.max_api_retries):
            try:
                with request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                    result = json.loads(response.read().decode("utf-8"))
                choice = result["choices"][0]["message"]
                content = choice.get("content") or ""
                usage = result.get("usage") or {}
                return ModelResponse(
                    content=content,
                    prompt_tokens=int(usage.get("prompt_tokens", 0)),
                    completion_tokens=int(usage.get("completion_tokens", 0)),
                )
            except error.HTTPError as exc:
                detail = _redact_secret(
                    exc.read().decode("utf-8", errors="replace")[:2000],
                    self.config.api_key,
                )
                last_error = ModelError(f"model API returned HTTP {exc.code}: {detail}")
                if exc.code < 500 and exc.code != 429:
                    break
                delay = _retry_delay(exc, detail, attempt)
            except (error.URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError) as exc:
                last_error = exc
                delay = min(16, 2**attempt)
            if attempt < self.config.max_api_retries - 1:
                time.sleep(delay)
        raise ModelError(f"model request failed after retries: {last_error}")


def _retry_delay(exc: error.HTTPError, detail: str, attempt: int) -> float:
    header = exc.headers.get("Retry-After") if exc.headers else None
    if header:
        try:
            return min(60.0, max(0.0, float(header)))
        except ValueError:
            pass
    match = re.search(r'"retry_after_seconds(?:_raw)?"\s*:\s*(\d+(?:\.\d+)?)', detail)
    if match:
        return min(60.0, float(match.group(1)))
    return min(16.0, float(2**attempt))


def _model_discovery_endpoint(config: Config) -> str:
    if config.provider == "qwen" and "/compatible-mode/v1" in config.base_url:
        native_base = config.base_url.replace("/compatible-mode/v1", "/api/v1")
        return f"{native_base}/models?providers=qwen&capabilities=TG&page_size=100"
    return f"{config.base_url}/models"


def _redact_secret(value: str, secret: str) -> str:
    if not secret:
        return value
    return value.replace(secret, "[REDACTED]")
