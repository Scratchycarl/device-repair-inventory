"""Parse Taobao order exports and match rows to pending order-part jobs."""

from __future__ import annotations

import re
import sqlite3
import uuid
from io import BytesIO
from typing import Any

from openpyxl import load_workbook
from repair_parts import normalize_model, screen_part_for_model

# (keywords, canonical part name). None = infer screen part from device model.
PART_KEYWORD_GROUPS: list[tuple[list[str], str | None]] = [
    (["激光雷达", "雷达", "lidar", "测距仪", "测距", "写码雷达"], "LiDAR Module"),
    (["尾插", "充电口", "充电接口", "数据线接口"], "Charging Port"),
    (["后盖", "后玻璃", "背玻璃", "背板", "后壳"], None),  # resolved per device
    (["电池", "电芯"], "Replacement Battery"),
    (["摄像头", "相机", "后置摄像", "前置摄像"], "Camera Module"),
    (["听筒"], "Earpiece Speaker"),
    (["扬声器", "喇叭"], "Loudspeaker"),
    (["wifi", "天线"], "WiFi Antenna"),
    (["face id", "面容", "truedepth"], "Face ID / TrueDepth"),
    (["home键", "home button", "指纹键"], "Home Button"),
    (["oled", "屏幕总成", "显示屏", "屏幕", "液晶", "总成"], None),
    (["lcd"], "LCD Assembly"),
    (["digitizer", "触摸", "外屏"], "Digitizer"),
]


def _cell_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_header_row(sheet) -> tuple[int, dict[str, int]] | None:
    for row_idx, row in enumerate(sheet.iter_rows(min_row=1, max_row=15, values_only=True), start=1):
        headers = [_cell_str(c) for c in row]
        if "订单号" in headers:
            col_map = {name: idx for idx, name in enumerate(headers) if name}
            return row_idx, col_map
    return None


def parse_taobao_xlsx(file_bytes: bytes) -> list[dict[str, Any]]:
    wb = load_workbook(BytesIO(file_bytes), read_only=True, data_only=True)
    sheet = wb.active
    header_info = _parse_header_row(sheet)
    if not header_info:
        raise ValueError("Could not find Taobao header row (订单号).")

    header_row, col_map = header_info
    required = ["订单号", "商品名称", "型号款式"]
    for key in required:
        if key not in col_map:
            raise ValueError(f"Missing column: {key}")

    qty_indices = [i for i, h in enumerate(sheet[header_row]) if _cell_str(h) == "商品数量"]
    qty_col = qty_indices[0] if qty_indices else None

    orders: list[dict[str, Any]] = []
    for row in sheet.iter_rows(min_row=header_row + 1, values_only=True):
        cells = list(row)
        order_id = _cell_str(cells[col_map["订单号"]]) if col_map["订单号"] < len(cells) else ""
        if not order_id:
            continue

        product_name = _cell_str(cells[col_map["商品名称"]]) if col_map["商品名称"] < len(cells) else ""
        variant = _cell_str(cells[col_map["型号款式"]]) if col_map["型号款式"] < len(cells) else ""
        qty = 1
        if qty_col is not None and qty_col < len(cells):
            raw_qty = cells[qty_col]
            try:
                qty = max(1, int(float(raw_qty)))
            except (TypeError, ValueError):
                qty = 1

        orders.append(
            {
                "order_id": order_id,
                "order_date": _cell_str(cells[col_map.get("订单提交时间", -1)])
                if col_map.get("订单提交时间") is not None
                and col_map["订单提交时间"] < len(cells)
                else "",
                "order_status": _cell_str(cells[col_map.get("订单状态", -1)])
                if col_map.get("订单状态") is not None
                and col_map["订单状态"] < len(cells)
                else "",
                "shop_name": _cell_str(cells[col_map.get("店铺名称", -1)])
                if col_map.get("店铺名称") is not None
                and col_map["店铺名称"] < len(cells)
                else "",
                "product_name": product_name,
                "variant": variant,
                "product_link": _cell_str(cells[col_map.get("商品链接", -1)])
                if col_map.get("商品链接") is not None
                and col_map["商品链接"] < len(cells)
                else "",
                "qty": qty,
                "search_text": f"{product_name} {variant}".lower(),
            }
        )
    wb.close()
    return orders


