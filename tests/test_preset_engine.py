"""Tests: preset engine (TICKET-002-D, variant A).

Covers core/preset_engine.py (validate/filter/path, no file reading or
mapping — scope 002-E) and the navigation:click branch in open_chat.
Style: plain asserts like test_config_web.py, MagicMock page like
test_custom_*.py. No live sites.
"""

from unittest.mock import MagicMock

from core.preset_engine import (
    CATALOG_FILENAME,
    DEFAULT_WAIT_AFTER_CLICK_MS,
    filter_valid_presets,
    resolve_catalog_path,
    resolve_navigation,
    validate_preset,
)


def _selector_preset(**over):
    p = {
        "id": "perplexity",
        "name": "Perplexity",
        "description": "Preset initially tested with Perplexity",
        "default_url": "https://www.perplexity.ai/",
        "version": 1,
        "checked_at": "2026-09-24",
        "strategy": {
            "type": "selector",
            "navigation": "goto",
            "wait_after_click_ms": 2000,
            "selectors": {
                "chat_list_selector": "nav a[href*='/chat/']",
                "title_selector": ".chat-title",
                "message_selector": ".message-content",
                "user_message_selector": ".user-message",
                "assistant_message_selector": ".assistant-message",
                "scroll_container_selector": "nav",
            },
            "scripts": {"list_chats_js": "", "extract_messages_js": ""},
        },
    }
    p.update(over)
    return p


def _script_preset():
    return {
        "id": "qwen-script",
        "strategy": {
            "type": "script",
            "navigation": "click",
            "wait_after_click_ms": 2000,
            "selectors": {},
            "scripts": {
                "list_chats_js": "() => { return []; }",
                "extract_messages_js": "() => { return []; }",
            },
        },
    }


class TestValidatePreset:
    def test_valid_selector_preset(self):
        ok, errors = validate_preset(_selector_preset())
        assert ok is True
        assert errors == []

    def test_valid_script_preset(self):
        ok, errors = validate_preset(_script_preset())
        assert ok is True
        assert errors == []

    def test_missing_wait_is_valid_default_applies(self):
        p = _selector_preset()
        del p["strategy"]["wait_after_click_ms"]
        ok, errors = validate_preset(p)
        assert ok is True
        assert errors == []

    def test_none_wait_is_valid_default_applies(self):
        p = _selector_preset()
        p["strategy"]["wait_after_click_ms"] = None
        ok, errors = validate_preset(p)
        assert ok is True
        assert errors == []

    def test_missing_navigation_defaults_goto_valid(self):
        p = _selector_preset()
        del p["strategy"]["navigation"]
        ok, errors = validate_preset(p)
        assert ok is True
        assert errors == []

    def test_not_a_dict(self):
        for bad in (None, [], "perplexity", 42):
            ok, errors = validate_preset(bad)
            assert ok is False
            assert errors != []

    def test_bad_id(self):
        for bad_id in ("", "   ", 123, None):
            p = _selector_preset(id=bad_id)
            ok, errors = validate_preset(p)
            assert ok is False, bad_id
            assert errors != []

    def test_missing_strategy_or_type(self):
        p = _selector_preset()
        del p["strategy"]
        ok, errors = validate_preset(p)
        assert ok is False
        assert errors != []
        for bad_type in ("selectors", "", None, 123):
            p = _selector_preset()
            p["strategy"]["type"] = bad_type
            ok, errors = validate_preset(p)
            assert ok is False, bad_type
            assert errors != []

    def test_selector_missing_required_selectors(self):
        for key in ("message_selector", "chat_list_selector"):
            p = _selector_preset()
            p["strategy"]["selectors"][key] = ""
            ok, errors = validate_preset(p)
            assert ok is False, key
            assert errors != []

    def test_selector_hybrid_js_forbidden(self):
        for key in ("list_chats_js", "extract_messages_js"):
            p = _selector_preset()
            p["strategy"]["scripts"][key] = "() => { return []; }"
            ok, errors = validate_preset(p)
            assert ok is False, key
            assert errors != []

    def test_script_requires_list_chats_js(self):
        p = _script_preset()
        p["strategy"]["scripts"]["list_chats_js"] = "   "
        ok, errors = validate_preset(p)
        assert ok is False
        assert errors != []

    def test_bad_wait_values(self):
        for bad in (0, -1, -2000, "2000", 2.5, True, False, [], {}):
            p = _selector_preset()
            p["strategy"]["wait_after_click_ms"] = bad
            ok, errors = validate_preset(p)
            assert ok is False, repr(bad)
            assert errors != []

    def test_bad_navigation(self):
        for bad in ("href", "", None.__class__ and 123, "GOTO"):
            p = _selector_preset()
            p["strategy"]["navigation"] = bad
            ok, errors = validate_preset(p)
            assert ok is False, repr(bad)
            assert errors != []

    def test_non_string_selector(self):
        p = _selector_preset()
        p["strategy"]["selectors"]["message_selector"] = 123
        ok, errors = validate_preset(p)
        assert ok is False
        assert errors != []

    def test_default_wait_value(self):
        assert DEFAULT_WAIT_AFTER_CLICK_MS == 2000

    def test_extra_unknown_fields_ignored(self):
        p = _selector_preset()
        p["future_field"] = {"nested": [1, 2, 3]}
        p["strategy"]["unknown_option"] = True
        p["strategy"]["selectors"]["custom_extra"] = "x"
        ok, errors = validate_preset(p)
        assert ok is True
        assert errors == []


