"""Tests: validation IO-driver on mocked page/adapter. No live browser."""

from unittest.mock import MagicMock, patch

from core.profiler import validation as validation_mod


def _candidate():
    return {
        "kind": "selector-new",
        "preset": {
            "id": "fooai-auto-12345678",
            "strategy": {
                "type": "selector",
                "navigation": "goto",
                "wait_after_click_ms": 2000,
                "selectors": {
                    "chat_list_selector": "a",
                    "title_selector": "",
                    "message_selector": ".msg",
                    "user_message_selector": ".user",
                    "assistant_message_selector": ".asst",
                    "scroll_container_selector": "",
                },
                "scripts": {"list_chats_js": "", "extract_messages_js": ""},
            },
        },
    }


def _page(counts):
    page = MagicMock()
    page.url = "https://foo.ai/c/1"
    page.evaluate.return_value = counts
    return page


def test_validate_candidate_compatible_evidence():
    page = _page({"chats": 2, "messages": 6, "user": 3, "assistant": 3})
    with patch("adapters.custom_web.CustomWebAdapter") as cls:
        adapter = cls.return_value
        adapter.list_chats.return_value = [
            {"id": "custom-0", "title": "T", "url": "https://foo.ai/c/1",
             "_index": 0}]
        adapter.open_chat.return_value = True
        report = validation_mod.validate_candidate(
            page, _candidate(), ["https://foo.ai/c/1"] * 3, [],
            default_url="https://foo.ai/")
    assert report["summary"]["Compatible"] >= 1
    assert report["per_chat"][0]["evidence"]["messages"] == 6


def test_validate_candidate_open_fail_timeout():
    page = _page({"chats": 0, "messages": 0, "user": 0, "assistant": 0})
    page.goto.side_effect = Exception("net down")
    with patch("adapters.custom_web.CustomWebAdapter") as cls:
        adapter = cls.return_value
        adapter.list_chats.return_value = []
        report = validation_mod.validate_candidate(
            page, _candidate(), ["https://foo.ai/c/9"] * 3, [],
            default_url="https://foo.ai/")
    assert report["per_chat"][0]["reason"] == "timeout"


def test_n_chats_respected():
    page = _page({"chats": 2, "messages": 6, "user": 3, "assistant": 3})
    with patch("adapters.custom_web.CustomWebAdapter") as cls:
        cls.return_value.list_chats.return_value = []
        report = validation_mod.validate_candidate(
            page, _candidate(), ["https://foo.ai/c/%d" % i for i in range(8)],
            [], default_url="https://foo.ai/", n_chats=8)
    assert len(report["per_chat"]) == 8


def test_blocked_when_links_present_but_titles_empty():
    """B3 canonical: raw chats > 0 (links in DOM) yet titled == 0.

    The old raw-only gate (chats <= 0) could never fire here; Blocked
    must follow the list_chats title filter semantics instead.
    """
    page = MagicMock()
    page.url = "https://foo.ai/search/1"

    def _eval(js, arg=None):
        if isinstance(arg, dict):
            return {"chats": 5, "messages": 0, "user": 0, "assistant": 0}
        return 0  # titled count: every link title-empty (filter :50 drops all)

    page.evaluate.side_effect = _eval
    evidence = {"a[href*='/search/']": {"total": 5, "empty": 5}}
    with patch("adapters.custom_web.CustomWebAdapter") as cls:
        cls.return_value.list_chats.return_value = []
        report = validation_mod.validate_candidate(
            page, _candidate(), ["https://foo.ai/search/1"] * 3, [],
            default_url="https://foo.ai/", blocked_reason="product-filter",
            blocked_evidence=evidence)
    first = report["per_chat"][0]
    assert first["verdict"] == "Blocked"
    assert first["reason"] == "product-filter"
    assert first["evidence"]["titled_chats"] == 0
    assert report["summary"]["Blocked"] == 3


def test_stale_page_after_click_is_wrong_target():
    """Binding: click without a switch must not fake a Compatible."""
    page = MagicMock()
    page.url = "https://foo.ai/c/1"
    page.title.return_value = "chat one"

    def _eval(js, arg=None):
        if isinstance(arg, dict):
            return {"chats": 2, "messages": 6, "user": 3, "assistant": 3}
        return 6  # pre-open message count: page already shows this chat

    page.evaluate.side_effect = _eval
    with patch("adapters.custom_web.CustomWebAdapter") as cls:
        adapter = cls.return_value
        adapter.list_chats.return_value = [
            {"id": "custom-0", "title": "one", "url": "", "_index": 0}]
        adapter.open_chat.return_value = True  # clicked, but page unchanged
        report = validation_mod.validate_candidate(
            page, _candidate(),
            [{"token": "index:0", "href": "", "index": 0,
              "selector": "nav button", "text": "one"}],
            [], default_url="https://foo.ai/")
    first = report["per_chat"][0]
    assert (first["verdict"], first["reason"]) == ("Incompatible",
                                                  "wrong_target")


