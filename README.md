# Device Repair Inventory

Flask + SQLite app for a phone repair shop. Intake devices from a phone browser with front and back photos (optional zoomed QR if needed), then review inventory on a desktop dashboard.

Exterior damage and phone-vs-tablet classification come from the sibling [device-vision](https://github.com/Scratchycarl/device-vision) models (local import or HTTP to the vision API).

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

For local vision inference without running the vision API separately, use the device-vision venv (has Ultralytics) or install `ultralytics` / keep `DEVICE_VISION_URL` pointed at http://127.0.0.1:8000.

- Dashboard: http://localhost:5000/
- Scanner: http://localhost:5000/scanner.html

On a phone, use the computer's LAN IP (or an HTTPS tunnel). Camera capture often requires HTTPS except on localhost.

## Scanner flow

1. Front photo (screen)
2. Back photo (full device — used for vision + QR)

If QR isn’t found on the back photo, you can optionally check **Take a zoomed-in photo of the QR label** and shoot a close-up.

QR labels are comma-separated:

`Model Name, Color, Capacity, Serial Number, iOS Version, IMEI, Battery Life, Date`

Uploads and `inventory.db` stay local (gitignored).
