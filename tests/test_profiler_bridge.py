"""Tests: TICKET-003 bridge (API profiler/catalog methods + Sync All guard).

Uses the mock_app fixture (no __init__ side effects) plus a fake worker.
"""

import json
import threading
from unittest.mock import MagicMock

import pytest

import main as main_mod
from core.profiler import worker as profiler_worker_mod


def _api(app):
    api = object.__new__(main_mod.API)
    api._app = app
    return api


def _fake_worker_cls(running_after_start=True, status_phase="completed"):
    def _make(*args, **kwargs):
        worker = MagicMock()
        worker.is_running.return_value = False
        thread = MagicMock()

        def _start(url, n_chats=5, resume=False):
            worker.is_running.return_value = running_after_start
            return thread

        worker.start.side_effect = _start
        worker.get_status.return_value = {
            "phase": status_phase, "label": status_phase, "detail": "",
            "candidates_done": 0, "candidates_total": 0,
            "chat_current": 0, "chat_total": 0,
            "awaiting_login": False, "error": "",
        }
        return worker

    return _make


class TestStartProfiler:
    def test_started(self, mock_app, monkeypatch):
        monkeypatch.setattr(profiler_worker_mod, "ProfilerWorker",
                            _fake_worker_cls())
        api = _api(mock_app)
        assert api.start_profiler("https://example-ai.com/", 5, False) == "STARTED"
        # watcher may already have flipped running -> done on the instant fake
        assert mock_app._sync_state["profiler"] in ("running", "done")
        assert mock_app._profiler_worker is not None

    def test_bad_url_raises(self, mock_app, monkeypatch):
        monkeypatch.setattr(profiler_worker_mod, "ProfilerWorker",
                            _fake_worker_cls())
        api = _api(mock_app)
        with pytest.raises(RuntimeError):
            api.start_profiler("", 5, False)
        with pytest.raises(RuntimeError):
            api.start_profiler("ftp://example-ai.com/", 5, False)

    def test_busy_when_export_running(self, mock_app, monkeypatch):
        monkeypatch.setattr(profiler_worker_mod, "ProfilerWorker",
                            _fake_worker_cls())
        mock_app._profile_sync_lock = threading.Lock()
        mock_app._sync_state["gemini"] = "running"
        api = _api(mock_app)
        with pytest.raises(RuntimeError) as exc:
            api.start_profiler("https://example-ai.com/", 5, False)
        assert "BUSY" in str(exc.value)

    def test_busy_when_sync_all_reserved(self, mock_app, monkeypatch):
        monkeypatch.setattr(profiler_worker_mod, "ProfilerWorker",
                            _fake_worker_cls())
        mock_app._profile_sync_lock = threading.Lock()
        mock_app._sync_all_reserved = True
        api = _api(mock_app)
        with pytest.raises(RuntimeError) as exc:
            api.start_profiler("https://example-ai.com/", 5, False)
        assert "BUSY" in str(exc.value)

    def test_second_start_is_busy(self, mock_app, monkeypatch):
        monkeypatch.setattr(profiler_worker_mod, "ProfilerWorker",
                            _fake_worker_cls())
        mock_app._profile_sync_lock = threading.Lock()
        api = _api(mock_app)
        assert api.start_profiler("https://example-ai.com/", 5, False) == "STARTED"
        with pytest.raises(RuntimeError) as exc:
            api.start_profiler("https://example-ai.com/", 5, False)
        assert "BUSY" in str(exc.value)

    def test_flag_set_before_lock_release(self, mock_app, monkeypatch):
        """Audit fix: _sync_state['profiler'] is running before start returns."""
        release = threading.Event()

        def _make(*args, **kwargs):
            worker = MagicMock()
            worker.is_running.return_value = True
            thread = MagicMock()
            thread.join.side_effect = lambda: release.wait(timeout=15)
            worker.start.return_value = thread
            return worker

        monkeypatch.setattr(profiler_worker_mod, "ProfilerWorker", _make)
        mock_app._profile_sync_lock = threading.Lock()
        try:
            assert _api(mock_app).start_profiler(
                "https://example-ai.com/", 5, False) == "STARTED"
            assert mock_app._sync_state["profiler"] == "running"
        finally:
            release.set()

    def test_save_invalid_json_raises_runtime(self, mock_app, tmp_path):
        mock_app._storage_dir = str(tmp_path)
        with pytest.raises(RuntimeError):
            _api(mock_app).save_preset("{broken json")