def _button_target(token="index:1", text="chat two"):
    return {"token": token, "href": "", "index": 1,
            "selector": "nav button", "text": text}


def test_click_target_text_match_is_verified():
    """B-A: shift + snapshot text in post title -> the target chat."""
    page = MagicMock()
    page.url = "https://z.ai/"
    page.title.return_value = "chat two"
    page.evaluate.return_value = {"chats": 2, "messages": 4,
                                  "user": 2, "assistant": 2}
    with patch("adapters.custom_web.CustomWebAdapter") as cls:
        adapter = cls.return_value
        adapter.list_chats.return_value = [
            {"id": "custom-0", "title": "one", "url": "", "_index": 0},
            {"id": "custom-1", "title": "chat two", "url": "", "_index": 1}]
        adapter.open_chat.return_value = True
        report = validation_mod.validate_candidate(
            page, _button_candidate(), [_button_target()], [],
            default_url="https://z.ai/")
    assert report["per_chat"][0]["verdict"] == "Compatible"


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


def test_click_target_text_mismatch_is_partial_wrong_target():
    """B-A'/B-B: switched but this target unconfirmed -> Partial, not
    Incompatible (opened, but we cannot claim whose chat it is)."""
    page = MagicMock()
    page.url = "https://z.ai/"
    page.title.return_value = "chat three — opened instead"
    page.evaluate.return_value = {"chats": 2, "messages": 9,
                                  "user": 4, "assistant": 5}
    with patch("adapters.custom_web.CustomWebAdapter") as cls:
        adapter = cls.return_value
        adapter.list_chats.return_value = [
            {"id": "custom-0", "title": "one", "url": "", "_index": 0},
            {"id": "custom-1", "title": "chat two", "url": "", "_index": 1}]
        adapter.open_chat.return_value = True
        report = validation_mod.validate_candidate(
            page, _button_candidate(), [_button_target()], [],
            default_url="https://z.ai/")
    first = report["per_chat"][0]
    assert (first["verdict"], first["reason"]) == ("Partial",
                                                  "wrong_target")


def _active_page(active_text):
    """Brand-title page: title carries no chat text; sidebar active does."""
    page = MagicMock()
    page.url = "https://z.ai/"
    page.title.return_value = "Z.ai"

    def _eval(js, arg=None):
        if isinstance(arg, dict) and "sels" in arg:
            return active_text
        if isinstance(arg, dict):
            return {"chats": 2, "messages": 4, "user": 2, "assistant": 2}
        # pre-open message count (".u, .a") starts at 0; titled count differs
        return 0 if arg == ".u, .a" else 4

    page.evaluate.side_effect = _eval
    return page


def _open_button_adapter():
    patcher = patch("adapters.custom_web.CustomWebAdapter")
    cls = patcher.start()
    adapter = cls.return_value
    adapter.list_chats.return_value = [
        {"id": "custom-0", "title": "one", "url": "", "_index": 0},
        {"id": "custom-1", "title": "chat two", "url": "", "_index": 1}]
    adapter.open_chat.return_value = True
    return patcher, adapter


def test_click_target_active_sidebar_verifies_despite_brand_title():
    """B-A'(a): brand document.title + matching active element -> verified."""
    page = _active_page("chat two")
    patcher, _ = _open_button_adapter()
    try:
        report = validation_mod.validate_candidate(
            page, _button_candidate(), [_button_target()], [],
            default_url="https://z.ai/")
    finally:
        patcher.stop()
    assert report["per_chat"][0]["verdict"] == "Compatible"


def test_click_target_active_mismatch_is_partial():
    """B-A'(a): shifted, title mute, active element foreign -> Partial."""
    page = _active_page("some other chat")
    patcher, _ = _open_button_adapter()
    try:
        report = validation_mod.validate_candidate(
            page, _button_candidate(), [_button_target()], [],
            default_url="https://z.ai/")
    finally:
        patcher.stop()
    first = report["per_chat"][0]
    assert (first["verdict"], first["reason"]) == ("Partial",
                                                  "wrong_target")


