import os
import uuid
import base64
import sqlite3
import json
from io import BytesIO
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from PIL import Image, ImageEnhance, ImageFilter
from pyzbar.pyzbar import decode as pyzbar_decode
from datetime import datetime, timezone
from database import init_db
from vision import analyze_photos
from repair_parts import determine_parts_needed as map_parts_needed
from ocr_label import extract_label_fields, parse_comma_payload
from taobao_xlsx import parse_taobao_xlsx, upsert_purchases
from llm_classify import (
    get_llm_settings,
    save_llm_settings,
    llm_configured,
    test_llm_connection,
    classify_items,
    CATEGORIES,
    PART_TYPES,
)
from matching import build_suggestions, incoming_parts_by_device

app = Flask(__name__, static_folder='static')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max upload
CORS(app)

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize database on startup
init_db()

def get_db_connection():
    conn = sqlite3.connect('inventory.db', timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn

def analyze_damage_vision_api(front_image_path, back_image_path):
    """Run the device-vision classifiers on saved front/back photos."""
    return analyze_photos(front_image_path, back_image_path)

def parse_battery_percent(battery_health):
    """Extract numeric battery % from values like '87%' or '87'."""
    if battery_health is None:
        return None
    text = str(battery_health).strip()
    if not text:
        return None
    digits = []
    for ch in text:
        if ch.isdigit():
            digits.append(ch)
        elif digits:
            break
    if not digits:
        return None
    try:
        return int("".join(digits))
    except ValueError:
        return None


def determine_parts_needed(damage_condition, remarks, battery_health=None, model=None):
    return map_parts_needed(
        damage_condition,
        remarks,
        battery_health=battery_health,
        model=model,
        parse_battery_percent=parse_battery_percent,
    )

def save_base64_image(base64_string, prefix):
    if not base64_string:
        return None
    
    # Handle data:image/jpeg;base64, prefix if present
    if ',' in base64_string:
        base64_string = base64_string.split(',')[1]
        
    try:
        image_data = base64.b64decode(base64_string)
        filename = f"{prefix}_{uuid.uuid4().hex}.jpg"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        
        with open(filepath, 'wb') as f:
            f.write(image_data)
            
        return f"/uploads/{filename}"
    except Exception as e:
        print(f"Error saving image: {e}")
        return None

def scan_qr_from_image(image_data_b64):
    """
    Server-side QR code scanning using pyzbar + Pillow.
    Tries multiple image processing techniques to find the QR code.
    Returns decoded text or None.
    """
    if not image_data_b64:
        return None
    
    # Strip data URL prefix if present
    if ',' in image_data_b64:
        image_data_b64 = image_data_b64.split(',')[1]
    
    try:
        image_data = base64.b64decode(image_data_b64)
        img = Image.open(BytesIO(image_data))
        print(f"[QR Scan] Image size: {img.size}, mode: {img.mode}")
    except Exception as e:
        print(f"[QR Scan] Failed to open image: {e}")
        return None
    
    # Strategy 1: Scan original image directly
    results = pyzbar_decode(img)
    if results:
        print(f"[QR Scan] Found with original image")
        return results[0].data.decode('utf-8')
    
    # Strategy 2: Convert to grayscale
    gray = img.convert('L')
    results = pyzbar_decode(gray)
    if results:
        print(f"[QR Scan] Found with grayscale")
        return results[0].data.decode('utf-8')
    
    # Strategy 3: Increase contrast + sharpen
    enhancer = ImageEnhance.Contrast(gray)
    high_contrast = enhancer.enhance(2.0)
    sharpened = high_contrast.filter(ImageFilter.SHARPEN)
    results = pyzbar_decode(sharpened)
    if results:
        print(f"[QR Scan] Found with high contrast + sharpen")
        return results[0].data.decode('utf-8')
    
    # Strategy 4: Try multiple scale factors (upscale and downscale)
    for scale in [2.0, 1.5, 0.75, 0.5]:
        new_size = (int(gray.width * scale), int(gray.height * scale))
        resized = gray.resize(new_size, Image.LANCZOS)
        results = pyzbar_decode(resized)
        if results:
            print(f"[QR Scan] Found with scale {scale}")
            return results[0].data.decode('utf-8')
    
    # Strategy 5: Threshold / binarize at different levels
    for threshold in [128, 100, 160]:
        binarized = gray.point(lambda x: 255 if x > threshold else 0)
        results = pyzbar_decode(binarized)
        if results:
            print(f"[QR Scan] Found with binarize threshold {threshold}")
            return results[0].data.decode('utf-8')
    
    # Strategy 6: Upscale 2x + high contrast + binarize
    upscaled = gray.resize((gray.width * 2, gray.height * 2), Image.LANCZOS)
    enhanced = ImageEnhance.Contrast(upscaled).enhance(2.5)
    binarized = enhanced.point(lambda x: 255 if x > 128 else 0)
    results = pyzbar_decode(binarized)
    if results:
        print(f"[QR Scan] Found with upscale+contrast+binarize combo")
        return results[0].data.decode('utf-8')
    
    print(f"[QR Scan] No QR code found after all strategies")
    return None

def parse_qr_text(qr_text):
    """
    Parse QR text into structured fields.

    Current: Model, Color, Capacity, Serial, iOS, IMEI, Battery, Date, Remarks, Lock Status
    Legacy:  Model, Color, Capacity, Serial, iOS, IMEI, Battery, Date
    """
    parsed = parse_comma_payload(qr_text)
    if parsed:
        return parsed

    parts = [p.strip() for p in qr_text.split(',')]
    return {
        'model': parts[0] if parts else 'Unknown',
        'raw_qr': qr_text
    }

# ---- Routes ----

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/scanner.html')
def scanner():
    return app.send_static_file('scanner.html')

@app.route('/uploads/<path:filename>')
def serve_uploads(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

INVENTORY_WITH_LOCATION_SQL = '''
    SELECT i.*,
           CASE
               WHEN s.status = 'received' THEN 'archived'
               WHEN s.status = 'in_transit' THEN 'in_transit'
               ELSE 'in_storage'
           END AS location_status,
           s.tracking_number,
           s.id AS shipment_id
    FROM inventory i
    LEFT JOIN shipment_items si ON si.inventory_id = i.id
    LEFT JOIN shipments s ON s.id = si.shipment_id
'''


def get_inventory_item(conn, item_id):
    row = conn.execute(INVENTORY_WITH_LOCATION_SQL + ' WHERE i.id = ?', (item_id,)).fetchone()
    return dict(row) if row else None


def _shipment_items(conn, shipment_id):
    rows = conn.execute('''
        SELECT i.id, i.model, i.serial_number, i.imei, i.inventory_number,
               i.color, i.capacity, i.lock_status, i.damage_condition
        FROM shipment_items si
        JOIN inventory i ON i.id = si.inventory_id
        WHERE si.shipment_id = ?
        ORDER BY i.id
    ''', (shipment_id,)).fetchall()
    return [dict(r) for r in rows]


def _shipment_payload(conn, shipment):
    data = dict(shipment)
    data['items'] = _shipment_items(conn, data['id'])
    data['item_count'] = len(data['items'])
    return data


def _delete_empty_shipments(conn):
    conn.execute('''
        DELETE FROM shipments
        WHERE NOT EXISTS (
            SELECT 1 FROM shipment_items WHERE shipment_items.shipment_id = shipments.id
        )
    ''')


@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    conn = get_db_connection()
    inventory = conn.execute(INVENTORY_WITH_LOCATION_SQL + ' ORDER BY i.id DESC').fetchall()
    conn.close()
    return jsonify([dict(ix) for ix in inventory])

@app.route('/api/scan', methods=['POST'])
def scan_photos():
    """Scan a dedicated close-up QR label photo (not the full back shot)."""
    data = request.json or {}
    qr_image_b64 = data.get('qr_image') or data.get('back_image') or ''

    if not qr_image_b64:
        return jsonify({'success': False, 'message': 'QR label image is required'}), 400

    qr_text = scan_qr_from_image(qr_image_b64)

    if qr_text:
        parsed = parse_qr_text(qr_text)
        return jsonify({
            'success': True,
            'qr_found': True,
            'qr_raw': qr_text,
            'parsed': parsed
        })

    return jsonify({
        'success': True,
        'qr_found': False,
        'message': 'No QR code detected on the back photo. You can optionally take a zoomed-in label shot or extract the printed text.'
    })


@app.route('/api/ocr', methods=['POST'])
def ocr_label():
    """Read printed label text when the QR code is too small."""
    data = request.json or {}
    image_b64 = data.get('label_image') or data.get('qr_image') or data.get('back_image') or ''
    if not image_b64:
        return jsonify({'success': False, 'message': 'Label image is required'}), 400

    result = extract_label_fields(image_b64)
    status = 200 if result.get('success') else 400
    return jsonify(result), status

@app.route('/api/inventory', methods=['POST'])
def add_inventory():
    data = request.json
    
    model = data.get('model', '')
    color = data.get('color', '')
    capacity = data.get('capacity', '')
    serial_number = data.get('serial_number', '')
    ios_version = data.get('ios_version', '')
    imei = data.get('imei', '')
    battery_health = data.get('battery_health', '')
    date_received = data.get('date_received', '')
    remarks = data.get('remarks', '')
    lock_status = (data.get('lock_status') or '').strip()
    inventory_number = (data.get('inventory_number') or '').strip()
    
    front_image_b64 = data.get('front_image', '')
    back_image_b64 = data.get('back_image', '')
    
    front_image_url = save_base64_image(front_image_b64, "front")
    back_image_url = save_base64_image(back_image_b64, "back")
    
    vision = analyze_damage_vision_api(front_image_url, back_image_url)
    damage_condition = vision.get("damage_condition") or "Vision unavailable"
    vision_device_type = vision.get("device_type") or "unknown"
    if not model and vision_device_type in {"phone", "tablet"}:
        model = vision_device_type.title()
    
    parts_needed = determine_parts_needed(
        damage_condition, remarks, battery_health, model=model
    )
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO inventory (
            date_received, model, color, capacity, serial_number, 
            ios_version, imei, battery_health, remarks, 
            front_image_url, back_image_url, damage_condition, parts_needed,
            vision_device_type, lock_status, inventory_number
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        date_received, model, color, capacity, serial_number,
        ios_version, imei, battery_health, remarks,
        front_image_url, back_image_url, damage_condition, json.dumps(parts_needed),
        vision_device_type, lock_status, inventory_number
    ))
    
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    
    return jsonify({
        "success": True, 
        "id": new_id, 
        "message": "Device added to inventory"
    }), 201


@app.route('/api/inventory/<int:item_id>', methods=['PATCH'])
def update_inventory(item_id):
    """Update editable device fields, parts list, remarks, and condition."""
    data = request.json or {}
    conn = get_db_connection()
    row = conn.execute('SELECT id FROM inventory WHERE id = ?', (item_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'message': 'Item not found'}), 404

    fields = []
    values = []

    if 'parts_needed' in data:
        parts = data['parts_needed']
        if not isinstance(parts, list):
            conn.close()
            return jsonify({'success': False, 'message': 'parts_needed must be a list'}), 400
        cleaned = [str(p).strip() for p in parts if str(p).strip()]
        fields.append('parts_needed = ?')
        values.append(json.dumps(cleaned))

    if 'remarks' in data:
        fields.append('remarks = ?')
        values.append(data.get('remarks') or '')

    if 'damage_condition' in data:
        fields.append('damage_condition = ?')
        values.append(data.get('damage_condition') or '')

    if 'lock_status' in data:
        fields.append('lock_status = ?')
        values.append((data.get('lock_status') or '').strip())

    if 'inventory_number' in data:
        fields.append('inventory_number = ?')
        values.append((data.get('inventory_number') or '').strip())

    text_fields = (
        'model',
        'color',
        'capacity',
        'serial_number',
        'ios_version',
        'imei',
        'battery_health',
        'date_received',
        'vision_device_type',
    )
    for key in text_fields:
        if key in data:
            fields.append(f'{key} = ?')
            values.append((data.get(key) or '').strip())

    if not fields:
        conn.close()
        return jsonify({'success': False, 'message': 'No updatable fields provided'}), 400

    values.append(item_id)
    conn.execute(f"UPDATE inventory SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    updated = get_inventory_item(conn, item_id)
    conn.close()
    return jsonify({'success': True, 'item': updated})


def _delete_upload_file(image_url):
    if not image_url:
        return
    name = os.path.basename(image_url)
    if not name or name in {'.', '..'}:
        return
    path = os.path.join(UPLOAD_FOLDER, name)
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError as exc:
        print(f"Could not delete upload {path}: {exc}")


@app.route('/api/inventory/<int:item_id>', methods=['DELETE'])
def delete_inventory(item_id):
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM inventory WHERE id = ?', (item_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'message': 'Item not found'}), 404

    item = dict(row)
    conn.execute('DELETE FROM inventory WHERE id = ?', (item_id,))
    _delete_empty_shipments(conn)
    conn.commit()
    conn.close()

    _delete_upload_file(item.get('front_image_url'))
    _delete_upload_file(item.get('back_image_url'))

    return jsonify({'success': True, 'message': 'Device deleted'})


# ---- Purchases (Taobao import) ----

@app.route('/api/purchases/import', methods=['POST'])
def import_purchases():
    """Import one or more Taobao xlsx exports (paid/shipped/received)."""
    files = request.files.getlist('files') or request.files.getlist('file')
    if not files:
        return jsonify({'success': False, 'message': 'No files uploaded'}), 400

    conn = get_db_connection()
    results = []
    any_ok = False
    for f in files:
        entry = {'filename': f.filename}
        try:
            rows = parse_taobao_xlsx(f.stream)
            counts = upsert_purchases(conn, rows)
            entry.update({'success': True, 'rows': len(rows), **counts})
            any_ok = True
        except Exception as exc:
            entry.update({'success': False, 'message': str(exc)})
        results.append(entry)
    conn.close()

    status = 200 if any_ok else 400
    return jsonify({'success': any_ok, 'files': results}), status


@app.route('/api/purchases/classify', methods=['POST'])
def classify_purchases():
    """Run LLM classification on unclassified items (or explicit item_ids)."""
    data = request.json or {}
    item_ids = data.get('item_ids')
    conn = get_db_connection()
    summary = classify_items(conn, item_ids=item_ids)
    conn.close()
    ok = summary.get('error') is None
    return jsonify({'success': ok, **summary}), 200 if ok else 502


@app.route('/api/purchases', methods=['GET'])
def get_purchases():
    review_status = request.args.get('review_status')
    conn = get_db_connection()

    query = '''
        SELECT p.*, o.submit_time, o.status AS order_status, o.shop_name,
               o.logistics_company, o.tracking_no
        FROM purchase_items p
        JOIN purchase_orders o ON o.order_no = p.order_no
    '''
    params = []
    if review_status:
        query += ' WHERE p.review_status = ?'
        params.append(review_status)
    query += ' ORDER BY o.submit_time DESC, p.order_no, p.id'

    items = [dict(r) for r in conn.execute(query, params).fetchall()]

    link_rows = conn.execute('''
        SELECT l.id AS link_id, l.purchase_item_id, l.inventory_id, l.qty,
               i.model, i.inventory_number, i.serial_number
        FROM item_device_links l
        JOIN inventory i ON i.id = l.inventory_id
    ''').fetchall()
    links_by_item = {}
    for row in link_rows:
        links_by_item.setdefault(row['purchase_item_id'], []).append(dict(row))

    suggestions = build_suggestions(conn, items)
    conn.close()

    for item in items:
        try:
            item['models'] = json.loads(item.get('models') or '[]')
        except (ValueError, TypeError):
            item['models'] = []
        item['links'] = links_by_item.get(item['id'], [])
        item['suggestions'] = suggestions.get(item['id'], [])

    return jsonify({
        'items': items,
        'categories': sorted(CATEGORIES),
        'part_types': sorted(PART_TYPES),
    })


@app.route('/api/purchases/items/<int:item_id>', methods=['PATCH'])
def update_purchase_item(item_id):
    """Manual edits to classification / review status."""
    data = request.json or {}
    conn = get_db_connection()
    row = conn.execute('SELECT id FROM purchase_items WHERE id = ?', (item_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'message': 'Item not found'}), 404

    fields = []
    values = []
    manual_edit = False

    if 'category' in data:
        category = str(data['category'] or 'unknown').strip().lower()
        if category not in CATEGORIES:
            conn.close()
            return jsonify({'success': False, 'message': f'Invalid category: {category}'}), 400
        fields.append('category = ?')
        values.append(category)
        manual_edit = True
        if category != 'part':
            fields.append('part_type = ?')
            values.append(None)

    if 'part_type' in data:
        part_type = data['part_type']
        if part_type is not None:
            part_type = str(part_type).strip().lower() or None
        if part_type is not None and part_type not in PART_TYPES:
            conn.close()
            return jsonify({'success': False, 'message': f'Invalid part_type: {part_type}'}), 400
        fields.append('part_type = ?')
        values.append(part_type)
        manual_edit = True

    if 'models' in data:
        models = data['models']
        if isinstance(models, str):
            models = [m.strip() for m in models.split(',') if m.strip()]
        if not isinstance(models, list):
            conn.close()
            return jsonify({'success': False, 'message': 'models must be a list'}), 400
        fields.append('models = ?')
        values.append(json.dumps([str(m).strip() for m in models], ensure_ascii=False))
        manual_edit = True

    if 'review_status' in data:
        review = str(data['review_status'] or 'pending').strip().lower()
        if review not in {'pending', 'confirmed', 'dismissed'}:
            conn.close()
            return jsonify({'success': False, 'message': f'Invalid review_status: {review}'}), 400
        fields.append('review_status = ?')
        values.append(review)

    if manual_edit:
        fields.append("classified_by = 'manual'")

    if not fields:
        conn.close()
        return jsonify({'success': False, 'message': 'No updatable fields provided'}), 400

    values.append(item_id)
    conn.execute(f"UPDATE purchase_items SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    updated = dict(conn.execute('SELECT * FROM purchase_items WHERE id = ?', (item_id,)).fetchone())
    conn.close()
    try:
        updated['models'] = json.loads(updated.get('models') or '[]')
    except (ValueError, TypeError):
        updated['models'] = []
    return jsonify({'success': True, 'item': updated})


@app.route('/api/purchases/items/<int:item_id>/links', methods=['POST'])
def link_purchase_item(item_id):
    """Allocate a purchased item to a device (confirmed by the user)."""
    data = request.json or {}
    inventory_id = data.get('inventory_id')
    qty = max(1, int(data.get('qty') or 1))
    if not inventory_id:
        return jsonify({'success': False, 'message': 'inventory_id is required'}), 400

    conn = get_db_connection()
    item = conn.execute('SELECT * FROM purchase_items WHERE id = ?', (item_id,)).fetchone()
    device = conn.execute('SELECT id FROM inventory WHERE id = ?', (inventory_id,)).fetchone()
    if not item or not device:
        conn.close()
        return jsonify({'success': False, 'message': 'Item or device not found'}), 404

    allocated = conn.execute(
        'SELECT COALESCE(SUM(qty), 0) FROM item_device_links WHERE purchase_item_id = ?',
        (item_id,),
    ).fetchone()[0]
    if allocated + qty > (item['quantity'] or 1):
        conn.close()
        return jsonify({
            'success': False,
            'message': f'Only {(item["quantity"] or 1) - allocated} of this item left to allocate',
        }), 400

    try:
        conn.execute(
            'INSERT INTO item_device_links (purchase_item_id, inventory_id, qty, created_at) '
            'VALUES (?, ?, ?, ?)',
            (item_id, inventory_id, qty, datetime.now(timezone.utc).isoformat()),
        )
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'success': False, 'message': 'Already linked to this device'}), 409
    conn.commit()
    conn.close()
    return jsonify({'success': True}), 201


@app.route('/api/purchases/items/<int:item_id>/links/<int:link_id>', methods=['DELETE'])
def unlink_purchase_item(item_id, link_id):
    conn = get_db_connection()
    row = conn.execute(
        'SELECT id FROM item_device_links WHERE id = ? AND purchase_item_id = ?',
        (link_id, item_id),
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'message': 'Link not found'}), 404
    conn.execute('DELETE FROM item_device_links WHERE id = ?', (link_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/inventory/<int:item_id>/incoming-parts', methods=['GET'])
def device_incoming_parts(item_id):
    """Parts allocated to this device with their shipping status."""
    conn = get_db_connection()
    incoming = incoming_parts_by_device(conn, inventory_id=item_id)
    conn.close()
    return jsonify(incoming.get(item_id, []))


@app.route('/api/inventory/incoming-parts', methods=['GET'])
def all_incoming_parts():
    """Allocated parts for every device, keyed by inventory id."""
    conn = get_db_connection()
    incoming = incoming_parts_by_device(conn)
    conn.close()
    return jsonify({str(device_id): parts for device_id, parts in incoming.items()})


# ---- Shipments ----

@app.route('/api/shipments', methods=['GET'])
def list_shipments():
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT * FROM shipments
        ORDER BY CASE status WHEN 'in_transit' THEN 0 ELSE 1 END, id DESC
    ''').fetchall()
    shipments = [_shipment_payload(conn, row) for row in rows]
    conn.close()
    return jsonify(shipments)


@app.route('/api/shipments', methods=['POST'])
def create_shipment():
    data = request.json or {}
    tracking_number = str(data.get('tracking_number') or '').strip()
    raw_ids = data.get('inventory_ids') or []
    if not tracking_number:
        return jsonify({'success': False, 'message': 'Tracking number is required'}), 400
    if not isinstance(raw_ids, list) or not raw_ids:
        return jsonify({'success': False, 'message': 'Select at least one device'}), 400

    try:
        inventory_ids = sorted({int(item_id) for item_id in raw_ids})
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'inventory_ids must be integers'}), 400

    conn = get_db_connection()
    placeholders = ','.join('?' * len(inventory_ids))
    found = {
        row['id']
        for row in conn.execute(
            f'SELECT id FROM inventory WHERE id IN ({placeholders})',
            inventory_ids,
        ).fetchall()
    }
    missing = [item_id for item_id in inventory_ids if item_id not in found]
    if missing:
        conn.close()
        return jsonify({
            'success': False,
            'message': f'Device(s) not found: {", ".join("#" + str(i) for i in missing)}',
        }), 400

    already = conn.execute(
        f'''
        SELECT si.inventory_id, s.tracking_number, s.status
        FROM shipment_items si
        JOIN shipments s ON s.id = si.shipment_id
        WHERE si.inventory_id IN ({placeholders})
        ''',
        inventory_ids,
    ).fetchall()
    if already:
        conn.close()
        labels = [
            f"#{row['inventory_id']} ({row['tracking_number']})"
            for row in already
        ]
        return jsonify({
            'success': False,
            'message': 'Already on a shipment: ' + ', '.join(labels),
        }), 409

    created_at = datetime.now(timezone.utc).isoformat()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO shipments (tracking_number, status, created_at) VALUES (?, ?, ?)',
        (tracking_number, 'in_transit', created_at),
    )
    shipment_id = cursor.lastrowid
    cursor.executemany(
        'INSERT INTO shipment_items (shipment_id, inventory_id) VALUES (?, ?)',
        [(shipment_id, item_id) for item_id in inventory_ids],
    )
    conn.commit()
    shipment = _shipment_payload(
        conn,
        conn.execute('SELECT * FROM shipments WHERE id = ?', (shipment_id,)).fetchone(),
    )
    conn.close()
    return jsonify({'success': True, 'shipment': shipment}), 201


@app.route('/api/shipments/<int:shipment_id>', methods=['DELETE'])
def cancel_shipment(shipment_id):
    conn = get_db_connection()
    shipment = conn.execute('SELECT * FROM shipments WHERE id = ?', (shipment_id,)).fetchone()
    if not shipment:
        conn.close()
        return jsonify({'success': False, 'message': 'Shipment not found'}), 404
    if shipment['status'] == 'received':
        conn.close()
        return jsonify({'success': False, 'message': 'Cannot cancel a received shipment'}), 409

    conn.execute('DELETE FROM shipments WHERE id = ?', (shipment_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/shipments/<int:shipment_id>/items/<int:inventory_id>', methods=['DELETE'])
def remove_shipment_item(shipment_id, inventory_id):
    conn = get_db_connection()
    shipment = conn.execute('SELECT * FROM shipments WHERE id = ?', (shipment_id,)).fetchone()
    if not shipment:
        conn.close()
        return jsonify({'success': False, 'message': 'Shipment not found'}), 404
    if shipment['status'] == 'received':
        conn.close()
        return jsonify({'success': False, 'message': 'Cannot edit a received shipment'}), 409

    row = conn.execute(
        'SELECT id FROM shipment_items WHERE shipment_id = ? AND inventory_id = ?',
        (shipment_id, inventory_id),
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'message': 'Device is not on this shipment'}), 404

    conn.execute(
        'DELETE FROM shipment_items WHERE shipment_id = ? AND inventory_id = ?',
        (shipment_id, inventory_id),
    )
    _delete_empty_shipments(conn)
    conn.commit()
    remaining = conn.execute('SELECT * FROM shipments WHERE id = ?', (shipment_id,)).fetchone()
    payload = _shipment_payload(conn, remaining) if remaining else None
    conn.close()
    if payload:
        return jsonify({'success': True, 'deleted': False, 'shipment': payload})
    return jsonify({'success': True, 'deleted': True})


@app.route('/api/shipments/<int:shipment_id>/receive', methods=['POST'])
def receive_shipment(shipment_id):
    conn = get_db_connection()
    shipment = conn.execute('SELECT * FROM shipments WHERE id = ?', (shipment_id,)).fetchone()
    if not shipment:
        conn.close()
        return jsonify({'success': False, 'message': 'Shipment not found'}), 404
    if shipment['status'] == 'received':
        conn.close()
        return jsonify({'success': False, 'message': 'Shipment is already marked received'}), 409

    received_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE shipments SET status = 'received', received_at = ? WHERE id = ?",
        (received_at, shipment_id),
    )
    conn.commit()
    updated = _shipment_payload(
        conn,
        conn.execute('SELECT * FROM shipments WHERE id = ?', (shipment_id,)).fetchone(),
    )
    conn.close()
    return jsonify({'success': True, 'shipment': updated})


# ---- LLM settings ----

@app.route('/api/settings/llm', methods=['GET'])
def get_llm_settings_route():
    conn = get_db_connection()
    settings = get_llm_settings(conn)
    conn.close()
    return jsonify({
        'llm_base_url': settings['llm_base_url'],
        'llm_model': settings['llm_model'],
        'llm_api_key_set': bool(settings['llm_api_key']),
        'configured': llm_configured(settings),
    })


@app.route('/api/settings/llm', methods=['PUT'])
def put_llm_settings_route():
    data = request.json or {}
    payload = {}
    for key in ('llm_base_url', 'llm_model'):
        if key in data:
            payload[key] = data[key]
    # Only overwrite the key when a non-empty value is sent, so the masked
    # placeholder from the UI never wipes a stored key.
    if data.get('llm_api_key'):
        payload['llm_api_key'] = data['llm_api_key']
    conn = get_db_connection()
    save_llm_settings(conn, payload)
    settings = get_llm_settings(conn)
    conn.close()
    return jsonify({'success': True, 'configured': llm_configured(settings)})


@app.route('/api/settings/llm/test', methods=['POST'])
def test_llm_settings_route():
    conn = get_db_connection()
    settings = get_llm_settings(conn)
    conn.close()
    ok, message = test_llm_connection(settings)
    return jsonify({'success': ok, 'message': message}), 200 if ok else 502


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
