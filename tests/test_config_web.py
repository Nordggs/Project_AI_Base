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
