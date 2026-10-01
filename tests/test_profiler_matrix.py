"""Tests: preset matrix incl. reuse and navigation mapping. No browser."""

from core.profiler.matrix import build_preset_matrix


def _obs(chat_sel="a[href*='/c/']", msg_sel=".message-bubble"):
    return {
        "provider_url": "https://foo.ai/",
        "navigation": {"type": "both"},
        "chat_list_selector": chat_sel,
        "chat_list_hits": {chat_sel: 5},
        "message_hits": {msg_sel: 4},
        "roles": {"message": ".message-bubble, .response-content-markdown",
                  "user": ".message-bubble",
                  "assistant": ".response-content-markdown", "found": True},
        "title": {"source": "text", "selector": ""},
        "scroll": {"container": "main"},
    }


def _catalog():
    return [{
        "id": "userscript-generic",
        "strategy": {
            "type": "selector",
            "navigation": "goto",
            "selectors": {
                "chat_list_selector": "a[href*='/other/']",
                "message_selector": '[class*="message"]',
            },
            "scripts": {"list_chats_js": "", "extract_messages_js": ""},
        },
    }]


def test_new_selector_candidate_valid():
    matrix = build_preset_matrix("fooai", _obs(), [], goto_empty=True)
    news = [c for c in matrix["candidates"] if c["kind"] == "selector-new"]
    assert len(news) == 1
    assert news[0]["preset"]["strategy"]["navigation"] == "click"


def test_both_maps_to_goto_without_spa_emptiness():
    matrix = build_preset_matrix("fooai", _obs(), [], goto_empty=False)
    news = [c for c in matrix["candidates"] if c["kind"] == "selector-new"]
    assert news and news[0]["preset"]["strategy"]["navigation"] == "goto"


def test_never_emits_both_in_strategy():
    matrix = build_preset_matrix("fooai", _obs(), [], goto_empty=True)
    for cand in matrix["candidates"]:
        if cand["kind"] == "selector-new":
            assert cand["preset"]["strategy"]["navigation"] in ("goto", "click")


def test_reuse_suppresses_duplicate():
    catalog = [{
        "id": "userscript-generic",
        "strategy": {
            "type": "selector",
            "navigation": "goto",
            "selectors": {
                "chat_list_selector": "a[href*='/c/']",
                "message_selector": ".message-bubble",
            },
            "scripts": {"list_chats_js": "", "extract_messages_js": ""},
        },
    }]
    matrix = build_preset_matrix("fooai", _obs(), catalog)
    kinds = [c["kind"] for c in matrix["candidates"]]
    assert "reuse" in kinds and "selector-new" not in kinds


def test_zero_candidates_valid():
    matrix = build_preset_matrix("fooai", {"navigation": {"type": "goto"},
                                           "chat_list_hits": {},
                                           "message_hits": {}}, [])
    assert matrix["candidates"] == []


def test_no_js_synthesis():
    matrix = build_preset_matrix("fooai", _obs(), [], goto_empty=True)
    for cand in matrix["candidates"]:
        if cand["kind"] == "selector-new":
            scripts = cand["preset"]["strategy"]["scripts"]
            assert scripts == {"list_chats_js": "", "extract_messages_js": ""}


def test_roles_populate_candidate_selectors():
    obs = _obs()
    obs["roles"] = {
        "message": ".message-bubble, .response-content-markdown",
        "user": ".message-bubble",
        "assistant": ".response-content-markdown",
        "found": True,
    }
    matrix = build_preset_matrix("fooai", obs, [], goto_empty=True)
    news = [c for c in matrix["candidates"] if c["kind"] == "selector-new"]
    assert news
    sels = news[0]["preset"]["strategy"]["selectors"]
    assert sels["user_message_selector"] == ".message-bubble"
    assert sels["assistant_message_selector"] == ".response-content-markdown"
    assert sels["message_selector"] == ".message-bubble, .response-content-markdown"


