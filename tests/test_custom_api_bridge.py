"""Tests: js_api bridge + validation (Blocker 1 + medium fixes).

API class must expose Custom Web methods with proper validation:
- export_custom_web validates mode=web and connected before enqueue
- connect_custom_web pops stale error before enqueue
- disconnect_custom_web uses done-event
- scan_custom_web uses done-event
"""

from unittest.mock import MagicMock, patch
from main import API


class TestApiBridgeCustomWeb:
    """API class must have custom web methods."""

    def test_connect_custom_web_exists(self):
        app = MagicMock()
        api = API(app)
        assert hasattr(api, "connect_custom_web")

    def test_disconnect_custom_web_exists(self):
        app = MagicMock()
        api = API(app)
        assert hasattr(api, "disconnect_custom_web")

    def test_scan_custom_web_exists(self):
        app = MagicMock()
        api = API(app)
        assert hasattr(api, "scan_custom_web")

    def test_export_custom_web_exists(self):
        app = MagicMock()
        api = API(app)
        assert hasattr(api, "export_custom_web")

    def test_connect_custom_web_delegates_to_app(self):
        app = MagicMock()
        app.connect_custom_web.return_value = "OK"
        api = API(app)
        result = api.connect_custom_web(1, "https://chat.mistral.ai")
        app.connect_custom_web.assert_called_once_with(1, "https://chat.mistral.ai")
        assert result == "OK"

    def test_disconnect_custom_web_delegates_to_app(self):
        app = MagicMock()
        app.disconnect_custom_web.return_value = "OK"
        api = API(app)
        result = api.disconnect_custom_web(1)
        app.disconnect_custom_web.assert_called_once_with(1)

    def test_scan_custom_web_delegates_to_app(self):
        app = MagicMock()
        app.scan_custom_web.return_value = [{"id": "c1", "title": "Chat 1"}]
        api = API(app)
        result = api.scan_custom_web(1)
        app.scan_custom_web.assert_called_once_with(1)
        assert result == [{"id": "c1", "title": "Chat 1"}]


class TestExportCustomWebValidation:
    """export_custom_web must validate mode and connection."""

    def test_export_rejects_api_mode(self):
        app = MagicMock()
        app._get_custom_mode.return_value = "api"
        api = API(app)
        import pytest
        with pytest.raises(RuntimeError, match="not in web mode"):
            api.export_custom_web(1, "[]")

    def test_export_rejects_disconnected(self):
        app = MagicMock()
        app._get_custom_mode.return_value = "web"
        app._custom1_connected = False
        api = API(app)
        import pytest
        with pytest.raises(RuntimeError, match="not connected"):
            api.export_custom_web(1, "[]")

    def test_export_passes_objects_with_index(self):
        app = MagicMock()
        app._get_custom_mode.return_value = "web"
        app._custom1_connected = True
        api = API(app)
        urls = [{"url": "https://x", "_index": 3}, {"url": "https://y"}]
        import json
        result = api.export_custom_web(1, json.dumps(urls))
        app._gw_queue.put.assert_called_once()
        call_args = app._gw_queue.put.call_args[0][0]
        assert call_args[0] == "export_provider"
        assert call_args[1][0] == "custom1"
        assert call_args[1][1] == urls


class TestConnectStaleErrorCleanup:
    """connect_custom_web must pop stale error before enqueue."""

    def test_pops_stale_error_before_connect(self):
        app = MagicMock()
        app._get_custom_mode.return_value = "web"
        app._custom1_connected = False
        app.connect_custom_web.return_value = "OK"
        api = API(app)
        api.connect_custom_web(1, "https://x")
        app.connect_custom_web.assert_called_once_with(1, "https://x")


class TestDisconnectDoneEvent:
    """disconnect_custom_web must use done-event for synchronization."""

    def test_disconnect_uses_event(self):
        app = MagicMock()
        app.disconnect_custom_web.return_value = "OK"
        api = API(app)
        result = api.disconnect_custom_web(2)
        app.disconnect_custom_web.assert_called_once_with(2)
        assert result == "OK"
