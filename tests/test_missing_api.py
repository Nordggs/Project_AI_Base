"""Tests: connect/disconnect/scan/get_custom_mode methods missing from App.

PROBLEM: Plan defines these as API bridge methods (Etapa 4) but they don't
exist yet. Without them the UI has no way to connect custom web providers.
"""


class TestMissingCustomWebAPI:
    """App must have connect/disconnect/scan/get_custom_mode methods."""

    def test_connect_custom_web_exists(self, mock_app):
        """FAIL: connect_custom_web() method doesn't exist on App."""
        assert hasattr(mock_app, "connect_custom_web"), (
            "App has no connect_custom_web() method"
        )

    def test_disconnect_custom_web_exists(self, mock_app):
        """FAIL: disconnect_custom_web() method doesn't exist on App."""
        assert hasattr(mock_app, "disconnect_custom_web"), (
            "App has no disconnect_custom_web() method"
        )

    def test_scan_custom_web_exists(self, mock_app):
        """FAIL: scan_custom_web() method doesn't exist on App."""
        assert hasattr(mock_app, "scan_custom_web"), (
            "App has no scan_custom_web() method"
        )

    def test_do_connect_custom_exists(self, mock_app):
        """FAIL: _do_connect_custom() internal method doesn't exist."""
        assert hasattr(mock_app, "_do_connect_custom"), (
            "App has no _do_connect_custom() method"
        )

    def test_do_disconnect_custom_exists(self, mock_app):
        """FAIL: _do_disconnect_custom() internal method doesn't exist."""
        assert hasattr(mock_app, "_do_disconnect_custom"), (
            "App has no _do_disconnect_custom() method"
        )

    def test_get_custom_mode_exists(self, mock_app):
        """FAIL: _get_custom_mode() helper doesn't exist."""
        assert hasattr(mock_app, "_get_custom_mode"), (
            "App has no _get_custom_mode() method — needed to distinguish "
            "API vs Web in _export_provider and _is_provider_connected"
        )
