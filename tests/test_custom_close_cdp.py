"""Tests: close_cdp command and _close_cdp_browser cleanup behavior."""

from unittest.mock import MagicMock, patch
import queue

from main import App


class TestCdpStatusBridge:
    """get_cdp_status must report the real manager state (TICKET-002-J)."""

    def _api(self, mock_app):
        import main as main_mod

        api = object.__new__(main_mod.API)
        api._app = mock_app
        return api

    def test_reports_running(self, mock_app):
        mock_app.cdp.state = "running"
        assert self._api(mock_app).get_cdp_status() == "running"

    def test_reports_stopped(self, mock_app):
        mock_app.cdp.state = "stopped"
        assert self._api(mock_app).get_cdp_status() == "stopped"

    def test_reports_starting(self, mock_app):
        mock_app.cdp.state = "starting"
        assert self._api(mock_app).get_cdp_status() == "starting"


class TestCloseCdpCommandBehavior:
    """close_cdp command must close custom pages via worker."""

    def test_close_cdp_worker_closes_custom_pages(self, mock_app):
        custom1_page = MagicMock()
        custom2_page = MagicMock()
        mock_app.custom1_page = custom1_page
        mock_app.custom2_page = custom2_page
        mock_app._gw_browser = MagicMock()

        call_count = [0]
        def get_side_effect(timeout=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return ("close_cdp", "gw")
            raise KeyboardInterrupt()
        mock_app._gw_queue.get = get_side_effect

        with patch("playwright.sync_api.sync_playwright") as mock_pw:
            mock_pw.return_value.start.return_value = MagicMock()
            try:
                App._gw_worker(mock_app)
            except (KeyboardInterrupt, Exception):
                pass

        custom1_page.close.assert_called()
        custom2_page.close.assert_called()

    def test_soft_stop_worker_stops_custom_pages(self, mock_app):
        custom1_page = MagicMock()
        custom2_page = MagicMock()
        mock_app.custom1_page = custom1_page
        mock_app.custom2_page = custom2_page

        call_count = [0]
        def get_side_effect(timeout=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return ("soft_stop", "")
            raise KeyboardInterrupt()
        mock_app._gw_queue.get = get_side_effect

        with patch("playwright.sync_api.sync_playwright") as mock_pw:
            mock_pw.return_value.start.return_value = MagicMock()
            try:
                App._gw_worker(mock_app)
            except (KeyboardInterrupt, Exception):
                pass

        custom1_page.evaluate.assert_called_with("window.stop()")
        custom2_page.evaluate.assert_called_with("window.stop()")


class TestCloseCdpBrowserBehavior:
    """_close_cdp_browser must reset custom pages and flags."""

    def _run_close_cdp_browser(self, mock_app):
        mock_app._pw_queue = MagicMock()
        mock_app._gw_queue = MagicMock()
        mock_app._close_pw_done = MagicMock()
        mock_app._close_gw_done = MagicMock()
        mock_app._close_pw_done.wait = MagicMock(return_value=True)
        mock_app._close_gw_done.wait = MagicMock(return_value=True)
        try:
            App._close_cdp_browser(mock_app)
        except Exception:
            pass

    def test_resets_custom1_page(self, mock_app):
        mock_app.custom1_page = MagicMock()
        mock_app.custom2_page = MagicMock()
        self._run_close_cdp_browser(mock_app)
        assert mock_app.custom1_page is None

    def test_resets_custom2_page(self, mock_app):
        mock_app.custom1_page = MagicMock()
        mock_app.custom2_page = MagicMock()
        self._run_close_cdp_browser(mock_app)
        assert mock_app.custom2_page is None

    def test_resets_custom_connected_flags(self, mock_app):
        mock_app._custom1_connected = True
        mock_app._custom2_connected = True
        self._run_close_cdp_browser(mock_app)
        assert mock_app._custom1_connected is False
        assert mock_app._custom2_connected is False
