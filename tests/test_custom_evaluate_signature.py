"""Tests: SelectorStrategy passes single arg object to evaluate (Blocker 2).

Playwright Page.evaluate(expression, arg) accepts ONE arg.
Previous code passed multiple positional args → TypeError on real browser.
"""

from unittest.mock import MagicMock
from adapters.custom_web import SelectorStrategy, ScriptStrategy


class TestSelectorStrategyEvaluateSignature:
    """evaluate must receive a single dict arg, not positional args."""

    def test_list_chats_passes_single_dict(self):
        page = MagicMock()
        page.evaluate.return_value = []
        config = {"chat_list_selector": "nav a", "title_selector": ".title"}
        strategy = SelectorStrategy(page, config)

        strategy.list_chats()

        call_args = page.evaluate.call_args
        js = call_args[0][0]
        arg = call_args[0][1]
        assert isinstance(arg, dict), f"Expected dict arg, got {type(arg).__name__}: {arg}"
        assert "listSel" in arg
        assert "titleSel" in arg
        assert arg["listSel"] == "nav a"
        assert arg["titleSel"] == ".title"

    def test_list_chats_one_arg_not_two(self):
        page = MagicMock()
        page.evaluate.return_value = []
        config = {"chat_list_selector": "nav a"}
        strategy = SelectorStrategy(page, config)

        strategy.list_chats()

        call_args = page.evaluate.call_args
        assert len(call_args[0]) == 2, (
            f"evaluate must have 2 positional args (js, arg), got {len(call_args[0])}"
        )

    def test_extract_chat_passes_single_dict(self):
        page = MagicMock()
        page.evaluate.return_value = []
        page.title.return_value = "Test"
        page.url = "https://example.com"
        config = {
            "message_selector": ".msg",
            "user_message_selector": ".user",
            "assistant_message_selector": ".bot",
        }
        strategy = SelectorStrategy(page, config)

        strategy.extract_chat({"id": "c1"})

        call_args = page.evaluate.call_args
        arg = call_args[0][1]
        assert isinstance(arg, dict)
        assert "msgSel" in arg
        assert "userSel" in arg
        assert "asstSel" in arg

    def test_scroll_counts_chat_list_not_container(self):
        page = MagicMock()
        page.evaluate.side_effect = [5, None, 5]
        config = {
            "chat_list_selector": "nav a",
            "scroll_container_selector": "nav",
        }
        strategy = SelectorStrategy(page, config)

        strategy._scroll_to_load("nav", "nav a")

        calls = page.evaluate.call_args_list
        # First call: count by chat_list_selector, not container
        assert calls[0][0][1] == "nav a", (
            f"First count should use chat_list_selector, got: {calls[0][0][1]}"
        )


class TestScriptStrategyPassesLogFunc:
    """ScriptStrategy must accept and use log_func."""

    def test_log_func_stored(self):
        page = MagicMock()
        log = MagicMock()
        config = {"list_chats_js": "return []"}
        strategy = ScriptStrategy(page, config, log_func=log)
        assert strategy.log is log

    def test_list_chats_logs_error(self):
        page = MagicMock()
        page.evaluate.side_effect = RuntimeError("evaluate failed")
        log = MagicMock()
        config = {"list_chats_js": "bad js"}
        strategy = ScriptStrategy(page, config, log_func=log)

        result = strategy.list_chats()

        assert result == []
        log.assert_called()
        assert "error" in str(log.call_args).lower()
