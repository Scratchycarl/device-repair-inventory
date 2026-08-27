"""Part order records bound to repair jobs with shipping lifecycle."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

SHIPPING_STAGES = (
    "ordered",
    "transit_warehouse",
    "in_warehouse",
    "transit_to_you",
    "delivered",
)

STAGE_LABELS = {
    "ordered": "Ordered",
    "transit_warehouse": "In transit to warehouse",
    "in_warehouse": "In warehouse",
    "transit_to_you": "In transit to you",
    "delivered": "Delivered",
}


def _row_dict(row) -> dict[str, Any]:
    return dict(row)


def migrate_legacy_bindings(conn: sqlite3.Connection) -> None:
    """Create part_orders rows for jobs that already have taobao_order_id."""
    rows = conn.execute(
        """
        SELECT j.id AS repair_job_id, j.taobao_order_id, j.taobao_product_name,
               j.inventory_id, j.part_name
        FROM repair_jobs j
        LEFT JOIN part_orders po ON po.repair_job_id = j.id
        WHERE j.job_type = 'order_part'
          AND j.taobao_order_id IS NOT NULL
          AND j.taobao_order_id != ''
          AND po.id IS NULL
        """
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            INSERT INTO part_orders (
                repair_job_id, inventory_id, taobao_order_id, product_name,
                part_name, shipping_stage, taobao_order_status
            ) VALUES (?, ?, ?, ?, ?, 'ordered', '交易成功')
            """,
            (
                row["repair_job_id"],
                row["inventory_id"],
                row["taobao_order_id"],
                row["taobao_product_name"] or "",
                row["part_name"] or "",
            ),
        )


def find_existing_bindings(
    conn: sqlite3.Connection,
    order_id: str,
    product_name: str,
    variant: str,
) -> list[dict[str, Any]]:
    """Find part_orders already bound to this Taobao order line (stable across re-imports)."""
    if variant:
        rows = conn.execute(
            """
            SELECT po.*, j.title AS job_title, i.model AS device_model
            FROM part_orders po
            JOIN repair_jobs j ON j.id = po.repair_job_id
            JOIN inventory i ON i.id = po.inventory_id
            WHERE po.taobao_order_id = ?
              AND po.product_name = ?
              AND (po.variant = ? OR po.variant IS NULL OR po.variant = '')
            ORDER BY po.id ASC
            """,
            (order_id, product_name, variant),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT po.*, j.title AS job_title, i.model AS device_model
            FROM part_orders po
            JOIN repair_jobs j ON j.id = po.repair_job_id
            JOIN inventory i ON i.id = po.inventory_id
            WHERE po.taobao_order_id = ?
              AND po.product_name = ?
            ORDER BY po.id ASC
            """,
            (order_id, product_name),
        ).fetchall()
    return [_row_dict(r) for r in rows]


def count_bindings_for_line(
    conn: sqlite3.Connection,
    order_id: str,
    product_name: str,
) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS c FROM part_orders
        WHERE taobao_order_id = ? AND product_name = ?
        """,
        (order_id, product_name),
    ).fetchone()
    return int(row["c"])


