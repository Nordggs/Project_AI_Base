"""Tests: _get_custom_mode and _page_for behavior.

PROBLEM: _get_custom_mode(slot) must return the mode from config ("api" or "web").
_page_for(name) must handle custom1/custom2 names.
"""

from unittest.mock import patch, MagicMock

from main import App


class TestGetCustomMode:
    """_get_custom_mode must return mode from config."""

    def test_returns_api_mode(self, mock_app):
        """FAIL: _get_custom_mode doesn't exist or return 'api'."""
        with patch("main.load_custom_config", return_value={"mode": "api"}):
            result = App._get_custom_mode(mock_app, 1)
        assert result == "api", f"Expected 'api', got {result!r}"

    def test_returns_web_mode(self, mock_app):
        """FAIL: _get_custom_mode doesn't return 'web'."""
        with patch("main.load_custom_config", return_value={"mode": "web"}):
            result = App._get_custom_mode(mock_app, 1)
        assert result == "web", f"Expected 'web', got {result!r}"

    def test_returns_api_when_mode_missing(self, mock_app):
        """FAIL: _get_custom_mode should default to 'api' when mode not in config."""
        with patch("main.load_custom_config", return_value={"endpoint": "x"}):
            result = App._get_custom_mode(mock_app, 1)
        assert result == "api", f"Expected 'api' default, got {result!r}"

    def test_custom2_slot(self, mock_app):
        """FAIL: _get_custom_mode doesn't work for slot 2."""
        with patch("main.load_custom_config", return_value={"mode": "web"}):
            result = App._get_custom_mode(mock_app, 2)
        assert result == "web", f"Expected 'web' for slot 2, got {result!r}"


class TestPageForCustom:
    """_page_for must handle custom1/custom2 names."""

    def test_page_for_custom1_returns_custom1_page(self, mock_app):
        """FAIL: _page_for('custom1') doesn't return custom1_page."""
        page = MagicMock()
        mock_app.custom1_page = page
        result = App._page_for(mock_app, "custom1")
        assert result is page, f"Expected custom1_page, got {result!r}"

    def test_page_for_custom2_returns_custom2_page(self, mock_app):
        """FAIL: _page_for('custom2') doesn't return custom2_page."""
        page = MagicMock()
        mock_app.custom2_page = page
        result = App._page_for(mock_app, "custom2")
        assert result is page, f"Expected custom2_page, got {result!r}"

    def test_page_for_custom1_returns_none_when_not_set(self, mock_app):
        """FAIL: _page_for('custom1') doesn't return None when page is None."""
        mock_app.custom1_page = None
        result = App._page_for(mock_app, "custom1")
        assert result is None

    def test_page_for_existing_providers_unchanged(self, mock_app):
        """PASS: _page_for still works for existing providers."""
        mock_app.gemini_page = MagicMock()
        result = App._page_for(mock_app, "gemini")
        assert result is mock_app.gemini_page
