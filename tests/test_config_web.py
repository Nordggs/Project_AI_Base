"""Tests: DEFAULT_SLOT and config system don't support web mode fields.

PROBLEM: Plan says to extend DEFAULT_SLOT with mode, url, *_selector, *_js
fields, but currently DEFAULT_SLOT only has API-specific fields.
"""

from core.custom_config import DEFAULT_SLOT, _merge_slot


class TestConfigWebFields:
    """Config must support web mode fields for Custom Web."""

    def test_default_slot_has_mode_field(self):
        """FAIL: DEFAULT_SLOT has no 'mode' field."""
        assert "mode" in DEFAULT_SLOT, (
            f"DEFAULT_SLOT missing 'mode'. Current keys: {list(DEFAULT_SLOT.keys())}"
        )

    def test_default_slot_has_url_field(self):
        """FAIL: DEFAULT_SLOT has no 'url' field."""
        assert "url" in DEFAULT_SLOT, (
            f"DEFAULT_SLOT missing 'url'. Current keys: {list(DEFAULT_SLOT.keys())}"
        )

    def test_default_slot_has_selector_fields(self):
        """FAIL: DEFAULT_SLOT has no CSS selector fields for web mode."""
        required_web_fields = [
            "chat_list_selector",
            "message_selector",
            "user_message_selector",
            "assistant_message_selector",
            "scroll_container_selector",
            "wait_after_click_ms",
            "list_chats_js",
            "extract_messages_js",
        ]
        missing = [f for f in required_web_fields if f not in DEFAULT_SLOT]
        assert not missing, (
            f"DEFAULT_SLOT missing web fields: {missing}. "
            f"Current keys: {list(DEFAULT_SLOT.keys())}"
        )


class TestLegacyConfigPreservation:
    """Old configs load with defaults; web preset save resets API fields
    by save mechanics (TICKET-002-B rule 8, documented fact — not a bug)."""

    def test_legacy_api_only_config_loads_with_web_defaults(self, tmp_path):
        import json
        from core.custom_config import load_custom_config

        path = str(tmp_path / "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"custom_providers": {"1": {
                "name": "c", "endpoint": "https://e", "model": "m",
                "api_key": "k", "protocol": "openai",
                "system_prompt": "", "timeout": 30}}}, f)
        cfg = load_custom_config(path, 1)
        assert cfg["endpoint"] == "https://e"
        assert cfg["mode"] == "api"
        assert cfg["url"] == ""
        assert cfg["message_selector"] == ""

    def test_save_other_slot_keeps_existing_config(self, tmp_path):
        import json
        from core.custom_config import load_custom_config, save_custom_config

        path = str(tmp_path / "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"custom_providers": {"1": {
                "name": "c", "endpoint": "https://e", "model": "m",
                "api_key": "k", "protocol": "openai",
                "system_prompt": "", "timeout": 30}}}, f)
        web = dict(load_custom_config(path, 2))
        web.update({"mode": "web", "url": "https://example.com/",
                    "message_selector": ".m", "chat_list_selector": "nav a"})
        save_custom_config(path, 2, web)
        assert load_custom_config(path, 1)["endpoint"] == "https://e"

    def test_web_preset_save_resets_api_fields_to_defaults(self, tmp_path):
        """Documents save mechanics: absent API keys are filled with
        DEFAULT_SLOT defaults (endpoint/model/key wiped). UI warns (002-E)."""
        from core.custom_config import DEFAULT_SLOT, load_custom_config, save_custom_config

        path = str(tmp_path / "config.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{}")
        web_cfg = {k: DEFAULT_SLOT[k] for k in DEFAULT_SLOT}
        web_cfg.update({"mode": "web", "url": "https://example.com/",
                        "message_selector": ".m", "chat_list_selector": "nav a"})
        save_custom_config(path, 1, web_cfg)
        loaded = load_custom_config(path, 1)
        assert loaded["endpoint"] == ""
        assert loaded["model"] == ""
        assert loaded["api_key"] == ""
