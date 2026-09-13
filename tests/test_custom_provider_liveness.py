"""Tests: _is_provider_connected uses flags, not evaluate (STOP-БЛОКЕР fix).

_is_provider_connected for web mode must read _customN_connected flag,
not call _is_page_alive(page) which does page.evaluate from wrong thread.
"""

from unittest.mock import patch, MagicMock

from main import App


class TestProviderConnectedUsesFlags:
    """_is_provider_connected must read _customN_connected, not evaluate."""

    def test_web_connected_when_flag_true(self, mock_app):
        mock_app._custom1_connected = True
        with patch("main.load_custom_config", return_value={"mode": "web", "url": "https://x"}):
            assert App._is_provider_connected(mock_app, "custom1") is True

    def test_web_disconnected_when_flag_false(self, mock_app):
        mock_app._custom1_connected = False
        with patch("main.load_custom_config", return_value={"mode": "web", "url": "https://x"}):
            assert App._is_provider_connected(mock_app, "custom1") is False

    def test_web_disconnected_when_flag_missing(self, mock_app):
        if hasattr(mock_app, "_custom1_connected"):
            delattr(mock_app, "_custom1_connected")
        with patch("main.load_custom_config", return_value={"mode": "web", "url": "https://x"}):
            assert App._is_provider_connected(mock_app, "custom1") is False

    def test_web_does_not_call_is_page_alive(self, mock_app):
        mock_app._custom1_connected = True
        with patch("main.load_custom_config", return_value={"mode": "web", "url": "https://x"}):
            with patch.object(App, "_is_page_alive") as mock_alive:
                result = App._is_provider_connected(mock_app, "custom1")
                mock_alive.assert_not_called()
                assert result is True

    def test_custom2_uses_correct_flag(self, mock_app):
        mock_app._custom2_connected = True
        with patch("main.load_custom_config", return_value={"mode": "web", "url": "https://y"}):
            assert App._is_provider_connected(mock_app, "custom2") is True

    def test_api_mode_unchanged(self, mock_app):
        with patch("main.load_custom_config", return_value={"mode": "api"}), \
             patch("main.custom_config_ready", return_value=True):
            assert App._is_provider_connected(mock_app, "custom1") is True
