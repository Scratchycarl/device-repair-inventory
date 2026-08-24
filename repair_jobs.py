"""Generate and sync per-device repair job checklists."""

from __future__ import annotations

import sqlite3
from typing import Any

from parts_format import parse_parts

SCREEN_PARTS = frozenset(
    {"OLED Assembly", "LCD Assembly", "Digitizer", "Display Assembly"}
)
AUTO_JOB_TYPES = frozenset({"order_part", "install_part", "program_part"})


def _desired_auto_jobs(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build ordered auto-job specs grouped by part."""
    jobs: list[dict[str, Any]] = []
    sort_base = 0
    for part in parts:
        name = part["name"]
        needs_programming = bool(part.get("needs_programming"))
        group = [
            ("order_part", f"Order {name}"),
            ("install_part", f"Replace {name}"),
        ]
        if needs_programming and name in SCREEN_PARTS:
            group.append(("program_part", f"Program {name}"))
        for offset, (job_type, title) in enumerate(group):
            jobs.append(
                {
                    "job_type": job_type,
                    "part_name": name,
                    "title": title,
                    "sort_order": sort_base + offset,
                }
            )
        sort_base += 10
    return jobs


def sync_repair_jobs(conn: sqlite3.Connection, inventory_id: int, parts_raw) -> None:
    """Align auto-generated jobs with the device's current parts list."""
    parts = parse_parts(parts_raw)
    desired = _desired_auto_jobs(parts)
    desired_keys = {(j["job_type"], j["part_name"]) for j in desired}
    desired_by_key = {(j["job_type"], j["part_name"]): j for j in desired}

    rows = conn.execute(
        """
        SELECT id, job_type, part_name, status, title, sort_order
        FROM repair_jobs
        WHERE inventory_id = ? AND job_type IN ('order_part', 'install_part', 'program_part')
        """,
        (inventory_id,),
    ).fetchall()

    existing = [dict(r) for r in rows]

    for job in existing:
        key = (job["job_type"], job["part_name"] or "")
        if key not in desired_keys and job["status"] == "pending":
            conn.execute("DELETE FROM repair_jobs WHERE id = ?", (job["id"],))

    for job in existing:
        key = (job["job_type"], job["part_name"] or "")
        if key in desired_by_key:
            spec = desired_by_key[key]
            if job["title"] != spec["title"] or job.get("sort_order") != spec["sort_order"]:
                conn.execute(
                    """
                    UPDATE repair_jobs
                    SET title = ?, sort_order = ?
                    WHERE id = ?
                    """,
                    (spec["title"], spec["sort_order"], job["id"]),
                )

    existing_keys = {(j["job_type"], j["part_name"] or "") for j in existing}
    for spec in desired:
        key = (spec["job_type"], spec["part_name"])
        if key in existing_keys:
            continue
        conn.execute(
            """
            INSERT INTO repair_jobs (
                inventory_id, job_type, part_name, title, status, sort_order
            ) VALUES (?, ?, ?, ?, 'pending', ?)
            """,
            (
                inventory_id,
                spec["job_type"],
                spec["part_name"],
                spec["title"],
                spec["sort_order"],
            ),
        )


def fetch_jobs_for_inventory(conn: sqlite3.Connection, inventory_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT * FROM repair_jobs
        WHERE inventory_id = ?
        ORDER BY sort_order ASC, id ASC
        """,
        (inventory_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_job_counts(conn: sqlite3.Connection) -> dict[int, dict[str, int]]:
    rows = conn.execute(
        """
        SELECT inventory_id,
               SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
               COUNT(*) AS total
        FROM repair_jobs
        GROUP BY inventory_id
        """
    ).fetchall()
    return {
        row["inventory_id"]: {"pending": row["pending"], "total": row["total"]}
        for row in rows
    }
