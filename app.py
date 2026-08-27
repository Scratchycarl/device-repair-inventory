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
from database import init_db
from vision import analyze_photos
from repair_parts import determine_parts_needed as map_parts_needed
from ocr_label import extract_label_fields, parse_comma_payload
from parts_format import parse_parts, serialize_parts
from repair_jobs import sync_repair_jobs, fetch_jobs_for_inventory, fetch_job_counts
from taobao_import_apply import apply_taobao_import, apply_taobao_llm_retry
from part_orders import (
    STAGE_LABELS,
    delete_part_order_for_job,
    get_part_order,
    get_part_order_by_job,
    list_assignable_part_orders,
    list_warehouse_shipments,
    create_warehouse_shipment,
    get_warehouse_shipment,
    set_shipping_stage,
    save_domestic_tracking,
)
from shipping_tracker import fetch_domestic_tracking, resolve_carrier_code
from app_settings import get_settings, public_settings, update_settings
from llm_match import llm_configured, test_llm_connection

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


def _sync_all_repair_jobs():
    conn = get_db_connection()
    rows = conn.execute("SELECT id, parts_needed FROM inventory").fetchall()
    for row in rows:
        sync_repair_jobs(conn, row["id"], row["parts_needed"])
    conn.commit()
    conn.close()


_sync_all_repair_jobs()

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

@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    conn = get_db_connection()
    inventory = conn.execute('SELECT * FROM inventory ORDER BY id DESC').fetchall()
    job_counts = fetch_job_counts(conn)
    conn.close()
    items = []
    for ix in inventory:
        item = dict(ix)
        counts = job_counts.get(item["id"], {"pending": 0, "total": 0})
        item["pending_jobs"] = counts["pending"]
        item["total_jobs"] = counts["total"]
        items.append(item)
    return jsonify(items)

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
    parts_json = serialize_parts([{"name": p, "needs_programming": False} for p in parts_needed])
    
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
        front_image_url, back_image_url, damage_condition, parts_json,
        vision_device_type, lock_status, inventory_number
    ))
    
    conn.commit()
    new_id = cursor.lastrowid
    sync_repair_jobs(conn, new_id, parts_json)
    conn.commit()
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
        parts_json = serialize_parts(parts)
        fields.append('parts_needed = ?')
        values.append(parts_json)

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
    if 'parts_needed' in data:
        sync_repair_jobs(conn, item_id, parts_json)
    conn.commit()
    updated = conn.execute('SELECT * FROM inventory WHERE id = ?', (item_id,)).fetchone()
    row_dict = dict(updated)
    counts = fetch_job_counts(conn).get(item_id, {"pending": 0, "total": 0})
    row_dict["pending_jobs"] = counts["pending"]
    row_dict["total_jobs"] = counts["total"]
    conn.close()
    return jsonify({'success': True, 'item': row_dict})


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
    conn.execute('DELETE FROM part_orders WHERE inventory_id = ?', (item_id,))
    conn.execute('DELETE FROM repair_jobs WHERE inventory_id = ?', (item_id,))
    conn.execute('DELETE FROM inventory WHERE id = ?', (item_id,))
    conn.commit()
    conn.close()

    _delete_upload_file(item.get('front_image_url'))
    _delete_upload_file(item.get('back_image_url'))

    return jsonify({'success': True, 'message': 'Device deleted'})


@app.route('/api/inventory/<int:item_id>/jobs', methods=['GET'])
def get_inventory_jobs(item_id):
    conn = get_db_connection()
    row = conn.execute('SELECT id FROM inventory WHERE id = ?', (item_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'message': 'Item not found'}), 404
    jobs = fetch_jobs_for_inventory(conn, item_id)
    enriched = []
    for job in jobs:
        j = dict(job)
        if j.get('job_type') == 'order_part':
            po = get_part_order_by_job(conn, j['id'])
            if po:
                j['part_order'] = {
                    'id': po['id'],
                    'shipping_stage': po['shipping_stage'],
                    'shipping_label': STAGE_LABELS.get(po['shipping_stage'], po['shipping_stage']),
                    'taobao_order_id': po['taobao_order_id'],
                    'domestic_carrier': po.get('domestic_carrier'),
                    'domestic_tracking_number': po.get('domestic_tracking_number'),
                }
        enriched.append(j)
    conn.close()
    return jsonify({'success': True, 'jobs': enriched})


@app.route('/api/inventory/<int:item_id>/jobs', methods=['POST'])
def add_custom_job(item_id):
    data = request.json or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'success': False, 'message': 'title is required'}), 400

    conn = get_db_connection()
    row = conn.execute('SELECT id FROM inventory WHERE id = ?', (item_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'message': 'Item not found'}), 404

    max_sort = conn.execute(
        'SELECT COALESCE(MAX(sort_order), 0) AS m FROM repair_jobs WHERE inventory_id = ?',
        (item_id,),
    ).fetchone()['m']

    cursor = conn.cursor()
    cursor.execute(
        '''
        INSERT INTO repair_jobs (inventory_id, job_type, part_name, title, status, sort_order)
        VALUES (?, 'custom', NULL, ?, 'pending', ?)
        ''',
        (item_id, title, max_sort + 1),
    )
    conn.commit()
    job = dict(conn.execute('SELECT * FROM repair_jobs WHERE id = ?', (cursor.lastrowid,)).fetchone())
    conn.close()
    return jsonify({'success': True, 'job': job}), 201


