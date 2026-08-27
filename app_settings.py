"""Persisted app settings (LLM matching, etc.)."""

from __future__ import annotations

import sqlite3
from typing import Any

DEFAULTS = {
    "llm_enabled": "0",
    "llm_base_url": "https://api.openai.com/v1",
    "llm_api_key": "",
    "llm_model": "gpt-4o-mini",
}

PUBLIC_KEYS = ("llm_enabled", "llm_base_url", "llm_model")


def ensure_settings_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    for key, value in DEFAULTS.items():
        conn.execute(
            "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
            (key, value),
        )


def get_settings(conn: sqlite3.Connection) -> dict[str, str]:
    ensure_settings_table(conn)
    rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
    data = dict(DEFAULTS)
    for row in rows:
        if isinstance(row, sqlite3.Row):
            data[row["key"]] = row["value"]
        else:
            data[row[0]] = row[1]
    return data


def public_settings(settings: dict[str, str]) -> dict[str, Any]:
    key = (settings.get("llm_api_key") or "").strip()
    return {
        "llm_enabled": (settings.get("llm_enabled") or "0") == "1",
        "llm_base_url": settings.get("llm_base_url") or DEFAULTS["llm_base_url"],
        "llm_model": settings.get("llm_model") or DEFAULTS["llm_model"],
        "llm_api_key_set": bool(key),
    }


def update_settings(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, str]:
    ensure_settings_table(conn)
    current = get_settings(conn)

    if "llm_enabled" in payload:
        val = payload.get("llm_enabled")
        current["llm_enabled"] = "1" if val in (True, 1, "1", "true", "True") else "0"
    if "llm_base_url" in payload:
        url = str(payload.get("llm_base_url") or "").strip() or DEFAULTS["llm_base_url"]
        current["llm_base_url"] = url.rstrip("/")
    if "llm_model" in payload:
        current["llm_model"] = str(payload.get("llm_model") or "").strip() or DEFAULTS["llm_model"]
    if "llm_api_key" in payload:
        new_key = str(payload.get("llm_api_key") or "").strip()
        if new_key and not set(new_key) <= {"•", "*"}:
            current["llm_api_key"] = new_key

    for key in DEFAULTS:
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, current[key]),
        )
    return current
