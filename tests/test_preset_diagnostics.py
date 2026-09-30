"""Tests: preset diagnostics check_custom_web (TICKET-002-G).

Verdicts on mocked counts, no live sites. Style: conftest.mock_app.
"""

import json
import os
from unittest.mock import MagicMock, patch

import main as main_mod


def _good_preset(**over):
    p = {
        "id": "perplexity",
        "name": "Perplexity",
        "description": "d",
        "default_url": "https://www.perplexity.ai/",
        "version": 1,
        "checked_at": "2026-09-24",
        "strategy": {
            "type": "selector",
            "navigation": "goto",
            "wait_after_click_ms": 2000,
            "selectors": {
                "chat_list_selector": "nav a",
                "title_selector": "",
                "message_selector": ".msg",
                "user_message_selector": ".user",
                "assistant_message_selector": ".asst",
                "scroll_container_selector": "",
            },
            "scripts": {"list_chats_js": "", "extract_messages_js": ""},
        },
    }
    p.update(over)
    return p


def _page_with_counts(counts, url="https://www.perplexity.ai/search/1"):
    page = MagicMock()
    page.url = url
    page.evaluate.return_value = counts
    return page


def _run_check(mock_app, page, catalog, preset_id="perplexity", slot=1):
    mock_app.custom1_page = page
    mock_app._preset_catalog = catalog
    mock_app._preset_binding = {1: preset_id} if preset_id else {}
    with patch("adapters.custom_web.CustomWebAdapter") as adapter_cls:
        adapter = adapter_cls.return_value
        try:
            n_chats = (page.evaluate.return_value or {}).get("chats", 0)
        except Exception:
            n_chats = 0
        adapter.list_chats.return_value = (
            [{"id": "custom-0", "title": "T", "url": "https://x/", "_index": 0}]
            if n_chats > 0
            else []
        )
        return mock_app._do_check_custom(slot, preset_id)


class TestVerdicts:
    def test_compatible(self, mock_app):
        page = _page_with_counts({"chats": 5, "messages": 10, "user": 5, "assistant": 5})
        res = _run_check(mock_app, page, [_good_preset()])
        assert res["verdict"] == "Compatible"
        assert res["reason"] == "ok"
        assert res["chat_list_N"] == 1
        assert res["messages_N"] == 10
        assert res["user_N"] == 5
        assert res["assistant_N"] == 5
        assert res["preset_id"] == "perplexity"
        assert "perplexity.ai" in res["page_url"]

    def test_partial_no_messages(self, mock_app):
        page = _page_with_counts({"chats": 5, "messages": 0, "user": 0, "assistant": 0})
        res = _run_check(mock_app, page, [_good_preset()])
        assert res["verdict"] == "Partial"
        assert res["chat_list_N"] == 1

    def test_partial_roles_not_split(self, mock_app):
        page = _page_with_counts({"chats": 2, "messages": 4, "user": 0, "assistant": 4})
        res = _run_check(mock_app, page, [_good_preset()])
        assert res["verdict"] == "Partial"

    def test_incompatible_no_chats(self, mock_app):
        page = _page_with_counts({"chats": 0, "messages": 0, "user": 0, "assistant": 0})
        res = _run_check(mock_app, page, [_good_preset()])
        assert res["verdict"] == "Incompatible"
        assert res["reason"] == "no_match"

    def test_wrong_page_hint(self, mock_app):
        page = _page_with_counts(
            {"chats": 0, "messages": 0, "user": 0, "assistant": 0},
            url="https://chat.mistral.ai/chat/1",
        )
        res = _run_check(mock_app, page, [_good_preset()])
        assert res["verdict"] == "Incompatible"
        assert res["reason"] == "wrong_page"

    def test_page_dead(self, mock_app):
        res = _run_check(mock_app, None, [_good_preset()])
        assert res["verdict"] == "Incompatible"
        assert res["reason"] == "page_dead"

    def test_format_invalid_no_evaluate(self, mock_app):
        page = _page_with_counts({"chats": 5, "messages": 5, "user": 2, "assistant": 3})
        bad = _good_preset(id="broken")
        bad["strategy"]["selectors"]["message_selector"] = ""
        res = _run_check(mock_app, page, [bad], preset_id="broken")
        assert res["verdict"] == "Incompatible"
        assert res["reason"] == "format_invalid"
        page.evaluate.assert_not_called()

    def test_chats_zero_with_messages_is_incompatible(self, mock_app):
        # Perplexity case (002-C): title-empty links dropped by the list
        # filter — export would find nothing, so never Compatible.
        page = _page_with_counts({"chats": 0, "messages": 6, "user": 3, "assistant": 3})
        res = _run_check(mock_app, page, [_good_preset()])
        assert res["verdict"] == "Incompatible"
        assert res["reason"] == "no_match"

    def test_scroll_selector_ok_empty(self, mock_app):
        page = _page_with_counts({"chats": 3, "messages": 0, "user": 0, "assistant": 0})
        res = _run_check(mock_app, page, [_good_preset()])
        assert res["scroll"] == "ok"

    def test_scroll_script_unknown(self, mock_app):
        preset = _good_preset()
        preset["strategy"]["type"] = "script"
        preset["strategy"]["selectors"] = {}
        preset["strategy"]["scripts"] = {
            "list_chats_js": "() => { return []; }",
            "extract_messages_js": "() => { return []; }",
        }
        page = _page_with_counts({"chats": 2, "messages": 4, "user": 2, "assistant": 2})
        res = _run_check(mock_app, page, [preset])
        assert res["scroll"] == "unknown"


