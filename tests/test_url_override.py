"""Tests: URL override contract (TICKET-002-F).

URL is a starting value, not the strategy identity: changing it must not
reset selectors, slot->preset binding, or navigation. Mocks only, no live
sites. Style: conftest.mock_app + MagicMock page.
"""

from unittest.mock import MagicMock, patch

import main as main_mod


def _web_cfg(url="https://chat.mistral.ai"):
    return {
        "mode": "web", "url": url,
        "chat_list_selector": "nav a", "title_selector": "",
        "message_selector": ".msg",
        "user_message_selector": ".user", "assistant_message_selector": ".asst",
        "scroll_container_selector": "", "wait_after_click_ms": 2000,
        "list_chats_js": "", "extract_messages_js": "",
    }


class TestReconnectPreservesStrategy:
    def test_do_connect_replaces_page_keeps_binding(self, mock_app):
        old_page = MagicMock()
        mock_app.custom1_page = old_page
        mock_app._preset_binding = {1: "perplexity"}
        browser = MagicMock()
        new_page = MagicMock()
        browser.contexts = [MagicMock()]
        browser.contexts[0].new_page.return_value = new_page
        mock_app._cdp_browser = MagicMock(return_value=browser)
        mock_app._is_page_alive = lambda p: True
        mock_app._do_connect_custom(1, "https://grok.x.ai")
        old_page.close.assert_called_once()
        assert mock_app.custom1_page is new_page
        assert mock_app._custom1_connected is True
        assert mock_app._preset_binding == {1: "perplexity"}

    def test_do_connect_does_not_touch_config(self, mock_app):
        mock_app.custom1_page = None
        mock_app._preset_binding = {}
        browser = MagicMock()
        browser.contexts = [MagicMock()]
        mock_app._cdp_browser = MagicMock(return_value=browser)
        mock_app._is_page_alive = lambda p: True
        with patch("main.load_custom_config") as load, \
                patch("main.save_custom_config") as save:
            mock_app._do_connect_custom(1, "https://example.com/")
            load.assert_not_called()
            save.assert_not_called()

    def test_disconnect_keeps_binding(self, mock_app):
        mock_app.custom1_page = MagicMock()
        mock_app._custom1_connected = True
        mock_app._preset_binding = {1: "perplexity"}
        mock_app._do_disconnect_custom(1)
        assert mock_app.custom1_page is None
        assert mock_app._custom1_connected is False
        assert mock_app._preset_binding == {1: "perplexity"}


class TestConfigUrlNotUsedInWork:
    def _page(self, chats=None, msgs=None):
        from adapters.custom_web import CustomWebAdapter  # noqa: F401

        page = MagicMock()
        page.url = "https://live.example/chat/1"
        page.title.return_value = "Live"
        return page

    def test_extract_same_result_for_foreign_and_empty_url(self):
        from adapters.custom_web import CustomWebAdapter

        raw = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        outs = []
        for url in ("https://foreign.example/", ""):
            page = MagicMock()
            page.url = "https://live.example/chat/1"
            page.title.return_value = "Live"
            page.evaluate.return_value = raw
            model = CustomWebAdapter(page, _web_cfg(url)).extract_chat({"id": "c"})
            outs.append([(m.role, m.content) for m in model.messages])
        assert outs[0] == outs[1] == [("user", "hi"), ("assistant", "hello")]

    def test_list_chats_ignores_url(self):
        from adapters.custom_web import CustomWebAdapter

        items = [{"id": "custom-0", "title": "T", "url": "https://x/", "_index": 0}]
        outs = []
        for url in ("https://foreign.example/", ""):
            page = MagicMock()
            page.url = "https://live.example/"
            page.evaluate.return_value = items
            outs.append(CustomWebAdapter(page, _web_cfg(url)).list_chats())
        assert outs[0] == outs[1] == items

    def test_export_does_not_compare_urls(self, mock_app):
        import main as main_mod

        mock_app._custom1_connected = True
        api = object.__new__(main_mod.API)
        api._app = mock_app
        with patch("main.load_custom_config", return_value=_web_cfg("https://other.example/")):
            assert api.export_custom_web(1, "[]") == "STARTED"

    def test_scan_uses_live_page_without_url_check(self, mock_app):
        page = MagicMock()
        page.url = "https://live-b.example/"
        page.evaluate.return_value = [{"id": "custom-0", "title": "T",
                                       "url": "https://live-b.example/", "_index": 0}]
        mock_app.custom1_page = page
        with patch("main.load_custom_config", return_value=_web_cfg("https://saved.example/")):
            chats = mock_app._do_scan_custom(1)
        assert chats == [{"id": "custom-0", "title": "T",
                          "url": "https://live-b.example/", "_index": 0}]