def create_part_order(
    conn: sqlite3.Connection,
    *,
    repair_job_id: int,
    inventory_id: int,
    taobao_order_id: str,
    product_name: str,
    variant: str,
    part_name: str,
    taobao_order_status: str = "",
    domestic_carrier: str = "",
    domestic_tracking_number: str = "",
) -> dict[str, Any]:
    stage = "ordered"
    if domestic_tracking_number:
        stage = "transit_warehouse"

    conn.execute(
        """
        INSERT INTO part_orders (
            repair_job_id, inventory_id, taobao_order_id, product_name, variant,
            part_name, taobao_order_status, shipping_stage,
            domestic_carrier, domestic_tracking_number
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            repair_job_id,
            inventory_id,
            taobao_order_id,
            product_name,
            variant,
            part_name,
            taobao_order_status,
            stage,
            domestic_carrier,
            domestic_tracking_number,
        ),
    )
    order_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.execute(
        """
        UPDATE repair_jobs
        SET status = 'done',
            completed_at = datetime('now'),
            taobao_order_id = ?,
            taobao_product_name = ?
        WHERE id = ?
        """,
        (taobao_order_id, product_name, repair_job_id),
    )
    return get_part_order(conn, order_id)


def update_part_order_from_import(
    conn: sqlite3.Connection,
    part_order_id: int,
    *,
    taobao_order_status: str,
    domestic_carrier: str = "",
    domestic_tracking_number: str = "",
) -> dict[str, Any]:
    row = get_part_order(conn, part_order_id)
    if not row:
        raise ValueError("part order not found")

    stage = row["shipping_stage"]
    if domestic_tracking_number and stage == "ordered":
        stage = "transit_warehouse"

    conn.execute(
        """
        UPDATE part_orders
        SET taobao_order_status = ?,
            domestic_carrier = COALESCE(NULLIF(?, ''), domestic_carrier),
            domestic_tracking_number = COALESCE(NULLIF(?, ''), domestic_tracking_number),
            shipping_stage = ?,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (
            taobao_order_status,
            domestic_carrier,
            domestic_tracking_number,
            stage,
            part_order_id,
        ),
    )
    return get_part_order(conn, part_order_id)


def get_part_order(conn: sqlite3.Connection, part_order_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT po.*,
               j.title AS job_title,
               i.model AS device_model,
               i.id AS device_id,
               ws.tracking_number AS warehouse_tracking_number,
               ws.carrier AS warehouse_carrier,
               ws.notes AS warehouse_notes,
               ws.status AS warehouse_shipment_status
        FROM part_orders po
        JOIN repair_jobs j ON j.id = po.repair_job_id
        JOIN inventory i ON i.id = po.inventory_id
        LEFT JOIN warehouse_shipments ws ON ws.id = po.warehouse_shipment_id
        WHERE po.id = ?
        """,
        (part_order_id,),
    ).fetchone()
    if not row:
        return None
    data = _row_dict(row)
    data["shipping_steps"] = build_shipping_steps(data)
    return data


def get_part_order_by_job(conn: sqlite3.Connection, repair_job_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id FROM part_orders WHERE repair_job_id = ?",
        (repair_job_id,),
    ).fetchone()
    if not row:
        return None
    return get_part_order(conn, row["id"])


def build_shipping_steps(order: dict[str, Any]) -> list[dict[str, Any]]:
    current = order.get("shipping_stage") or "ordered"
    stage_order = list(SHIPPING_STAGES)
    current_idx = stage_order.index(current) if current in stage_order else 0

    tracking_events = []
    raw = order.get("domestic_tracking_json")
    if raw:
        try:
            tracking_events = json.loads(raw).get("events", [])
        except json.JSONDecodeError:
            tracking_events = []

    steps = []
    for idx, stage in enumerate(stage_order):
        step: dict[str, Any] = {
            "stage": stage,
            "label": STAGE_LABELS[stage],
            "completed": idx < current_idx,
            "current": idx == current_idx,
        }
        if stage == "transit_warehouse" and (idx <= current_idx):
            step["carrier"] = order.get("domestic_carrier") or ""
            step["tracking_number"] = order.get("domestic_tracking_number") or ""
            step["events"] = tracking_events if idx == current_idx else []
        if stage == "transit_to_you" and order.get("warehouse_shipment_id"):
            step["tracking_number"] = order.get("warehouse_tracking_number") or ""
            step["carrier"] = order.get("warehouse_carrier") or ""
            step["notes"] = order.get("warehouse_notes") or ""
        steps.append(step)
    return steps


def list_part_orders_for_inventory(
    conn: sqlite3.Connection, inventory_id: int
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT po.id, po.repair_job_id, po.part_name, po.shipping_stage,
               po.taobao_order_id, po.domestic_carrier, po.domestic_tracking_number,
               po.warehouse_shipment_id
        FROM part_orders po
        WHERE po.inventory_id = ?
        ORDER BY po.id ASC
        """,
        (inventory_id,),
    ).fetchall()
    return [_row_dict(r) for r in rows]


