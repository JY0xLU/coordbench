from __future__ import annotations

import json
from typing import Any

from track_b_agent.constants import (
    AUDIT_BLACKLIST_SUBSTRINGS,
    DIAGNOSIS_INPUT_ALLOWLIST,
)


def audit_payload_allowlist(payload: dict[str, Any]) -> list[str]:
    """Return list of violations: keys not in allowlist."""
    bad = [k for k in payload if k not in DIAGNOSIS_INPUT_ALLOWLIST]
    return bad


def audit_payload_blacklist(text: str) -> list[str]:
    """Return matched blacklist substrings (case-insensitive for ASCII parts)."""
    lower = text.lower()
    hits: list[str] = []
    for sub in AUDIT_BLACKLIST_SUBSTRINGS:
        if sub.lower() in lower:
            hits.append(sub)
    # Chinese substrings
    for sub in ("大多数人类", "众数"):
        if sub in text:
            hits.append(sub)
    return list(dict.fromkeys(hits))


def audit_serialized_payload(obj: Any) -> tuple[list[str], list[str]]:
    """Allowlist (if dict) + blacklist on JSON string."""
    allow_violations: list[str] = []
    if isinstance(obj, dict):
        allow_violations = audit_payload_allowlist(obj)
    raw = json.dumps(obj, ensure_ascii=False, default=str)
    return allow_violations, audit_payload_blacklist(raw)


def audit_rendered_prompts(system: str, user: str) -> list[str]:
    """Blacklist scan on final prompt strings."""
    _, h1 = audit_serialized_payload(system)
    _, h2 = audit_serialized_payload(user)
    return list(dict.fromkeys(h1 + h2))