class TestCatalogMemory:
    def test_list_presets_populates_memory_catalog(self, tmp_path):
        import shutil

        import main as main_mod

        src = os.path.join(os.path.dirname(__file__), "fixtures", "custom_presets.json")
        shutil.copy(src, os.path.join(str(tmp_path), "custom_presets.json"))
        api = object.__new__(main_mod.API)
        app = object.__new__(main_mod.App)
        app._storage_dir = str(tmp_path)
        api._app = app
        presets = api.list_presets()
        assert [p["id"] for p in presets] == ["perplexity"]
        assert [p["id"] for p in app._preset_catalog] == ["perplexity"]

    def test_check_resolves_from_memory_catalog(self, mock_app, tmp_path):
        import shutil

        src = os.path.join(os.path.dirname(__file__), "fixtures", "custom_presets.json")
        shutil.copy(src, os.path.join(str(tmp_path), "custom_presets.json"))
        mock_app._storage_dir = str(tmp_path)
        api = object.__new__(__import__("main").API)
        api._app = mock_app
        api.list_presets()  # fills mock_app._preset_catalog, no manual setup
        page = _page_with_counts({"chats": 2, "messages": 4, "user": 2, "assistant": 2})
        mock_app.custom1_page = page
        with patch("adapters.custom_web.CustomWebAdapter") as adapter_cls:
            adapter_cls.return_value.list_chats.return_value = [{"id": "c"}]
            res = mock_app._do_check_custom(1, "perplexity")
        assert res["verdict"] == "Compatible"
        assert res["reason"] == "ok"

    def test_unknown_preset_falls_back_to_slot(self, mock_app):
        page = _page_with_counts({"chats": 2, "messages": 4, "user": 2, "assistant": 2})
        mock_app.custom1_page = page
        mock_app._preset_catalog = [_good_preset()]
        cfg = {
            "mode": "web", "url": "https://www.perplexity.ai/",
            "chat_list_selector": "nav a", "title_selector": "",
            "message_selector": ".msg",
            "user_message_selector": ".user", "assistant_message_selector": ".asst",
            "scroll_container_selector": "", "wait_after_click_ms": 2000,
            "list_chats_js": "", "extract_messages_js": "",
        }
        with patch("main.load_custom_config", return_value=cfg), \
                patch("adapters.custom_web.CustomWebAdapter") as adapter_cls:
            adapter_cls.return_value.list_chats.return_value = [{"id": "c"}]
            res = mock_app._do_check_custom(1, "stale-id")
        assert res["verdict"] == "Compatible"
        assert res["preset_id"] == ""
        page.evaluate.assert_called()


class TestManualFields:
    def test_no_preset_checks_slot_selectors(self, mock_app):
        page = _page_with_counts({"chats": 2, "messages": 4, "user": 2, "assistant": 2})
        mock_app.custom1_page = page
        mock_app._preset_catalog = []
        mock_app._preset_binding = {}
        cfg = {
            "mode": "web", "url": "https://example.com/",
            "chat_list_selector": "nav a", "title_selector": "",
            "message_selector": ".msg",
            "user_message_selector": ".user", "assistant_message_selector": ".asst",
            "scroll_container_selector": "", "wait_after_click_ms": 2000,
            "list_chats_js": "", "extract_messages_js": "",
        }
        with patch("main.load_custom_config", return_value=cfg), \
                patch("adapters.custom_web.CustomWebAdapter") as adapter_cls:
            adapter_cls.return_value.list_chats.return_value = [{"id": "c"}]
            res = mock_app._do_check_custom(1, None)
        assert res["verdict"] == "Compatible"
        assert res["preset_id"] in ("", None)


class TestBridge:
    def test_bridge_delegates_and_json_serializable(self, mock_app):
        import main as main_mod

        expected = {"preset_id": "p", "page_url": "u", "chat_list_N": 1,
                    "messages_N": 2, "user_N": 1, "assistant_N": 1,
                    "scroll": "ok", "verdict": "Compatible", "reason": "ok"}
        mock_app.check_custom_web = MagicMock(return_value=expected)
        api = object.__new__(main_mod.API)
        api._app = mock_app
        res = api.check_custom_web(1, "p")
        mock_app.check_custom_web.assert_called_once_with(1, "p")
        json.dumps(res)

    def test_bridge_queues_command_not_evaluate(self, mock_app):
        mock_app._sync_results = {}
        mock_app._sync_done_events = {}
        mock_app._gw_queue = MagicMock()
        mock_app._preset_catalog = [_good_preset()]
        mock_app._preset_binding = {1: "perplexity"}
        with _immediate_events():
            mock_app.check_custom_web(1, "perplexity")
        mock_app._gw_queue.put.assert_called_once()
        cmd, _arg = mock_app._gw_queue.put.call_args[0][0]
        assert cmd == "check_custom1"


class _immediate_events:
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
