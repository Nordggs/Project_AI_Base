"""Tests: UI tabs contract — static checks for tab/panel mapping and JS functions."""

import os
import re

import pytest

UI_DIR = os.path.join(os.path.dirname(__file__), "..", "ui")

PROVIDERS = ["deepseek", "gemini", "qwen", "chatgpt", "claude", "custom1", "custom2"]


def _read(name):
    with open(os.path.join(UI_DIR, name), encoding="utf-8") as f:
        return f.read()


class TestTabPanelMapping:
    """Each provider must have exactly one .tab button and one .tab-panel."""

    def test_tab_count(self):
        html = _read("app.html")
        tabs = re.findall(r'class="tab[^"]*"\s+data-provider="(\w+)"', html)
        assert len(tabs) == 7, f"Expected 7 tabs, found {len(tabs)}: {tabs}"
        assert set(tabs) == set(PROVIDERS), f"Tab providers mismatch: {tabs}"

    def test_panel_count(self):
        html = _read("app.html")
        panels = re.findall(r'class="tab-panel[^"]*"\s+data-panel="(\w+)"', html)
        assert len(panels) == 7, f"Expected 7 panels, found {len(panels)}: {panels}"
        assert set(panels) == set(PROVIDERS), f"Panel providers mismatch: {panels}"

    def test_tab_panel_names_match(self):
        html = _read("app.html")
        tabs = set(re.findall(r'data-provider="(\w+)"', html))
        panels = set(re.findall(r'data-panel="(\w+)"', html))
        assert tabs == panels, f"Provider mismatch: only in tabs={tabs-panels}, only in panels={panels-tabs}"

    def test_one_active_tab_default(self):
        html = _read("app.html")
        active_tabs = re.findall(r'class="tab\s+active"\s+data-provider="(\w+)"', html)
        assert len(active_tabs) == 1, f"Expected exactly 1 active tab, found {len(active_tabs)}"

    def test_one_active_panel_default(self):
        html = _read("app.html")
        active_panels = re.findall(r'class="tab-panel\s+active"\s+data-panel="(\w+)"', html)
        assert len(active_panels) == 1, f"Expected exactly 1 active panel, found {len(active_panels)}"


class TestJSFunctions:
    """Required JS functions must exist in app.js."""

    def _load(self):
        return _read("app.js")

    def test_switch_tab_defined(self):
        js = self._load()
        assert re.search(r"function\s+switchTab\s*\(", js), "switchTab() not found"

    def test_set_tab_connection_state_defined(self):
        js = self._load()
        assert re.search(r"function\s+setTabConnectionState\s*\(", js), "setTabConnectionState() not found"

    def test_reset_all_tab_states_defined(self):
        js = self._load()
        assert re.search(r"function\s+resetAllTabStates\s*\(", js), "resetAllTabStates() not found"

    def test_connected_classes_complete(self):
        js = self._load()
        for p in PROVIDERS:
            assert f"connected-{p}" in js, f"Missing 'connected-{p}' in JS"

    def test_set_connected_calls_tab_state(self):
        js = self._load()
        for fn, prov in [
            ("setConnected", "deepseek"),
            ("setGeminiConnected", "gemini"),
            ("setQwenConnected", "qwen"),
            ("setChatGPTConnected", "chatgpt"),
            ("setClaudeConnected", "claude"),
        ]:
            pattern = rf"function\s+{fn}\b.*?setTabConnectionState\('{prov}'"
            assert re.search(pattern, js, re.DOTALL), (
                f"{fn}() must call setTabConnectionState('{prov}', true)"
            )


class TestCSSSpecificity:
    """Active+connected and active+sync-failed must override .tab.active."""

    def _load(self):
        return _read("app.css")

    def test_active_connected_overrides(self):
        css = self._load()
        for p in PROVIDERS:
            sel = f".tab.active.connected-{p}"
            assert sel in css, f"Missing CSS rule: {sel}"

    def test_active_sync_failed_override(self):
        css = self._load()
        assert ".tab.active.sync-failed" in css, "Missing .tab.active.sync-failed rule"
