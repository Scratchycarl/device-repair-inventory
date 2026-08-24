"""Domestic (China) carrier detection and tracking via Kuaidi100 public endpoints."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# Common Taobao / Chinese carrier names → Kuaidi100 type codes
CARRIER_NAME_TO_CODE: dict[str, str] = {
    "顺丰": "shunfeng",
    "顺丰速运": "shunfeng",
    "sf": "shunfeng",
    "圆通": "yuantong",
    "圆通速递": "yuantong",
    "yt": "yuantong",
    "中通": "zhongtong",
    "中通快递": "zhongtong",
    "zt": "zhongtong",
    "韵达": "yunda",
    "韵达快递": "yunda",
    "yd": "yunda",
    "申通": "shentong",
    "申通快递": "shentong",
    "sto": "shentong",
    "极兔": "jtexpress",
    "极兔速递": "jtexpress",
    "jt": "jtexpress",
    "邮政": "youzhengguonei",
    "ems": "ems",
    "京东": "jd",
    "京东物流": "jd",
    "德邦": "debangkuaidi",
    "百世": "huitongkuaidi",
}


def normalize_carrier_name(name: str) -> str:
    return re.sub(r"\s+", "", (name or "").strip().lower())


def carrier_name_to_code(name: str) -> str | None:
    if not name:
        return None
    cleaned = normalize_carrier_name(name)
    for key, code in CARRIER_NAME_TO_CODE.items():
        if normalize_carrier_name(key) in cleaned or cleaned in normalize_carrier_name(key):
            return code
    return None


def detect_carrier_code(tracking_number: str) -> str | None:
    """Best-effort auto-detect using Kuaidi100 autonumber API."""
    num = (tracking_number or "").strip()
    if not num:
        return None
    url = f"https://www.kuaidi100.com/autonumber/auto?num={urllib.parse.quote(num)}"
    try:
        with urllib.request.urlopen(url, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        if isinstance(data, list) and data:
            return data[0].get("comCode") or data[0].get("com")
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, KeyError):
        pass
    return None


def resolve_carrier_code(carrier_hint: str, tracking_number: str) -> str | None:
    code = carrier_name_to_code(carrier_hint)
    if code:
        return code
    return detect_carrier_code(tracking_number)


def fetch_domestic_tracking(carrier_code: str, tracking_number: str) -> dict[str, Any]:
    """Query Kuaidi100 for tracking events."""
    num = (tracking_number or "").strip()
    if not num:
        return {"success": False, "message": "Tracking number required", "events": []}

    code = carrier_code or detect_carrier_code(num)
    if not code:
        return {
            "success": False,
            "message": "Could not detect carrier. Set carrier manually and retry.",
            "events": [],
            "tracking_number": num,
        }

    url = (
        "https://www.kuaidi100.com/query?"
        + urllib.parse.urlencode({"type": code, "postid": num, "temp": "0"})
    )
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; RepairInventory/1.0)",
                "Referer": "https://www.kuaidi100.com/",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        return {
            "success": False,
            "message": f"Tracking lookup failed: {exc}",
            "events": [],
            "carrier_code": code,
            "tracking_number": num,
        }

    if payload.get("status") != "200" and payload.get("message") != "ok":
        return {
            "success": False,
            "message": payload.get("message") or "No tracking data yet",
            "events": [],
            "carrier_code": code,
            "tracking_number": num,
            "raw_state": payload.get("state"),
        }

    events = []
    for item in payload.get("data") or []:
        events.append(
            {
                "time": item.get("time") or "",
                "context": item.get("context") or "",
                "location": item.get("location") or "",
            }
        )

    state = str(payload.get("state") or "")
    return {
        "success": True,
        "carrier_code": code,
        "tracking_number": num,
        "state": state,
        "events": events,
        "delivered": state == "3",
    }


def infer_stage_from_tracking(
    current_stage: str,
    tracking_result: dict[str, Any],
    taobao_status: str = "",
) -> str:
    """Advance shipping stage based on tracking / Taobao status text."""
    status = (taobao_status or "").lower()
    if tracking_result.get("delivered"):
        if current_stage in ("ordered", "transit_warehouse"):
            return "in_warehouse"
    if tracking_result.get("success") and tracking_result.get("events"):
        if current_stage == "ordered":
            return "transit_warehouse"
    if any(k in status for k in ("运输", "发货", "揽收", "派送")):
        if current_stage == "ordered":
            return "transit_warehouse"
    if "交易成功" in status and current_stage == "ordered" and not tracking_result.get("events"):
        pass
    return current_stage
