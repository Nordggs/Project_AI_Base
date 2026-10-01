"""Probe orchestration on a live page (TICKET-002-L, Phase 2). IO layer.

Contract: ``page`` is injected from the outside (CLI launcher or App worker).
This module never creates or closes a browser; all browser IO must run in
the owning worker thread. Each probe records an observation with evidence
(counts + selector), never a bare boolean.

Research-context order is mandatory (B1+B2 fix):

    chat-list probe
       -> pick first chat
       -> try goto(chat_url)  -> messages?
          - present -> navigation = goto
          - empty   -> click fallback + wait_for_function + wait_after_click
                       -> messages?
    and ONLY after the chat is open:
       message probes -> user/assistant probes -> title probe -> scroll probe

``run_probes`` never judges navigation from the home page: it first builds the
research context, then investigates it.
"""

from core.profiler import probes as probe_specs

_COUNT_JS = "(sel) => { try { return document.querySelectorAll(sel).length; } catch (e) { return 0; } }"

_TEXTY_COUNT_JS = """(arg) => {
    const {sel, minLen} = arg;
    let n = 0;
    try {
        document.querySelectorAll(sel).forEach(el => {
            const t = (el.innerText || '').trim();
            if (t && t.length >= minLen) n++;
        });
    } catch (e) {}
    return n;
}"""

_EMPTY_TITLE_LINKS_JS = """(sel) => {
    let total = 0, empty = 0;
    try {
        document.querySelectorAll(sel).forEach(el => {
            total++;
            const t = (el.textContent || '').trim();
            if (!t) empty++;
        });
    } catch (e) {}
    return {total, empty};
}"""

_CHAT_ITEMS_JS = """(sel) => {
    const out = [];
    try {
        document.querySelectorAll(sel).forEach((el, i) => {
            let href = el.getAttribute('href') || '';
            if (href && !href.startsWith('http')) {
                try { href = new URL(href, location.href).href; } catch (e) {}
            }
            out.push({
                index: i,
                href: href,
                text: ((el.textContent || '').trim()).slice(0, 200)
            });
        });
    } catch (e) {}
    return out;
}"""

_PRESENCE_JS = """(arg) => {
    const {sels, minLen} = arg;
    let n = 0;
    for (const s of sels) {
        try {
            document.querySelectorAll(s).forEach(el => {
                const t = (el.innerText || '').trim();
                if (t && t.length >= minLen) n++;
            });
        } catch (e) {}
    }
    return n;
}"""

_CLICK_INDEX_JS = """(arg) => {
    const {sel, idx} = arg;
    try {
        const els = document.querySelectorAll(sel);
        if (els[idx]) { els[idx].click(); return true; }
    } catch (e) {}
    return false;
}"""

_TITLE_JS = """(arg) => {
    const {sel, children} = arg;
    let el = null;
    try { el = document.querySelector(sel); } catch (e) {}
    if (!el) return {source: 'url', selector: ''};
    if ((el.textContent || '').trim()) return {source: 'text', selector: ''};
    for (const cs of children) {
        let c = null;
        try { c = el.querySelector(cs); } catch (e) {}
        if (c && (c.textContent || '').trim()) return {source: 'child', selector: cs};
    }
    return {source: 'url', selector: ''};
}"""

_WAIT_PRESENCE_JS = """(arg) => {
    const {sels, minLen} = arg;
    for (const s of sels) {
        try {
            let ok = false;
            document.querySelectorAll(s).forEach(el => {
                const t = (el.innerText || '').trim();
                if (t && t.length >= minLen) ok = true;
            });
            if (ok) return true;
        } catch (e) {}
    }
    return false;
}"""


def _safe_evaluate(page, js, arg=None):
    try:
        if arg is None:
            return page.evaluate(js)
        return page.evaluate(js, arg)
    except Exception:
        return None


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _count(page, sel) -> int:
    return _safe_int(_safe_evaluate(page, _COUNT_JS, sel))


def _texty_count(page, sel) -> int:
    return _safe_int(_safe_evaluate(
        page, _TEXTY_COUNT_JS, {"sel": sel, "minLen": probe_specs.MIN_TEXTY_LEN}))


def _has_texty_messages(page) -> bool:
    result = _safe_evaluate(page, _PRESENCE_JS, {
        "sels": probe_specs.MESSAGE_WAIT_SELECTORS,
        "minLen": probe_specs.MIN_TEXTY_LEN,
    })
    return bool(result)


def _chat_opened(page) -> bool:
    """Opened = narrow presence OR non-trivial miners / roles (R2, N1).

    A provider with fully custom message classes is absent from
    MESSAGE_WAIT_SELECTORS but present in role triples / specific miners.
    Judging only by the narrow set caused false ``opened=False``.
    The ultra-broad ``main div`` miner must NEVER confirm an open (N1):
    any SPA shell has text in ``main div``, which would fake a successful
    goto and skip the click fallback (Grok regression, B2).
    """
    if _has_texty_messages(page):
        return True
    try:
        hits = probe_messages(page) or {}
        hits.pop("main div", None)
        if any(hits.values()):
            return True
        return bool(probe_roles(page).get("found"))
    except Exception:
        return False