class TestConnectSerialization:
    def test_export_running_blocks_connect(self, mock_app):
        mock_app._locks["custom1"].acquire()
        try:
            try:
                mock_app.connect_custom_web(1, "https://example.com/")
            except RuntimeError as e:
                assert "BUSY" in str(e)
            else:
                raise AssertionError("expected BUSY")
        finally:
            mock_app._locks["custom1"].release()

    def test_second_concurrent_connect_gets_busy(self, mock_app):
        import threading

        mock_app._locks["custom1"].acquire()
        errors = []
        try:
            t = threading.Thread(
                target=lambda: errors.append(_try_connect(mock_app)))
            t.start()
            t.join(timeout=10)
        finally:
            mock_app._locks["custom1"].release()
        assert errors and "BUSY" in errors[0]

    def test_successful_connect_releases_lock(self, mock_app):
        mock_app.custom1_page = MagicMock()
        with _immediate_events():
            assert mock_app.connect_custom_web(1, "https://example.com/") == "OK"
        assert mock_app._locks["custom1"].acquire(blocking=False)
        mock_app._locks["custom1"].release()

    def test_export_running_blocks_disconnect(self, mock_app):
        page = MagicMock()
        mock_app.custom1_page = page
        mock_app._custom1_connected = True
        mock_app._locks["custom1"].acquire()
        try:
            try:
                mock_app.disconnect_custom_web(1)
            except RuntimeError as e:
                assert "BUSY" in str(e)
            else:
                raise AssertionError("expected BUSY")
        finally:
            mock_app._locks["custom1"].release()
        assert mock_app.custom1_page is page
        assert mock_app._custom1_connected is True

    def test_successful_disconnect_releases_lock(self, mock_app):
        # The mocked queue never runs the worker: only the bridge contract
        # (OK + released lock) is asserted here. Worker side-effects are
        # covered by direct _do_disconnect_custom tests.
        with _immediate_events():
            assert mock_app.disconnect_custom_web(1) == "OK"
        assert mock_app._locks["custom1"].acquire(blocking=False)
        mock_app._locks["custom1"].release()


def _try_connect(app):
    try:
        app.connect_custom_web(1, "https://example.com/")
        return "OK"
    except RuntimeError as e:
        return str(e)


class _immediate_events:
    """Patch threading.Event so connect_custom_web does not wait 30s."""

    def __init__(self):
        self._real = None

    def __enter__(self):
        import threading as _th

        real = _th.Event

        class _Ev(real):
            def wait(self, timeout=None):
                return True

        self._real = real
        _th.Event = _Ev
        main_mod.threading.Event = _Ev
        return self

    def __exit__(self, *a):
        import threading as _th

        _th.Event = self._real
        main_mod.threading.Event = self._real


class TestClickDirectAdapter:
    def test_selector_click_skips_goto(self):
        from adapters.custom_web import SelectorStrategy

        page = MagicMock()
        page.url = "https://x/"
        strat = SelectorStrategy(page, _web_cfg(), navigation="click")
        assert strat.open_chat({"url": "https://x/c/1", "_index": 0}) is True
        page.goto.assert_not_called()

    def test_script_click_skips_goto(self):
        from adapters.custom_web import ScriptStrategy

        page = MagicMock()
        page.url = "https://x/"
        cfg = _web_cfg()
        cfg["list_chats_js"] = "() => { return []; }"
        strat = ScriptStrategy(page, cfg, navigation="click")
        assert strat.open_chat({"url": "https://x/c/1", "_index": 0}) is True
        page.goto.assert_not_called()

    def test_empty_catalog_navigation_is_goto(self, mock_app):
        mock_app._preset_catalog = []
        mock_app._preset_binding = {1: "anything"}
        assert mock_app._preset_navigation(1) == "goto"
