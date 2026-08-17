"""Map device model + damage to the correct repair part names."""

from __future__ import annotations

import re


def normalize_model(model: str | None) -> str:
    text = (model or "").lower()
    text = text.replace("iphone", "iphone ")
    text = text.replace("ipad", "ipad ")
    text = re.sub(r"[^a-z0-9+]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _iphone_number(model: str) -> int | None:
    m = re.search(r"iphone\s*(\d{1,2})", model)
    if not m:
        return None
    return int(m.group(1))


def is_iphone(model: str) -> bool:
    return "iphone" in model or bool(re.search(r"\bse\b", model))


def is_ipad(model: str) -> bool:
    return "ipad" in model


def is_iphone_lcd(model: str) -> bool:
    """LCD: SE, 6–8, XR, 11 (non-Pro). OLED starts with X / 11 Pro / 12+."""
    if not is_iphone(model):
        return False
    if re.search(r"\bse\b", model):
        return True
    if "xr" in model:
        return True
    # iPhone 11 non-Pro only
    if re.search(r"iphone\s*11\b", model) and "pro" not in model:
        return True
    n = _iphone_number(model)
    if n is not None and n <= 8:
        return True
    # Named older models without a number in the string
    if any(x in model for x in ("iphone 6", "iphone 7", "iphone 8")):
        return True
    return False


def is_digitizer_ipad(model: str) -> bool:
    """
    Separate digitizer (glass) + LCD — not a fused display assembly.
    Includes Air 1, Mini 1/2, and classic numbered iPads 1–9.
    """
    if not is_ipad(model):
        return False

    # Pro models are fused assemblies
    if "pro" in model:
        return False

    # iPad Mini 1 & 2 (and bare "ipad mini" → treat as digitizer-era)
    if "mini" in model:
        m = re.search(r"mini\s*(\d+)", model)
        if m:
            return int(m.group(1)) <= 2
        # "iPad mini" with no generation often means 1st gen in older stock
        return True

    # iPad Air 1 only (bare "ipad air" = 1st gen). Air 2+ are fused.
    if "air" in model:
        m = re.search(r"air\s*(\d+)", model)
        if m:
            return int(m.group(1)) == 1
        if re.search(r"air\s*2|air\s*3|air\s*4|air\s*5|air\s*6|air\s*m", model):
            return False
        return True

    # Numbered iPad 1–9: digitizer separate from LCD
    m = re.search(r"ipad\s*(\d+)", model)
    if m:
        return int(m.group(1)) <= 9

    # Bare "iPad" / "iPad WiFi" etc. — safer as digitizer for older stock
    if re.fullmatch(r"ipad( wifi| cellular| wi fi)?", model):
        return True

    return False


def iphone_opens_from_back(model: str) -> bool:
    """
    Removable back glass / back cover (service from the rear):
    - iPhone 14 & 14 Plus (not 14 Pro / Pro Max)
    - iPhone 15 and newer (all variants, including 16e)
    """
    if not is_iphone(model):
        return False

    n = _iphone_number(model)
    if n is None:
        return False
    if n >= 15:
        return True
    if n == 14 and "pro" not in model:
        return True
    return False


def iphone_has_glass_back(model: str) -> bool:
    """Glass backs start at iPhone 8 / X era (wireless charging)."""
    if not is_iphone(model):
        return False
    if re.search(r"\bse\b", model):
        # SE 2/3 share 8 body (glass). SE 1 is aluminum — rare; prefer glass for "SE".
        return True
    if any(x in model for x in ("iphone x", "iphone xr", "iphone xs")):
        return True
    n = _iphone_number(model)
    return n is not None and n >= 8


def screen_part_for_model(model_name: str | None) -> str:
    model = normalize_model(model_name)
    if is_digitizer_ipad(model):
        return "Digitizer"
    if is_ipad(model):
        return "Display Assembly"
    if is_iphone_lcd(model):
        return "LCD Assembly"
    # Default for modern iPhones / unknown phones from vision
    return "OLED Assembly"


def back_part_for_model(model_name: str | None) -> str:
    model = normalize_model(model_name)
    if is_iphone(model):
        if iphone_opens_from_back(model):
            return "Back Cover"
        if iphone_has_glass_back(model):
            return "Back Glass"
        return "Back Housing"
    return "Back Housing"


def determine_parts_needed(
    damage_condition,
    remarks,
    battery_health=None,
    model=None,
    parse_battery_percent=None,
):
    """Build a starting parts list from vision + model + battery."""
    parts: list[str] = []
    condition = (damage_condition or "").lower()

    if "cracked screen" in condition:
        parts.append(screen_part_for_model(model))
    if "back glass" in condition:
        parts.append(back_part_for_model(model))

    remarks_lower = (remarks or "").lower()
    if "battery" in remarks_lower and "Replacement Battery" not in parts:
        parts.append("Replacement Battery")
    if "camera" in remarks_lower and "Camera Module" not in parts:
        parts.append("Camera Module")

    if parse_battery_percent is not None:
        battery_pct = parse_battery_percent(battery_health)
        if battery_pct is not None and battery_pct < 90:
            if "Replacement Battery" not in parts:
                parts.append("Replacement Battery")

    return parts
