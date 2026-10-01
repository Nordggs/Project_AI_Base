"""Tests: ProfilerWorker (TICKET-003 Phase B). No browser.

Page/Playwright/session are faked; engine sub-probes are monkeypatched.
Checks: phases start->completed, n_chats clamp, resume skips completed,
cancel between candidates, awaiting_login -> continue, foreign browser
never closed, rollup in results, double-start guard.
"""

import json
import os
import threading
import time
from unittest.mock import MagicMock

import pytest

from core.profiler import checkpoint as checkpoint_mod
from core.profiler import orchestrator as orch_mod
from core.profiler import run as run_mod
from core.profiler import validation as validation_mod
from core.profiler import worker as worker_mod
from core.profiler.worker import ProfilerWorker, assemble_observations

URL = "https://example-ai.com/"


class _FakePW:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _chat(n=5):
    return {
        "hits": {"nav a": n},
        "best_sel": "nav a",
        "items": [{"index": i, "href": f"https://example-ai.com/c/{i}",
                   "text": f"chat {i}"} for i in range(n)],
        "empty_title": {},
    }


def _report(cid, verdicts_list):
    per_chat = [{"chat_url": f"tok-{i}", "target": {"href": "", "index": i},
                 "verdict": v, "reason": "ok",
                 "evidence": {"chats": 1, "messages": 2}}
                for i, v in enumerate(verdicts_list)]
    summary = {"total": len(verdicts_list), "Compatible": 0, "Partial": 0,
               "Incompatible": 0, "Blocked": 0}
    for v in verdicts_list:
        summary[v] += 1
    return {"candidate_id": cid, "per_chat": per_chat, "summary": summary}


def _session(monkeypatch, owned=True):
    browser, page = MagicMock(), MagicMock()
    page.url = URL
    monkeypatch.setattr(run_mod, "_open_session",
                        lambda pw, cdp="": (browser, page, owned))
    return browser, page


def _probes_ok(monkeypatch, chat=None, opened=True):
    chat = chat if chat is not None else _chat()
    monkeypatch.setattr(orch_mod, "probe_chat_list", lambda page, log=None: chat)
    nav = {"type": "goto", "goto_empty": False, "spa": False,
           "hydration_required": False, "wait_after_navigation_ms": 2000}
    monkeypatch.setattr(orch_mod, "open_research_context",
                        lambda page, url, c, log=None: (nav, opened))
    monkeypatch.setattr(orch_mod, "probe_messages", lambda page: {".m": 4})
    monkeypatch.setattr(orch_mod, "probe_roles",
                        lambda page, log=None: {"message": ".m", "user": ".u",
                                                "assistant": ".a", "user_n": 2,
                                                "assistant_n": 2, "found": True})
    monkeypatch.setattr(orch_mod, "probe_title",
                        lambda page, sel, log=None: {"source": "text", "selector": ""})
    monkeypatch.setattr(orch_mod, "probe_scroll",
                        lambda page, sel, log=None: {"required": False, "container": "",
                                                    "infinite": False, "status": "ok"})
    return chat


def _mkworker(tmp_path, **kw):
    kw.setdefault("playwright_factory", lambda: _FakePW())
    kw.setdefault("catalog", [])
    kw.setdefault("login_timeout", 30)
    return ProfilerWorker(str(tmp_path), **kw)


