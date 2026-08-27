"""Parse Taobao order exports, bind to devices, and refresh shipping on re-import."""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from llm_match import llm_configured, match_order_with_llm
from part_orders import (
    create_part_order,
    find_existing_bindings,
    update_part_order_from_import,
)
from taobao_import import (
    _part_names_match,
    models_compatible,
    order_model_tokens,
    order_part_name,
    parse_taobao_xlsx,
)


def _bind_job(
    conn: sqlite3.Connection,
    job: dict[str, Any],
    order: dict[str, Any],
    inferred: str | None,
) -> dict[str, Any] | None:
    try:
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
    except sqlite3.IntegrityError:
        job["status"] = "done"
        return None
    job["status"] = "done"
    return {
        "job_id": job["id"],
        "part_order_id": po["id"],
        "inventory_id": job["inventory_id"],
        "part_name": job["part_name"],
        "device_model": job["device_model"],
    }


def _pending_order_jobs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
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
    return [dict(r) for r in rows]


def apply_taobao_import(
    conn: sqlite3.Connection,
    file_bytes: bytes,
) -> dict[str, Any]:
    orders = parse_taobao_xlsx(file_bytes)
    batch_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO taobao_import_batches (id, row_count) VALUES (?, ?)",
        (batch_id, len(orders)),
    )

    pending_list = _pending_order_jobs(conn)

    results: list[dict[str, Any]] = []
    matched_count = 0
    updated_count = 0

    for order in orders:
        order_tokens = order_model_tokens(order)
        inferred_default = order_part_name(order)
        matched_jobs: list[dict] = []
        updated_bindings: list[dict] = []
        match_source = "rules"

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

        # Re-import: refresh existing device bindings, never reassign.
        # Live carrier lookup is skipped here so a large sheet cannot hang;
        # use Refresh on the shipping modal after import.
        for binding in existing:
            updated_po = update_part_order_from_import(
                conn,
                binding["id"],
                taobao_order_status=order.get("order_status", ""),
                domestic_carrier=order.get("domestic_carrier", ""),
                domestic_tracking_number=order.get("domestic_tracking_number", ""),
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
                    "match_source": "existing",
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
            if job.get("status") != "pending":
                continue
            if not models_compatible(job["device_model"] or "", order_tokens):
                continue
            inferred = order_part_name(order, device_model=job["device_model"])
            if not inferred:
                inferred = inferred_default
            if not _part_names_match(job["part_name"] or "", inferred or ""):
                continue

            bound = _bind_job(conn, job, order, inferred)
            if not bound:
                continue
            matched_jobs.append(bound)
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
                "inferred_model": next(iter(order_tokens), ""),
                "unmatched_qty": max(0, remaining),
                "match_source": match_source,
            }
        )

    unmatched_count = sum(
        1 for r in results if (r.get("unmatched_qty") or 0) > 0 or r.get("status") == "unmatched"
    )
    conn.commit()
    return {
        "batch_id": batch_id,
        "total_rows": len(orders),
        "matched_count": matched_count,
        "updated_count": updated_count,
        "unmatched_count": unmatched_count,
        "results": results,
    }


def _order_from_import_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "order_id": row.get("order_id") or "",
        "order_date": row.get("order_date") or "",
        "order_status": row.get("order_status") or "",
        "shop_name": row.get("shop_name") or "",
        "product_name": row.get("product_name") or "",
        "variant": row.get("variant") or "",
        "product_link": row.get("product_link") or "",
        "qty": int(row.get("qty") or 0),
        "domestic_carrier": "",
        "domestic_tracking_number": "",
    }