def list_assignable_part_orders(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Orders already placed but not yet on an outbound warehouse shipment."""
    rows = conn.execute(
        """
        SELECT po.*, i.model AS device_model, j.title AS job_title
        FROM part_orders po
        JOIN inventory i ON i.id = po.inventory_id
        JOIN repair_jobs j ON j.id = po.repair_job_id
        WHERE po.warehouse_shipment_id IS NULL
          AND po.shipping_stage IN ('ordered', 'transit_warehouse', 'in_warehouse')
        ORDER BY po.id ASC
        """
    ).fetchall()
    return [_row_dict(r) for r in rows]


def set_shipping_stage(conn: sqlite3.Connection, part_order_id: int, stage: str) -> dict[str, Any]:
    if stage not in SHIPPING_STAGES:
        raise ValueError(f"Invalid stage: {stage}")
    conn.execute(
        """
        UPDATE part_orders
        SET shipping_stage = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (stage, part_order_id),
    )
    return get_part_order(conn, part_order_id)


def save_domestic_tracking(
    conn: sqlite3.Connection,
    part_order_id: int,
    carrier: str,
    tracking_number: str,
    tracking_json: dict,
) -> dict[str, Any]:
    conn.execute(
        """
        UPDATE part_orders
        SET domestic_carrier = ?,
            domestic_tracking_number = ?,
            domestic_tracking_json = ?,
            domestic_tracking_updated_at = datetime('now'),
            shipping_stage = CASE
                WHEN shipping_stage = 'ordered' THEN 'transit_warehouse'
                ELSE shipping_stage
            END,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (carrier, tracking_number, json.dumps(tracking_json), part_order_id),
    )
    return get_part_order(conn, part_order_id)


def delete_part_order_for_job(conn: sqlite3.Connection, repair_job_id: int) -> None:
    conn.execute("DELETE FROM part_orders WHERE repair_job_id = ?", (repair_job_id,))
    conn.execute(
        """
        UPDATE repair_jobs
        SET taobao_order_id = NULL, taobao_product_name = NULL
        WHERE id = ?
        """,
        (repair_job_id,),
    )


def create_warehouse_shipment(
    conn: sqlite3.Connection,
    *,
    tracking_number: str,
    carrier: str = "",
    notes: str = "",
    part_order_ids: list[int],
) -> dict[str, Any]:
    if not tracking_number.strip():
        raise ValueError("tracking_number is required")
    if not part_order_ids:
        raise ValueError("Select at least one part order")

    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO warehouse_shipments (tracking_number, carrier, notes)
        VALUES (?, ?, ?)
        """,
        (tracking_number.strip(), carrier.strip(), notes.strip()),
    )
    shipment_id = cursor.lastrowid
    for po_id in part_order_ids:
        conn.execute(
            """
            UPDATE part_orders
            SET warehouse_shipment_id = ?,
                shipping_stage = 'transit_to_you',
                updated_at = datetime('now')
            WHERE id = ? AND warehouse_shipment_id IS NULL
            """,
            (shipment_id, po_id),
        )
    return get_warehouse_shipment(conn, shipment_id)


def get_warehouse_shipment(conn: sqlite3.Connection, shipment_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM warehouse_shipments WHERE id = ?",
        (shipment_id,),
    ).fetchone()
    if not row:
        raise ValueError("Shipment not found")
    shipment = _row_dict(row)
    items = conn.execute(
        """
        SELECT po.id, po.part_name, po.taobao_order_id, po.inventory_id,
               i.model AS device_model
        FROM part_orders po
        JOIN inventory i ON i.id = po.inventory_id
        WHERE po.warehouse_shipment_id = ?
        ORDER BY po.id ASC
        """,
        (shipment_id,),
    ).fetchall()
    shipment["part_orders"] = [_row_dict(r) for r in items]
    return shipment


def list_warehouse_shipments(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT ws.*,
               (SELECT COUNT(*) FROM part_orders po WHERE po.warehouse_shipment_id = ws.id) AS item_count
        FROM warehouse_shipments ws
        ORDER BY ws.id DESC
        """
    ).fetchall()
    return [_row_dict(r) for r in rows]
