"""OpenAI-compatible chat matching for Taobao rows that rules cannot classify."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

CANONICAL_PARTS = [
    "OLED Assembly",
    "LCD Assembly",
    "Digitizer",
    "Display Assembly",
    "Back Glass",
    "Back Cover",
    "Back Housing",
    "Replacement Battery",
    "LiDAR Module",
    "Camera Module",
    "Rear Camera Glass",
    "WiFi Antenna",
    "Power Button",
    "Power Flex",
    "Volume Flex",
    "Charging Port",
    "Loudspeaker",
    "Earpiece Speaker",
    "Microphone",
    "Face ID / TrueDepth",
    "Home Button",
    "Vibrator",
    "Logic Board Repair",
]


def llm_configured(settings: dict[str, str]) -> bool:
    return (
        bool((settings.get("llm_api_key") or "").strip())
        and bool((settings.get("llm_base_url") or "").strip())
        and bool((settings.get("llm_model") or "").strip())
    )


def completions_url(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def chat_completion(settings: dict[str, str], messages: list[dict[str, str]], timeout: int = 25) -> str:
    url = completions_url(settings.get("llm_base_url") or "")
    body = json.dumps(
        {
            "model": settings.get("llm_model") or "gpt-4o-mini",
            "messages": messages,
            "temperature": 0,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {(settings.get('llm_api_key') or '').strip()}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM request failed: {exc.reason}") from exc

    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError(payload.get("error", {}).get("message") or "Empty LLM response")
    return (choices[0].get("message") or {}).get("content") or ""


def _parse_json_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    if fence:
        raw = fence.group(1)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(raw[start : end + 1])
                return data if isinstance(data, dict) else None
            except json.JSONDecodeError:
                return None
    return None


def match_order_with_llm(
    settings: dict[str, str],
    order: dict[str, Any],
    pending_jobs: list[dict[str, Any]],
    qty: int,
) -> dict[str, Any] | None:
    """Ask the LLM which pending order-part jobs this Taobao row fulfills."""
    if not llm_configured(settings) or qty <= 0:
        return None
    candidates = [
        {
            "job_id": job["id"],
            "inventory_id": job["inventory_id"],
            "device_model": job.get("device_model") or "",
            "part_name": job.get("part_name") or "",
        }
        for job in pending_jobs
        if job.get("status") == "pending"
    ][:80]
    if not candidates:
        return None

    user = {
        "product_name": order.get("product_name") or "",
        "variant": order.get("variant") or "",
        "qty": qty,
        "canonical_parts": CANONICAL_PARTS,
        "pending_jobs": candidates,
    }
    messages = [
        {
            "role": "system",
            "content": (
                "You match Taobao phone-repair part orders to pending shop jobs. "
                "商品名称 is the part type. 型号款式 is the device model. "
                "Pick at most qty pending jobs that this order actually supplies. "
                "Only use job_id values from pending_jobs. If nothing fits, return empty job_ids. "
                'Reply with JSON only: {"job_ids":[int],"part":"canonical part or empty","model":"device model or empty"}'
            ),
        },
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]
    try:
        content = chat_completion(settings, messages)
    except Exception as exc:
        print(f"[llm] match skipped: {exc}")
        return None

    data = _parse_json_object(content)
    if not data:
        return None
    allowed = {c["job_id"] for c in candidates}
    job_ids: list[int] = []
    for raw_id in data.get("job_ids") or []:
        try:
            jid = int(raw_id)
        except (TypeError, ValueError):
            continue
        if jid in allowed and jid not in job_ids:
            job_ids.append(jid)
        if len(job_ids) >= qty:
            break
    return {
        "job_ids": job_ids,
        "part": str(data.get("part") or "").strip(),
        "model": str(data.get("model") or "").strip(),
    }


def test_llm_connection(settings: dict[str, str]) -> dict[str, Any]:
    if not (settings.get("llm_api_key") or "").strip():
        return {"success": False, "message": "API key is required"}
    if not (settings.get("llm_base_url") or "").strip():
        return {"success": False, "message": "Base URL is required"}
    try:
        content = chat_completion(
            settings,
            [
                {"role": "user", "content": "Reply with the single word pong."},
            ],
            timeout=15,
        )
    except Exception as exc:
        return {"success": False, "message": str(exc)}
    return {"success": True, "message": "Connected", "sample": (content or "")[:120]}
