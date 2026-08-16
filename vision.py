"""Call the device-vision classifiers from this inventory app."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VISION_ROOT = Path(
    os.environ.get("DEVICE_VISION_ROOT", ROOT.parent / "device-vision")
)
VISION_URL = os.environ.get("DEVICE_VISION_URL", "http://127.0.0.1:8000")


def upload_url_to_path(image_url: str | None) -> str | None:
    if not image_url:
        return None
    name = Path(image_url).name
    path = ROOT / "uploads" / name
    return str(path) if path.exists() else None


def _assess_local(front_path: str, back_path: str) -> dict | None:
    src = VISION_ROOT / "src"
    if not src.exists():
        return None
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from device_vision.infer import assess

    result = assess(front_path, back_path)
    return {
        "device_type": result.device_type,
        "damage_condition": result.damage_condition(),
        "screen": result.screen,
        "back_glass": result.back_glass,
    }


def _assess_http(front_path: str, back_path: str) -> dict | None:
    import json
    from urllib.request import Request, urlopen

    boundary = "----DeviceVisionBoundary"
    chunks: list[bytes] = []
    for field, path in (("front", front_path), ("back", back_path)):
        name = Path(path).name
        header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{field}"; filename="{name}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        chunks.append(header + Path(path).read_bytes() + b"\r\n")
    body = b"".join(chunks) + f"--{boundary}--\r\n".encode()
    request = Request(
        f"{VISION_URL.rstrip('/')}/assess",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        data = json.loads(response.read().decode())

    return {
        "device_type": data.get("device_type", "unknown"),
        "damage_condition": data.get("damage_condition")
        or "No visible exterior damage",
        "screen": data.get("screen", "unknown"),
        "back_glass": data.get("back_glass", "unknown"),
    }


def analyze_photos(front_image_url: str | None, back_image_url: str | None) -> dict:
    """Return device_type + damage_condition from the trained models."""
    fallback = {
        "device_type": "unknown",
        "damage_condition": "Vision unavailable",
        "screen": "unknown",
        "back_glass": "unknown",
    }
    front_path = upload_url_to_path(front_image_url)
    back_path = upload_url_to_path(back_image_url)
    if not front_path or not back_path:
        print("[vision] missing front or back photo on disk")
        return fallback

    try:
        result = _assess_local(front_path, back_path)
        if result:
            print(f"[vision] local {result}")
            return result
    except Exception as exc:
        print(f"[vision] local inference failed: {exc}")

    try:
        result = _assess_http(front_path, back_path)
        if result:
            print(f"[vision] http {result}")
            return result
    except Exception as exc:
        print(f"[vision] http inference failed: {exc}")

    return fallback
