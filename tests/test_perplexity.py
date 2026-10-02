"""Tests: Perplexity provider (TICKET-004, Iteration 2).

Covers ticket stage 12 minimum: provider registration, adapter init,
message extraction, role detection, ordering, duplicate prevention,
long-chat handling (split .prose merge), export, configuration/UI integration,
regression of existing providers.
"""

import threading

import pytest

from adapters.perplexity import PerplexityAdapter
from conversation.irbuilder import IRBuilder, Provider
from exporters.perplexity_extract import (
    extract_perplexity_dom,
    is_home_screen,
    merge_same_role,
    parse_sidebar_items,
)
from exporters.writer import ExportWriter

UUID1 = "52c2317c-b992-4a4d-aae4-1e1374cca2e2"
UUID2 = "c32e6994-cd69-4442-b01d-20ff18475efe"


class FakePage:
    """Minimal scriptable page stub (evaluate by JS marker)."""

    def __init__(self, script=None, url="https://www.perplexity.ai/"):
        self._script = script or {}
        self.url = url
        self.goto_calls = []
        self.waited = []

    def evaluate(self, js, *args):
        for marker, resp in self._script.items():
            if marker in js:
                return resp() if callable(resp) else resp
        raise AssertionError(f"unexpected evaluate: {js[:80]}")

    def goto(self, url, **kwargs):
        self.goto_calls.append(url)
        self.url = url

    def wait_for_timeout(self, ms):
        self.waited.append(ms)

    def wait_for_function(self, js, **kwargs):
        if self._script.get("__wait_turns__", True):
            return True
        raise TimeoutError("no turns")


def _adapter(page=None, **kw):
    pg = page or FakePage()
    return PerplexityAdapter(
        pg, threading.Lock(), kw.get("log", lambda m: None), kw.get("cancel", lambda: False),
    )


class TestProviderRegistration:
    def test_enum_member(self):
        assert Provider.PERPLEXITY.value == "perplexity"

    def test_build_routes_to_generic(self):
        raw = {"messages": [{"role": "user", "content": "hi"}],
               "title": "t", "chat_id": UUID1, "source_url": "https://www.perplexity.ai/search/" + UUID1}
        model = IRBuilder.build(Provider.PERPLEXITY, raw)
        assert model.source == "perplexity"
        assert model.stable_id == UUID1
        assert [m.role for m in model.messages] == ["user"]
        assert model.metadata == {"provider": "perplexity", "source": "dom"}

    def test_all_providers_still_route(self):
        """Regression: existing providers unaffected by the new member."""
        for prov, raw in [
            (Provider.GEMINI, {"messages": [], "title": "g", "chat_id": "x", "source_url": ""}),
            (Provider.CLAUDE, {"messages": [], "title": "c", "chat_id": "x", "source_url": ""}),
            (Provider.QWEN, {"messages": [], "title": "q", "chat_id": "x", "source_url": ""}),
            (Provider.DEEPSEEK, {"messages": [], "title": "d", "chat_id": "x", "source_url": ""}),
        ]:
            model = IRBuilder.build(prov, raw)
            assert model.source == prov.value


class TestParseSidebarItems:
    def test_uuid_accepted(self):
        raw = [{"id": UUID1, "title": "t", "url": "/search/" + UUID1, "_index": 0}]
        out = parse_sidebar_items(raw)
        assert len(out) == 1 and out[0]["id"] == UUID1

    def test_index_id_rejected(self):
        """perplexity-0 style ids must never become Stable IDs."""
        raw = [{"id": "perplexity-0", "title": "t", "url": "/search/x", "_index": 0}]
        assert parse_sidebar_items(raw) == []

    def test_missing_and_bad_ids_rejected(self):
        raw = [{"id": "", "title": "t", "url": "", "_index": 0},
               {"id": "short", "title": "t", "url": "", "_index": 1},
               {"title": "no-id", "url": "", "_index": 2},
               "not-a-dict"]
        assert parse_sidebar_items(raw) == []

    def test_dedup_by_id(self):
        raw = [{"id": UUID1, "title": "a", "url": "/search/" + UUID1, "_index": 0},
               {"id": UUID1, "title": "b", "url": "/search/" + UUID1, "_index": 1},
               {"id": UUID2, "title": "c", "url": "/search/" + UUID2, "_index": 2}]
        out = parse_sidebar_items(raw)
        assert [o["id"] for o in out] == [UUID1, UUID2]