class TestFilterValidPresets:
    def test_mixed_list_keeps_only_valid(self):
        bad = _selector_preset(id="")
        good = _selector_preset()
        script = _script_preset()
        out = filter_valid_presets([good, bad, script, None, "x", 42])
        assert out == [good, script]

    def test_empty(self):
        assert filter_valid_presets([]) == []
        assert filter_valid_presets(None) == []


class TestCatalogPath:
    def test_resolve_catalog_path(self, tmp_path):
        path = resolve_catalog_path(str(tmp_path))
        assert path.endswith(CATALOG_FILENAME)
        assert str(tmp_path) in path

    def test_catalog_filename(self):
        assert CATALOG_FILENAME == "custom_presets.json"


class TestResolveNavigation:
    def test_click_preset(self):
        assert resolve_navigation([_script_preset()], "qwen-script") == "click"

    def test_goto_preset(self):
        assert resolve_navigation([_selector_preset()], "perplexity") == "goto"

    def test_unknown_id_defaults_goto(self):
        assert resolve_navigation([_selector_preset()], "nope") == "goto"

    def test_invalid_preset_defaults_goto(self):
        assert resolve_navigation([_selector_preset(id="")], "") == "goto"

    def test_empty_catalog_defaults_goto(self):
        assert resolve_navigation([], "perplexity") == "goto"


class TestPresetBinding:
    def test_no_binding_defaults_goto(self, mock_app):
        assert mock_app._preset_navigation(1) == "goto"

    def test_bind_and_resolve_click(self, mock_app):
        mock_app._preset_catalog = [_script_preset()]
        mock_app.bind_preset(1, "qwen-script")
        assert mock_app._preset_navigation(1) == "click"
        assert mock_app._preset_navigation(2) == "goto"

    def test_unbind_restores_goto(self, mock_app):
        mock_app._preset_catalog = [_script_preset()]
        mock_app.bind_preset(1, "qwen-script")
        mock_app.bind_preset(1, None)
        assert mock_app._preset_navigation(1) == "goto"

    def test_bind_unknown_slot_raises(self, mock_app):
        import pytest

        with pytest.raises(RuntimeError):
            mock_app.bind_preset(3, "qwen-script")

    def test_catalog_path_helper(self, mock_app, tmp_path):
        mock_app._storage_dir = str(tmp_path)
        path = mock_app._preset_catalog_path()
        assert path.endswith("custom_presets.json")
        assert str(tmp_path) in path


def _mock_page():
    page = MagicMock()
    page.url = "https://example.com/"
    return page