def apply_taobao_llm_retry(
    conn: sqlite3.Connection,
    batch_id: str,
    llm_settings: dict[str, str],
) -> dict[str, Any]:
    """Retry unmatched rows in an import batch using the configured LLM."""
    if not llm_configured(llm_settings):
        raise ValueError("Configure the LLM API in Settings first.")
    batch = conn.execute(
        "SELECT id FROM taobao_import_batches WHERE id = ?",
        (batch_id,),
    ).fetchone()
    if not batch:
        raise ValueError("Import batch not found. Upload the sheet again.")

    pending_list = _pending_order_jobs(conn)
    rows = conn.execute(
        """
        SELECT * FROM taobao_import_rows
        WHERE batch_id = ?
        ORDER BY id ASC
        """,
        (batch_id,),
    ).fetchall()

    results: list[dict[str, Any]] = []
    llm_match_count = 0
    matched_count = 0
    updated_count = 0

    for raw in rows:
        row = dict(raw)
        order = _order_from_import_row(row)
        order_tokens = order_model_tokens(order)
        inferred_default = row.get("inferred_part") or order_part_name(order)
        existing = find_existing_bindings(
            conn,
            order["order_id"],
            order["product_name"],
            order["variant"],
        )
        remaining = max(0, order["qty"] - len(existing))
        matched_jobs: list[dict[str, Any]] = []
        updated_bindings = [
            {
                "part_order_id": binding["id"],
                "inventory_id": binding["inventory_id"],
                "part_name": binding.get("part_name"),
                "device_model": binding.get("device_model"),
            }
            for binding in existing
        ]
        updated_count += len(updated_bindings)

        if remaining > 0:
            llm_result = match_order_with_llm(
                llm_settings, order, pending_list, remaining
            )
            if llm_result:
                if llm_result.get("part") and not inferred_default:
                    inferred_default = llm_result["part"]
                by_id = {job["id"]: job for job in pending_list}
                for jid in llm_result.get("job_ids") or []:
                    if remaining <= 0:
                        break
                    job = by_id.get(jid)
                    if not job or job.get("status") != "pending":
                        continue
                    bound = _bind_job(conn, job, order, inferred_default)
                    if not bound:
                        continue
                    bound["match_source"] = "llm"
                    matched_jobs.append(bound)
                    remaining -= 1
                    matched_count += 1
                    llm_match_count += 1

        prior_status = row.get("match_status") or ""
        if matched_jobs:
            status = "matched"
            match_source = "mixed" if updated_bindings else "llm"
        elif remaining <= 0:
            status = prior_status or ("updated" if updated_bindings else "skipped_duplicate")
            match_source = "existing" if status in ("updated", "skipped_duplicate") else "rules"
            if status == "matched":
                matched_jobs = [
                    {
                        "job_id": binding.get("repair_job_id"),
                        "part_order_id": binding["id"],
                        "inventory_id": binding["inventory_id"],
                        "part_name": binding.get("part_name"),
                        "device_model": binding.get("device_model"),
                    }
                    for binding in existing
                ]
                updated_bindings = []
        else:
            status = "unmatched"
            match_source = "rules"

        job_ids = ",".join(
            str(m.get("part_order_id") or m.get("job_id", ""))
            for m in (*matched_jobs, *updated_bindings)
        )
        conn.execute(
            """
            UPDATE taobao_import_rows
            SET inferred_part = ?, match_status = ?, matched_job_ids = ?
            WHERE id = ?
            """,
            (inferred_default or "", status, job_ids, row["id"]),
        )

        results.append(
            {
                **order,
                "status": status,
                "matched_jobs": matched_jobs,
                "updated_bindings": updated_bindings,
                "inferred_part": inferred_default,
                "inferred_model": next(iter(order_tokens), ""),
                "unmatched_qty": max(0, remaining),
                "match_source": match_source,
            }
        )

    unmatched_count = sum(
        1 for r in results if (r.get("unmatched_qty") or 0) > 0 or r.get("status") == "unmatched"
    )
    conn.commit()
    return {
        "batch_id": batch_id,
        "total_rows": len(results),
        "matched_count": matched_count,
        "updated_count": updated_count,
        "unmatched_count": unmatched_count,
        "llm_match_count": llm_match_count,
        "results": results,
    }