def test_click_target_empty_text_falls_back_to_shift():
    """B-A: text == '' -> legacy shift check decides."""
    page = MagicMock()
    page.url = "https://z.ai/"
    page.title.return_value = "something unrelated"
    page.evaluate.return_value = {"chats": 2, "messages": 4,
                                  "user": 2, "assistant": 2}
    with patch("adapters.custom_web.CustomWebAdapter") as cls:
        adapter = cls.return_value
        adapter.list_chats.return_value = [
            {"id": "custom-0", "title": "one", "url": "", "_index": 0},
            {"id": "custom-1", "title": "two", "url": "", "_index": 1}]
        adapter.open_chat.return_value = True
        report = validation_mod.validate_candidate(
            page, _button_candidate(), [_button_target(text="")], [],
            default_url="https://z.ai/")
    assert report["per_chat"][0]["verdict"] == "Compatible"


def test_href_target_already_open_is_verified():
    """Binding: already-on-target URL verifies without a visible switch."""
    page = MagicMock()
    page.url = "https://foo.ai/c/1"
    page.title.return_value = "same"
    page.evaluate.return_value = {"chats": 2, "messages": 6,
                                  "user": 3, "assistant": 3}
    with patch("adapters.custom_web.CustomWebAdapter") as cls:
        adapter = cls.return_value
        adapter.list_chats.return_value = [
            {"id": "custom-0", "title": "T", "url": "https://foo.ai/c/1",
             "_index": 0}]
        adapter.open_chat.return_value = True
        report = validation_mod.validate_candidate(
            page, _candidate(), ["https://foo.ai/c/1"] * 3, [],
            default_url="https://foo.ai/")
    assert report["per_chat"][0]["verdict"] == "Compatible"


def test_blocked_when_opened_chat_has_zero_titled():
    """N2: open state does not shield a titleless list; titled==0 → Blocked."""
    page = MagicMock()
    page.url = "https://foo.ai/search/1"

    def _eval(js, arg=None):
        if isinstance(arg, dict):
            return {"chats": 6, "messages": 4, "user": 2, "assistant": 2}
        return 0  # list opens, but every title empty

    page.evaluate.side_effect = _eval
    with patch("adapters.custom_web.CustomWebAdapter") as cls:
        adapter = cls.return_value
        adapter.list_chats.return_value = [
            {"id": "custom-0", "title": "", "url": "https://foo.ai/search/1",
             "_index": 0}]
        adapter.open_chat.return_value = True
        report = validation_mod.validate_candidate(
            page, _candidate(), ["https://foo.ai/search/1"] * 3, [],
            default_url="https://foo.ai/", blocked_reason="product-filter",
            blocked_evidence={"a": {"total": 6, "empty": 6}})
    assert report["per_chat"][0]["verdict"] == "Blocked"


def test_titled_chats_present_no_blocked():
    """B3 converse: titled > 0 with a blocked_reason still validates normally."""
    page = MagicMock()
    page.url = "https://foo.ai/c/1"

    def _eval(js, arg=None):
        if isinstance(arg, dict):
            return {"chats": 4, "messages": 6, "user": 3, "assistant": 3}
        return 4

    page.evaluate.side_effect = _eval
    with patch("adapters.custom_web.CustomWebAdapter") as cls:
        adapter = cls.return_value
        adapter.list_chats.return_value = [
            {"id": "custom-0", "title": "T", "url": "https://foo.ai/c/1",
             "_index": 0}]
        adapter.open_chat.return_value = True
        report = validation_mod.validate_candidate(
            page, _candidate(), ["https://foo.ai/c/1"] * 3, [],
            default_url="https://foo.ai/", blocked_reason="product-filter",
            blocked_evidence={})
    assert report["per_chat"][0]["verdict"] == "Compatible"


def test_blocked_on_product_filter_without_chats():
    page = _page({"chats": 0, "messages": 0, "user": 0, "assistant": 0})
    page.goto.side_effect = lambda url, **kw: setattr(page, "url", url)
    evidence = {"a[href*='/search/']": {"total": 3, "empty": 3}}
    with patch("adapters.custom_web.CustomWebAdapter") as cls:
        cls.return_value.list_chats.return_value = []
        report = validation_mod.validate_candidate(
            page, _candidate(), ["https://foo.ai/search/1"] * 3, [],
            default_url="https://foo.ai/", blocked_reason="product-filter",
            blocked_evidence=evidence)
    first = report["per_chat"][0]
    assert first["verdict"] == "Blocked"
    assert first["reason"] == "product-filter"
    assert first["evidence"]["empty_title"] == evidence
    assert report["summary"]["Blocked"] == 3
