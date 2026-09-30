"""Tests: _do_connect_custom / _do_disconnect_custom behavior.

PROBLEM: Plan defines _do_connect_custom(slot, url) that creates a page via
CDP browser, and _do_disconnect_custom(slot) that closes it. These methods
must actually create/close pages, not just exist.
"""

from unittest.mock import patch, MagicMock, PropertyMock


class TestDoConnectCustom:
    """_do_connect_custom must create a page and store it."""

    def test_connect_creates_page_attribute(self, mock_app):
        """FAIL: _do_connect_custom doesn't create custom1_page."""
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_browser.contexts = [MagicMock()]
        mock_browser.contexts[0].new_page.return_value = mock_page

        with patch.object(mock_app, "_cdp_browser", return_value=mock_browser), \
             patch.object(mock_app, "_is_page_alive", return_value=True):
            mock_app._do_connect_custom(1, "https://chat.mistral.ai")

        assert mock_app.custom1_page is mock_page, (
            "_do_connect_custom must set custom1_page to the new page"
        )

    def test_connect_closes_old_page_first(self, mock_app):
        """FAIL: _do_connect_custom doesn't close existing page."""
        old_page = MagicMock()
        mock_app.custom1_page = old_page

        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_browser.contexts = [MagicMock()]
        mock_browser.contexts[0].new_page.return_value = mock_page

        with patch.object(mock_app, "_cdp_browser", return_value=mock_browser), \
             patch.object(mock_app, "_is_page_alive", return_value=True):
            mock_app._do_connect_custom(1, "https://chat.mistral.ai")

        old_page.close.assert_called_once()
        assert mock_app.custom1_page is mock_page

    def test_connect_calls_goto_url(self, mock_app):
        """FAIL: _do_connect_custom doesn't navigate to the URL."""
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_browser.contexts = [MagicMock()]
        mock_browser.contexts[0].new_page.return_value = mock_page

        with patch.object(mock_app, "_cdp_browser", return_value=mock_browser), \
             patch.object(mock_app, "_is_page_alive", return_value=True):
            mock_app._do_connect_custom(1, "https://chat.mistral.ai")

        mock_page.goto.assert_called_once()
        call_args = mock_page.goto.call_args
        assert "mistral" in str(call_args), (
            f"_do_connect_custom must goto the URL, got: {call_args}"
        )

    def test_connect_raises_when_page_not_alive(self, mock_app):
        """FAIL: _do_connect_custom should raise when page is not alive."""
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_browser.contexts = [MagicMock()]
        mock_browser.contexts[0].new_page.return_value = mock_page

        with patch.object(mock_app, "_cdp_browser", return_value=mock_browser), \
             patch.object(mock_app, "_is_page_alive", return_value=False):
            try:
                mock_app._do_connect_custom(1, "https://bad-url")
                assert False, "Should have raised RuntimeError"
            except RuntimeError:
                pass

    def test_connect_custom2_uses_correct_attr(self, mock_app):
        """FAIL: _do_connect_custom(2) doesn't set custom2_page."""
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_browser.contexts = [MagicMock()]
        mock_browser.contexts[0].new_page.return_value = mock_page

        with patch.object(mock_app, "_cdp_browser", return_value=mock_browser), \
             patch.object(mock_app, "_is_page_alive", return_value=True):
            mock_app._do_connect_custom(2, "https://grok.x.ai")

        assert mock_app.custom2_page is mock_page, (
            "_do_connect_custom(2) must set custom2_page"
        )


class TestDoDisconnectCustom:
    """_do_disconnect_custom must close the page and set it to None."""

    def test_disconnect_closes_page(self, mock_app):
        """FAIL: _do_disconnect_custom doesn't close the page."""
        page = MagicMock()
        mock_app.custom1_page = page

        mock_app._do_disconnect_custom(1)

        page.close.assert_called_once()
        assert mock_app.custom1_page is None

    def test_disconnect_sets_none_when_no_page(self, mock_app):
        """FAIL: _do_disconnect_custom crashes when page is None."""
        mock_app.custom1_page = None
        mock_app._do_disconnect_custom(1)
        assert mock_app.custom1_page is None

    def test_disconnect_custom2_closes_correct_page(self, mock_app):
        """FAIL: _do_disconnect_custom(2) doesn't close custom2_page."""
        page = MagicMock()
        mock_app.custom2_page = page

        mock_app._do_disconnect_custom(2)

        page.close.assert_called_once()
        assert mock_app.custom2_page is None
