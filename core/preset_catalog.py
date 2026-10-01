"""Preset catalog write side (TICKET-003, Phase A).

Read-modify-write for ``custom_presets.json``: save / delete / load.

``core/preset_engine.py`` stays pure (validate/filter/path only, no file IO)
per its documented contract — all filesystem access lives here.

Security (§13 ticket): cookies, credentials, API keys, session tokens and
other secrets must never land in the catalog. Sanitization drops denylisted
keys; if a secret pattern is found inside a string value the whole save is
refused (STOP, nothing is written).
"""

import json
import os
import threading

from core.preset_engine import CATALOG_FILENAME, resolve_catalog_path, validate_preset

__all__ = [
    "CATALOG_FILENAME",
    "DENYLISTED_KEYS",
    "SECRET_VALUE_PATTERNS",
    "load_catalog",
    "save_preset",
    "delete_preset",
]

# Keys that are never stored: dropped silently at any nesting level.
DENYLISTED_KEYS = frozenset({
    "cookies",
    "credentials",
    "credential",
    "api_key",
    "apikey",
    "apiKey",
    "session",
    "session_id",
    "sessionid",
    "session_token",
    "token",
    "access_token",
    "refresh_token",
    "auth_token",
    "authorization",
    "secret",
    "client_secret",
    "password",
    "passwd",
})

# Substrings (case-insensitive) that, when found inside any string value,
# refuse the whole save (STOP — nothing is written, §13 ticket).
SECRET_VALUE_PATTERNS = (
    "sessionid=",
    "session_id=",
    "token=",
    "api_key=",
    "apikey=",
    "secret=",
    "authorization:",
    "bearer ",
)

_lock = threading.Lock()


def _sanitized(preset):
    """Return (cleaned_dict, dropped_keys) with denylisted keys removed."""
    dropped = []

    def _clean(node):
        if isinstance(node, dict):
            out = {}
            for key, value in node.items():
                if isinstance(key, str) and key.lower() in DENYLISTED_KEYS:
                    dropped.append(key)
                    continue
                out[key] = _clean(value)
            return out
        if isinstance(node, list):
            return [_clean(item) for item in node]
        return node

    return _clean(preset), dropped


def _iter_strings(node):
    """Yield every string value in a nested structure."""
    if isinstance(node, dict):
        for value in node.values():
            yield from _iter_strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_strings(item)
    elif isinstance(node, str):
        yield node


def _find_secret(preset):
    """Return the offending pattern, or None if values look clean."""
    for value in _iter_strings(preset):
        lowered = value.lower()
        for pattern in SECRET_VALUE_PATTERNS:
            if pattern in lowered:
                return pattern
    return None


def _read_catalog_file(path):
    """Read catalog file -> (presets_list, wrapper_dict_or_None).

    Supports both shapes the reader accepts: a bare list (seed shape)
    and {"presets": [...]}. Missing file -> ([], None).
    Raises RuntimeError on broken JSON / unexpected shape.
    """
    if not os.path.exists(path):
        return [], None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise RuntimeError(f"preset catalog is broken ({path}): {exc}")
    if isinstance(data, list):
        return data, None
    if isinstance(data, dict) and isinstance(data.get("presets"), list):
        return data["presets"], data
    raise RuntimeError(f"preset catalog has unexpected shape ({path})")


def _write_catalog_file(path, presets, wrapper):
    """Atomic write: .tmp in the same dir -> os.replace."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    payload = presets if wrapper is None else dict(wrapper, presets=presets)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def load_catalog(storage_dir):
    """Read the catalog (no seeding). Returns a list (may be empty).

    Raises RuntimeError on broken file / unexpected shape.
    """
    path = resolve_catalog_path(storage_dir)
    presets, _ = _read_catalog_file(path)
    return presets


def save_preset(storage_dir, preset_dict):
    """Validate -> sanitize -> atomic upsert by id. Returns (ok, errors).

    Refusals (ok=False, nothing written):
      - preset is not a dict / fails validate_preset();
      - a secret pattern is found in any string value (STOP, §13);
      - catalog file exists but is broken (no silent overwrite).
    Denylisted keys (cookies/credentials/tokens/...) are dropped before
    writing. Only CustomWebAdapter contract fields are stored — no new
    fields are introduced here.
    """
    if not isinstance(preset_dict, dict):
        return False, ["preset must be an object"]
    ok, errors = validate_preset(preset_dict)
    if not ok:
        return False, list(errors)

    cleaned, _dropped = _sanitized(preset_dict)
    # Re-validate after key drops: drops only remove data, but stay strict.
    ok, errors = validate_preset(cleaned)
    if not ok:
        return False, list(errors)

    offender = _find_secret(cleaned)
    if offender is not None:
        return False, [f"STOP: possible secret in preset values ({offender!r}); nothing saved"]

    path = resolve_catalog_path(storage_dir)
    with _lock:
        try:
            presets, wrapper = _read_catalog_file(path)
        except RuntimeError as exc:
            return False, [str(exc)]
        if not isinstance(presets, list):
            return False, [f"preset catalog has unexpected shape ({path})"]
        # Upsert by id, keep neighbours (and wrapper keys) untouched.
        replaced = False
        kept = []
        for existing in presets:
            if isinstance(existing, dict) and existing.get("id") == cleaned.get("id"):
                if not replaced:
                    kept.append(cleaned)
                    replaced = True
                # else: drop duplicate id entries
            else:
                kept.append(existing)
        if not replaced:
            kept.append(cleaned)
        try:
            _write_catalog_file(path, kept, wrapper)
        except OSError as exc:
            return False, [f"cannot write preset catalog ({path}): {exc}"]
    return True, []


def delete_preset(storage_dir, preset_id):
    """Remove a preset by id. Returns (ok, errors).

    Deleting an unknown id is a no-op success (idempotent).
    Broken catalog -> refusal (no silent overwrite).
    """
    if not isinstance(preset_id, str) or not preset_id.strip():
        return False, ["preset_id must be a non-empty string"]
    path = resolve_catalog_path(storage_dir)
    with _lock:
        try:
            presets, wrapper = _read_catalog_file(path)
        except RuntimeError as exc:
            return False, [str(exc)]
        if not isinstance(presets, list):
            return False, [f"preset catalog has unexpected shape ({path})"]
        kept = [p for p in presets
                if not (isinstance(p, dict) and p.get("id") == preset_id)]
        if len(kept) == len(presets):
            return True, []
        try:
            _write_catalog_file(path, kept, wrapper)
        except OSError as exc:
            return False, [f"cannot write preset catalog ({path}): {exc}"]
    return True, []
