"""Suggest which queued devices a purchased part could be allocated to.

A suggestion requires BOTH:
  - the device model matches one of the item's classified models, and
  - the device's parts_needed list contains a part of the same part_type
    that is not already covered by an existing item link.

Nothing here auto-binds; links are only created when confirmed via the API.
"""

from __future__ import annotations

import json
import re

from repair_parts import normalize_model

# part_type (LLM vocabulary) -> parts_needed names it can satisfy
PART_TYPE_TO_PART_NAMES = {
    "battery": ["Replacement Battery"],
    "screen": ["OLED Assembly", "LCD Assembly", "Digitizer", "Display Assembly"],
    "back": ["Back Glass", "Back Cover", "Back Housing"],
    "housing": ["Back Housing", "Back Cover"],
    "camera": ["Camera Module"],
    "camera_glass": ["Rear Camera Glass"],
    "charging_port": ["Charging Port"],
    "speaker": ["Loudspeaker"],
    "earpiece": ["Earpiece Speaker"],
    "microphone": ["Microphone"],
    "button": ["Power Button", "Home Button"],
    "flex_cable": ["Power Flex", "Volume Flex"],
    "logic_board": ["Logic Board Repair"],
    "antenna": ["WiFi Antenna"],
    "face_id": ["Face ID / TrueDepth"],
}


def _is_tablet(device):
    if str(device.get("vision_device_type") or "").lower() == "tablet":
        return True
    return bool(re.search(r"ipad|tablet", device.get("model") or "", re.IGNORECASE))


def _is_blocked(device):
    """Mirror the dashboard rule: FMI-locked always blocked; Bypassed phones blocked."""
    status = device.get("lock_status") or ""
    if status == "Locked (FMI ON)":
        return True
    if status == "Bypassed" and not _is_tablet(device):
        return True
    return False


def _parse_parts(raw):
    try:
        parsed = json.loads(raw or "[]")
        return [str(p) for p in parsed] if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


def _models_match(item_models_normalized, device_model):
    device_norm = normalize_model(device_model)
    if not device_norm:
        return False
    return device_norm in item_models_normalized


def incoming_parts_by_device(conn, inventory_id=None):
    """Map inventory_id -> allocated parts with their shipping status.

    Each allocation is resolved back to the parts_needed entry it covers so the
    dashboard can tell which repairs are already waiting on a delivery and keep
    them off the shopping list.
    """
    query = '''
        SELECT l.id AS link_id, l.inventory_id, l.qty,
               p.item_title, p.sku_text, p.part_type,
               o.status AS order_status, o.logistics_company, o.tracking_no,
               i.parts_needed
        FROM item_device_links l
        JOIN purchase_items p ON p.id = l.purchase_item_id
        JOIN purchase_orders o ON o.order_no = p.order_no
        JOIN inventory i ON i.id = l.inventory_id
    '''
    params = []
    if inventory_id is not None:
        query += ' WHERE l.inventory_id = ?'
        params.append(inventory_id)

    result = {}
    for row in conn.execute(query, params).fetchall():
        candidates = PART_TYPE_TO_PART_NAMES.get(row["part_type"] or "", [])
        device_parts = _parse_parts(row["parts_needed"])
        part_name = next((p for p in device_parts if p in candidates), None)
        if part_name is None and candidates:
            part_name = candidates[0]
        result.setdefault(row["inventory_id"], []).append({
            "link_id": row["link_id"],
            "qty": row["qty"] or 1,
            "item_title": row["item_title"],
            "sku_text": row["sku_text"],
            "part_type": row["part_type"],
            "part_name": part_name,
            "order_status": row["order_status"],
            "logistics_company": row["logistics_company"],
            "tracking_no": row["tracking_no"],
        })
    return result


def build_suggestions(conn, items):
    """items: list of purchase_item dicts (id, category, part_type, models JSON,
    quantity, review_status). Returns {item_id: [suggestion, ...]}.
    """
    devices = [dict(r) for r in conn.execute("SELECT * FROM inventory").fetchall()]

    link_rows = conn.execute(
        """SELECT l.purchase_item_id, l.inventory_id, l.qty, p.part_type
           FROM item_device_links l JOIN purchase_items p ON p.id = l.purchase_item_id"""
    ).fetchall()

    # part_types already covered per device, and qty already allocated per item
    covered = {}   # inventory_id -> set of part_types
    allocated = {}  # purchase_item_id -> total linked qty
    for row in link_rows:
        if row["part_type"]:
            covered.setdefault(row["inventory_id"], set()).add(row["part_type"])
        allocated[row["purchase_item_id"]] = (
            allocated.get(row["purchase_item_id"], 0) + (row["qty"] or 1)
        )

    suggestions = {}
    for item in items:
        item_id = item["id"]
        suggestions[item_id] = []

        if item.get("category") != "part" or item.get("review_status") == "dismissed":
            continue
        part_type = item.get("part_type")
        part_names = PART_TYPE_TO_PART_NAMES.get(part_type or "", [])
        if not part_names:
            continue

        item_models = _parse_parts(item.get("models"))
        item_models_normalized = {normalize_model(m) for m in item_models if m}
        item_models_normalized.discard("")
        if not item_models_normalized:
            continue

        remaining = (item.get("quantity") or 1) - allocated.get(item_id, 0)
        if remaining <= 0:
            continue

        for device in devices:
            if _is_blocked(device):
                continue
            if not _models_match(item_models_normalized, device.get("model")):
                continue
            if part_type in covered.get(device["id"], set()):
                continue
            device_parts = _parse_parts(device.get("parts_needed"))
            matched_part = next((p for p in device_parts if p in part_names), None)
            if not matched_part:
                continue
            suggestions[item_id].append({
                "inventory_id": device["id"],
                "model": device.get("model"),
                "inventory_number": device.get("inventory_number"),
                "serial_number": device.get("serial_number"),
                "lock_status": device.get("lock_status"),
                "part_name": matched_part,
            })

    return suggestions