def test_product_filter_surfaces_in_matrix():
    obs = {
        "provider_url": "https://foo.ai/",
        "navigation": {"type": "goto"},
        "chat_list_selector": "a[href*='/search/']",
        "chat_list_hits": {"a[href*='/search/']": 3},
        "message_hits": {},
        "roles": {},
        "blocked": {"reason": "product-filter",
                    "evidence": {"a[href*='/search/']": {"total": 3, "empty": 3}}},
    }
    matrix = build_preset_matrix("fooai", obs, [])
    assert matrix["blocked"]["reason"] == "product-filter"
    assert matrix["candidates"] == []


def test_noisy_generic_selectors_do_not_emit_candidates():
    """R10: nav a / a[href] hits are evidence only; one best_sel candidate."""
    obs = _obs(chat_sel="a[href*='/c/']")
    obs["chat_list_hits"] = {
        "a[href*='/c/']": 5,
        "nav a": 12,
        "aside a": 12,
        "a[href]": 40,
    }
    matrix = build_preset_matrix("fooai", obs, [], goto_empty=True)
    news = [c for c in matrix["candidates"] if c["kind"] == "selector-new"]
    assert len(news) == 1
    assert news[0]["preset"]["strategy"]["selectors"][
        "chat_list_selector"] == "a[href*='/c/']"
    assert news[0]["probes"]["chat_list_evidence"]["a[href]"] == 40


def test_foreign_preset_not_confirmed_by_generic_miner():
    """R11: grok's own triple unobserved -> no reuse via чужой miner."""
    from core.profiler.reuse import detect_reuse
    catalog = [{
        "id": "grok",
        "strategy": {
            "type": "selector",
            "navigation": "click",
            "selectors": {
                "chat_list_selector": "a[href*='/c/']",
                "message_selector": ".message-bubble, .response-content-markdown",
                "user_message_selector": ".message-bubble",
                "assistant_message_selector": ".response-content-markdown",
            },
            "scripts": {"list_chats_js": "", "extract_messages_js": ""},
        },
    }]
    obs = {
        "chat_list_hits": {"a[href*='/c/']": 5},
        # only a foreign generic miner fired (incl. main div noise)
        "message_hits": {'[class*="message"]': 4, "main div": 30},
        "roles": {},
    }
    assert detect_reuse(catalog, obs) == []


def test_generic_preset_with_own_parts_observed_is_reuse():
    """N3: userscript-generic matches only via its OWN observed selectors."""
    from core.profiler.reuse import detect_reuse
    catalog = [{
        "id": "userscript-generic",
        "strategy": {
            "type": "selector",
            "navigation": "goto",
            "selectors": {
                "chat_list_selector": "a[href*='/c/']",
                "message_selector": '[class*="message"], [class*="chat-message"]',
            },
            "scripts": {"list_chats_js": "", "extract_messages_js": ""},
        },
    }]
    obs = {
        "chat_list_hits": {"a[href*='/c/']": 5},
        "message_hits": {'[class*="assistant"]': 3,
                         '[class*="chat-message"]': 2},
        "roles": {},
    }
    found = detect_reuse(catalog, obs)
    assert [r["preset_id"] for r in found] == ["userscript-generic"]


def test_generic_preset_with_only_foreign_miner_is_not_reuse():
    """N3: foreign .message-bubble alone must not confirm userscript-generic."""
    from core.profiler.reuse import detect_reuse
    catalog = [{
        "id": "userscript-generic",
        "strategy": {
            "type": "selector",
            "navigation": "goto",
            "selectors": {
                "chat_list_selector": "a[href*='/c/']",
                "message_selector": '[class*="message"], [class*="chat-message"]',
            },
            "scripts": {"list_chats_js": "", "extract_messages_js": ""},
        },
    }]
    obs = {
        "chat_list_hits": {"a[href*='/c/']": 5},
        "message_hits": {".message-bubble": 6},
        "roles": {},
    }
    assert detect_reuse(catalog, obs) == []
