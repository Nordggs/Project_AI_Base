"""Tests: _is_provider_connected() behavior after STOP-БЛОКЕР fix.

Web mode: reads _customN_connected flag (no page.evaluate).
API mode: reads custom_config_ready (endpoint+model filled).
"""

from unittest.mock import patch, MagicMock

from main import App


class TestIsProviderConnected:
    """_is_provider_connected() behavior for custom providers."""

    def test_custom_api_connected_when_config_ready(self, mock_app):
        with patch("main.custom_config_ready", return_value=True):
            assert App._is_provider_connected(mock_app, "custom1") is True

    def test_custom_api_disconnected_when_config_incomplete(self, mock_app):
        with patch("main.custom_config_ready", return_value=False):
            assert App._is_provider_connected(mock_app, "custom1") is False

    def test_custom_web_connected_when_flag_true(self, mock_app):
        mock_app._custom1_connected = True
        with patch("main.load_custom_config", return_value={
            "mode": "web", "url": "https://chat.mistral.ai",
        }):
            assert App._is_provider_connected(mock_app, "custom1") is True

    def test_custom_web_disconnected_when_flag_false(self, mock_app):
        mock_app._custom1_connected = False
        with patch("main.load_custom_config", return_value={
            "mode": "web", "url": "https://chat.mistral.ai",
        }):
            assert App._is_provider_connected(mock_app, "custom1") is False

    def test_custom_web_disconnected_when_page_none(self, mock_app):
        mock_app.custom1_page = None
        mock_app._custom1_connected = False
        with patch("main.load_custom_config", return_value={
            "mode": "web", "url": "https://chat.mistral.ai",
        }):
            assert App._is_provider_connected(mock_app, "custom1") is False

    def test_custom_web_connected_when_flag_true_despite_empty_url(self, mock_app):
        mock_app._custom1_connected = True
        with patch("main.load_custom_config", return_value={
            "mode": "web", "url": "",
        }):
            assert App._is_provider_connected(mock_app, "custom1") is True

    def test_custom_web_does_not_call_is_page_alive(self, mock_app):
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
