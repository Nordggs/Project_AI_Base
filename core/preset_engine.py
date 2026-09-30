"""Preset engine (TICKET-002-D, variant A) — validation/filter/path only.

Pure functions, no state, no Playwright, no App, no jsonschema.
File reading (load) and v1 mapping live in 002-E scope; this module only
judges already-read dicts and resolves the catalog path.

Source of truth for behavior is the preset dict, NOT the slot config:
_merge_slot strips unknown keys on save, so transit keys (e.g. navigation)
do not survive a load/save round-trip. Slot->preset_id binding lives in
App memory; if it is lost (e.g. app restart), callers fall back to "goto"
and the UI should prompt to Apply the preset again.
"""

from typing import Any

STRATEGY_TYPES = ("selector", "script")
NAVIGATION_TYPES = ("goto", "click")
DEFAULT_NAVIGATION = "goto"
DEFAULT_WAIT_AFTER_CLICK_MS = 2000
CATALOG_FILENAME = "custom_presets.json"

_REQUIRED_SELECTOR_KEYS = ("message_selector", "chat_list_selector")


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _strategy_of(preset: dict) -> Any:
    return preset.get("strategy")


def validate_preset(preset: Any) -> "tuple[bool, list[str]]":
    """Check a preset dict against format v1. Returns (ok, errors).

    wait_after_click_ms is optional: absent/None means the DEFAULT_SLOT
    default (2000) applies at mapping time. A present value must be
    int > 0. navigation is optional: absent/None means "goto".
    """
    errors: list[str] = []
    if not isinstance(preset, dict):
        return False, ["preset must be an object"]
    if not _is_nonempty_str(preset.get("id")):
        errors.append("id must be a non-empty string")
    strategy = _strategy_of(preset)
    if not isinstance(strategy, dict):
        return False, errors + ["strategy must be an object"]
    stype = strategy.get("type")
    if stype not in STRATEGY_TYPES:
        errors.append(f"strategy.type must be one of {list(STRATEGY_TYPES)}")
        return False, errors
    selectors = strategy.get("selectors", {})
    scripts = strategy.get("scripts", {})
    if not isinstance(selectors, dict):
        errors.append("strategy.selectors must be an object")
        selectors = {}
    if not isinstance(scripts, dict):
        errors.append("strategy.scripts must be an object")
        scripts = {}
    list_js = scripts.get("list_chats_js", "")
    extract_js = scripts.get("extract_messages_js", "")
    if stype == "selector":
        for key in _REQUIRED_SELECTOR_KEYS:
            if not _is_nonempty_str(selectors.get(key)):
                errors.append(f"strategy.selectors.{key} must be a non-empty string")
        for key, value in selectors.items():
            if not isinstance(value, str):
                errors.append(f"strategy.selectors.{key} must be a string")
        if _is_nonempty_str(list_js) or _is_nonempty_str(extract_js):
            errors.append("selector preset must not carry *_js (hybrid forbidden)")
    else:  # script
        if not _is_nonempty_str(list_js):
            errors.append("strategy.scripts.list_chats_js must be a non-empty string")
        for key in ("list_chats_js", "extract_messages_js"):
            value = scripts.get(key, "")
            if value not in ("", None) and not isinstance(value, str):
                errors.append(f"strategy.scripts.{key} must be a string")
    wait = strategy.get("wait_after_click_ms", None)
    if wait is not None:
        if isinstance(wait, bool) or not isinstance(wait, int) or wait <= 0:
            errors.append("strategy.wait_after_click_ms must be int > 0")
    navigation = strategy.get("navigation", None)
    if navigation is not None and navigation not in NAVIGATION_TYPES:
        errors.append(f"strategy.navigation must be one of {list(NAVIGATION_TYPES)}")
    return (len(errors) == 0), errors


def filter_valid_presets(presets: Any) -> list:
    """Keep only valid preset dicts. Never raises, never reads files."""
    if not isinstance(presets, list):
        return []
    return [p for p in presets if validate_preset(p)[0]]


def resolve_catalog_path(storage_dir: str) -> str:
    """Catalog path next to config.json (same storage dir)."""
    import os

    return os.path.join(storage_dir, CATALOG_FILENAME)


def resolve_navigation(presets: Any, preset_id: Any, default: str = DEFAULT_NAVIGATION) -> str:
    """Navigation for a bound preset id. Falls back to default ("goto").

    Used at operation time from the in-memory slot->preset_id binding.
    """
    if not isinstance(presets, list) or not _is_nonempty_str(preset_id):
        return default
    for preset in presets:
        if not isinstance(preset, dict):
            continue
        if preset.get("id") != preset_id:
            continue
        ok, _ = validate_preset(preset)
        if not ok:
            return default
        navigation = preset.get("strategy", {}).get("navigation", None)
        if navigation in NAVIGATION_TYPES:
            return navigation
        return default
    return default