def _wait_status(worker, *phases, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        phase = worker.get_status()["phase"]
        if phase in phases:
            return phase
        time.sleep(0.05)
    raise AssertionError(f"status never reached {phases}: {worker.get_status()}")


class TestAssembleObservations:
    def test_same_keys_as_run_probes(self):
        obs = assemble_observations(URL, _chat(), {"type": "goto"}, True,
                                    {".m": 1}, {"found": True},
                                    {"source": "text"}, {"required": False})
        assert sorted(obs) == sorted([
            "provider_url", "navigation", "chat_open", "chat_list_hits",
            "chat_list_selector", "chat_items", "empty_title_links",
            "message_hits", "roles", "title", "scroll", "blocked"])
        assert obs["chat_list_selector"] == "nav a"
        assert len(obs["chat_items"]) == 5
        assert obs["blocked"] == {}

    def test_product_filter_path_preserved(self):
        chat = _chat()
        chat["empty_title"] = {"nav a": {"total": 4, "empty": 4}}
        obs = assemble_observations(URL, chat, {}, False, {}, {}, {}, {})
        assert obs["blocked"] == {"reason": "product-filter",
                                  "evidence": {"nav a": {"total": 4, "empty": 4}}}


class TestWorkerRun:
    def test_happy_path_completed_with_rollup(self, tmp_path, monkeypatch):
        browser, page = _session(monkeypatch, owned=True)
        _probes_ok(monkeypatch)

        def _validate(page, cand, pending, catalog, **kw):
            cid = (cand.get("preset_id")
                   or (cand.get("preset") or {}).get("id", "?"))
            return _report(cid, ["Compatible"] * len(pending))

        monkeypatch.setattr(validation_mod, "validate_candidate", _validate)
        worker = _mkworker(tmp_path)
        worker.start(URL, n_chats=5)
        worker._join()
        status = worker.get_status()
        assert status["phase"] == "completed", status
        results = worker.get_results()
        assert results["url"] == URL
        assert results["n_chats"] == 5
        assert results["matrix"]["candidates"]
        assert results["validations"]
        first = results["validations"][0]
        assert first["rollup"] == "Compatible"
        assert first["summary"]["total"] == 5
        # checkpoint got per-chat records
        ckpt = checkpoint_mod.checkpoint_path(str(tmp_path))
        assert os.path.exists(ckpt)
        done, _ignored = checkpoint_mod.load_completed(ckpt)
        assert len(done) == 5 * len(results["validations"])
        # owned browser closed, page closed
        page.close.assert_called_once_with()
        browser.close.assert_called_once_with()

    def test_n_chats_clamped_to_minimum(self, tmp_path, monkeypatch):
        _session(monkeypatch)
        _probes_ok(monkeypatch)
        monkeypatch.setattr(validation_mod, "validate_candidate",
                            lambda *a, **k: _report("c", ["Compatible"]))
        worker = _mkworker(tmp_path)
        worker.start(URL, n_chats=1)
        worker._join()
        assert worker.get_results()["n_chats"] == 3

    def test_foreign_browser_never_closed(self, tmp_path, monkeypatch):
        browser, page = _session(monkeypatch, owned=False)
        _probes_ok(monkeypatch, chat={"hits": {}, "best_sel": "",
                                      "items": [], "empty_title": {}})
        # empty account + instant continue -> no-chats path
        worker = _mkworker(tmp_path)
        worker.start(URL)
        assert _wait_status(worker, "awaiting_login") == "awaiting_login"
        worker.continue_after_login()
        worker._join()
        assert worker.get_status()["phase"] == "completed"
        page.close.assert_called_once_with()
        browser.close.assert_not_called()

    def test_login_reprobe_after_continue(self, tmp_path, monkeypatch):
        _session(monkeypatch)
        calls = {"n": 0}

        def _probe(page, log=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"hits": {}, "best_sel": "", "items": [],
                        "empty_title": {}}
            return _chat()

        monkeypatch.setattr(orch_mod, "probe_chat_list", _probe)
        nav = {"type": "goto", "goto_empty": False}
        monkeypatch.setattr(orch_mod, "open_research_context",
                            lambda page, url, c, log=None: (nav, True))
        monkeypatch.setattr(orch_mod, "probe_messages", lambda page: {".m": 2})
        monkeypatch.setattr(orch_mod, "probe_roles",
                            lambda page, log=None: {"message": ".m", "user": ".u",
                                                    "assistant": ".a", "user_n": 1,
                                                    "assistant_n": 1, "found": True})
        monkeypatch.setattr(orch_mod, "probe_title",
                            lambda page, sel, log=None: {"source": "text", "selector": ""})
        monkeypatch.setattr(orch_mod, "probe_scroll",
                            lambda page, sel, log=None: {"required": False, "container": "",
                                                        "infinite": False, "status": "ok"})
        monkeypatch.setattr(validation_mod, "validate_candidate",
                            lambda *a, **k: _report("c", ["Compatible"]))
        worker = _mkworker(tmp_path)
        worker.start(URL)
        assert _wait_status(worker, "awaiting_login") == "awaiting_login"
        worker.continue_after_login()
        worker._join()
        assert calls["n"] == 2
        assert worker.get_status()["phase"] == "completed"

    def test_cancel_between_candidates(self, tmp_path, monkeypatch):
        _session(monkeypatch)
        _probes_ok(monkeypatch)
        cands = [{"kind": "selector-new", "preset": {"id": "cand-1"}},
                 {"kind": "selector-new", "preset": {"id": "cand-2"}}]
        import core.profiler.matrix as matrix_mod
        monkeypatch.setattr(matrix_mod, "build_preset_matrix",
                            lambda *a, **k: {"candidates": cands,
                                             "chat_list_kind": "links"})
        worker = _mkworker(tmp_path)

        def _validate(page, cand, pending, catalog, **kw):
            worker.cancel()
            cid = (cand.get("preset") or {}).get("id", "?")
            return _report(cid, ["Compatible"])

        monkeypatch.setattr(validation_mod, "validate_candidate", _validate)
        worker.start(URL)
        worker._join()
        assert worker.get_status()["phase"] == "cancelled"
        assert [v["candidate_id"] for v in worker.get_results()["validations"]] == ["cand-1"]

    def test_resume_skips_completed(self, tmp_path, monkeypatch):
        _session(monkeypatch)
        chat = _probes_ok(monkeypatch)
        ckpt = checkpoint_mod.checkpoint_path(str(tmp_path))
        for target in chat["items"][:5]:
            checkpoint_mod.append_record(ckpt, {
                "provider_url": URL, "candidate_id": "cand-1",
                "target_token": target["href"],
                "chat_url": target["href"], "index": target["index"],
                "selector": "nav a", "verdict": "Compatible", "reason": "ok"})
        cands = [{"kind": "selector-new",
                  "preset": {"id": "cand-1", "strategy": {"type": "selector"}}}]
        import core.profiler.matrix as matrix_mod
        monkeypatch.setattr(matrix_mod, "build_preset_matrix",
                            lambda *a, **k: {"candidates": cands,
                                             "chat_list_kind": "links"})
        called = {"n": 0}

        def _validate(*a, **k):
            called["n"] += 1
            raise AssertionError("must be skipped")

        monkeypatch.setattr(validation_mod, "validate_candidate", _validate)
        worker = _mkworker(tmp_path)
        assert worker.has_resume(URL) is True
        assert worker.has_resume("https://other.ai/") is False
        worker.start(URL, resume=True)
        worker._join()
        assert worker.get_status()["phase"] == "completed"
        assert called["n"] == 0
        skipped = worker.get_results()["validations"][0]
        assert skipped["skipped"] == "completed"
        assert skipped["rollup"] == "Incompatible"

    def test_double_start_raises(self, tmp_path, monkeypatch):
        _session(monkeypatch)
        _probes_ok(monkeypatch)
        entered = threading.Event()
        release = threading.Event()

        def _validate(*a, **k):
            entered.set()
            release.wait(timeout=15)
            return _report("c", ["Compatible"])

        monkeypatch.setattr(validation_mod, "validate_candidate", _validate)
        worker = _mkworker(tmp_path)
        worker.start(URL)
        assert entered.wait(timeout=15)
        with pytest.raises(RuntimeError):
            worker.start(URL)
        release.set()
        worker._join()

    def test_open_failure_is_failed_not_crash(self, tmp_path, monkeypatch):
        _session(monkeypatch)
        worker = _mkworker(tmp_path, login_timeout=1)
        worker.start(URL)
        worker._join()
        # real probes on a MagicMock page must not hang the thread;
        # any outcome besides a stuck thread is acceptable here
        assert worker.get_status()["phase"] in ("completed", "failed")

    def test_legacy_checkpoint_refuses_resume(self, tmp_path, monkeypatch):
        _session(monkeypatch)
        ckpt = checkpoint_mod.checkpoint_path(str(tmp_path))
        with open(ckpt, "w", encoding="utf-8") as f:
            f.write('{"provider_url": "%s", "candidate_id": "c"}\n' % URL)
        assert checkpoint_mod.has_legacy_records(ckpt) is True
        worker = _mkworker(tmp_path)
        worker.start(URL, resume=True)
        worker._join()
        status = worker.get_status()
        assert status["phase"] == "failed"
        assert "v1" in status["error"]

    def test_legacy_checkpoint_refuses_fresh_start(self, tmp_path, monkeypatch):
        _session(monkeypatch)
        ckpt = checkpoint_mod.checkpoint_path(str(tmp_path))
        with open(ckpt, "w", encoding="utf-8") as f:
            f.write("not json at all\n")
        worker = _mkworker(tmp_path)
        worker.start(URL)
        worker._join()
        status = worker.get_status()
        assert status["phase"] == "failed"
        assert "v1" in status["error"]
