"""Validation driver: open N chats -> extract/count (TICKET-002-L, Phase 4). IO.

Each candidate is validated on N real chats (default 5, minimum 3, N from the
CLI). Per-chat verdicts come from verdicts.per_chat_verdict; the summary is
aggregated by verdicts.aggregate_report. Per-chat evidence is kept. A provider
with product-filter evidence (empty-title links) yields Blocked, not a silent
Incompatible (Perplexity lesson).
"""

from core.profiler import verdicts

MIN_CHATS = 3
DEFAULT_CHATS = 5

_DIAG_COUNTS_JS = """(arg) => {
    const c = (s) => {
        try { return s ? document.querySelectorAll(s).length : 0; }
        catch (e) { return 0; }
    };
    return {
        chats: c(arg.chatSel),
        messages: c(arg.msgSel),
        user: c(arg.userSel),
        assistant: c(arg.asstSel)
    };
}"""

# B3: "titled chats" mirrors the list_chats title filter (custom_web.py:50
# ``if (title && title.length > 0)``) which decides real exportability.
# A product-filter provider has links in DOM (raw chats > 0) but every
# title empty, so the raw counter alone can never trigger Blocked.
_TITLED_COUNT_JS = """(sel) => {
    let n = 0;
    try {
        document.querySelectorAll(sel).forEach(el => {
            if ((el.textContent || '').trim()) n++;
        });
    } catch (e) {}
    return n;
}"""

_MSG_COUNT_JS = """(sel) => {
    try { return sel ? document.querySelectorAll(sel).length : 0; }
    catch (e) { return 0; }
}"""

# B-A'(a): text of the active sidebar element. Fallback confirmation for
# click/no-href targets when document.title carries no chat text (brand
# title). Strictly the three DOM signals below — no further heuristics.
_ACTIVE_TEXT_JS = """(arg) => {
    const sels = (arg && arg.sels) || [];
    const scope_of = (root) => {
        for (const s of sels) {
            try {
                const el = root.querySelector(s);
                if (el && (el.textContent || '').trim()) return el;
            } catch (e) {}
        }
        return null;
    };
    try {
        if (arg && arg.chatSel) {
            const scope = document.querySelector(arg.chatSel);
            if (scope) {
                const hit = scope_of(scope);
                if (hit) return ((hit.textContent || '').trim()).slice(0, 200);
            }
        }
        const hit = scope_of(document);
        if (hit) return ((hit.textContent || '').trim()).slice(0, 200);
    } catch (e) {}
    return '';
}"""

_ACTIVE_SIGNALS = ('[aria-current="page"]', ".active", '[aria-selected="true"]')


def _page_identity(page) -> tuple:
    """(url, title) snapshot, never raises. Used to verify a switch."""
    try:
        url = page.url or ""
    except Exception:
        url = ""
    try:
        title = page.title() or ""
    except Exception:
        title = ""
    return url, title


def _identity_verified(target: dict, href: str, pre: tuple, post: tuple,
                       pre_messages: int, post_messages: int,
                       active_text: str = "") -> str:
    """Did the open land on the TARGET chat (binding check)?

    Graded outcome (B-B): "verified" (target proven), "shifted" (a switch
    happened but this target is unconfirmed), "stale" (no switch at all).
    href targets navigated to (or already on) their URL are verified by
    navigation itself. Click-opened (no-href) targets must show a switch
    (changed URL, title, or message count) AND, when the snapshot text is
    non-empty, that text in the post-open page title (B-A) or, as a
    fallback, in the active sidebar element (B-A'(a) for brand titles):
    a mere shift proves *a* switch, not *the* target chat (index drift
    after a sidebar re-render); text alone proves nothing on a stale
    page. Empty snapshot text falls back to the shift check. Without
    proof the evidence belongs to the previous page (stale) or the same
    chat — attributing it to the target would fake a Compatible.
    """
    if href.startswith("http") and (post[0] == href or pre[0] == href):
        return "verified"
    shifted = (post[0] != pre[0] or post[1] != pre[1]
               or post_messages != pre_messages)
    if not shifted:
        return "stale"
    if not href.startswith("http"):
        want = (target.get("text", "") or "").strip().lower()
        if want:
            if want in (post[1] or "").strip().lower():
                return "verified"
            return ("verified"
                    if want in (active_text or "").strip().lower()
                    else "shifted")
    return "verified"