def _wait_ms(page, ms):
    try:
        page.wait_for_timeout(ms)
    except Exception:
        pass


def probe_chat_list(page, log=None) -> dict:
    """Count chat-list candidates (anchor -> button) and capture the best list.

    Returns {hits, empty_title, best_sel, items}. ``empty_title`` carries the
    Perplexity evidence (links present in DOM but without text), used to emit
    a product-filter Blocked instead of a false Incompatible.
    """
    _log = log or (lambda msg: None)
    hits: dict = {}
    empty_title: dict = {}
    best_sel = ""
    for sel in probe_specs.chat_list_probe_order():
        n = _count(page, sel)
        if n <= 0:
            continue
        hits[sel] = n
        info = _safe_evaluate(page, _EMPTY_TITLE_LINKS_JS, sel) or {}
        if isinstance(info, dict):
            empty_title[sel] = info
        if not best_sel:
            best_sel = sel
    items = []
    if best_sel:
        raw = _safe_evaluate(page, _CHAT_ITEMS_JS, best_sel)
        if isinstance(raw, list):
            items = [i for i in raw if isinstance(i, dict)]
    _log(f"[profiler] chat-list: {len(hits)} selectors, best={best_sel!r}, "
         f"items={len(items)}")
    return {"hits": hits, "empty_title": empty_title,
            "best_sel": best_sel, "items": items}


def _try_goto(page, href: str) -> bool:
    if not href or not href.startswith("http"):
        return False
    try:
        page.goto(href, wait_until="domcontentloaded", timeout=15000)
    except Exception:
        return False
    _wait_ms(page, 800)
    return _chat_opened(page)


def _try_click(page, provider_url: str, chat_sel: str, index: int) -> bool:
    if not chat_sel:
        return False
    try:
        page.goto(provider_url, wait_until="domcontentloaded", timeout=15000)
    except Exception:
        return False
    _wait_ms(page, 800)
    clicked = _safe_evaluate(page, _CLICK_INDEX_JS, {"sel": chat_sel, "idx": index})
    if not clicked:
        return False
    try:
        page.wait_for_function(
            _WAIT_PRESENCE_JS,
            arg={"sels": probe_specs.MESSAGE_WAIT_SELECTORS,
                 "minLen": probe_specs.MIN_TEXTY_LEN},
            timeout=10000,
        )
    except Exception:
        # fall through: wait_after_click may still reveal messages
        pass
    _wait_ms(page, 2000)
    return _chat_opened(page)


def open_research_context(page, provider_url: str, chat: dict, log=None) -> tuple:
    """Open the first chat and decide navigation (Phase 2.1).

    goto first; if the SPA leaves messages empty, fall back to a click on the
    original chat-list element + wait_for_function. Returns (nav_dict, opened).
    """
    _log = log or (lambda msg: None)
    nav = {"type": "goto", "goto_empty": True, "spa": False,
           "hydration_required": False, "wait_after_navigation_ms": 2000}
    items = (chat or {}).get("items") or []
    if not items:
        return nav, False
    first = items[0]
    href = first.get("href", "") or ""
    chat_sel = (chat or {}).get("best_sel") or ""
    idx = _safe_int(first.get("index", 0))
    goto_attempted = bool(href.startswith("http"))

    if goto_attempted and _try_goto(page, href):
        nav.update({"type": "goto", "goto_empty": False, "spa": False,
                    "hydration_required": False})
        _log("[profiler] navigation: goto (messages present after goto)")
        return nav, True

    click_ok = _try_click(page, provider_url, chat_sel, idx)
    if click_ok:
        nav_type = "both" if goto_attempted else "click"
        nav.update({"type": nav_type, "goto_empty": goto_attempted,
                    "spa": True, "hydration_required": True})
        _log(f"[profiler] navigation: click (goto_empty={goto_attempted})")
        return nav, True

    _log("[profiler] chat could not be opened (goto empty, click failed)")
    nav.update({"type": "goto", "goto_empty": True})
    return nav, False


def probe_messages(page) -> dict:
    """Message selector mining, run on the OPENED chat only."""
    hits: dict = {}
    for sel in probe_specs.message_probe_selectors():
        n = _texty_count(page, sel)
        if n > 0:
            hits[sel] = n
    return hits


def probe_roles(page, log=None) -> dict:
    """First verified user/assistant triple with non-zero counts (Phase 2.4).

    Priority order (verified triples before generic), never a max-count pick:
    a noisy generic like ``[class*="ai"]`` must not outscore ``.message-bubble``.
    """
    result = {"message": "", "user": "", "assistant": "",
              "user_n": 0, "assistant_n": 0, "found": False}
    user_sel, user_n = "", 0
    for cand in probe_specs.role_user_candidates():
        n = _texty_count(page, cand)
        if n > 0:
            user_sel, user_n = cand, n
            break
    asst_sel, asst_n = "", 0
    for cand in probe_specs.role_assistant_candidates():
        if cand == user_sel:
            continue
        n = _texty_count(page, cand)
        if n > 0:
            asst_sel, asst_n = cand, n
            break
    if not user_sel or not asst_sel:
        return result
    result.update({"message": f"{user_sel}, {asst_sel}", "user": user_sel,
                   "assistant": asst_sel, "user_n": user_n,
                   "assistant_n": asst_n, "found": True})
    return result


