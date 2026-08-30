"""Classify Taobao purchase lines with an OpenAI-compatible LLM.

Each purchase item (Chinese listing title + SKU text) is classified into:
  - category: is this a repair part, a service, a tool, or a personal purchase?
  - part_type: normalized part vocabulary used for job matching
  - models: which device models the part fits (expanded from the SKU text)

Results are cached per (item_title, sku_text) so re-imports and repeat
purchases never re-hit the API. There is deliberately no keyword fallback:
unclassified items stay 'unknown' and are handled manually in the review UI.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import requests

DEFAULT_TIMEOUT = 120
BATCH_SIZE = 25

CATEGORIES = {"part", "service", "tool", "accessory", "personal", "unknown"}

PART_TYPES = {
    "battery",
    "screen",
    "back",
    "camera",
    "camera_glass",
    "charging_port",
    "speaker",
    "earpiece",
    "microphone",
    "button",
    "flex_cable",
    "housing",
    "logic_board",
    "antenna",
    "face_id",
    "other",
}

SYSTEM_PROMPT = """You classify Taobao purchase order lines for a phone/tablet repair shop.
Each line has a listing title (商品名称) and a variant/SKU (型号款式), usually in Chinese.

For EACH input item return a JSON object with:
- "id": the same id you were given (integer, copy it exactly)
- "category": one of "part" (a repair part/component for a device), "service" (paid service like serial lookup, unlock, remote repair - not a physical part), "tool" (repair tools, glue, screwdrivers, machines), "accessory" (cases, cables, chargers sold as consumer accessories), "personal" (clearly a personal/household purchase unrelated to device repair), "unknown" (cannot tell)
- "part_type": only when category is "part"; one of: battery, screen, back (back glass/cover/housing), camera, camera_glass, charging_port, speaker, earpiece, microphone, button, flex_cable, housing, logic_board, antenna, face_id, other. Otherwise null.
- "models": list of specific device models this line is for, in standard English naming, e.g. ["iPhone 6 Plus"], ["iPhone 13 Pro Max"], ["iPad Air 1"], ["iPad mini 2"]. Derive the model from the SKU/variant text first (it is usually the specific model bought, e.g. "6P标容全新电池" means iPhone 6 Plus battery); the title often lists many compatible models but the SKU tells which one was actually purchased. Chinese shorthand: 6P/6SP/7P/8P = Plus models, X/XR/XS/XSM, 11/12/13/14/15 promax = Pro Max, mini, 苹果 = Apple/iPhone. Empty list if not model-specific or not a part.
- "confidence": 0.0-1.0 how confident you are in category+part_type+models
- "notes": very short English note, e.g. what the item actually is

