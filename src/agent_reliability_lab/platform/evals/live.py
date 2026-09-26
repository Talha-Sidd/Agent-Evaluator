"""Bounded, local report artifacts for explicit live-model evaluation runs."""

import json
import os
from pathlib import Path
from typing import Any

from agent_reliability_lab.platform.security import sanitize

MAX_LIVE_REPORT_BYTES = 32 * 1024 * 1024


def save_live_report(report: dict[str, Any], path: Path) -> None:
    """Save a sanitized live report without overwriting prior evaluation evidence."""
    encoded = (json.dumps(sanitize(report), indent=2, sort_keys=True, allow_nan=False) + "\n")
    payload = encoded.encode("utf-8")
    if len(payload) > MAX_LIVE_REPORT_BYTES:
        raise ValueError("live evaluation report exceeds 32 MiB")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents races and accidental replacement of evidence.
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(encoded)
        output.flush()
        os.fsync(output.fileno())