class TestClickBranch:
    def _cfg(self):
        return {
            "chat_list_selector": "nav a",
            "message_selector": ".msg",
            "wait_after_click_ms": 2000,
        }

    def test_selector_click_skips_goto(self):
        from adapters.custom_web import SelectorStrategy

        page = _mock_page()
        strat = SelectorStrategy(page, self._cfg(), navigation="click")
        assert strat.open_chat({"url": "https://example.com/c/1", "_index": 0}) is True
        page.goto.assert_not_called()
        page.evaluate.assert_called()
        page.wait_for_timeout.assert_called_with(2000)

    def test_selector_click_uses_keyword_arg(self):
        # Live bug (2026-09-29 log): positional arg raises TypeError in this
        # Playwright version (arg is keyword-only) -> click always failed.
        from adapters.custom_web import SelectorStrategy

        page = _mock_page()

        def strict_wait(expression, *args, **kwargs):
            if args:
                raise TypeError(
                    "Page.wait_for_function() takes 2 positional arguments "
                    f"but {2 + len(args)} positional arguments were given"
                )
            return MagicMock()

        page.wait_for_function.side_effect = strict_wait
        strat = SelectorStrategy(page, self._cfg(), navigation="click")
        assert strat.open_chat({"url": "https://example.com/c/1", "_index": 0}) is True
        page.goto.assert_not_called()

    def test_selector_click_waits_for_messages(self):
        from adapters.custom_web import SelectorStrategy

        page = _mock_page()
        strat = SelectorStrategy(page, self._cfg(), navigation="click")
        strat.open_chat({"_index": 0})
        page.wait_for_function.assert_called_once()
        args, kwargs = page.wait_for_function.call_args
        assert any(".msg" in str(a) for a in list(args) + list(kwargs.values()))

    def test_selector_click_timeout_is_honest_false(self):
        from adapters.custom_web import SelectorStrategy

        page = _mock_page()
        page.wait_for_function.side_effect = Exception("timeout")
        strat = SelectorStrategy(page, self._cfg(), navigation="click")
        assert strat.open_chat({"_index": 0}) is False
        page.goto.assert_not_called()

    def test_selector_goto_default_regression(self):
        from adapters.custom_web import SelectorStrategy

        page = _mock_page()
        strat = SelectorStrategy(page, self._cfg())
        assert strat.open_chat({"url": "https://example.com/c/1", "_index": 0}) is True
        page.goto.assert_called_once()

    def test_selector_invalid_navigation_defaults_goto(self):
        from adapters.custom_web import SelectorStrategy

        page = _mock_page()
        strat = SelectorStrategy(page, self._cfg(), navigation="href")
        assert strat.open_chat({"url": "https://example.com/c/1"}) is True
        page.goto.assert_called_once()

    def test_script_click_skips_goto(self):
        from adapters.custom_web import ScriptStrategy

        page = _mock_page()
        cfg = dict(self._cfg())
        cfg["list_chats_js"] = "() => { return []; }"
        strat = ScriptStrategy(page, cfg, navigation="click")
        assert strat.open_chat({"url": "https://example.com/c/1", "_index": 0}) is True
        page.goto.assert_not_called()

    def test_script_goto_default_regression(self):
        from adapters.custom_web import ScriptStrategy

        page = _mock_page()
        cfg = dict(self._cfg())
        cfg["list_chats_js"] = "() => { return []; }"
        strat = ScriptStrategy(page, cfg)
        assert strat.open_chat({"url": "https://example.com/c/1"}) is True
        page.goto.assert_called_once()

    def test_slot_binding_routes_click_through_adapter(self, mock_app):
        from adapters.custom_web import CustomWebAdapter, ScriptStrategy
        from unittest.mock import MagicMock, patch
        from main import App

        mock_app._preset_catalog = [_script_preset()]
        mock_app._preset_binding = {1: "qwen-script"}
        page = _mock_page()
        web_cfg = {"mode": "web", "chat_list_selector": "nav a",
                   "message_selector": ".msg", "wait_after_click_ms": 2000,
                   "list_chats_js": "() => { return []; }"}
        with patch("main.load_custom_config", return_value=web_cfg):
            adapter = App._adapter_for(mock_app, "custom1", page)
        assert isinstance(adapter, CustomWebAdapter)
        assert adapter.navigation == "click"
        assert isinstance(adapter._strategy, ScriptStrategy)
        assert adapter.open_chat({"url": "https://x/c/1", "_index": 0}) is True
        page.goto.assert_not_called()

    def test_slot_without_binding_defaults_goto(self, mock_app):
        from adapters.custom_web import CustomWebAdapter
        from unittest.mock import MagicMock, patch
        from main import App

        mock_app._preset_catalog = []
        mock_app._preset_binding = {}
        page = _mock_page()
        web_cfg = {"mode": "web", "chat_list_selector": "nav a",
                   "message_selector": ".msg", "wait_after_click_ms": 2000}
        with patch("main.load_custom_config", return_value=web_cfg):
            adapter = App._adapter_for(mock_app, "custom1", page)
        assert isinstance(adapter, CustomWebAdapter)
        assert adapter.navigation == "goto"
