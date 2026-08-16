# Device Repair Inventory

Flask + SQLite app for a phone repair shop. Intake devices from a phone browser, decode the QR label on the back photo, then review inventory on a desktop dashboard.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

- Dashboard: http://localhost:5000/
- Scanner: http://localhost:5000/scanner.html

On an iPhone, use the computer's LAN IP (or an HTTPS tunnel). Camera capture often requires HTTPS except on localhost.

QR labels are comma-separated:

`Model Name, Color, Capacity, Serial Number, iOS Version, IMEI, Battery Life, Date`