class TestMergeSameRole:
    def test_consecutive_assistant_merged(self):
        msgs = [{"role": "user", "content": "q", "timestamp": "05:48"},
                {"role": "assistant", "content": "a1"},
                {"role": "assistant", "content": "a2"}]
        out = merge_same_role(msgs)
        assert [(m["role"]) for m in out] == ["user", "assistant"]
        assert out[1]["content"] == "a1\n\na2"

    def test_alternating_kept(self):
        msgs = [{"role": "user", "content": "q1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "q2"},
                {"role": "assistant", "content": "a2"}]
        assert len(merge_same_role(msgs)) == 4

    def test_first_timestamp_kept(self):
        msgs = [{"role": "assistant", "content": "a1", "timestamp": "t1"},
                {"role": "assistant", "content": "a2", "timestamp": "t2"}]
        out = merge_same_role(msgs)
        assert out[0]["timestamp"] == "t1"

    def test_empty_content_dropped(self):
        msgs = [{"role": "user", "content": "  "},
                {"role": "assistant", "content": "a"}]
        out = merge_same_role(msgs)
        assert [m["role"] for m in out] == ["assistant"]


class TestExtractDom:
    def _page(self, payload):
        return FakePage(script={"compareDocumentPosition": payload})

    def test_js_emits_timestamp_key(self):
        """B1 guard: JS must emit `timestamp` (what merge_same_role reads)."""
        from exporters import perplexity_extract as px
        assert "timestamp: time" in px.PERPLEXITY_EXTRACT_JS
        assert "{role, content, time}" not in px.PERPLEXITY_EXTRACT_JS

    def test_messages_and_citations(self):
        payload = {
            "messages": [
                {"role": "user", "content": "05:48\n\nquery", "timestamp": "05:48"},
                {"role": "assistant", "content": "answer", "timestamp": None},
            ],
            "citations": ["aliexpress +1"],
            "title": "Thread title",
        }
        page = self._page(payload)
        data = extract_perplexity_dom(page, "https://www.perplexity.ai/search/" + UUID1)
        assert data["chat_id"] == UUID1
        assert data["title"] == "Thread title"
        assert data["source_url"].endswith(UUID1)
        assert [m["role"] for m in data["messages"]] == ["user", "assistant"]
        assert data["messages"][0]["timestamp"] == "05:48"
        assert "[sources: aliexpress +1]" in data["messages"][-1]["content"]

    def test_no_messages_returns_none(self):
        page = self._page({"messages": [], "citations": [], "title": ""})
        assert extract_perplexity_dom(page, "https://www.perplexity.ai/") is None

    def test_cancel_returns_none(self):
        page = self._page({"messages": [{"role": "user", "content": "q", "time": None}],
                           "citations": [], "title": "t"})
        assert extract_perplexity_dom(page, "https://x/", cancel_check=lambda: True) is None

    def test_evaluate_error_returns_none(self):
        class Boom(FakePage):
            def evaluate(self, js, *a):
                raise RuntimeError("boom")
        assert extract_perplexity_dom(Boom(), "https://x/") is None


class TestAdapter:
    def test_name_and_healthcheck(self):
        a = _adapter()
        assert a.name == "perplexity"
        assert a.healthcheck() is True

    def test_healthcheck_dead_page(self):
        class Dead:
            @property
            def url(self):
                raise RuntimeError("gone")
        a = PerplexityAdapter(Dead(), threading.Lock(), lambda m: None, lambda: False)
        assert a.healthcheck() is False

    def test_list_chats_parses_and_dedups(self):
        raw = [{"id": UUID1, "title": "t1", "url": "/search/" + UUID1, "_index": 0},
               {"id": "perplexity-0", "title": "idx", "url": "", "_index": 1}]
        page = FakePage(script={"querySelectorAll('a')": raw})
        # snapshot helper also evaluates — serve sidebar-state JS generically
        orig_eval = page.evaluate

        def ev(js, *a):
            if "app_links" in js:
                return {"url": "", "title": "", "app_links": 1, "all_links": 1,
                        "listitem_count": 0, "history_visible": True,
                        "ready_state": "complete", "timeOrigin": 0, "perf_now": 0}
            return orig_eval(js, *a)
        page.evaluate = ev
        logs = []
        a = PerplexityAdapter(page, threading.Lock(), logs.append, lambda: False)
        out = a.list_chats()
        assert [c["id"] for c in out] == [UUID1]
        assert page.goto_calls and page.goto_calls[0].startswith("https://www.perplexity.ai/")

    def test_open_chat_goto_primary(self):
        page = FakePage(url="https://www.perplexity.ai/",
                        script={"__wait_turns__": True})
        a = _adapter(page)
        ok = a.open_chat({"url": "/search/" + UUID1, "title": "t", "_index": 0, "id": UUID1})
        assert ok is True
        assert page.url.endswith(UUID1)

    def test_open_chat_empty_thread_false(self):
        class HomePage(FakePage):
            def evaluate(self, js, *a):
                if "Что вы хотите узнать" in js or "What do you want to know" in js:
                    return True
                if "user-bubble" in js or "div.prose" in js:
                    return False
                return super().evaluate(js, *a)

            def wait_for_function(self, js, **kw):
                raise TimeoutError("no turns")
        a = _adapter(HomePage())
        assert a.open_chat({"url": "/search/" + UUID1, "_index": 0}) is False

    def test_extract_chat_builds_model(self):
        payload = {"messages": [{"role": "user", "content": "q", "time": None},
                                {"role": "assistant", "content": "a", "time": None}],
                   "citations": [], "title": " Doc Title "}
        page = FakePage(url="https://www.perplexity.ai/search/" + UUID1,
                        script={"compareDocumentPosition": payload})
        a = _adapter(page)
        model = a.extract_chat({"id": UUID1, "title": "Sidebar", "url": "/search/" + UUID1})
        assert model is not None
        assert model.source == "perplexity"
        assert model.stable_id == UUID1
        assert model.title == "Doc Title"

    def test_extract_chat_title_fallback(self):
        payload = {"messages": [{"role": "user", "content": "q", "time": None}],
                   "citations": [], "title": "Perplexity"}
        page = FakePage(url="https://www.perplexity.ai/search/" + UUID1,
                        script={"compareDocumentPosition": payload})
        a = _adapter(page)
        model = a.extract_chat({"id": UUID1, "title": "Sidebar Title", "url": ""})
        assert model.title == "Sidebar Title"

    def test_extract_chat_none_when_empty(self):
        page = FakePage(url="https://www.perplexity.ai/",
                        script={"compareDocumentPosition": {"messages": [], "citations": [], "title": ""}})
        assert _adapter(page).extract_chat({}) is None


class TestWriterIntegration:
    def test_display_name(self):
        assert ExportWriter._DISPLAY_PROVIDER["perplexity"] == "Perplexity"

    def test_index_id_rejected_for_perplexity(self, tmp_path):
        w = ExportWriter(out_dir=str(tmp_path))
        data = {"chat_id": "perplexity-0", "title": "T", "source": "perplexity",
                "source_url": "https://www.perplexity.ai/search/" + UUID1,
                "messages": [{"role": "user", "content": "q"}]}
        assert w._stable_id(data) == UUID1  # falls through to URL segment

    def test_uuid_chat_id_kept(self, tmp_path):
        w = ExportWriter(out_dir=str(tmp_path))
        data = {"chat_id": UUID1, "title": "T", "source": "perplexity",
                "source_url": "", "messages": [{"role": "user", "content": "q"}]}
        assert w._stable_id(data) == UUID1

    def test_write_roundtrip(self, tmp_path):
        raw = {"messages": [{"role": "user", "content": "q"},
                            {"role": "assistant", "content": "a"}],
               "title": "t", "chat_id": UUID1,
               "source_url": "https://www.perplexity.ai/search/" + UUID1}
        model = IRBuilder.build(Provider.PERPLEXITY, raw)
        w = ExportWriter(out_dir=str(tmp_path))
        path = w.write(model.to_dict(), chat_order=0)
        assert path.exists() and "perplexity" in path.name


class TestMainIntegration:
    def test_page_for(self, mock_app):
        from main import App
        mock_app.perplexity_page = "PX"
        assert App._page_for(mock_app, "perplexity") == "PX"

    def test_adapter_for(self, mock_app):
        from main import App
        from adapters.perplexity import PerplexityAdapter as PA
        assert isinstance(App._adapter_for(mock_app, "perplexity", "PX"), PA)

    def test_is_provider_connected(self, mock_app):
        from main import App
        mock_app._perplexity_connected = True
        assert App._is_provider_connected(mock_app, "perplexity") is True
        mock_app._perplexity_connected = False
        assert App._is_provider_connected(mock_app, "perplexity") is False

    def test_get_providers_status_has_perplexity(self, mock_app):
        from main import API
        api = API(mock_app)
        status = api.get_providers_status()
        assert "perplexity" in status

    def test_bridge_methods_exist(self, mock_app):
        from main import API, App
        assert callable(API.connect_perplexity) and callable(API.sync_perplexity)
        for m in ("_do_connect_perplexity", "ensure_perplexity_alive",
                  "add_perplexity_account", "sync_perplexity", "reconnect_perplexity"):
            assert callable(getattr(App, m)), m
