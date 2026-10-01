"""Tests: R1 button-list validation, R2 opened-by-miners, R3 gated filter."""

from unittest.mock import MagicMock, patch

from core.profiler import orchestrator
from core.profiler import run as run_mod
from core.profiler import validation as validation_mod


def _button_candidate():
    return {
        "kind": "selector-new",
        "preset": {
            "id": "zai-auto-12345678",
            "strategy": {
                "type": "selector",
                "navigation": "click",
                "wait_after_click_ms": 2000,
                "selectors": {
                    "chat_list_selector": "nav button",
                    "title_selector": "",
                    "message_selector": ".u, .a",
                    "user_message_selector": ".u",
                    "assistant_message_selector": ".a",
                    "scroll_container_selector": "",
                },
                "scripts": {"list_chats_js": "", "extract_messages_js": ""},
            },
        },
    }


def test_button_list_validation_opens_by_index():
    """R1: href-less targets validate via stable _index, token index:N."""
    page = MagicMock()
    page.url = "https://z.ai/c/1"
    page.title.return_value = "chat two — Z.ai"
    page.evaluate.return_value = {"chats": 2, "messages": 4,
                                  "user": 2, "assistant": 2}
    targets = [{"token": "index:1", "href": "", "index": 1,
                "selector": "nav button", "text": "chat two"}]
    with patch("adapters.custom_web.CustomWebAdapter") as cls:
        adapter = cls.return_value
        adapter.list_chats.return_value = [
            {"id": "custom-0", "title": "one", "url": "", "_index": 0},
            {"id": "custom-1", "title": "two", "url": "", "_index": 1},
        ]
        adapter.open_chat.return_value = True
        report = validation_mod.validate_candidate(
            page, _button_candidate(), targets, [],
            default_url="https://z.ai/")
    assert report["per_chat"][0]["chat_url"] == "index:1"
    assert report["per_chat"][0]["target"]["index"] == 1
    assert report["summary"]["Compatible"] == 1
    opened_arg = adapter.open_chat.call_args[0][0]
    assert opened_arg["_index"] == 1  # stable index, not reshuffled first item


def test_href_match_wins_for_reuse_with_other_selector():
    """N5: href targets resolve by href (frozen index belongs to best_sel)."""
    items = [{"id": "custom-0", "title": "B", "url": "https://x/b",
              "_index": 0},
             {"id": "custom-1", "title": "A", "url": "https://x/a",
              "_index": 1}]
    target = {"token": "https://x/a", "href": "https://x/a", "index": 0,
              "selector": "nav button", "text": "A"}
    assert validation_mod._resolve_target(items, target)["_index"] == 1


def test_pure_index_target_resolves_by_stable_index():
    """R1: href-less button targets still resolve by frozen index."""
    items = [{"id": "custom-0", "title": "one", "url": "", "_index": 0},
             {"id": "custom-1", "title": "two", "url": "", "_index": 1}]
    target = {"token": "index:1", "href": "", "index": 1,
              "selector": "nav button", "text": "two"}
    assert validation_mod._resolve_target(items, target)["_index"] == 1


def test_opened_by_miners_with_custom_classes():
    """R2: custom message classes confirm open despite narrow presence miss."""
    page = MagicMock()
    page.url = "https://foo.ai/c/1"

    def _eval(js, arg=None):
        if isinstance(arg, dict) and "sels" in arg:
            return 0  # narrow MESSAGE_WAIT_SELECTORS: nothing
        if isinstance(arg, dict) and arg.get("sel") == ".custom-msg":
            return 3
        if isinstance(arg, dict) and arg.get("sel") in (".custom-u",
                                                        ".custom-a"):
            return 2
        return 0

    page.evaluate.side_effect = _eval
    with patch.object(orchestrator.probe_specs, "MSG_PROBE_SELS",
                       [".custom-msg"]):
        with patch.object(orchestrator.probe_specs, "ROLE_USER_CANDIDATES",
                           [".custom-u"]):
            with patch.object(orchestrator.probe_specs, "ROLE_ASST_CANDIDATES",
                               [".custom-a"]):
                assert orchestrator._chat_opened(page) is True


def test_shell_with_only_main_div_is_not_opened():
    """N1: SPA shell text in main div must not fake a successful goto."""
    page = MagicMock()
    page.url = "https://grok.com/"

    def _eval(js, arg=None):
        if isinstance(arg, dict) and "sels" in arg:
            return 0  # narrow presence: nothing
        if isinstance(arg, dict) and arg.get("sel") == "main div":
            return 5  # shell chrome text only
        return 0

    page.evaluate.side_effect = _eval
    assert orchestrator._chat_opened(page) is False


def test_product_filter_gated_by_best_sel_not_opened():
    """N2: observation reported regardless of open state; best_sel gates."""
    empty = {"nav button": {"total": 5, "empty": 5},
             "aside a": {"total": 9, "empty": 9}}
    res = orchestrator._detect_product_filter(empty, "nav button")
    assert res["reason"] == "product-filter"
    assert res["evidence"] == {"nav button": {"total": 5, "empty": 5}}


def test_report_carries_provider_blocked_with_no_candidates(tmp_path):
    """B3: empty matrix still lands Blocked + evidence in the artifact."""
    matrix = {"provider": "fooai", "candidates": [],
              "blocked": {"reason": "product-filter",
                          "evidence": {"a": {"total": 5, "empty": 5}}}}
    out = str(tmp_path / "validation_report.md")
    run_mod._write_validation_report(out, matrix, [])
    text = open(out, encoding="utf-8").read()
    assert "Blocked (product-filter)" in text
    assert "'empty': 5" in text or '"empty": 5' in text


def test_scroll_growth_ok_and_unknown():
    """R7: growth -> ok, no container -> unknown (never silent fail)."""
    page = MagicMock()
    calls = {"n": 0}

    def _eval(js, arg=None):
        if "scrollTop" in (js or ""):
            calls["n"] += 1
            return None
        return 2 if calls["n"] == 0 else 5

    page.evaluate.side_effect = _eval
    page.wait_for_timeout.return_value = None
    res = orchestrator.detect_scroll(page, "nav a", "aside")
    assert res["status"] == "ok" and res["infinite"] is True
    res2 = orchestrator.detect_scroll(page, "nav a", "")
    assert res2["status"] == "unknown"
