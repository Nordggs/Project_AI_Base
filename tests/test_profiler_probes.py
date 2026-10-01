"""Tests: probe specs + research flow (TICKET-002-L, Phase 2). No browser."""

from core.profiler import orchestrator, probes


class FakePage:
    """Minimal Playwright-page double for the orchestrator flow."""

    def __init__(self, dom=None, texty=None, empty=None, items=None,
                 title=None, click_texty=None, url="https://foo.ai/"):
        self.dom = dict(dom or {})
        self.texty = dict(texty or {})
        self.empty = dict(empty or {})
        self.items = dict(items or {})
        self.title = dict(title or {})
        self.click_texty = dict(click_texty or {})
        self._url = url
        self.clicked = None
        self.goto_calls = []
        self.last_arg = None

    @property
    def url(self):
        return self._url

    def goto(self, url, **_):
        self.goto_calls.append(url)
        self._url = url

    def wait_for_timeout(self, ms):
        return None

    def wait_for_function(self, js, **kw):
        return True

    def evaluate(self, js, arg=None):
        s = js or ""
        if "out.push" in s:  # _CHAT_ITEMS_JS
            return list(self.items.get(arg, []))
        if "children" in s:  # _TITLE_JS
            return self.title.get((arg or {}).get("sel"),
                                  {"source": "text", "selector": ""})
        if "els[idx]" in s:  # _CLICK_INDEX_JS
            self.clicked = arg
            self.texty.update(self.click_texty)
            return True
        if "total" in s and "empty" in s:  # _EMPTY_TITLE_LINKS_JS
            return self.empty.get(arg, {"total": 0, "empty": 0})
        if "sels" in s and "minLen" in s:  # _PRESENCE_JS
            return sum(self.texty.get(x, 0) for x in arg.get("sels", [])) > 0
        if "minLen" in s:  # _TEXTY_COUNT_JS
            self.last_arg = arg
            return self.texty.get((arg or {}).get("sel"), 0)
        if "querySelectorAll(sel)" in s:  # _COUNT_JS
            return self.dom.get(arg, 0)
        return 0


def _chat_page(**kw):
    base = {
        "dom": {"a[href*='/c/']": 5, "main": 1},
        "texty": {".message-bubble": 2, ".response-content-markdown": 2},
        "empty": {"a[href*='/c/']": {"total": 5, "empty": 0}},
        "items": {"a[href*='/c/']": [
            {"index": 0, "href": "https://foo.ai/c/1", "text": "chat 1"}]},
        "title": {"a[href*='/c/']": {"source": "text", "selector": ""}},
    }
    base.update(kw)
    return FakePage(**base)


def test_anchor_before_button_order():
    order = probes.chat_list_probe_order()
    first_button = next(i for i, s in enumerate(order)
                        if s in probes.BUTTON_CHAT_LIST_SLS)
    last_anchor = max(i for i, s in enumerate(order)
                      if s in probes.ANCHOR_CHAT_LIST_SLS)
    assert last_anchor < first_button


def test_navigation_mapping_both():
    assert probes.map_profile_navigation_to_strategy("both", True) == "click"
    assert probes.map_profile_navigation_to_strategy("both", False) == "goto"
    assert probes.map_profile_navigation_to_strategy("click", False) == "click"
    assert probes.map_profile_navigation_to_strategy("goto", True) == "goto"
    assert probes.map_profile_navigation_to_strategy("weird", False) == "goto"


def test_goto_first_then_probes_run_after_open():
    obs = orchestrator.run_probes(_chat_page(), "https://foo.ai/")
    assert obs["chat_open"] is True
    assert obs["navigation"]["type"] == "goto"
    assert obs["navigation"]["goto_empty"] is False
    # message/role/title/scroll probes only make sense after the open
    assert obs["message_hits"]
    assert obs["roles"]["found"] is True
    assert obs["roles"]["user"] == ".message-bubble"
    assert obs["roles"]["assistant"] == ".response-content-markdown"
    assert obs["scroll"]["container"] == "main"
    assert obs["blocked"] == {}


def test_click_fallback_when_goto_empty():
    page = _chat_page(texty={}, click_texty={
        ".message-bubble": 3, ".response-content-markdown": 3})
    obs = orchestrator.run_probes(page, "https://foo.ai/")
    assert obs["chat_open"] is True
    # goto was attempted and came back empty -> both (maps to click)
    assert obs["navigation"]["type"] == "both"
    assert obs["navigation"]["goto_empty"] is True
    assert obs["roles"]["found"] is True
    assert page.clicked is not None


def test_product_filter_detected_from_empty_titles():
    page = FakePage(
        dom={"a[href*='/search/']": 3},
        texty={},
        empty={"a[href*='/search/']": {"total": 3, "empty": 3}},
        items={"a[href*='/search/']": [
            {"index": 0, "href": "https://foo.ai/search/abc", "text": ""}]},
    )
    obs = orchestrator.run_probes(page, "https://foo.ai/")
    assert obs["chat_open"] is False
    assert obs["blocked"]["reason"] == "product-filter"
    assert obs["blocked"]["evidence"]["a[href*='/search/']"] == {
        "total": 3, "empty": 3}


def test_texty_gate_filters_composer_noise():
    page = _chat_page()
    hits = orchestrator.probe_messages(page)
    assert ".message-bubble" in hits
    assert page.last_arg["minLen"] == probes.MIN_TEXTY_LEN


def test_roles_priority_verified_first():
    page = _chat_page(texty={".message-bubble": 1,
                             '[class*="user"]': 9,
                             ".response-content-markdown": 1,
                             '[class*="ai"]': 9})
    roles = orchestrator.probe_roles(page)
    assert roles["user"] == ".message-bubble"
    assert roles["assistant"] == ".response-content-markdown"
