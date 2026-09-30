"""Tests: CustomWebAdapter, SelectorStrategy, ScriptStrategy don't exist.

PROBLEM: Plan defines CustomWebAdapter in adapters/custom_web.py with
SelectorStrategy and ScriptStrategy — none of these exist yet.
"""

import importlib

import pytest


class TestCustomWebAdapterExists:
    """adapters/custom_web.py with CustomWebAdapter must exist."""

    def test_custom_web_module_importable(self):
        """FAIL: adapters.custom_web module doesn't exist."""
        try:
            importlib.import_module("adapters.custom_web")
        except ImportError:
            pytest.fail(
                "Module adapters.custom_web does not exist. "
                "Plan requires it at adapters/custom_web.py"
            )

    def test_custom_web_adapter_class_exists(self):
        """FAIL: CustomWebAdapter class doesn't exist."""
        try:
            mod = importlib.import_module("adapters.custom_web")
        except ImportError:
            pytest.fail("Cannot test: adapters.custom_web not importable")
        assert hasattr(mod, "CustomWebAdapter"), (
            "adapters.custom_web has no CustomWebAdapter class"
        )

    def test_selector_strategy_class_exists(self):
        """FAIL: SelectorStrategy class doesn't exist."""
        try:
            mod = importlib.import_module("adapters.custom_web")
        except ImportError:
            pytest.fail("Cannot test: adapters.custom_web not importable")
        assert hasattr(mod, "SelectorStrategy"), (
            "adapters.custom_web has no SelectorStrategy class"
        )

    def test_script_strategy_class_exists(self):
        """FAIL: ScriptStrategy class doesn't exist."""
        try:
            mod = importlib.import_module("adapters.custom_web")
        except ImportError:
            pytest.fail("Cannot test: adapters.custom_web not importable")
        assert hasattr(mod, "ScriptStrategy"), (
            "adapters.custom_web has no ScriptStrategy class"
        )