@app.route('/api/jobs/<int:job_id>', methods=['PATCH'])
def update_job(job_id):
    data = request.json or {}
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM repair_jobs WHERE id = ?', (job_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'message': 'Job not found'}), 404

    fields = []
    values = []
    if 'status' in data:
        status = data['status']
        if status not in ('pending', 'done'):
            conn.close()
            return jsonify({'success': False, 'message': 'status must be pending or done'}), 400
        fields.append('status = ?')
        values.append(status)
        if status == 'done':
            fields.append("completed_at = datetime('now')")
        else:
            fields.append('completed_at = NULL')
            fields.append('taobao_order_id = NULL')
            fields.append('taobao_product_name = NULL')
            if row['job_type'] == 'order_part':
                delete_part_order_for_job(conn, job_id)

    if 'title' in data and row['job_type'] == 'custom':
        title = (data.get('title') or '').strip()
        if title:
            fields.append('title = ?')
            values.append(title)

    if not fields:
        conn.close()
        return jsonify({'success': False, 'message': 'No updatable fields'}), 400

    values.append(job_id)
    conn.execute(f"UPDATE repair_jobs SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    job = dict(conn.execute('SELECT * FROM repair_jobs WHERE id = ?', (job_id,)).fetchone())
    conn.close()
    return jsonify({'success': True, 'job': job})


@app.route('/api/jobs/<int:job_id>', methods=['DELETE'])
def delete_job(job_id):
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM repair_jobs WHERE id = ?', (job_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'message': 'Job not found'}), 404
    if row['job_type'] != 'custom':
        conn.close()
        return jsonify({'success': False, 'message': 'Only custom jobs can be deleted'}), 400
    conn.execute('DELETE FROM repair_jobs WHERE id = ?', (job_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/taobao/import', methods=['POST'])
def import_taobao():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'file is required'}), 400
    upload = request.files['file']
    if not upload.filename:
        return jsonify({'success': False, 'message': 'Empty filename'}), 400
    if not upload.filename.lower().endswith(('.xlsx', '.xlsm')):
        return jsonify({'success': False, 'message': 'Upload a .xlsx Taobao export'}), 400

    conn = get_db_connection()
    try:
        result = apply_taobao_import(conn, upload.read())
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        print(f"[taobao] import error: {exc}")
        return jsonify({'success': False, 'message': 'Failed to parse spreadsheet'}), 500
    finally:
        conn.close()

    return jsonify({'success': True, **result})


@app.route('/api/taobao/import/<batch_id>/llm-match', methods=['POST'])
def taobao_llm_match(batch_id):
    conn = get_db_connection()
    try:
        settings = get_settings(conn)
        if (settings.get('llm_enabled') or '0') != '1':
            return jsonify({
                'success': False,
                'message': 'Turn on Enable LLM matching in Settings, then Save.',
            }), 400
        if not llm_configured(settings):
            return jsonify({
                'success': False,
                'message': 'Configure the LLM API in Settings first.',
            }), 400
        result = apply_taobao_llm_retry(conn, batch_id, settings)
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        print(f"[taobao] llm match error: {exc}")
        return jsonify({'success': False, 'message': 'LLM matching failed'}), 500
    finally:
        conn.close()

    return jsonify({'success': True, **result})


@app.route('/api/settings', methods=['GET'])
def settings_get():
    conn = get_db_connection()
    data = public_settings(get_settings(conn))
    conn.close()
    return jsonify({'success': True, **data})


@app.route('/api/settings', methods=['PUT'])
def settings_put():
    payload = request.json or {}
    conn = get_db_connection()
    updated = update_settings(conn, payload)
    conn.commit()
    public = public_settings(updated)
    conn.close()
    return jsonify({'success': True, **public})


@app.route('/api/settings/test-llm', methods=['POST'])
def settings_test_llm():
    payload = request.json or {}
    conn = get_db_connection()
    settings = get_settings(conn)
    conn.close()
    if payload.get('llm_base_url'):
        settings['llm_base_url'] = str(payload['llm_base_url']).strip().rstrip('/')
    if payload.get('llm_model'):
        settings['llm_model'] = str(payload['llm_model']).strip()
    new_key = str(payload.get('llm_api_key') or '').strip()
    if new_key and not set(new_key) <= {'•', '*'}:
        settings['llm_api_key'] = new_key
    result = test_llm_connection(settings)
    status = 200 if result.get('success') else 400
    return jsonify(result), status


@app.route('/api/part-orders/<int:part_order_id>', methods=['GET'])
def part_order_detail(part_order_id):
    conn = get_db_connection()
    po = get_part_order(conn, part_order_id)
    conn.close()
    if not po:
        return jsonify({'success': False, 'message': 'Part order not found'}), 404
    return jsonify({'success': True, 'part_order': po})


@app.route('/api/part-orders/<int:part_order_id>', methods=['PATCH'])
def part_order_update(part_order_id):
    data = request.json or {}
    conn = get_db_connection()
    po = get_part_order(conn, part_order_id)
    if not po:
        conn.close()
        return jsonify({'success': False, 'message': 'Part order not found'}), 404
    if 'shipping_stage' in data:
        po = set_shipping_stage(conn, part_order_id, data['shipping_stage'])
    if data.get('domestic_carrier') or data.get('domestic_tracking_number'):
        carrier = (data.get('domestic_carrier') or po.get('domestic_carrier') or '').strip()
        tracking = (data.get('domestic_tracking_number') or po.get('domestic_tracking_number') or '').strip()
        code = resolve_carrier_code(carrier, tracking)
        result = fetch_domestic_tracking(code or '', tracking) if tracking else {'success': False, 'events': []}
        po = save_domestic_tracking(conn, part_order_id, result.get('carrier_code') or carrier, tracking, result)
    conn.commit()
    po = get_part_order(conn, part_order_id)
    conn.close()
    return jsonify({'success': True, 'part_order': po})


@app.route('/api/part-orders/<int:part_order_id>/refresh-tracking', methods=['POST'])
def part_order_refresh_tracking(part_order_id):
    conn = get_db_connection()
    po = get_part_order(conn, part_order_id)
    if not po:
        conn.close()
        return jsonify({'success': False, 'message': 'Part order not found'}), 404
    tracking = po.get('domestic_tracking_number') or ''
    if not tracking:
        conn.close()
        return jsonify({'success': False, 'message': 'No domestic tracking number on this order'}), 400
    code = resolve_carrier_code(po.get('domestic_carrier') or '', tracking)
    result = fetch_domestic_tracking(code or '', tracking)
    po = save_domestic_tracking(
        conn,
        part_order_id,
        result.get('carrier_code') or po.get('domestic_carrier') or '',
        tracking,
        result,
    )
    conn.commit()
    po = get_part_order(conn, part_order_id)
    conn.close()
    return jsonify({'success': True, 'part_order': po, 'tracking': result})


@app.route('/api/part-orders/assignable', methods=['GET'])
def part_orders_assignable():
    conn = get_db_connection()
    items = list_assignable_part_orders(conn)
    conn.close()
    return jsonify({'success': True, 'part_orders': items})


@app.route('/api/warehouse-shipments', methods=['GET'])
def warehouse_shipments_list():
    conn = get_db_connection()
    shipments = list_warehouse_shipments(conn)
    conn.close()
    return jsonify({'success': True, 'shipments': shipments})


@app.route('/api/warehouse-shipments', methods=['POST'])
def warehouse_shipments_create():
    data = request.json or {}
    tracking = (data.get('tracking_number') or '').strip()
    carrier = (data.get('carrier') or '').strip()
    notes = (data.get('notes') or '').strip()
    part_order_ids = data.get('part_order_ids') or []
    if not isinstance(part_order_ids, list):
        return jsonify({'success': False, 'message': 'part_order_ids must be a list'}), 400
    try:
        conn = get_db_connection()
        shipment = create_warehouse_shipment(
            conn,
            tracking_number=tracking,
            carrier=carrier,
            notes=notes,
            part_order_ids=[int(x) for x in part_order_ids],
        )
        conn.commit()
        conn.close()
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    return jsonify({'success': True, 'shipment': shipment}), 201


@app.route('/api/warehouse-shipments/<int:shipment_id>', methods=['GET'])
def warehouse_shipment_detail(shipment_id):
    conn = get_db_connection()
    try:
        shipment = get_warehouse_shipment(conn, shipment_id)
    except ValueError as exc:
        conn.close()
        return jsonify({'success': False, 'message': str(exc)}), 404
    conn.close()
    return jsonify({'success': True, 'shipment': shipment})


@app.route('/api/warehouse-shipments/<int:shipment_id>', methods=['PATCH'])
def warehouse_shipment_update(shipment_id):
    data = request.json or {}
    conn = get_db_connection()
    row = conn.execute('SELECT id FROM warehouse_shipments WHERE id = ?', (shipment_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'message': 'Shipment not found'}), 404
    fields = []
    values = []
    for key in ('tracking_number', 'carrier', 'notes', 'status'):
        if key in data:
            fields.append(f'{key} = ?')
            values.append((data.get(key) or '').strip())
    if fields:
        fields.append("updated_at = datetime('now')")
        values.append(shipment_id)
        conn.execute(f"UPDATE warehouse_shipments SET {', '.join(fields)} WHERE id = ?", values)
    if data.get('mark_delivered'):
        conn.execute(
            "UPDATE warehouse_shipments SET status = 'delivered', updated_at = datetime('now') WHERE id = ?",
            (shipment_id,),
        )
        conn.execute(
            """
            UPDATE part_orders SET shipping_stage = 'delivered', updated_at = datetime('now')
            WHERE warehouse_shipment_id = ?
            """,
            (shipment_id,),
        )
    conn.commit()
    shipment = get_warehouse_shipment(conn, shipment_id)
    conn.close()
    return jsonify({'success': True, 'shipment': shipment})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
