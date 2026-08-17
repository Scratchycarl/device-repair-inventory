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
from ocr_label import extract_label_fields

app = Flask(__name__, static_folder='static')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max upload
CORS(app)

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize database on startup
init_db()

def get_db_connection():
    conn = sqlite3.connect('inventory.db')
    conn.row_factory = sqlite3.Row
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
    Expected format: Model Name, Color, Capacity, Serial Number, iOS Version, IMEI, Battery Life, Date
    """
    parts = [p.strip() for p in qr_text.split(',')]
    
    if len(parts) >= 8:
        return {
            'model': parts[0],
            'color': parts[1],
            'capacity': parts[2],
            'serial_number': parts[3],
            'ios_version': parts[4],
            'imei': parts[5],
            'battery_health': parts[6],
            'date_received': parts[7]
        }
    else:
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
    """Update editable fields (parts list, remarks, condition)."""
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

    if not fields:
        conn.close()
        return jsonify({'success': False, 'message': 'No updatable fields provided'}), 400

    values.append(item_id)
    conn.execute(f"UPDATE inventory SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    updated = conn.execute('SELECT * FROM inventory WHERE id = ?', (item_id,)).fetchone()
    conn.close()
    return jsonify({'success': True, 'item': dict(updated)})


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
    conn.commit()
    conn.close()

    _delete_upload_file(item.get('front_image_url'))
    _delete_upload_file(item.get('back_image_url'))

    return jsonify({'success': True, 'message': 'Device deleted'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
