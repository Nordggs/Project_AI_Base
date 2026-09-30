"""Custom API provider configuration — CRUD on config.json["custom_providers"].

Security note (v1): api_key is stored in plain text inside config.json.
It must never be logged, included in diagnostic dumps, or returned to the UI
(use sanitize_config_for_display / "__KEEP__" sentinel instead).
"""

import json
import os

DEFAULT_SLOT = {
    "name": "",
    "endpoint": "",
    "model": "",
    "api_key": "",
    "protocol": "openai",  # openai | anthropic
    "system_prompt": "",
    "timeout": 30,
    # ── Web mode fields ──
    "mode": "api",  # api | web
    "url": "",
    "chat_list_selector": "",
    "title_selector": "",
    "message_selector": "",
    "user_message_selector": "",
    "assistant_message_selector": "",
    "scroll_container_selector": "",
    "wait_after_click_ms": 2000,
    "list_chats_js": "",
    "extract_messages_js": "",
}

SLOTS = (1, 2)
KEEP_KEY = "__KEEP__"  # sentinel: keep existing api_key


def _load(config_path):
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(config_path, data):
    tmp = config_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, config_path)


def _merge_slot(cfg):
    merged = dict(DEFAULT_SLOT)
    if isinstance(cfg, dict):
        for k in DEFAULT_SLOT:
            if k in cfg:
                merged[k] = cfg[k]
    return merged


def load_custom_config(config_path, slot):
    return _merge_slot(_load(config_path).get("custom_providers", {}).get(str(slot)))


def save_custom_config(config_path, slot, config):
    data = _load(config_path)
    providers = data.get("custom_providers")
    if not isinstance(providers, dict):
        providers = {}
    providers[str(slot)] = {k: config.get(k, DEFAULT_SLOT[k]) for k in DEFAULT_SLOT}
    data["custom_providers"] = providers
    _save(config_path, data)


def get_all_custom_configs(config_path):
    return {str(slot): load_custom_config(config_path, slot) for slot in SLOTS}


def custom_config_ready(config_path, slot):
    """True when endpoint and model are filled — provider is usable."""
    cfg = load_custom_config(config_path, slot)
    return bool(str(cfg.get("endpoint", "")).strip() and str(cfg.get("model", "")).strip())


def sanitize_config_for_display(config):
    """Copy safe for UI/logs: api_key removed, replaced by has_api_key flag."""
    out = {k: v for k, v in config.items() if k != "api_key"}
    out["has_api_key"] = bool(str(config.get("api_key", "")).strip())
    return out
