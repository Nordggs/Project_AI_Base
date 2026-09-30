"""Tests: preset catalog seed supply (TICKET-002-I).

Seed carries only PoC-verified presets (002-C matrix). Fixture catalog
(tests/fixtures) is untouched — these tests use presets/seed_presets.json.
"""

import json
import os
import shutil

import main as main_mod
from core.preset_engine import filter_valid_presets, validate_preset

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = os.path.join(REPO_ROOT, "presets", "seed_presets.json")


def _load_seed():
    with open(SEED, encoding="utf-8") as f:
        return json.load(f)


def _api_with_storage(tmp_path):
    api = object.__new__(main_mod.API)
    app = object.__new__(main_mod.App)
    app._storage_dir = str(tmp_path)
    app._preset_binding = {}
    app._preset_catalog = []
    api._app = app
    return api


class TestSeedContent:
    def test_seed_exists_and_has_two_verified_entries(self):
        data = _load_seed()
        assert [p["id"] for p in data] == ["grok", "userscript-generic"]

    def test_seed_all_valid(self):
        data = _load_seed()
        for preset in data:
            ok, errors = validate_preset(preset)
            assert ok is True, errors
        assert len(filter_valid_presets(data)) == len(data)

    def test_seed_checked_at_is_poc_run(self):
        for preset in _load_seed():
            assert preset["checked_at"] == "2026-09-25"
            assert preset["version"] == 1


class TestSeedSupply:
    def test_missing_catalog_seeded_from_repo(self, tmp_path):
        api = _api_with_storage(tmp_path)
        presets = api.list_presets()
        assert [p["id"] for p in presets] == ["grok", "userscript-generic"]
        dst = os.path.join(str(tmp_path), "custom_presets.json")
        assert os.path.isfile(dst)
        with open(dst, "rb") as f:
            copied = f.read()
        with open(SEED, "rb") as f:
            assert copied == f.read()

    def test_existing_user_file_untouched(self, tmp_path):
        mine = [{"id": "mine", "strategy": {"type": "selector", "selectors": {
            "chat_list_selector": "nav a", "message_selector": ".m"},
            "scripts": {}}}]
        dst = os.path.join(str(tmp_path), "custom_presets.json")
        with open(dst, "w", encoding="utf-8") as f:
            json.dump(mine, f)
        before = open(dst, "rb").read()
        api = _api_with_storage(tmp_path)
        assert [p["id"] for p in api.list_presets()] == ["mine"]
        assert open(dst, "rb").read() == before

    def test_broken_seed_record_dropped(self, tmp_path):
        data = _load_seed() + [{"id": "", "strategy": {}}]
        with open(os.path.join(str(tmp_path), "custom_presets.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)
        api = _api_with_storage(tmp_path)
        assert [p["id"] for p in api.list_presets()] == ["grok", "userscript-generic"]

    def test_seed_navigation(self):
        from core.preset_engine import resolve_navigation

        data = _load_seed()
        # grok SPA needs click-opening (live run: goto leaves chat empty).
        assert resolve_navigation(data, "grok") == "click"
        assert resolve_navigation(data, "userscript-generic") == "goto"


class TestSeedRecheck:
    """Re-check seed entries to Compatible on 002-C matrix counts (gap 7)."""

    def _check_seed(self, mock_app, preset_id, chats, counts):
        from unittest.mock import MagicMock, patch

        data = _load_seed()
        page = MagicMock()
        page.url = next(p["default_url"] for p in data if p["id"] == preset_id) + "c/1"
        page.evaluate.return_value = counts
        mock_app.custom1_page = page
        mock_app._preset_catalog = data
        mock_app._preset_binding = {1: preset_id}
        with patch("adapters.custom_web.CustomWebAdapter") as adapter_cls:
            adapter_cls.return_value.list_chats.return_value = chats
            return mock_app._do_check_custom(1, preset_id)

    def test_grok_seed_recheck_compatible(self, mock_app):
        chats = [{"id": f"custom-{i}"} for i in range(5)]
        res = self._check_seed(
            mock_app, "grok", chats,
            {"chats": 5, "messages": 4, "user": 2, "assistant": 2})
        assert res["verdict"] == "Compatible"
        assert res["reason"] == "ok"

    def test_userscript_seed_recheck_compatible(self, mock_app):
        chats = [{"id": f"custom-{i}"} for i in range(5)]
        res = self._check_seed(
            mock_app, "userscript-generic", chats,
            {"chats": 5, "messages": 2, "user": 1, "assistant": 1})
        assert res["verdict"] == "Compatible"

    def test_partial_example_not_compatible(self, mock_app):
        from main import _diagnose_verdict

        verdict, _reason = _diagnose_verdict(
            5, 1, 0, 1, "https://grok.com/c/1", "https://grok.com/")
        assert verdict != "Compatible"


class TestSeedResolver:
    def test_resolver_finds_dev_seed(self):
        assert main_mod._resolve_seed_path() == SEED

    def test_resolver_finds_frozen_seed(self, tmp_path, monkeypatch):
        bundled = os.path.join(str(tmp_path), "presets")
        os.makedirs(bundled)
        shutil.copy(SEED, os.path.join(bundled, "seed_presets.json"))
        monkeypatch.setattr("sys._MEIPASS", str(tmp_path), raising=False)
        try:
            assert main_mod._resolve_seed_path() == os.path.join(bundled, "seed_presets.json")
        finally:
            monkeypatch.delattr("sys._MEIPASS", raising=False)

    def test_spec_bundles_presets(self):
        spec = os.path.join(REPO_ROOT, "AIChatExporter.spec")
        with open(spec, encoding="utf-8") as f:
            text = f.read()
        assert '("presets", "presets")' in text
