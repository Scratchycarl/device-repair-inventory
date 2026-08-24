"""Parse Taobao order exports, bind to devices, and refresh shipping on re-import."""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from part_orders import (
    create_part_order,
    find_existing_bindings,
    update_part_order_from_import,
)
from shipping_tracker import (
    fetch_domestic_tracking,
    infer_stage_from_tracking,
    resolve_carrier_code,
)
from taobao_import import (
    _part_names_match,
    extract_model_tokens,
    infer_part_from_text,
    models_compatible,
    parse_taobao_xlsx,
)


def _apply_tracking_refresh(conn: sqlite3.Connection, part_order_id: int) -> None:
    row = conn.execute(
        "SELECT * FROM part_orders WHERE id = ?",
        (part_order_id,),
    ).fetchone()
    if not row or not row["domestic_tracking_number"]:
        return
    po = dict(row)
    code = resolve_carrier_code(po.get("domestic_carrier") or "", po["domestic_tracking_number"])
    if not code:
        return
    result = fetch_domestic_tracking(code, po["domestic_tracking_number"])
    if not result.get("success"):
        return
    new_stage = infer_stage_from_tracking(
        po["shipping_stage"],
        result,
        po.get("taobao_order_status") or "",
    )
    import json

    conn.execute(
        """
        UPDATE part_orders
        SET domestic_carrier = COALESCE(NULLIF(domestic_carrier, ''), ?),
            domestic_tracking_json = ?,
            domestic_tracking_updated_at = datetime('now'),
            shipping_stage = ?,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (
            result.get("carrier_code") or code,
            json.dumps(result),
            new_stage,
            part_order_id,
        ),
    )


def apply_taobao_import(conn: sqlite3.Connection, file_bytes: bytes) -> dict[str, Any]:
    orders = parse_taobao_xlsx(file_bytes)
    batch_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO taobao_import_batches (id, row_count) VALUES (?, ?)",
        (batch_id, len(orders)),
    )

    pending_jobs = conn.execute(
        """
        SELECT j.*, i.model AS device_model
        FROM repair_jobs j
        JOIN inventory i ON i.id = j.inventory_id
        WHERE j.job_type = 'order_part'
          AND j.status = 'pending'
          AND NOT EXISTS (SELECT 1 FROM part_orders po WHERE po.repair_job_id = j.id)
        ORDER BY j.inventory_id ASC, j.sort_order ASC, j.id ASC
        """
    ).fetchall()
    pending_list = [dict(r) for r in pending_jobs]

    results: list[dict[str, Any]] = []
    matched_count = 0
    updated_count = 0

    for order in orders:
        order_tokens = extract_model_tokens(order["search_text"])
        inferred_default = infer_part_from_text(order["search_text"])
        matched_jobs: list[dict] = []
        updated_bindings: list[dict] = []

        existing = find_existing_bindings(
            conn,
            order["order_id"],
            order["product_name"],
            order["variant"],
        )

        # Backfill variant on legacy rows missing it
        for binding in existing:
            if order["variant"] and not binding.get("variant"):
                conn.execute(
                    "UPDATE part_orders SET variant = ? WHERE id = ?",
                    (order["variant"], binding["id"]),
                )

        # Re-import: refresh existing device bindings, never reassign
        for binding in existing:
            updated_po = update_part_order_from_import(
                conn,
                binding["id"],
                taobao_order_status=order.get("order_status", ""),
                domestic_carrier=order.get("domestic_carrier", ""),
                domestic_tracking_number=order.get("domestic_tracking_number", ""),
            )
            if order.get("domestic_tracking_number"):
                _apply_tracking_refresh(conn, binding["id"])
                updated_po = dict(
                    conn.execute("SELECT * FROM part_orders WHERE id = ?", (binding["id"],)).fetchone()
                )
            updated_bindings.append(
                {
                    "part_order_id": binding["id"],
                    "inventory_id": binding["inventory_id"],
                    "part_name": binding.get("part_name"),
                    "device_model": binding.get("device_model"),
                    "shipping_stage": updated_po.get("shipping_stage"),
                }
            )
            updated_count += 1

        remaining = max(0, order["qty"] - len(existing))

        if remaining <= 0:
            status = "updated" if updated_bindings else "skipped_duplicate"
            results.append(
                {
                    **order,
                    "status": status,
                    "matched_jobs": [],
                    "updated_bindings": updated_bindings,
                    "inferred_part": inferred_default,
                }
            )
            conn.execute(
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
                    ",".join(str(b["part_order_id"]) for b in updated_bindings),
                ),
            )
            continue

        for job in pending_list:
            if remaining <= 0:
                break
            if not models_compatible(job["device_model"] or "", order_tokens):
                continue
            inferred = infer_part_from_text(
                order["search_text"], device_model=job["device_model"]
            )
            if not inferred:
                inferred = inferred_default
            if not _part_names_match(job["part_name"] or "", inferred or ""):
                continue

            po = create_part_order(
                conn,
                repair_job_id=job["id"],
                inventory_id=job["inventory_id"],
                taobao_order_id=order["order_id"],
                product_name=order["product_name"],
                variant=order["variant"],
                part_name=job["part_name"] or inferred or "",
                taobao_order_status=order.get("order_status", ""),
                domestic_carrier=order.get("domestic_carrier", ""),
                domestic_tracking_number=order.get("domestic_tracking_number", ""),
            )
            if order.get("domestic_tracking_number"):
                _apply_tracking_refresh(conn, po["id"])

            job["status"] = "done"
            matched_jobs.append(
                {
                    "job_id": job["id"],
                    "part_order_id": po["id"],
                    "inventory_id": job["inventory_id"],
                    "part_name": job["part_name"],
                    "device_model": job["device_model"],
                }
            )
            remaining -= 1
            matched_count += 1

        status = "matched" if matched_jobs else ("updated" if updated_bindings else "unmatched")
        conn.execute(
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
                ",".join(
                    str(m.get("part_order_id") or m.get("job_id", ""))
                    for m in (*matched_jobs, *updated_bindings)
                ),
            ),
        )

        results.append(
            {
                **order,
                "status": status,
                "matched_jobs": matched_jobs,
                "updated_bindings": updated_bindings,
                "inferred_part": inferred_default,
                "unmatched_qty": max(0, remaining),
            }
        )

    conn.commit()
    return {
        "batch_id": batch_id,
        "total_rows": len(orders),
        "matched_count": matched_count,
        "updated_count": updated_count,
        "results": results,
    }
