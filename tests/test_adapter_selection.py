"""Tests: _adapter_for() always returns CustomAdapter for custom slots.

PROBLEM: Plan introduces CustomWebAdapter for web mode, but _adapter_for()
has no logic to choose between CustomAdapter (API) and CustomWebAdapter (Web).
"""

from unittest.mock import patch, MagicMock

from main import App


class TestAdapterForCustomSlots:
    """_adapter_for() must return different adapters for API vs Web mode."""

    def test_custom1_returns_custom_adapter_in_api_mode(self, mock_app):
        """PASS: custom1 returns CustomAdapter in API mode."""
        with patch("main.load_custom_config", return_value={
            "mode": "api", "endpoint": "https://api.example.com",
            "model": "gpt-4", "api_key": "", "protocol": "openai",
            "system_prompt": "", "timeout": 30,
        }):
            adapter = App._adapter_for(mock_app, "custom1", None)
            assert type(adapter).__name__ == "CustomAdapter"

    def test_custom1_web_should_return_custom_web_adapter(self, mock_app):
        """FAIL: custom1 in 'web' mode still returns CustomAdapter."""
        with patch("main.load_custom_config", return_value={
            "mode": "web",
            "url": "https://chat.mistral.ai",
            "endpoint": "", "model": "", "api_key": "",
            "protocol": "openai", "system_prompt": "", "timeout": 30,
        }):
            adapter = App._adapter_for(mock_app, "custom1", MagicMock())
            assert type(adapter).__name__ == "CustomWebAdapter", (
                f"Expected CustomWebAdapter for web mode, got {type(adapter).__name__}"
            )

    def test_custom2_web_should_return_custom_web_adapter(self, mock_app):
        """FAIL: custom2 in 'web' mode still returns CustomAdapter."""
        with patch("main.load_custom_config", return_value={
            "mode": "web",
            "url": "https://grok.x.ai",
            "endpoint": "", "model": "", "api_key": "",
            "protocol": "openai", "system_prompt": "", "timeout": 30,
        }):
            adapter = App._adapter_for(mock_app, "custom2", MagicMock())
            assert type(adapter).__name__ == "CustomWebAdapter", (
                f"Expected CustomWebAdapter for web mode, got {type(adapter).__name__}"
            )