def probe_title(page, chat_sel: str, log=None) -> dict:
    """Title source for the list element, readable by list_chats (Phase 2.3)."""
    if not chat_sel:
        return {"source": "url", "selector": ""}
    info = _safe_evaluate(page, _TITLE_JS, {
        "sel": chat_sel, "children": list(probe_specs.TITLE_CHILD_SELECTORS)})
    if isinstance(info, dict) and info.get("source"):
        return {"source": info.get("source", "url"),
                "selector": info.get("selector", "")}
    return {"source": "url", "selector": ""}


def find_scroll_container(page) -> str:
    for sel in probe_specs.SCROLL_CONTAINER_CANDIDATES:
        if _count(page, sel) > 0:
            return sel
    return ""


def detect_scroll(page, chat_list_sel: str, container_sel: str = "") -> dict:
    """Scroll probe: growth of chat_list_N on scroll. Pure-IO helper.

    Rule (Audit 2 §12.4.3): no container or script strategy -> honest
    ``unknown``; ``fail`` is reserved for "container exists but no growth".
    """
    result = {"required": False, "container": container_sel or "",
              "infinite": False, "status": "unknown"}
    if not chat_list_sel or not container_sel:
        return result
    try:
        before = _count(page, chat_list_sel)
        page.evaluate(
            "(sel) => { const el = document.querySelector(sel); if (el) el.scrollTop += 800; }",
            container_sel,
        )
        _wait_ms(page, 800)
        after = _count(page, chat_list_sel)
    except Exception:
        return result
    if after > before:
        result.update({"required": True, "infinite": True, "status": "ok"})
    else:
        result.update({"required": False, "status": "fail"})
    return result


def probe_scroll(page, chat_list_sel: str, log=None) -> dict:
    """Detect the scroll container, then measure chat-list growth."""
    container = find_scroll_container(page)
    result = detect_scroll(page, chat_list_sel, container)
    result["container"] = container
    return result


def run_probes(page, provider_url: str = "", log=None) -> dict:
    """Run the full research flow on the live page. Returns observations dict."""
    _log = log or (lambda msg: None)
    try:
        current_url = page.url or ""
    except Exception:
        current_url = ""
    provider_url = provider_url or current_url

    chat = probe_chat_list(page, _log)
    nav, opened = open_research_context(page, provider_url, chat, _log)

    if opened:
        message_hits = probe_messages(page)
        roles = probe_roles(page, _log)
        title = probe_title(page, chat.get("best_sel") or "", _log)
        scroll = probe_scroll(page, chat.get("best_sel") or "", _log)
    else:
        message_hits = {}
        roles = {"message": "", "user": "", "assistant": "",
                 "user_n": 0, "assistant_n": 0, "found": False}
        title = {"source": "url", "selector": ""}
        scroll = {"required": False, "container": "", "infinite": False,
                  "status": "unknown"}

    blocked = _detect_product_filter(chat.get("empty_title") or {},
                                       chat.get("best_sel") or "")
    obs = {
        "provider_url": provider_url,
        "navigation": nav,
        "chat_open": opened,
        "chat_list_hits": chat.get("hits") or {},
        "chat_list_selector": chat.get("best_sel") or "",
        "chat_items": chat.get("items") or [],
        "empty_title_links": chat.get("empty_title") or {},
        "message_hits": message_hits,
        "roles": roles,
        "title": title,
        "scroll": scroll,
        "blocked": blocked,
    }
    _log(f"[profiler] probes: chat_list {len(obs['chat_list_hits'])}, "
         f"messages {len(message_hits)}, open={opened}, nav={nav.get('type')}")
    return obs


def _detect_product_filter(empty_title: dict, best_sel: str = "") -> dict:
    """Perplexity lesson: links exist but all titles empty -> product-filter.

    Gated only by best_sel (N2): whether the chat opened or not says
    nothing about titleless sidebar links, and gating on ``opened`` hid
    the evidence exactly when validation needs it. The Blocked DECISION
    stays in validation (titled_chats <= 0); this function only reports
    the observation. A stray selector with empty titles on a working
    provider must not poison the matrix, hence the best_sel gate.
    """
    if not empty_title:
        return {}
    evidence = {}
    for sel, info in empty_title.items():
        if best_sel and sel != best_sel:
            continue
        if not isinstance(info, dict):
            continue
        total = _safe_int(info.get("total"))
        empty = _safe_int(info.get("empty"))
        if total > 0 and empty >= total:
            evidence[sel] = {"total": total, "empty": empty}
    if not evidence:
        return {}
    return {"reason": "product-filter", "evidence": evidence}
