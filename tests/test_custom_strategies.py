"""Tests: SelectorStrategy and ScriptStrategy behavior.

PROBLEM: Plan defines SelectorStrategy and ScriptStrategy inside
adapters/custom_web.py. They must implement list_chats(), open_chat(),
extract_chat() with correct return types.
"""

import importlib
import pytest


class TestSelectorStrategyBehavior:
    """SelectorStrategy must implement the strategy interface."""

    def test_has_list_chats_method(self):
        """FAIL: SelectorStrategy must have list_chats method."""
        try:
            mod = importlib.import_module("adapters.custom_web")
        except ImportError:
            pytest.fail("adapters.custom_web not importable")
        cls = getattr(mod, "SelectorStrategy", None)
        assert cls is not None, "SelectorStrategy not found"
        assert callable(getattr(cls, "list_chats", None)), (
            "SelectorStrategy must have list_chats method"
        )

    def test_has_open_chat_method(self):
        """FAIL: SelectorStrategy must have open_chat method."""
        try:
            mod = importlib.import_module("adapters.custom_web")
        except ImportError:
            pytest.fail("adapters.custom_web not importable")
        cls = getattr(mod, "SelectorStrategy", None)
        assert cls is not None
        assert callable(getattr(cls, "open_chat", None)), (
            "SelectorStrategy must have open_chat method"
        )

    def test_has_extract_chat_method(self):
        """FAIL: SelectorStrategy must have extract_chat method."""
        try:
            mod = importlib.import_module("adapters.custom_web")
        except ImportError:
            pytest.fail("adapters.custom_web not importable")
        cls = getattr(mod, "SelectorStrategy", None)
        assert cls is not None
        assert callable(getattr(cls, "extract_chat", None)), (
            "SelectorStrategy must have extract_chat method"
        )

    def test_list_chats_returns_list(self):
        """FAIL: SelectorStrategy.list_chats must return a list."""
        try:
            mod = importlib.import_module("adapters.custom_web")
        except ImportError:
            pytest.fail("adapters.custom_web not importable")
        cls = getattr(mod, "SelectorStrategy", None)
        assert cls is not None
        from unittest.mock import MagicMock
        page = MagicMock()
        page.evaluate.return_value = []
        strategy = cls(page=page, config={
            "chat_list_selector": "nav a",
            "message_selector": ".msg",
            "user_message_selector": ".user",
            "assistant_message_selector": ".assistant",
        })
        result = strategy.list_chats()
        assert isinstance(result, list), (
            f"list_chats must return list, got {type(result).__name__}"
        )


class TestScriptStrategyBehavior:
    """ScriptStrategy must implement the strategy interface."""

    def test_has_list_chats_method(self):
        """FAIL: ScriptStrategy must have list_chats method."""
        try:
            mod = importlib.import_module("adapters.custom_web")
        except ImportError:
            pytest.fail("adapters.custom_web not importable")
        cls = getattr(mod, "ScriptStrategy", None)
        assert cls is not None
        assert callable(getattr(cls, "list_chats", None)), (
            "ScriptStrategy must have list_chats method"
        )

    def test_has_open_chat_method(self):
        """FAIL: ScriptStrategy must have open_chat method."""
        try:
            mod = importlib.import_module("adapters.custom_web")
        except ImportError:
            pytest.fail("adapters.custom_web not importable")
        cls = getattr(mod, "ScriptStrategy", None)
        assert cls is not None
        assert callable(getattr(cls, "open_chat", None)), (
            "ScriptStrategy must have open_chat method"
        )

    def test_has_extract_chat_method(self):
        """FAIL: ScriptStrategy must have extract_chat method."""
        try:
            mod = importlib.import_module("adapters.custom_web")
        except ImportError:
            pytest.fail("adapters.custom_web not importable")
        cls = getattr(mod, "ScriptStrategy", None)
        assert cls is not None
        assert callable(getattr(cls, "extract_chat", None)), (
            "ScriptStrategy must have extract_chat method"
        )
