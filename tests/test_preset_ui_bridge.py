"""Tests: preset UI bridge (TICKET-002-E).

Covers API.list_presets (valid file -> list; missing/broken -> []) and
the bind_preset bridge expose. Uses a fixture catalog with 1 valid + 1
broken preset (battle catalog content is 002-I scope). Manual mode without
a catalog and API mode are covered by existing tests (must stay green).
"""

import json
import os

import pytest

import main as main_mod

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "custom_presets.json")


def _api_with_storage(tmp_path):
    api = object.__new__(main_mod.API)
    app = object.__new__(main_mod.App)
    app._storage_dir = str(tmp_path)
    app._preset_binding = {}
    app._preset_catalog = []
    api._app = app
    return api


class TestListPresets:
    def test_valid_file_returns_only_valid(self, tmp_path):
        with open(FIXTURE, encoding="utf-8") as f:
            data = f.read()
        with open(os.path.join(str(tmp_path), "custom_presets.json"), "w", encoding="utf-8") as f:
            f.write(data)
        api = _api_with_storage(tmp_path)
        presets = api.list_presets()
        assert isinstance(presets, list)
        assert [p["id"] for p in presets] == ["perplexity"]
        assert presets[0]["strategy"]["type"] == "selector"

    def test_missing_file_seeded(self, tmp_path):
        # TICKET-002-I: a missing catalog is seeded from the bundled seed.
        api = _api_with_storage(tmp_path)
        assert [p["id"] for p in api.list_presets()] == ["grok", "userscript-generic"]

    def test_missing_file_and_no_seed_returns_empty(self, tmp_path, monkeypatch):
        import main as main_mod

        monkeypatch.setattr(main_mod, "_resolve_seed_path", lambda: "")
        api = _api_with_storage(tmp_path)
        assert api.list_presets() == []

    def test_broken_json_returns_empty(self, tmp_path):
        with open(os.path.join(str(tmp_path), "custom_presets.json"), "w", encoding="utf-8") as f:
            f.write("{not json")
        api = _api_with_storage(tmp_path)
        assert api.list_presets() == []

    def test_non_list_json_returns_empty(self, tmp_path):
        with open(os.path.join(str(tmp_path), "custom_presets.json"), "w", encoding="utf-8") as f:
            json.dump({"id": "x"}, f)
        api = _api_with_storage(tmp_path)
        assert api.list_presets() == []

    def test_scalar_json_returns_empty(self, tmp_path):
        with open(os.path.join(str(tmp_path), "custom_presets.json"), "w", encoding="utf-8") as f:
            f.write("42")
        api = _api_with_storage(tmp_path)
        assert api.list_presets() == []

    def test_contract_shape(self, tmp_path):
        with open(FIXTURE, encoding="utf-8") as f:
            data = f.read()
        with open(os.path.join(str(tmp_path), "custom_presets.json"), "w", encoding="utf-8") as f:
            f.write(data)
        api = _api_with_storage(tmp_path)
        (preset,) = api.list_presets()
        assert set(("id", "name", "strategy")) <= set(preset.keys())
        assert set(("type", "selectors", "scripts")) <= set(preset["strategy"].keys())


class TestPythonMappingMirror:
    """Python mirror of JS _presetToWebConfig (TICKET-002-J gap 2)."""

    def test_mapping_ten_fields_exact(self):
        import json as _json
        from main import _preset_to_web_config

        with open(FIXTURE, encoding="utf-8") as f:
            preset = _json.load(f)[0]
        cfg = _preset_to_web_config(preset)
        assert cfg == {
            "mode": "web",
            "url": "https://www.perplexity.ai/",
            "chat_list_selector": "nav a[href*='/chat/']",
            "title_selector": ".chat-title",
            "message_selector": ".message-content",
            "user_message_selector": ".user-message",
            "assistant_message_selector": ".assistant-message",
            "scroll_container_selector": "nav",
            "wait_after_click_ms": 2000,
            "list_chats_js": "",
            "extract_messages_js": "",
        }

    def test_mapping_wait_default_and_no_extra_keys(self):
        from main import _preset_to_web_config

        preset = {"id": "x", "default_url": "https://example.com/",
                  "strategy": {"type": "selector", "selectors": {
                      "chat_list_selector": "nav a",
                      "message_selector": ".m"}}}
        cfg = _preset_to_web_config(preset)
        assert cfg["wait_after_click_ms"] == 2000
        assert cfg["mode"] == "web"
        assert set(cfg.keys()) == {
            "mode", "url", "chat_list_selector", "title_selector",
            "message_selector", "user_message_selector",
            "assistant_message_selector", "scroll_container_selector",
            "wait_after_click_ms", "list_chats_js", "extract_messages_js",
        }


class TestBindPresetBridge:
    def test_bind_exposed_and_resolves(self, tmp_path):
        api = _api_with_storage(tmp_path)
        api.bind_preset(1, "perplexity")
        assert api._app._preset_binding == {1: "perplexity"}

    def test_bind_unknown_slot_raises(self, tmp_path):
        api = _api_with_storage(tmp_path)
        with pytest.raises(RuntimeError):
            api.bind_preset(3, "perplexity")
