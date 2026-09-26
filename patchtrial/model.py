from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from typing import Any
from urllib import error, request

from .config import Config


# Current free routes with JSON-mode support, ordered for coding reliability.
# OpenRouter accepts one primary model plus at most three fallbacks.
OPENROUTER_FREE_FALLBACKS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
    "dots-studio/dots-3-note-preview:free",
    "google/gemma-4-26b-a4b-it:free",
]


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

    def complete(self, messages: list[dict[str, str]]) -> ModelResponse:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "stream": False,
        }
        if self.config.provider == "openrouter":
            # The free router may otherwise select a model that answers the tool
            # protocol in prose. Require a route that supports JSON mode.
            payload["response_format"] = {"type": "json_object"}
            payload["provider"] = {"require_parameters": True}
            if self.config.model == "openrouter/free":
                payload["model"] = OPENROUTER_FREE_FALLBACKS[0]
                payload["models"] = OPENROUTER_FREE_FALLBACKS[1:]
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
                detail = exc.read().decode("utf-8", errors="replace")[:2000]
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
