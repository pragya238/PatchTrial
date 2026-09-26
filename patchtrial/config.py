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
    min_valid_counterfeits: int = 3
    min_fault_categories: int = 2
    max_api_retries: int = 5
    command_timeout_seconds: int = 180
    max_output_chars: int = 16_000
    max_context_chars: int = 80_000
    temperature: float = 0.0
    stop_after_candidate: bool = False

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ConfigError("AI_MODEL is required")
        if not self.base_url.startswith("https://"):
            raise ConfigError("AI_BASE_URL must use HTTPS")
        if self.min_valid_counterfeits > self.max_counterfeits:
            raise ConfigError(
                "PATCHTRIAL_MIN_VALID_COUNTERFEITS cannot exceed PATCHTRIAL_MAX_COUNTERFEITS"
            )
        if self.min_fault_categories > self.min_valid_counterfeits:
            raise ConfigError(
                "PATCHTRIAL_MIN_FAULT_CATEGORIES cannot exceed the minimum valid counterfeits"
            )

    @classmethod
    def from_env(cls, *, require_key: bool = True) -> "Config":
        api_key = os.getenv("AI_API_KEY", "")
        if require_key and not api_key:
            raise ConfigError("AI_API_KEY is required")

        provider = os.getenv("AI_PROVIDER", "deepseek").strip().lower()
        presets = {
            "deepseek": ("https://api.deepseek.com", "deepseek-flash"),
            "qwen": (
                "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                "qwen3-coder-plus",
            ),
        }
        preset_url, preset_model = presets.get(
            provider, ("https://api.deepseek.com", "deepseek-flash")
        )
        base_url = os.getenv("AI_BASE_URL", preset_url).rstrip("/")
        model = os.getenv("AI_MODEL", preset_model)
        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            provider=provider,
            timeout_seconds=_env_int("PATCHTRIAL_API_TIMEOUT", 120),
            max_steps=_env_int("PATCHTRIAL_MAX_STEPS", 24),
            max_counterfeits=_env_int("PATCHTRIAL_MAX_COUNTERFEITS", 5),
            min_valid_counterfeits=_env_int("PATCHTRIAL_MIN_VALID_COUNTERFEITS", 3),
            min_fault_categories=_env_int("PATCHTRIAL_MIN_FAULT_CATEGORIES", 2),
            max_api_retries=_env_int("PATCHTRIAL_MAX_API_RETRIES", 5),
            command_timeout_seconds=_env_int("PATCHTRIAL_COMMAND_TIMEOUT", 180),
            max_output_chars=_env_int("PATCHTRIAL_MAX_OUTPUT_CHARS", 16_000),
            max_context_chars=_env_int("PATCHTRIAL_CONTEXT_CHARS", 80_000),
            temperature=float(os.getenv("PATCHTRIAL_TEMPERATURE", "0")),
            stop_after_candidate=_env_bool("PATCHTRIAL_STOP_AFTER_CANDIDATE", False),
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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean")
