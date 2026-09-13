"""Tests: open_chat resolves relative URLs to absolute (Blocker 7).

Both SelectorStrategy and ScriptStrategy must resolve relative URLs
(e.g. /chat/123) to absolute before calling page.goto().
Also, ScriptStrategy must fall back to _index-based click when no selector.
"""

from unittest.mock import MagicMock
from adapters.custom_web import SelectorStrategy, ScriptStrategy


class TestSelectorStrategyUrlResolution:
    """SelectorStrategy must resolve relative URLs before goto."""

    def test_relative_url_resolved_to_absolute(self):
        page = MagicMock()
        page.evaluate.return_value = "https://example.com/chat/42"
        config = {"chat_list_selector": "nav a"}
        strategy = SelectorStrategy(page, config)

        result = strategy.open_chat({"url": "/chat/42"})

        page.evaluate.assert_called_once()
        call_args = page.evaluate.call_args
        assert "new URL(href, location.href)" in call_args[0][0]
        assert call_args[0][1] == "/chat/42"
        page.goto.assert_called_once_with(
            "https://example.com/chat/42",
            wait_until="domcontentloaded",
            timeout=15000,
        )

    def test_absolute_url_skips_resolution(self):
        page = MagicMock()
        config = {"chat_list_selector": "nav a"}
        strategy = SelectorStrategy(page, config)

        result = strategy.open_chat({"url": "https://example.com/chat/42"})

        page.evaluate.assert_not_called()
        page.goto.assert_called_once_with(
            "https://example.com/chat/42",
            wait_until="domcontentloaded",
            timeout=15000,
        )

    def test_empty_url_falls_back_to_index_click(self):
        page = MagicMock()
        page.evaluate.return_value = True
        config = {"chat_list_selector": "nav a", "wait_after_click_ms": 500}
        strategy = SelectorStrategy(page, config)

        result = strategy.open_chat({"url": "", "_index": 3})

        assert result is True
        page.evaluate.assert_called_once()
        call_args = page.evaluate.call_args
        assert call_args[0][1] == {"sel": "nav a", "idx": 3}


class TestScriptStrategyUrlResolution:
    """ScriptStrategy must resolve relative URLs before goto."""

    def test_relative_url_resolved_to_absolute(self):
        page = MagicMock()
        page.evaluate.return_value = "https://example.com/chat/99"
        config = {"list_chats_js": "return []"}
        strategy = ScriptStrategy(page, config)

        result = strategy.open_chat({"url": "/chat/99"})

        page.evaluate.assert_called_once()
        call_args = page.evaluate.call_args
        assert "new URL(href, location.href)" in call_args[0][0]
        page.goto.assert_called_once_with(
            "https://example.com/chat/99",
            wait_until="domcontentloaded",
            timeout=15000,
        )

    def test_absolute_url_skips_resolution(self):
        page = MagicMock()
        config = {"list_chats_js": "return []"}
        strategy = ScriptStrategy(page, config)

        result = strategy.open_chat({"url": "https://example.com/chat/99"})

        page.evaluate.assert_not_called()
        page.goto.assert_called_once()

    def test_fallback_to_index_click_when_no_selector(self):
        page = MagicMock()
        page.evaluate.return_value = True
        config = {"chat_list_selector": "nav a", "wait_after_click_ms": 1000}
        strategy = ScriptStrategy(page, config)

        result = strategy.open_chat({"url": "", "_index": 2})

        assert result is True
        call_args = page.evaluate.call_args
        assert call_args[0][1] == {"sel": "nav a", "idx": 2}

    def test_no_url_no_selector_no_index_returns_false(self):
        page = MagicMock()
        config = {"list_chats_js": "return []"}
        strategy = ScriptStrategy(page, config)

        result = strategy.open_chat({})

        assert result is False