def extract_model_tokens(text: str) -> set[str]:
    lowered = text.lower()
    tokens: set[str] = set()
    normalized = normalize_model(text)

    patterns = [
        r"iphone\s*(\d{1,2})\s*pro\s*max",
        r"iphone\s*(\d{1,2})\s*pro",
        r"iphone\s*(\d{1,2})\s*plus",
        r"iphone\s*(\d{1,2})",
        r"(\d{1,2})\s*pro\s*max",
        r"(\d{1,2})\s*promax",
        r"(\d{1,2})\s*pro",
        r"(\d{1,2})\s*plus",
        r"ipad\s*pro",
        r"ipad\s*air",
        r"ipad\s*mini",
        r"ipad\s*(\d+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, lowered)
        if m:
            tokens.add(normalize_model(m.group(0)))

    if "iphone" in normalized or re.search(r"\b1[0-7]\b", normalized):
        tokens.add(normalized)
    if "ipad" in normalized:
        tokens.add(normalized)
    return tokens


def models_compatible(device_model: str, order_tokens: set[str]) -> bool:
    device_norm = normalize_model(device_model)
    if not device_norm or not order_tokens:
        return False
    for token in order_tokens:
        if not token:
            continue
        if token in device_norm or device_norm in token:
            return True
        device_nums = re.findall(r"\d+", device_norm)
        token_nums = re.findall(r"\d+", token)
        if device_nums and token_nums and device_nums[0] == token_nums[0]:
            device_pro = "pro" in device_norm
            token_pro = "pro" in token
            device_max = "max" in device_norm or "plus" in device_norm
            token_max = "max" in token or "plus" in token
            if device_pro == token_pro and device_max == token_max:
                return True
    return False


def infer_part_from_text(text: str, device_model: str | None = None) -> str | None:
    lowered = text.lower()
    for keywords, part_name in PART_KEYWORD_GROUPS:
        if any(kw.lower() in lowered for kw in keywords):
            if part_name is None:
                if any(k in lowered for k in ("后盖", "后玻璃", "背玻璃", "背板", "后壳")):
                    from repair_parts import back_part_for_model

                    return back_part_for_model(device_model)
                return screen_part_for_model(device_model)
            return part_name
    return None


def _part_names_match(job_part: str, inferred: str) -> bool:
    if not job_part or not inferred:
        return False
    if job_part.lower() == inferred.lower():
        return True
    if job_part.lower() in inferred.lower() or inferred.lower() in job_part.lower():
        return True
    return False


def apply_taobao_import(conn: sqlite3.Connection, file_bytes: bytes) -> dict[str, Any]:
    orders = parse_taobao_xlsx(file_bytes)
    batch_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO taobao_import_batches (id, row_count) VALUES (?, ?)",
        (batch_id, len(orders)),
    )

    inventory_rows = conn.execute(
        "SELECT id, model, parts_needed FROM inventory ORDER BY id ASC"
    ).fetchall()
    devices = [dict(r) for r in inventory_rows]

    pending_jobs = conn.execute(
        """
        SELECT j.*, i.model AS device_model
        FROM repair_jobs j
        JOIN inventory i ON i.id = j.inventory_id
        WHERE j.job_type = 'order_part' AND j.status = 'pending'
        ORDER BY j.inventory_id ASC, j.sort_order ASC, j.id ASC
        """
    ).fetchall()
    pending_list = [dict(r) for r in pending_jobs]

    results: list[dict[str, Any]] = []
    matched_count = 0

    for order in orders:
        order_tokens = extract_model_tokens(order["search_text"])
        inferred_default = infer_part_from_text(order["search_text"])
        matched_jobs: list[dict] = []
        remaining = order["qty"]

        already = conn.execute(
            """
            SELECT COUNT(*) AS c FROM taobao_import_rows
            WHERE order_id = ? AND product_name = ? AND variant = ? AND matched_job_ids IS NOT NULL AND matched_job_ids != ''
            """,
            (order["order_id"], order["product_name"], order["variant"]),
        ).fetchone()["c"]
        if already >= order["qty"]:
            results.append(
                {
                    **order,
                    "status": "skipped_duplicate",
                    "matched_jobs": [],
                    "inferred_part": inferred_default,
                }
            )
            continue

        for job in pending_list:
            if remaining <= 0:
                break
            if job["status"] != "pending":
                continue
            if job.get("taobao_order_id") == order["order_id"]:
                continue
            if not models_compatible(job["device_model"] or "", order_tokens):
                continue
            inferred = infer_part_from_text(
                order["search_text"], device_model=job["device_model"]
            )
            if not inferred:
                inferred = inferred_default
            if not _part_names_match(job["part_name"] or "", inferred or ""):
                continue

            conn.execute(
                """
                UPDATE repair_jobs
                SET status = 'done',
                    completed_at = datetime('now'),
                    taobao_order_id = ?,
                    taobao_product_name = ?
                WHERE id = ?
                """,
                (order["order_id"], order["product_name"], job["id"]),
            )
            job["status"] = "done"
            matched_jobs.append(
                {
                    "job_id": job["id"],
                    "inventory_id": job["inventory_id"],
                    "part_name": job["part_name"],
                    "device_model": job["device_model"],
                }
            )
            remaining -= 1
            matched_count += 1

        status = "matched" if matched_jobs else "unmatched"
        row_id = conn.execute(
            """
            INSERT INTO taobao_import_rows (
                batch_id, order_id, order_date, order_status, shop_name,
                product_name, variant, product_link, qty,
                inferred_part, match_status, matched_job_ids
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                order["order_id"],
                order.get("order_date", ""),
                order.get("order_status", ""),
                order.get("shop_name", ""),
                order["product_name"],
                order["variant"],
                order.get("product_link", ""),
                order["qty"],
                inferred_default or "",
                status,
                ",".join(str(m["job_id"]) for m in matched_jobs),
            ),
        ).lastrowid

        results.append(
            {
                **order,
                "row_id": row_id,
                "status": status,
                "matched_jobs": matched_jobs,
                "inferred_part": inferred_default,
                "unmatched_qty": max(0, order["qty"] - len(matched_jobs)),
            }
        )

    conn.commit()
    return {
        "batch_id": batch_id,
        "total_rows": len(orders),
        "matched_count": matched_count,
        "results": results,
        "device_count": len(devices),
    }
