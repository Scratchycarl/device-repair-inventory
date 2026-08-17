"""OCR a printed device label when the QR code is too small to scan."""

from __future__ import annotations

import re
from io import BytesIO

from PIL import Image, ImageEnhance, ImageOps

_ENGINE = None

COLORS = [
    "midnight",
    "starlight",
    "space gray",
    "space grey",
    "space black",
    "graphite",
    "silver",
    "gold",
    "rose gold",
    "yellow",
    "coral",
    "orange",
    "red",
    "product red",
    "blue",
    "pacific blue",
    "sierra blue",
    "alpine green",
    "green",
    "purple",
    "deep purple",
    "pink",
    "white",
    "black",
    "natural titanium",
    "black titanium",
    "white titanium",
    "blue titanium",
    "desert titanium",
    "ultramarine",
    "teal",
]

LOCK_UNLOCKED = "Unlocked"
LOCK_LOCKED = "Locked (FMI ON)"
LOCK_SIGNAL = "Signal Bypassed"
LOCK_BYPASSED = "Bypassed"
LOCK_SN = "SN Unlocked"
LOCK_STATUSES = (
    LOCK_UNLOCKED,
    LOCK_LOCKED,
    LOCK_SIGNAL,
    LOCK_BYPASSED,
    LOCK_SN,
)


def parse_lock_status(raw_text: str, lines: list[str] | None = None) -> str:
    """Map label codes: U, L, Sig-B, B, SN-U."""
    lines = lines or [ln.strip() for ln in (raw_text or "").splitlines() if ln.strip()]

    def token_key(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9]", "", value).upper()

    # Prefer a whole line that is only the lock code (common on compact labels)
    for line in lines:
        key = token_key(line)
        if key in {"SNU", "SNUNLOCKED"}:
            return LOCK_SN
        if key in {"SIGB", "SIGNALBYPASSED", "SIGBYPASS"}:
            return LOCK_SIGNAL
        if key in {"U", "UNLOCKED"}:
            return LOCK_UNLOCKED
        if key in {"L", "LOCKED", "FMION"}:
            return LOCK_LOCKED
        if key in {"B", "BYPASSED"}:
            return LOCK_BYPASSED

    blob = raw_text or ""
    if re.search(r"\bsn[\s\-]?u(?:nlocked)?\b", blob, re.I):
        return LOCK_SN
    if re.search(r"\bsig(?:nal)?[\s\-]?b(?:ypassed)?\b", blob, re.I):
        return LOCK_SIGNAL
    if re.search(r"\bfmi\s*on\b|\blocked\b", blob, re.I):
        return LOCK_LOCKED
    if re.search(r"\bunlocked\b", blob, re.I):
        return LOCK_UNLOCKED
    if re.search(r"\bbypassed\b", blob, re.I):
        return LOCK_BYPASSED

    tokens = re.findall(r"[A-Za-z0-9\-]+", blob)
    for token in tokens:
        key = token_key(token)
        if key in {"SNU"}:
            return LOCK_SN
        if key in {"SIGB", "SIG-B"}:
            return LOCK_SIGNAL
    for token in tokens:
        if token.upper() == "U":
            return LOCK_UNLOCKED
        if token.upper() == "L":
            return LOCK_LOCKED
        if token.upper() == "B":
            return LOCK_BYPASSED
    return ""


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _ENGINE = RapidOCR()
    return _ENGINE


def _decode_image(image_data_b64: str) -> Image.Image | None:
    if not image_data_b64:
        return None
    if "," in image_data_b64:
        image_data_b64 = image_data_b64.split(",", 1)[1]
    try:
        import base64

        img = Image.open(BytesIO(base64.b64decode(image_data_b64)))
        return ImageOps.exif_transpose(img.convert("RGB"))
    except Exception as exc:
        print(f"[OCR] Failed to open image: {exc}")
        return None


def _preprocess_variants(img: Image.Image) -> list[Image.Image]:
    """A few variants so small printed labels have a better chance."""
    variants = [img]
    gray = img.convert("L")
    variants.append(ImageEnhance.Contrast(gray).enhance(2.0).convert("RGB"))
    if max(img.size) < 1600:
        scale = 1600 / max(img.size)
        up = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
        variants.append(up)
        variants.append(ImageEnhance.Contrast(up.convert("L")).enhance(2.2).convert("RGB"))
    return variants