def _candidate_web_config(candidate: dict, catalog) -> tuple:
    """Resolve candidate -> (web_cfg, preset_id). Reuse looks up the catalog."""
    catalog = catalog if isinstance(catalog, list) else []
    if not isinstance(candidate, dict):
        return None, ""
    if candidate.get("kind") == "reuse":
        pid = str(candidate.get("preset_id", "") or "")
        preset = next((p for p in catalog
                       if isinstance(p, dict) and p.get("id") == pid), None)
        if preset is None:
            return None, pid
    else:
        preset = candidate.get("preset") or {}
        pid = str(preset.get("id", "") or "selector-new")
    try:
        strategy = preset.get("strategy", {})
        sels = strategy.get("selectors", {})
        web_cfg = {
            "chat_list_selector": sels.get("chat_list_selector", "") or "",
            "title_selector": sels.get("title_selector", "") or "",
            "message_selector": sels.get("message_selector", "") or "",
            "user_message_selector": sels.get("user_message_selector", "") or "",
            "assistant_message_selector": sels.get("assistant_message_selector", "") or "",
            "scroll_container_selector": sels.get("scroll_container_selector", "") or "",
            "wait_after_click_ms": strategy.get("wait_after_click_ms") or 2000,
        }
    except Exception:
        return None, pid
    return web_cfg, pid


def _candidate_navigation(candidate: dict, catalog) -> str:
    """Navigation for the candidate ("goto" default). Reuse reads the catalog."""
    preset = candidate.get("preset") if candidate.get("kind") != "reuse" else None
    if preset is None and candidate.get("kind") == "reuse":
        pid = str(candidate.get("preset_id", "") or "")
        preset = next((p for p in (catalog or [])
                       if isinstance(p, dict) and p.get("id") == pid), None)
    if isinstance(preset, dict):
        return preset.get("strategy", {}).get("navigation", "") or "goto"
    return "goto"


def _normalize_targets(chat_targets: list, n_chats=None) -> list:
    """Accept v2 target dicts (and legacy bare URL strings)."""
    limit = max(MIN_CHATS, int(n_chats or DEFAULT_CHATS))
    out = []
    for pos, entry in enumerate(list(chat_targets or [])[:limit]):
        if isinstance(entry, dict) and entry.get("token"):
            out.append({
                "token": str(entry.get("token") or ""),
                "href": str(entry.get("href", "") or ""),
                "index": int(entry.get("index", pos) or 0),
                "selector": str(entry.get("selector", "") or ""),
                "text": str(entry.get("text", "") or ""),
            })
        elif isinstance(entry, str) and entry:
            out.append({"token": entry, "href": entry, "index": pos,
                        "selector": "", "text": ""})
    return out


def _resolve_target(items: list, target: dict):
    """Resolve a frozen target to a live list item (N5).

    The queue order comes from the frozen snapshot, never from a re-scan.
    When the target carries an http href, the href match wins: the frozen
    index belongs to the snapshot's selector list, which a reuse candidate
    with a different chat_list_selector does not share. Pure button
    targets (no href) still resolve by stable index.
    """
    if not items or not isinstance(target, dict):
        return None
    href = target.get("href", "") or ""
    if href.startswith("http"):
        for item in items:
            if isinstance(item, dict) and item.get("url") == href:
                return item
    idx = target.get("index", 0)
    try:
        idx = int(idx)
    except Exception:
        idx = 0
    if 0 <= idx < len(items) and isinstance(items[idx], dict):
        return items[idx]
    return None


