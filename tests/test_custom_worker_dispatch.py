"""Tests: Worker command dispatch for custom connect/disconnect."""

from unittest.mock import patch, MagicMock
import queue

from main import App


class TestWorkerCustomCommands:
    """_gw_worker must dispatch connect_custom1/2 and disconnect_custom1/2."""

    def _run_worker_with_cmd(self, mock_app, cmd, arg=""):
        call_count = [0]
        def get_side_effect(timeout=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return (cmd, arg)
            raise KeyboardInterrupt()
        mock_app._gw_queue.get = get_side_effect

        with patch("playwright.sync_api.sync_playwright") as mock_pw:
            mock_pw.return_value.start.return_value = MagicMock()
            try:
                App._gw_worker(mock_app)
            except (KeyboardInterrupt, Exception):
                pass

    def test_worker_handles_connect_custom1(self, mock_app):
        with patch.object(mock_app, "_do_connect_custom") as mock_connect, \
             patch.object(mock_app, "_cdp_lock"):
            self._run_worker_with_cmd(mock_app, "connect_custom1", "https://chat.mistral.ai")
            mock_connect.assert_called_once_with(1, "https://chat.mistral.ai")

    def test_worker_handles_disconnect_custom1(self, mock_app):
        with patch.object(mock_app, "_do_disconnect_custom") as mock_disconnect:
            self._run_worker_with_cmd(mock_app, "disconnect_custom1")
            mock_disconnect.assert_called_once_with(1)

    def test_worker_handles_connect_custom2(self, mock_app):
        with patch.object(mock_app, "_do_connect_custom") as mock_connect, \
             patch.object(mock_app, "_cdp_lock"):
            self._run_worker_with_cmd(mock_app, "connect_custom2", "https://grok.x.ai")
            mock_connect.assert_called_once_with(2, "https://grok.x.ai")
