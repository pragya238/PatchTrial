from __future__ import annotations

from dataclasses import dataclass
import os


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    api_key: str
    base_url: str
    model: str
    provider: str = "openai-compatible"
    timeout_seconds: int = 120
    max_steps: int = 24
    max_counterfeits: int = 5
    command_timeout_seconds: int = 180
    max_output_chars: int = 16_000
    max_context_chars: int = 80_000
    temperature: float = 0.0

    @classmethod
    def from_env(cls, *, require_key: bool = True) -> "Config":
        api_key = os.getenv("AI_API_KEY", "")
        if require_key and not api_key:
            raise ConfigError("AI_API_KEY is required")

        base_url = os.getenv("AI_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
        model = os.getenv("AI_MODEL", "deepseek-chat")
        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            provider=os.getenv("AI_PROVIDER", "openai-compatible"),
            timeout_seconds=_env_int("PATCHTRIAL_API_TIMEOUT", 120),
            max_steps=_env_int("PATCHTRIAL_MAX_STEPS", 24),
            max_counterfeits=_env_int("PATCHTRIAL_MAX_COUNTERFEITS", 5),
            command_timeout_seconds=_env_int("PATCHTRIAL_COMMAND_TIMEOUT", 180),
            max_output_chars=_env_int("PATCHTRIAL_MAX_OUTPUT_CHARS", 16_000),
            max_context_chars=_env_int("PATCHTRIAL_CONTEXT_CHARS", 80_000),
            temperature=float(os.getenv("PATCHTRIAL_TEMPERATURE", "0")),
        )


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be positive")
    return value