def _run_ocr(img: Image.Image) -> list[str]:
    import numpy as np

    engine = _engine()
    best: list[str] = []
    for variant in _preprocess_variants(img):
        result, _elapse = engine(np.array(variant))
        if not result:
            continue
        lines = []
        for item in result:
            if len(item) < 2:
                continue
            text = str(item[1]).strip()
            if text:
                lines.append(text)
        if len(lines) > len(best):
            best = lines
        if len(best) >= 6:
            break
    return best


def parse_label_text(raw_text: str, lines: list[str] | None = None) -> dict:
    """Pull model / color / capacity / serial / iOS / IMEI / battery / date from OCR text."""
    text = raw_text or ""
    blob = re.sub(r"[ \t]+", " ", text)
    lower = blob.lower()
    lines = lines or [ln.strip() for ln in text.splitlines() if ln.strip()]

    # Same comma-separated payload as the QR codes
    comma_parts = [p.strip() for p in re.split(r"\s*,\s*", blob) if p.strip()]
    if len(comma_parts) >= 6 and re.search(r"iphone|ipad", comma_parts[0], re.I):
        parsed = {
            "model": comma_parts[0],
            "color": comma_parts[1] if len(comma_parts) > 1 else "",
            "capacity": comma_parts[2] if len(comma_parts) > 2 else "",
            "serial_number": comma_parts[3] if len(comma_parts) > 3 else "",
            "ios_version": comma_parts[4] if len(comma_parts) > 4 else "",
            "imei": comma_parts[5] if len(comma_parts) > 5 else "",
            "battery_health": comma_parts[6] if len(comma_parts) > 6 else "",
            "date_received": comma_parts[7] if len(comma_parts) > 7 else "",
            "inventory_number": "",
        }
        parsed["raw_ocr"] = raw_text
        parsed["lock_status"] = parse_lock_status(raw_text, lines)
        return parsed

    parsed = {
        "model": "",
        "color": "",
        "capacity": "",
        "serial_number": "",
        "ios_version": "",
        "imei": "",
        "battery_health": "",
        "date_received": "",
        "inventory_number": "",
        "label_notes": "",
        "lock_status": "",
        "raw_ocr": raw_text,
    }

    # Accept "iPhone11" (no space) as well as "iPhone 11 Pro Max"
    model_re = re.compile(
        r"(iphone|ipad)\s*(air|mini|pro|se)?"
        r"\s*(\d{1,2}|x[sr]?|m\d)?"
        r"\s*(plus|pro|max|mini|e)?",
        re.I,
    )
    model = ""
    for line in lines:
        m = model_re.search(line)
        if not m:
            continue
        brand = m.group(1).lower()
        brand = "iPhone" if brand == "iphone" else "iPad"
        bits = [brand]
        for g in m.groups()[1:]:
            if not g:
                continue
            token = g.lower()
            if token in {"pro", "max", "plus", "mini", "air", "se", "e"}:
                bits.append(token.capitalize() if token != "se" else "SE")
            elif token.startswith("m") and token[1:].isdigit():
                bits.append(token.upper())
            elif token in {"x", "xr", "xs"}:
                bits.append(token.upper())
            else:
                bits.append(token)
        model = " ".join(bits)
        # Prefer a match that includes a number / generation
        if m.group(3) or m.group(2):
            break
    if not model:
        m = model_re.search(blob)
        if m:
            brand = "iPhone" if m.group(1).lower() == "iphone" else "iPad"
            bits = [brand] + [g for g in m.groups()[1:] if g]
            model = " ".join(bits)
            model = re.sub(r"\bIphone\b", "iPhone", model, flags=re.I)
            model = re.sub(r"\bIpad\b", "iPad", model, flags=re.I)
    # Normalize "iPhone11" style leftovers
    model = re.sub(r"(iPhone|iPad)(\d)", r"\1 \2", model)
    parsed["model"] = model.strip()

    # Skip color if the line is clearly a parts/damage checklist
    notes_match = re.search(
        r"\b((?:screen|back|batt(?:ery)?|cam(?:era)?|housing)(?:\s*,\s*(?:screen|back|batt(?:ery)?|cam(?:era)?|housing))+)\b",
        lower,
    )
    if notes_match:
        parsed["label_notes"] = notes_match.group(1)

    for color in sorted(COLORS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(color)}\b", lower):
            parsed["color"] = color.title().replace("Iphone", "iPhone")
            if parsed["color"].lower() == "product red":
                parsed["color"] = "PRODUCT(RED)"
            break

    cap = re.search(r"\b(\d{2,4})\s*(gb|tb)\b", lower)
    if cap:
        parsed["capacity"] = f"{cap.group(1)}{cap.group(2).upper()}"

    imei = re.search(r"(?:imei\s*[:#]?\s*)?(\d{15})\b", blob.replace(" ", ""))
    if not imei:
        imei = re.search(r"imei\s*[:#]?\s*([\d\s]{15,20})", lower)
    if imei:
        digits = re.sub(r"\D", "", imei.group(1))
        if len(digits) >= 15:
            parsed["imei"] = digits[:15]

    ios = re.search(r"(?:ios|ipados|i\.?os)\s*[:#]?\s*(1[0-9](?:\.\d+){0,3})", lower)
    if not ios:
        # Standalone version line like "17.4"
        ios = re.search(r"(?m)^(?:ios\s*)?(1[0-9](?:\.\d{1,2}){1,2})$", "\n".join(lines), re.I)
    if not ios:
        ios = re.search(r"\b(1[0-9](?:\.\d{1,2}){1,2})\b", blob)
    if ios:
        parsed["ios_version"] = ios.group(1)

    batt = re.search(r"(\d{1,3})\s*%", blob)
    if batt:
        pct = int(batt.group(1))
        if 0 <= pct <= 100:
            parsed["battery_health"] = f"{pct}%"

    for line in lines:
        m = re.fullmatch(r"(\d{2,4})", line.strip())
        if not m:
            continue
        raw_num = m.group(1)
        # Skip storage sizes already captured as GB/TB
        if parsed.get("capacity") and raw_num == re.sub(r"\D", "", parsed["capacity"]):
            continue
        parsed["inventory_number"] = raw_num
        break

    serial = re.search(
        r"(?:s/?n|serial(?:\s*(?:no|number|#))?)\s*[:#]?\s*([A-Z0-9]{8,14})",
        blob,
        re.I,
    )
    if serial:
        parsed["serial_number"] = serial.group(1).upper()
    else:
        for line in lines:
            token = re.sub(r"[^A-Za-z0-9]", "", line)
            if 10 <= len(token) <= 12 and re.search(r"[A-Za-z]", token) and re.search(r"\d", token):
                if token.lower() in {"iphone", "ipad"}:
                    continue
                parsed["serial_number"] = token.upper()
                break

    date = re.search(r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b", blob)
    if date:
        parsed["date_received"] = date.group(1)

    parsed["lock_status"] = parse_lock_status(raw_text, lines)
    return parsed


def extract_label_fields(image_data_b64: str) -> dict:
    img = _decode_image(image_data_b64)
    if img is None:
        return {"success": False, "message": "Could not read the label photo."}

    try:
        lines = _run_ocr(img)
    except Exception as exc:
        print(f"[OCR] engine failed: {exc}")
        return {
            "success": False,
            "message": f"Could not read the label ({exc}). Try a closer photo.",
        }

    raw_text = "\n".join(lines).strip()
    print("[OCR] ---------- recognized text ----------")
    if lines:
        for i, line in enumerate(lines, 1):
            print(f"[OCR] {i:02d}: {line}")
    else:
        print("[OCR] (no lines)")
    print("[OCR] ------------------------------------")
    print(f"[OCR] raw ({len(lines)} lines):\n{raw_text}")

    if not raw_text:
        return {
            "success": True,
            "found": False,
            "raw_ocr": "",
            "message": "No text found. Zoom in on the printed label and try again.",
        }

    parsed = parse_label_text(raw_text, lines)
    print(f"[OCR] lock_status={parsed.get('lock_status')!r} battery={parsed.get('battery_health')!r} inv={parsed.get('inventory_number')!r}")
    useful = any(
        parsed.get(k)
        for k in ("model", "serial_number", "imei", "capacity", "battery_health", "lock_status")
    )
    if not useful:
        return {
            "success": True,
            "found": False,
            "raw_ocr": raw_text,
            "parsed": parsed,
            "message": "Read some text, but could not identify device fields. Try a closer, sharper photo.",
        }

    return {
        "success": True,
        "found": True,
        "raw_ocr": raw_text,
        "parsed": parsed,
    }