def validate_candidate(page, candidate: dict, chat_targets: list, catalog,
                       default_url: str = "", log=None, n_chats=None,
                       blocked_reason: str = "", blocked_evidence=None) -> dict:
    """Validate ONE candidate on up to N frozen targets. Returns report dict."""
    _log = log or (lambda msg: None)
    chats = _normalize_targets(chat_targets, n_chats)
    web_cfg, preset_id = _candidate_web_config(candidate, catalog)
    candidate_id = preset_id or candidate.get("kind", "?")

    if web_cfg is None:
        per_chat = []
        for target in chats:
            per_chat.append({"chat_url": target.get("token", ""),
                             "target": target, "verdict": "Incompatible",
                             "reason": "format_invalid",
                             "evidence": {"chats": 0, "messages": 0}})
        return {"candidate_id": candidate_id, "per_chat": per_chat,
                "summary": verdicts.aggregate_report(per_chat)}

    from adapters.custom_web import CustomWebAdapter

    try:
        adapter = CustomWebAdapter(page, web_cfg, _log,
                                   navigation=_candidate_navigation(candidate, catalog))
    except Exception:
        adapter = None

    per_chat = []
    # One scan per candidate (L2): resolve frozen targets by stable index.
    items: list = []
    if adapter is not None:
        try:
            items = adapter.list_chats() or []
        except Exception:
            items = []

    for target in chats:
        token = target.get("token", "")
        href = target.get("href", "") or ""
        evidence = {"chats": 0, "messages": 0, "user": 0, "assistant": 0}
        try:
            pre_url, pre_title = _page_identity(page)
            try:
                pre_messages = int(page.evaluate(
                    _MSG_COUNT_JS,
                    web_cfg.get("message_selector", "")) or 0)
            except Exception:
                pre_messages = 0
            opened = False
            if adapter is not None:
                live = _resolve_target(items, target)
                if live is not None:
                    opened = bool(adapter.open_chat(live))
            if not opened and href.startswith("http"):
                try:
                    page.goto(href, wait_until="domcontentloaded", timeout=15000)
                    opened = True
                except Exception:
                    opened = False
            if not opened:
                per_chat.append({"chat_url": token, "target": target,
                                 "verdict": "Incompatible",
                                 "reason": "timeout", "evidence": evidence})
                continue
            try:
                counts = page.evaluate(_DIAG_COUNTS_JS, {
                    "chatSel": web_cfg.get("chat_list_selector", ""),
                    "msgSel": web_cfg.get("message_selector", ""),
                    "userSel": web_cfg.get("user_message_selector", ""),
                    "asstSel": web_cfg.get("assistant_message_selector", ""),
                }) or {}
            except Exception:
                counts = {}
            try:
                titled = page.evaluate(
                    _TITLED_COUNT_JS,
                    web_cfg.get("chat_list_selector", ""))
                titled = int(titled or 0)
            except Exception:
                titled = 0
            try:
                page_url = page.url or ""
            except Exception:
                page_url = ""
            evidence = {
                "chats": int(counts.get("chats", 0) or 0),
                "titled_chats": titled,
                "messages": int(counts.get("messages", 0) or 0),
                "user": int(counts.get("user", 0) or 0),
                "assistant": int(counts.get("assistant", 0) or 0),
            }
            post_url, post_title = _page_identity(page)
            try:
                active_text = page.evaluate(_ACTIVE_TEXT_JS, {
                    "chatSel": web_cfg.get("chat_list_selector", ""),
                    "sels": list(_ACTIVE_SIGNALS),
                }) or ""
            except Exception:
                active_text = ""
            identity = _identity_verified(
                target, href, (pre_url, pre_title),
                (post_url, post_title),
                pre_messages, evidence["messages"],
                active_text if isinstance(active_text, str) else "")
            if identity == "stale":
                per_chat.append({"chat_url": token, "target": target,
                                 "verdict": "Incompatible",
                                 "reason": "wrong_target",
                                 "evidence": evidence})
                continue
            if identity == "shifted":
                per_chat.append({"chat_url": token, "target": target,
                                 "verdict": "Partial",
                                 "reason": "wrong_target",
                                 "evidence": evidence})
                continue
            if blocked_reason and titled <= 0:
                evidence["empty_title"] = blocked_evidence or {}
                per_chat.append({"chat_url": token, "target": target,
                                 "verdict": "Blocked",
                                 "reason": blocked_reason, "evidence": evidence})
                continue
            verdict, reason = verdicts.per_chat_verdict(
                evidence["chats"], evidence["messages"], evidence["user"],
                evidence["assistant"], page_url, default_url or "")
            per_chat.append({"chat_url": token, "target": target,
                             "verdict": verdict,
                             "reason": reason, "evidence": evidence})
        except Exception as e:
            _log(f"[profiler] validate error: {e}")
            per_chat.append({"chat_url": token, "target": target,
                             "verdict": "Incompatible",
                             "reason": "timeout", "evidence": evidence})
    return {"candidate_id": candidate_id, "per_chat": per_chat,
            "summary": verdicts.aggregate_report(per_chat)}
