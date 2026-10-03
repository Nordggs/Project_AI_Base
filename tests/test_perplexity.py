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


class FakeMouse:
    """Records move/wheel calls (Phase 0: unpositioned wheel is a no-op)."""

    def __init__(self, fail_move=False, fail_wheel=False):
        self.moved = []
        self.wheels = []
        self._fail_move = fail_move
        self._fail_wheel = fail_wheel

    def move(self, x, y):
        if self._fail_move:
            raise RuntimeError("no mouse")
        self.moved.append((x, y))

    def wheel(self, dx, dy):
        if self._fail_wheel:
            raise RuntimeError("no wheel")
        self.wheels.append((dx, dy))


class FakePage:
    """Minimal scriptable page stub (evaluate by JS marker)."""

    def __init__(self, script=None, url="https://www.perplexity.ai/"):
        self._script = script or {}
        self.url = url
        self.goto_calls = []
        self.waited = []
        self.mouse = FakeMouse()

    def evaluate(self, js, *args):
        if "plast" in js and "FP" in self._script:
            resp = self._script["FP"]
            return resp() if callable(resp) else resp
        if "getBoundingClientRect" in js and "RECT" in self._script:
            resp = self._script["RECT"]
            return resp() if callable(resp) else resp
        for marker, resp in self._script.items():
            if marker in ("FP", "RECT", "__wait_turns__"):
                continue
            if marker in js:
                return resp() if callable(resp) else resp
        # WAIT_TURNS_JS contains 'user-bubble' (also present in FP_JS/EXTRACT_JS)
        if "user-bubble" in js and "__wait_turns__" in self._script:
            return True
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
                        script={"__wait_turns__": True,
                                "RECT": {"cx": 100, "cy": 200},
                                "FP": {"nb": 1, "np": 1, "b0": "q", "blast": "q",
                                       "plast": "a", "top": 0, "sh": 100}})
        a = _adapter(page)
        ok = a.open_chat({"url": "/search/" + UUID1, "title": "t", "_index": 0, "id": UUID1})
        assert ok is True
        assert page.url.endswith(UUID1)
        # climb ran: mouse positioned first (Phase 0 no-op guard), then wheels
        assert page.mouse.moved == [(100, 200)]
        assert page.mouse.wheels == [(0, -2000)] * 2

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


class TestFpKey:
    def test_valid_fp(self):
        from exporters.perplexity_extract import fp_key
        fp = {"nb": 2, "np": 3, "b0": "q1 text", "blast": "q2 text",
              "plast": "a2 text", "top": 100, "sh": 5000}
        assert fp_key(fp) == (2, 3, "q1 text", "a2 text")

    def test_garbage_is_not_stable(self):
        from exporters.perplexity_extract import fp_key
        assert fp_key(None) is None
        assert fp_key("x") is None
        assert fp_key([1, 2]) is None


class TestRelated:
    def test_js_collects_labels_and_filters_computer(self):
        """Phase 0: related = label.relative.cursor-pointer minus engine chips."""
        from exporters import perplexity_extract as px
        assert "label.relative.cursor-pointer" in px.PERPLEXITY_EXTRACT_JS
        assert "Computer" in px.PERPLEXITY_EXTRACT_JS

    def test_js_skips_research_step_cards(self):
        """Transient step cards must not become leading assistant messages."""
        from exporters import perplexity_extract as px
        assert '[class*="step"]' in px.PERPLEXITY_EXTRACT_JS

    def test_related_appended(self):
        # payload mimics post-JS shape (JS already filtered/deduped)
        payload = {"messages": [{"role": "user", "content": "q", "timestamp": None},
                                {"role": "assistant", "content": "a", "timestamp": None}],
                   "citations": ["example +1"], "related": ["Why x?", "How y?"],
                   "title": "t"}
        page = FakePage(script={"compareDocumentPosition": payload})
        data = extract_perplexity_dom(page, "https://www.perplexity.ai/search/" + UUID1)
        body = data["messages"][-1]["content"]
        assert "Related:\n- Why x?\n- How y?" in body
        # paste order: answer -> related -> sources
        assert body.index("Related:") < body.index("[sources: example +1]")

    def test_no_related_no_block(self):
        payload = {"messages": [{"role": "assistant", "content": "a", "timestamp": None}],
                   "citations": [], "related": [], "title": "t"}
        page = FakePage(script={"compareDocumentPosition": payload})
        data = extract_perplexity_dom(page, "https://www.perplexity.ai/search/" + UUID1)
        assert "Related:" not in data["messages"][-1]["content"]


