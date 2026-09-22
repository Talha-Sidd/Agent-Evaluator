"""Sanitized evidence and explicit synthetic-only replay exports."""

import hashlib
import json
import re
from typing import Any

from agent_reliability_lab.domain.models import AgentResult, Scenario

_SECRET_KEY = re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|authorization)")
_SECRET_TEXT = re.compile(
    r"(?i)((?:password|passwd|secret|token|api[_-]?key|authorization)\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)|"
    r"\b(?:sk-[\w-]{16,}|ghp_[\w]{20,}|AKIA[A-Z0-9]{16})\b|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*"
)


def sensitive_path(path: str) -> bool:
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return (
        name == ".env"
        or name.startswith(".env.")
        or name.endswith((".pem", ".key", ".p12"))
        or name in {"id_rsa", "id_ed25519", "credentials"}
    )


def fingerprint(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            _SECRET_TEXT.sub("[REDACTED]", str(key)): (
                (
                    item
                    if isinstance(item, dict)
                    and set(item) == {"fixture_sha256"}
                    and isinstance(item["fixture_sha256"], str)
                    and re.fullmatch(r"[0-9a-f]{64}", item["fixture_sha256"])
                    else {"fixture_sha256": fingerprint(item)}
                )
                if key == "repository_files"
                else "[REDACTED]"
                if _SECRET_KEY.search(str(key)) or sensitive_path(str(key))
                else sanitize(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return "[REDACTED]" if sensitive_path(value) else _SECRET_TEXT.sub("[REDACTED]", value)
    return value


def public_result(result: AgentResult) -> AgentResult:
    """Do not expose free-form agent text or raw arguments through the API."""
    value = result.model_dump(mode="json")
    value["final_answer"] = f"Run {result.status.value}."
    for call in value["tool_calls"]:
        call["arguments"] = {}
    for event in value["trace"]:
        event["detail"] = None
    return AgentResult.model_validate(sanitize(value))


def require_safe_replay(scenario: Scenario) -> None:
    if not scenario.replay_safe:
        raise ValueError("replay export requires an explicitly synthetic replay_safe fixture")
    value = scenario.model_dump(mode="json")
    if any(sensitive_path(path) for path in scenario.repository_files):
        raise ValueError("sensitive files cannot be exported as replay fixtures")
    # Include corpus contents here; sanitize normally replaces them with a digest.
    value.pop("repository_files")
    if sanitize(value) != value or any(
        sanitize(path) != path or sanitize(content) != content
        for path, content in scenario.repository_files.items()
    ):
        raise ValueError("sensitive text cannot be exported as a replay fixture")
