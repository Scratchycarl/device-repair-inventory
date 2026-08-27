"""Normalize parts_needed JSON between legacy strings and structured objects."""

from __future__ import annotations

import json
from typing import Any


def parse_parts(raw: str | list | None) -> list[dict[str, Any]]:
    """Return [{name, needs_programming}, ...] from DB JSON or API payload."""
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            data = json.loads(raw or "[]")
        except json.JSONDecodeError:
            return []
    else:
        data = raw

    if not isinstance(data, list):
        return []

    parts: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, str):
            name = item.strip()
            if name:
                parts.append({"name": name, "needs_programming": False})
        elif isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            parts.append(
                {
                    "name": name,
                    "needs_programming": bool(item.get("needs_programming")),
                }
            )
    return parts


def serialize_parts(parts: list) -> str:
    """Persist parts as JSON objects."""
    normalized = parse_parts(parts)
    return json.dumps(normalized)


def part_names(parts: list) -> list[str]:
    return [p["name"] for p in parse_parts(parts)]