class TestProfilerPolling:
    def test_status_idle_without_worker(self, mock_app):
        assert _api(mock_app).get_profiler_status()["phase"] == "idle"

    def test_results_not_ready_without_worker(self, mock_app):
        assert _api(mock_app).get_profiler_results() == {"ready": False}

    def test_status_and_results_shapes(self, mock_app, monkeypatch):
        monkeypatch.setattr(profiler_worker_mod, "ProfilerWorker",
                            _fake_worker_cls())
        api = _api(mock_app)
        api.start_profiler("https://example-ai.com/", 5, False)
        status = api.get_profiler_status()
        assert status["phase"] == "completed"
        worker = mock_app._profiler_worker
        worker.get_results.return_value = {"url": "https://example-ai.com/",
                                           "validations": []}
        results = api.get_profiler_results()
        assert results["ready"] is True
        assert results["validations"] == []

    def test_continue_requires_running(self, mock_app):
        with pytest.raises(RuntimeError):
            _api(mock_app).continue_after_login()

    def test_cancel_is_idempotent(self, mock_app):
        assert _api(mock_app).cancel_profiler() == "OK"

    def test_has_resume_false_on_empty_storage(self, mock_app, tmp_path):
        mock_app._storage_dir = str(tmp_path)
        assert _api(mock_app).has_resume("https://example-ai.com/") is False


class TestSyncAllGuard:
    def test_legacy_fixture_without_lock_runs_old_path(self, mock_app, monkeypatch):
        called = {"n": 0}
        monkeypatch.setattr(main_mod.App, "_do_sync_all_run",
                            lambda self: called.__setitem__("n", 1))
        assert not hasattr(mock_app, "_profile_sync_lock")
        mock_app._do_sync_all()
        assert called["n"] == 1

    def test_refuses_while_profiler_running(self, mock_app, monkeypatch):
        called = {"n": 0}
        monkeypatch.setattr(main_mod.App, "_do_sync_all_run",
                            lambda self: called.__setitem__("n", 1))
        mock_app._profile_sync_lock = threading.Lock()
        mock_app._sync_all_reserved = False
        mock_app._sync_state["profiler"] = "running"
        mock_app._do_sync_all()
        assert called["n"] == 0

    def test_refuses_live_worker_even_without_flag(self, mock_app, monkeypatch):
        """Audit fix: belt & braces — live worker blocks Sync All w/o flag."""
        called = {"n": 0}
        monkeypatch.setattr(main_mod.App, "_do_sync_all_run",
                            lambda self: called.__setitem__("n", 1))
        mock_app._profile_sync_lock = threading.Lock()
        mock_app._sync_all_reserved = False
        mock_app._sync_state["profiler"] = "idle"
        worker = MagicMock()
        worker.is_running.return_value = True
        mock_app._profiler_worker = worker
        mock_app._do_sync_all()
        assert called["n"] == 0

    def test_reserves_and_releases(self, mock_app, monkeypatch):
        seen = {}
        orig = main_mod.App._do_sync_all_run

        def _spy(self):
            seen["reserved"] = getattr(self, "_sync_all_reserved", None)

        monkeypatch.setattr(main_mod.App, "_do_sync_all_run", _spy)
        mock_app._profile_sync_lock = threading.Lock()
        mock_app._sync_all_reserved = False
        mock_app._do_sync_all()
        assert seen["reserved"] is True
        assert mock_app._sync_all_reserved is False


class TestSaveDeleteBridge:
    def _preset(self):
        return {
            "id": "bridge-ai", "name": "Bridge AI",
            "default_url": "https://example-ai.com/", "version": 1,
            "strategy": {
                "type": "selector", "navigation": "goto",
                "selectors": {"chat_list_selector": "nav a",
                              "message_selector": ".m"},
                "scripts": {"list_chats_js": "", "extract_messages_js": ""},
            },
        }

    def test_save_roundtrip(self, mock_app, tmp_path):
        mock_app._storage_dir = str(tmp_path)
        mock_app._preset_catalog = []
        api = _api(mock_app)
        assert api.save_preset(json.dumps(self._preset())) == "bridge-ai"
        assert [p["id"] for p in api.list_presets()] == [
            "grok", "userscript-generic", "bridge-ai"]

    def test_save_invalid_raises(self, mock_app, tmp_path):
        mock_app._storage_dir = str(tmp_path)
        with pytest.raises(RuntimeError):
            _api(mock_app).save_preset(json.dumps({"id": "", "strategy": {}}))

    def test_delete_roundtrip(self, mock_app, tmp_path):
        mock_app._storage_dir = str(tmp_path)
        mock_app._preset_catalog = []
        api = _api(mock_app)
        api.save_preset(json.dumps(self._preset()))
        assert api.delete_preset("bridge-ai") == "OK"
        assert [p["id"] for p in api.list_presets()] == [
            "grok", "userscript-generic"]

    def test_providers_status_has_profiler_key(self, mock_app):
        status = _api(mock_app).get_providers_status()
        assert status["profiler"] is False
        assert set(status) >= {"gemini", "qwen", "chatgpt", "claude",
                               "deepseek", "profiler"}
