import sqlite3

def init_db():
    conn = sqlite3.connect('inventory.db', timeout=30)
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
    CREATE TABLE IF NOT EXISTS purchase_orders (
        order_no TEXT PRIMARY KEY,
        submit_time TEXT,
        status TEXT DEFAULT 'paid',
        shop_name TEXT,
        order_total REAL,
        shipping_fee REAL,
        logistics_company TEXT,
        tracking_no TEXT,
        imported_at TEXT
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS purchase_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_no TEXT NOT NULL REFERENCES purchase_orders(order_no) ON DELETE CASCADE,
        item_title TEXT NOT NULL,
        item_link TEXT,
        sku_text TEXT,
        quantity INTEGER DEFAULT 1,
        unit_price REAL,
        category TEXT DEFAULT 'unknown',
        part_type TEXT,
        models TEXT DEFAULT '[]',
        confidence REAL,
        classified_by TEXT,
        review_status TEXT DEFAULT 'pending',
        notes TEXT,
        UNIQUE(order_no, item_title, sku_text)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS item_device_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        purchase_item_id INTEGER NOT NULL REFERENCES purchase_items(id) ON DELETE CASCADE,
        inventory_id INTEGER NOT NULL REFERENCES inventory(id) ON DELETE CASCADE,
        qty INTEGER DEFAULT 1,
        created_at TEXT,
        UNIQUE(purchase_item_id, inventory_id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS llm_classify_cache (
        cache_key TEXT PRIMARY KEY,
        result TEXT,
        created_at TEXT
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS shipments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tracking_number TEXT NOT NULL,
        status TEXT DEFAULT 'in_transit',
        created_at TEXT,
        received_at TEXT
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS shipment_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shipment_id INTEGER NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
        inventory_id INTEGER NOT NULL REFERENCES inventory(id) ON DELETE CASCADE,
        UNIQUE(inventory_id)
    )
    ''')

    conn.commit()
    conn.close()
    print("Database initialized.")

if __name__ == '__main__':
    init_db()
