# AGENTS.md

## Cursor Cloud specific instructions

This is a single Flask + SQLite app ("Device Repair Inventory"). See `README.md` for the product overview and scanner flow.

### Services

- **Flask app** — the only service. Run it with the project venv: `.venv/bin/python app.py`. It serves on `0.0.0.0:5000` with `debug=True` (auto-reload on file changes).
  - Dashboard: `http://localhost:5000/`
  - Scanner (mobile intake): `http://localhost:5000/scanner.html`
  - JSON API: `GET/POST /api/inventory`, `PATCH/DELETE /api/inventory/<id>`, `POST /api/scan` (QR), `POST /api/ocr` (label OCR).
- **SQLite** is embedded (`inventory.db`, auto-created/migrated at startup by `database.py`). There is no separate database server. `inventory.db` and `uploads/` are gitignored.

### Environment / gotchas

- Python dependencies live in a **virtualenv at `.venv`** (the update script creates it and installs `requirements.txt`). Always invoke Python via `.venv/bin/python` / `.venv/bin/pip`.
- **`pyzbar` needs the native `libzbar0` system library.** It is baked into the environment snapshot. If `from pyzbar.pyzbar import decode` fails to load the shared library, reinstall with `sudo apt-get install -y libzbar0` — this is the most common startup gotcha.
- `rapidocr-onnxruntime` (used by `/api/ocr`) pulls in `opencv-python`/`onnxruntime`; the first OCR call lazily initializes and may be slow.
- The **`device-vision`** ML integration (damage classification / phone-vs-tablet) is **optional**. It is a separate repo and is not installed here. Without it the app gracefully returns `damage_condition: "Vision unavailable"` and `device_type: "unknown"`, and the rest of the app works fully. To enable it, set `DEVICE_VISION_ROOT` (local import) or `DEVICE_VISION_URL` (HTTP, default `http://127.0.0.1:8000`).

### Lint / test / build

- No linter, test suite, or build step is configured (frontend is static, served directly by Flask). "Build" is a no-op.