Rules:
- Serial number / IMEI lookup, iCloud checks, activation and unlock services are "service".
- Screen protectors, cases, charging cables for daily use are "accessory".
- Battery adhesive, waterproof glue, screwdriver kits are "tool" (even when bundled free with a part, classify by the main purchased item).
- If the SKU indicates a specific model variant of a multi-model listing, models must contain exactly that one model.
- Reply with a JSON object: {"items": [ ... one object per input item ... ]}."""


# ---- Settings ----

SETTING_KEYS = ("llm_base_url", "llm_api_key", "llm_model")


def get_llm_settings(conn):
    rows = conn.execute(
        f"SELECT key, value FROM app_settings WHERE key IN ({','.join('?' * len(SETTING_KEYS))})",
        SETTING_KEYS,
    ).fetchall()
    settings = {k: "" for k in SETTING_KEYS}
    for row in rows:
        settings[row["key"]] = row["value"] or ""
    return settings


def save_llm_settings(conn, data):
    for key in SETTING_KEYS:
        if key in data:
            conn.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(data[key] or "").strip()),
            )
    conn.commit()


def llm_configured(settings):
    return bool(settings.get("llm_base_url") and settings.get("llm_model"))


# ---- API plumbing ----

def _chat_completion(settings, messages, timeout=DEFAULT_TIMEOUT):
    base = settings["llm_base_url"].rstrip("/")
    url = f"{base}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if settings.get("llm_api_key"):
        headers["Authorization"] = f"Bearer {settings['llm_api_key']}"
    payload = {
        "model": settings["llm_model"],
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def test_llm_connection(settings):
    """Returns (ok, message)."""
    if not llm_configured(settings):
        return False, "Base URL and model are required"
    try:
        content = _chat_completion(
            settings,
            [
                {"role": "system", "content": "Reply with a JSON object."},
                {"role": "user", "content": 'Reply exactly with {"ok": true}'},
            ],
            timeout=30,
        )
        json.loads(content)
        return True, "Connection OK"
    except requests.HTTPError as exc:
        body = exc.response.text[:300] if exc.response is not None else str(exc)
        return False, f"HTTP {exc.response.status_code if exc.response is not None else '?'}: {body}"
    except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
        return False, str(exc)


# ---- Classification ----

def _cache_key(item_title, sku_text):
    raw = f"{item_title}\n{sku_text}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _sanitize_result(raw):
    """Validate/normalize one LLM result object."""
    category = str(raw.get("category") or "unknown").strip().lower()
    if category not in CATEGORIES:
        category = "unknown"
    part_type = raw.get("part_type")
    if part_type is not None:
        part_type = str(part_type).strip().lower() or None
    if category != "part":
        part_type = None
    elif part_type not in PART_TYPES:
        part_type = "other"
    models = raw.get("models") or []
    if not isinstance(models, list):
        models = []
    models = [str(m).strip() for m in models if str(m).strip()]
    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0.0
    notes = str(raw.get("notes") or "").strip()
    return {
        "category": category,
        "part_type": part_type,
        "models": models,
        "confidence": confidence,
        "notes": notes,
    }


def _classify_batch(settings, batch):
    """batch: list of dicts with local_id, item_title, sku_text. Returns {local_id: result}."""
    payload = [
        {"id": item["local_id"], "title": item["item_title"], "sku": item["sku_text"]}
        for item in batch
    ]
    content = _chat_completion(
        settings,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({"items": payload}, ensure_ascii=False)},
        ],
    )
    parsed = json.loads(content)
    results = {}
    items = parsed.get("items") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        raise ValueError(f"LLM returned unexpected structure: {content[:200]}")
    for obj in items:
        if not isinstance(obj, dict):
            continue
        try:
            local_id = int(obj.get("id"))
        except (TypeError, ValueError):
            continue
        results[local_id] = _sanitize_result(obj)
    return results


def classify_items(conn, item_ids=None):
    """Classify purchase items via cache + LLM.

    Targets items still 'unknown' that were never manually classified
    (or the explicit item_ids). Returns a summary dict.
    """
    settings = get_llm_settings(conn)

    if item_ids:
        marks = ",".join("?" * len(item_ids))
        rows = conn.execute(
            f"SELECT id, item_title, sku_text FROM purchase_items WHERE id IN ({marks})",
            list(item_ids),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, item_title, sku_text FROM purchase_items "
            "WHERE category = 'unknown' AND (classified_by IS NULL OR classified_by = 'llm')"
        ).fetchall()

    items = [dict(r) for r in rows]
    summary = {"total": len(items), "from_cache": 0, "from_llm": 0, "failed": 0, "error": None}
    if not items:
        return summary

    now = datetime.now(timezone.utc).isoformat()
    to_classify = []
    for item in items:
        key = _cache_key(item["item_title"], item["sku_text"])
        item["cache_key"] = key
        cached = conn.execute(
            "SELECT result FROM llm_classify_cache WHERE cache_key = ?", (key,)
        ).fetchone()
        if cached:
            _apply_result(conn, item["id"], json.loads(cached["result"]))
            summary["from_cache"] += 1
        else:
            to_classify.append(item)

    if to_classify and not llm_configured(settings):
        summary["failed"] = len(to_classify)
        summary["error"] = "LLM is not configured (set base URL and model in Settings)"
        conn.commit()
        return summary

    for start in range(0, len(to_classify), BATCH_SIZE):
        batch = to_classify[start:start + BATCH_SIZE]
        for local_id, item in enumerate(batch):
            item["local_id"] = local_id
        try:
            results = _classify_batch(settings, batch)
        except Exception as exc:  # noqa: BLE001 - report per-batch failure
            summary["failed"] += len(batch)
            summary["error"] = str(exc)
            continue
        for local_id, item in enumerate(batch):
            result = results.get(local_id)
            if result is None:
                summary["failed"] += 1
                continue
            _apply_result(conn, item["id"], result)
            conn.execute(
                "INSERT OR REPLACE INTO llm_classify_cache (cache_key, result, created_at) "
                "VALUES (?, ?, ?)",
                (item["cache_key"], json.dumps(result, ensure_ascii=False), now),
            )
            summary["from_llm"] += 1

    conn.commit()
    return summary


def _apply_result(conn, item_id, result):
    conn.execute(
        """UPDATE purchase_items
           SET category = ?, part_type = ?, models = ?, confidence = ?,
               classified_by = 'llm', notes = ?
           WHERE id = ? AND (classified_by IS NULL OR classified_by = 'llm')""",
        (
            result["category"],
            result["part_type"],
            json.dumps(result["models"], ensure_ascii=False),
            result["confidence"],
            result["notes"],
            item_id,
        ),
    )
