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
    conn.close()
    print("Database initialized.")

if __name__ == '__main__':
    init_db()
