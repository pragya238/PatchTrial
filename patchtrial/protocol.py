from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class Action:
    name: str
    arguments: dict[str, Any]
    reason: str = ""


def parse_json_object(text: str) -> dict[str, Any]:
    """Extract the first balanced JSON object, tolerating markdown fences."""
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ProtocolError("model response did not contain a valid JSON object")


def parse_action(text: str, allowed_tools: set[str]) -> Action:
    payload = parse_json_object(text)
    raw_action = payload.get("action", payload)
    if not isinstance(raw_action, dict):
        raise ProtocolError("action must be an object")
    name = raw_action.get("name")
    arguments = raw_action.get("arguments", {})
    if not isinstance(name, str) or name not in allowed_tools:
        raise ProtocolError(f"unknown tool: {name!r}")
    if not isinstance(arguments, dict):
        raise ProtocolError("action arguments must be an object")
    reason = payload.get("reason", "")
    return Action(name=name, arguments=arguments, reason=str(reason))