def _fp_seq(*seq):
    it = iter(seq)
    return lambda: next(it)


class TestClimb:
    def _page(self, fps, rect=None):
        return FakePage(script={"FP": _fp_seq(*fps),
                                "RECT": rect if rect is not None else {"cx": 50, "cy": 60}})

    def test_stable_at_top_stops(self):
        fp = {"nb": 1, "np": 1, "b0": "q", "blast": "q", "plast": "a", "top": 0, "sh": 100}
        page = self._page([fp, fp, fp, fp, fp])
        a = _adapter(page)
        a._climb_history(budget_s=25, interval_ms=1, need_stable=3)
        assert page.mouse.moved == [(50, 60)]
        assert page.mouse.wheels == [(0, -2000)] * 2

    def test_growth_resets_stability(self):
        k1 = {"nb": 1, "np": 1, "b0": "q2", "blast": "q2", "plast": "a2", "top": 0, "sh": 100}
        k2 = {"nb": 2, "np": 2, "b0": "q1", "blast": "q2", "plast": "a2b", "top": 0, "sh": 200}
        page = self._page([k1, k1, k2, k2, k2, k2])
        a = _adapter(page)
        a._climb_history(budget_s=25, interval_ms=1, need_stable=3)
        # k1,k1 (stable 2, reset) then k2 x4 -> stop at 3rd k2: 2+3 wheels
        assert len(page.mouse.wheels) == 4

    def test_top_required_despite_stability(self):
        fp = {"nb": 1, "np": 1, "b0": "q", "blast": "q", "plast": "a", "top": 500, "sh": 5000}
        page = self._page([fp] * 10)
        a = _adapter(page)
        a._climb_history(budget_s=0.05, interval_ms=1, need_stable=3)
        # never at top -> burns budget instead of stopping early
        assert len(page.mouse.wheels) > 3

    def test_budget_exhaustion(self):
        fp = {"nb": 1, "np": 1, "b0": "q", "blast": "q", "plast": "a", "top": 0, "sh": 100}
        page = self._page([fp] * 50)
        logs = []
        a = PerplexityAdapter(page, threading.Lock(), logs.append, lambda: False)
        a._climb_history(budget_s=0, interval_ms=1, need_stable=3)
        assert page.mouse.wheels == []
        assert any("budget" in m for m in logs)

    def test_cancel_stops(self):
        fp = {"nb": 1, "np": 1, "b0": "q", "blast": "q", "plast": "a", "top": 500, "sh": 5000}
        page = self._page([fp] * 10)
        a = _adapter(page, cancel=lambda: True)
        a._climb_history(budget_s=25, interval_ms=1, need_stable=3)
        assert page.mouse.wheels == []

    def test_evaluate_errors_tolerated(self):
        class ErrPage(FakePage):
            def evaluate(self, js, *a):
                raise RuntimeError("boom")
        page = ErrPage()
        logs = []
        a = PerplexityAdapter(page, threading.Lock(), logs.append, lambda: False)
        a._climb_history(budget_s=0, interval_ms=1, need_stable=3)  # must not raise
        assert page.mouse.wheels == []

    def test_no_rect_still_wheels(self):
        fp = {"nb": 1, "np": 1, "b0": "q", "blast": "q", "plast": "a", "top": 0, "sh": 100}
        page = FakePage(script={"FP": _fp_seq(*([fp] * 5)), "RECT": None})
        logs = []
        a = PerplexityAdapter(page, threading.Lock(), logs.append, lambda: False)
        a._climb_history(budget_s=25, interval_ms=1, need_stable=3)
        assert page.mouse.moved == []
        assert len(page.mouse.wheels) == 2
        assert any("no container rect" in m for m in logs)

    def test_move_failure_proceeds(self):
        fp = {"nb": 1, "np": 1, "b0": "q", "blast": "q", "plast": "a", "top": 0, "sh": 100}
        page = FakePage(script={"FP": _fp_seq(*([fp] * 5)),
                                "RECT": {"cx": 10, "cy": 20}})
        page.mouse = FakeMouse(fail_move=True)
        a = _adapter(page)
        a._climb_history(budget_s=25, interval_ms=1, need_stable=3)
        assert len(page.mouse.wheels) == 2


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
