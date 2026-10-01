"""Tests: preset catalog write side (TICKET-003 Phase A).

Covers save/delete/sanitize/upsert for core/preset_catalog.py:
  - save valid preset (fresh file + upsert, neighbours kept);
  - invalid preset refused, nothing written;
  - denylisted keys dropped, secret values -> STOP (nothing written);
  - delete existing/unknown id;
  - broken catalog -> meaningful error, file untouched.
"""

import json
import os

import pytest

from core.preset_catalog import delete_preset, load_catalog, save_preset
from core.preset_engine import CATALOG_FILENAME


def _valid_preset(pid="example-ai"):
    return {
        "id": pid,
        "name": "Example AI",
        "description": "Profiled preset",
        "default_url": "https://example-ai.com/",
        "version": 1,
        "strategy": {
            "type": "selector",
            "navigation": "goto",
            "wait_after_click_ms": 2000,
            "selectors": {
                "chat_list_selector": "nav a",
                "message_selector": ".msg",
                "user_message_selector": ".u",
                "assistant_message_selector": ".a",
            },
            "scripts": {"list_chats_js": "", "extract_messages_js": ""},
        },
    }


def _catalog_path(storage_dir):
    return os.path.join(str(storage_dir), CATALOG_FILENAME)


def _read_raw(storage_dir):
    with open(_catalog_path(storage_dir), encoding="utf-8") as f:
        return json.load(f)


class TestSavePreset:
    def test_save_fresh_file(self, tmp_path):
        ok, errors = save_preset(str(tmp_path), _valid_preset())
        assert ok is True, errors
        assert errors == []
        data = _read_raw(tmp_path)
        assert isinstance(data, list)
        assert [p["id"] for p in data] == ["example-ai"]

    def test_save_refused_when_invalid(self, tmp_path):
        bad = {"id": "", "strategy": {"type": "selector", "selectors": {}}}
        ok, errors = save_preset(str(tmp_path), bad)
        assert ok is False
        assert errors
        assert not os.path.exists(_catalog_path(tmp_path))

    def test_save_refused_when_not_object(self, tmp_path):
        ok, errors = save_preset(str(tmp_path), ["not", "a", "dict"])
        assert ok is False
        assert errors

    def test_upsert_replaces_same_id_keeps_neighbours(self, tmp_path):
        first = _valid_preset("a")
        second = _valid_preset("b")
        assert save_preset(str(tmp_path), first)[0] is True
        assert save_preset(str(tmp_path), second)[0] is True
        updated = _valid_preset("a")
        updated["name"] = "A renamed"
        ok, errors = save_preset(str(tmp_path), updated)
        assert ok is True, errors
        data = _read_raw(tmp_path)
        assert [p["id"] for p in data] == ["a", "b"]
        assert data[0]["name"] == "A renamed"

    def test_upsert_dedupes_duplicate_ids(self, tmp_path):
        dupes = [_valid_preset("a"), _valid_preset("a"), _valid_preset("b")]
        with open(_catalog_path(tmp_path), "w", encoding="utf-8") as f:
            json.dump(dupes, f)
        renamed = _valid_preset("a")
        renamed["name"] = "A renamed"
        ok, errors = save_preset(str(tmp_path), renamed)
        assert ok is True, errors
        data = _read_raw(tmp_path)
        assert [p["id"] for p in data] == ["a", "b"]
        assert data[0]["name"] == "A renamed"

    def test_save_preserves_wrapper_shape(self, tmp_path):
        wrapper = {"version": 1, "presets": [_valid_preset("a")]}
        with open(_catalog_path(tmp_path), "w", encoding="utf-8") as f:
            json.dump(wrapper, f)
        ok, errors = save_preset(str(tmp_path), _valid_preset("b"))
        assert ok is True, errors
        data = _read_raw(tmp_path)
        assert data["version"] == 1
        assert [p["id"] for p in data["presets"]] == ["a", "b"]


class TestSanitize:
    def test_denylisted_keys_dropped(self, tmp_path):
        preset = _valid_preset()
        preset["cookies"] = [{"name": "sid", "value": "abc"}]
        preset["api_key"] = "sk-live-123"
        preset["strategy"]["session"] = "sess-1"
        ok, errors = save_preset(str(tmp_path), preset)
        assert ok is True, errors
        stored = _read_raw(tmp_path)[0]
        assert "cookies" not in stored
        assert "api_key" not in stored
        assert "session" not in stored["strategy"]
        assert stored["strategy"]["selectors"]["chat_list_selector"] == "nav a"

    def test_secret_in_value_stops_save(self, tmp_path):
        preset = _valid_preset()
        preset["description"] = "helper note sessionid=abc123"
        ok, errors = save_preset(str(tmp_path), preset)
        assert ok is False
        assert any("STOP" in e for e in errors)
        assert not os.path.exists(_catalog_path(tmp_path))

    def test_secret_in_selector_value_stops_save(self, tmp_path):
        preset = _valid_preset()
        preset["strategy"]["selectors"]["message_selector"] = ".m[token=xyz]"
        ok, errors = save_preset(str(tmp_path), preset)
        assert ok is False
        assert any("STOP" in e for e in errors)

    def test_stop_does_not_touch_existing_file(self, tmp_path):
        assert save_preset(str(tmp_path), _valid_preset("kept"))[0] is True
        before = _read_raw(tmp_path)
        evil = _valid_preset("evil")
        evil["name"] = "note Bearer abcdef"
        ok, errors = save_preset(str(tmp_path), evil)
        assert ok is False
        assert _read_raw(tmp_path) == before


class TestDeletePreset:
    def test_delete_existing(self, tmp_path):
        assert save_preset(str(tmp_path), _valid_preset("a"))[0] is True
        assert save_preset(str(tmp_path), _valid_preset("b"))[0] is True
        ok, errors = delete_preset(str(tmp_path), "a")
        assert ok is True, errors
        assert [p["id"] for p in _read_raw(tmp_path)] == ["b"]

    def test_delete_unknown_id_is_noop_success(self, tmp_path):
        assert save_preset(str(tmp_path), _valid_preset("a"))[0] is True
        before = _read_raw(tmp_path)
        ok, errors = delete_preset(str(tmp_path), "nope")
        assert ok is True, errors
        assert _read_raw(tmp_path) == before

    def test_delete_bad_id_refused(self, tmp_path):
        ok, errors = delete_preset(str(tmp_path), "  ")
        assert ok is False
        assert errors


class TestBrokenCatalog:
    def test_broken_file_meaningful_error(self, tmp_path):
        with open(_catalog_path(tmp_path), "w", encoding="utf-8") as f:
            f.write("{not json")
        with pytest.raises(RuntimeError):
            load_catalog(str(tmp_path))
        ok, errors = save_preset(str(tmp_path), _valid_preset())
        assert ok is False
        assert any("broken" in e for e in errors)
        with open(_catalog_path(tmp_path), encoding="utf-8") as f:
            assert f.read() == "{not json"

    def test_unexpected_shape_refused(self, tmp_path):
        with open(_catalog_path(tmp_path), "w", encoding="utf-8") as f:
            json.dump({"nope": 1}, f)
        ok, errors = save_preset(str(tmp_path), _valid_preset())
        assert ok is False
        assert any("unexpected shape" in e for e in errors)

    def test_missing_file_loads_empty(self, tmp_path):
        assert load_catalog(str(tmp_path)) == []
