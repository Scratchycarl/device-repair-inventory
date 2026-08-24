import sqlite3

def init_db():
    conn = sqlite3.connect('inventory.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date_received TEXT,
        model TEXT,
        color TEXT,
        capacity TEXT,
        serial_number TEXT,
        ios_version TEXT,
        imei TEXT,
        battery_health TEXT,
        remarks TEXT,
        front_image_url TEXT,
        back_image_url TEXT,
        damage_condition TEXT,
        parts_needed TEXT
    )
    ''')
    
    conn.commit()

    cursor.execute("PRAGMA table_info(inventory)")
    columns = {row[1] for row in cursor.fetchall()}
    if "vision_device_type" not in columns:
        cursor.execute("ALTER TABLE inventory ADD COLUMN vision_device_type TEXT")
        conn.commit()
    if "lock_status" not in columns:
        cursor.execute("ALTER TABLE inventory ADD COLUMN lock_status TEXT")
        conn.commit()
    if "inventory_number" not in columns:
        cursor.execute("ALTER TABLE inventory ADD COLUMN inventory_number TEXT")
        conn.commit()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS repair_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inventory_id INTEGER NOT NULL,
        job_type TEXT NOT NULL,
        part_name TEXT,
        title TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        sort_order INTEGER NOT NULL DEFAULT 0,
        completed_at TEXT,
        taobao_order_id TEXT,
        taobao_product_name TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (inventory_id) REFERENCES inventory(id) ON DELETE CASCADE
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS taobao_import_batches (
        id TEXT PRIMARY KEY,
        imported_at TEXT DEFAULT (datetime('now')),
        row_count INTEGER NOT NULL DEFAULT 0
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS taobao_import_rows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id TEXT NOT NULL,
        order_id TEXT NOT NULL,
        order_date TEXT,
        order_status TEXT,
        shop_name TEXT,
        product_name TEXT,
        variant TEXT,
        product_link TEXT,
        qty INTEGER NOT NULL DEFAULT 1,
        inferred_part TEXT,
        match_status TEXT,
        matched_job_ids TEXT,
        FOREIGN KEY (batch_id) REFERENCES taobao_import_batches(id)
    )
    ''')

    conn.commit()
    conn.close()
    print("Database initialized.")

if __name__ == '__main__':
    init_db()
