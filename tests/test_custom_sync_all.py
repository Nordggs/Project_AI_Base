"""Tests: _do_sync_all includes Custom Web providers."""

from unittest.mock import patch, MagicMock
import threading

from main import App


class TestSyncAllIncludesCustomWeb:
    """_do_sync_all must include Custom Web in sync order."""

    def test_sync_all_includes_custom1_web(self, mock_app):
        def connected(name):
            return name == "custom1"

        def mode(slot):
            return "web"

        with patch.object(App, "_is_provider_connected", side_effect=connected), \
             patch.object(App, "_get_custom_mode", side_effect=mode), \
             patch.object(App, "_emit_sync_all_summary"), \
             patch.object(mock_app, "window"), \
             patch.object(threading.Event, "wait", return_value=True):
            with patch.object(mock_app, "_gw_queue") as mock_queue:
                App._do_sync_all(mock_app)

                put_calls = [str(c) for c in mock_queue.put.call_args_list]
                assert any("custom1" in c for c in put_calls), (
                    f"_do_sync_all must queue custom1 for export. Calls: {put_calls}"
                )

    def test_sync_all_excludes_custom_api_mode(self, mock_app):
        def connected(name):
            return name == "custom1"

        def mode(slot):
            return "api"

        with patch.object(App, "_is_provider_connected", side_effect=connected), \
             patch.object(App, "_get_custom_mode", side_effect=mode), \
             patch.object(App, "_emit_sync_all_summary"), \
             patch.object(mock_app, "window"), \
             patch.object(threading.Event, "wait", return_value=True):
            with patch.object(mock_app, "_gw_queue") as mock_queue:
                App._do_sync_all(mock_app)

                put_calls = [str(c) for c in mock_queue.put.call_args_list]
                assert not any("custom1" in c for c in put_calls), (
                    f"_do_sync_all must NOT queue custom1 in API mode. Calls: {put_calls}"
                )

    def test_sync_all_custom_comes_after_standard_providers(self, mock_app):
        def connected(name):
            return True

        def mode(slot):
            return "web"

        with patch.object(App, "_is_provider_connected", side_effect=connected), \
             patch.object(App, "_get_custom_mode", side_effect=mode), \
             patch.object(App, "_emit_sync_all_summary"), \
             patch.object(mock_app, "window"), \
             patch.object(threading.Event, "wait", return_value=True):
            with patch.object(mock_app, "_gw_queue") as mock_queue:
                App._do_sync_all(mock_app)

                put_calls = [str(c) for c in mock_queue.put.call_args_list]
                standard_pos = -1
                custom_pos = -1
                for i, c in enumerate(put_calls):
                    if "chatgpt" in c or "gemini" in c:
                        standard_pos = i
                    if "custom1" in c:
                        custom_pos = i
                if standard_pos >= 0 and custom_pos >= 0:
                    assert custom_pos > standard_pos, (
                        f"Custom providers must come after standard. "
                        f"standard_pos={standard_pos}, custom_pos={custom_pos}"
                    )
