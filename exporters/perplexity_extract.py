"""Perplexity DOM extraction (TICKET-004).

Findings (Iteration 1, verified on live DOM, 19 chats):
- Sidebar links: ``a[href^="/search/"]`` inside ``nav``. The ``<a>`` itself has
  EMPTY content (``<span></span>``) but carries the thread title in its
  ``aria-label``; a visible label ``div`` sits in the same row.
- Thread page (``/search/<uuid>``) renders the FULL history at once — no
  lazy-load on scroll-up, no scroll engine needed.
- User turns: ``div`` whose class contains ``group/user-bubble`` (note: the
  ``/`` makes it unusable in ``querySelectorAll`` — filter by ``className``).
  Text is prefixed with a ``HH:MM`` timestamp, no date, no ``<time>`` elements.
- Assistant turns: ``div.prose`` (markdown: ``pre``/``code``/``table`` inside).
  One answer may be split across 2-3 consecutive ``.prose`` blocks — merged.
- Sources: ``.citation`` elements (domain + counter). Collected into meta and
  appended to the last assistant message as ``[sources: ...]``.
- Related questions: ``label.relative.cursor-pointer`` (engine chips like
  "Computer" are filtered out). Appended to the last assistant message as a
  ``Related:`` block (paste order: answer → related → sources).
- ``goto()`` on a deep link hydrates fine (== click-FSM) → goto is primary.
- History loading: a fresh render contains the LATEST turn only (server-side
  window — old answers are absent even from raw HTML). Older turns are fetched
  when the user climbs up with trusted wheel events (Phase 0: 8x wheel(0,-300)
  triggered the fetch; passive waiting, programmatic scrollTop, focus, reload,
  re-click all inert; mouse.wheel without positioning the mouse is a no-op).
  See ``PerplexityAdapter._climb_history``.
"""

import re

PERPLEXITY_LIST_JS = """
() => [...document.querySelectorAll('a')]
    .filter(a => (a.getAttribute('href') || '').startsWith('/search/'))
    .map((a, i) => {
        const href = a.getAttribute('href') || '';
        const uuid = (href.match(/\\/search\\/([0-9a-f-]{36})/) || [])[1] || '';
        let title = (a.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ');
        if (!title) {
            const row = a.closest('div[class*="sidebar-session"], div[class*="group"]');
            title = row ? (row.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 200) : '';
        }
        return {id: uuid, title: title.slice(0, 200), url: href, _index: i};
    })
"""

PERPLEXITY_WAIT_TURNS_JS = """
() => document.querySelectorAll('div.prose').length > 0 ||
    [...document.querySelectorAll('[class*="user-bubble"]')].some(
        e => typeof e.className === 'string' && e.className.includes('group/user-bubble'))
"""

PERPLEXITY_HOME_JS = """
() => {
    const t = (document.body.innerText || '').slice(0, 200);
    return t.includes('Что вы хотите узнать?') || t.includes('What do you want to know');
}
"""

PERPLEXITY_EXTRACT_JS = """
() => {
    const items = [];
    document.querySelectorAll('[class*="user-bubble"]').forEach(el => {
        if (typeof el.className === 'string' && el.className.includes('group/user-bubble'))
            items.push({el, role: 'user'});
    });
    // Skip research-step cards (transient collapsible UI, not part of the
    // pasted/visible answer; final answers live under group/final-text).
    document.querySelectorAll('div.prose').forEach(el => {
        if (el.closest('[class*="step"]')) return;
        items.push({el, role: 'assistant'});
    });
    items.sort((a, b) => {
        const pos = a.el.compareDocumentPosition(b.el);
        if (pos & Node.DOCUMENT_POSITION_FOLLOWING) return -1;
        if (pos & Node.DOCUMENT_POSITION_PRECEDING) return 1;
        return 0;
    });
    const seen = new Set();
    const messages = [];
    for (const {el, role} of items) {
        const text = (el.innerText || '').trim();
        if (!text) continue;
        const key = role + '|' + text.slice(0, 300);
        if (seen.has(key)) continue;
        seen.add(key);
        let content = text, time = null;
        if (role === 'user') {
            const m = text.match(/^(\\d{1,2}:\\d{2})\\s+[\\s\\S]*$/);
            if (m) { time = m[1]; content = text.slice(m[1].length).trim(); }
        }
        if (content) messages.push({role, content, timestamp: time});
    }
    const cites = [...new Set([...document.querySelectorAll('.citation')]
        .map(e => (e.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 60))
        .filter(Boolean))].slice(0, 30);
    const related = [...new Set([...document.querySelectorAll('label.relative.cursor-pointer')]
        .map(e => (e.innerText || '').trim().replace(/\\s+/g, ' '))
        .filter(t => t && t !== 'Computer'))].slice(0, 12);
    return {messages, citations: cites, related, title: document.title || ''};
}
"""

PERPLEXITY_TURNS_FP_JS = """
() => {
    const c = document.querySelector('.scrollable-container');
    const bubbles = [...document.querySelectorAll('[class*="user-bubble"]')]
        .filter(e => typeof e.className === 'string' && e.className.includes('group/user-bubble'))
        .map(e => (e.innerText || '').trim().replace(/\\s+/g, ' '));
    const prose = [...document.querySelectorAll('div.prose')]
        .map(e => (e.innerText || '').trim().replace(/\\s+/g, ' '));
    return {
        nb: bubbles.length, np: prose.length,
        b0: (bubbles[0] || '').slice(0, 80),
        blast: (bubbles[bubbles.length - 1] || '').slice(0, 80),
        plast: (prose[prose.length - 1] || '').slice(0, 80),
        top: c ? Math.round(c.scrollTop) : -1,
        sh: c ? c.scrollHeight : -1,
    };
}
"""

PERPLEXITY_CONTAINER_RECT_JS = """
() => {
    const c = document.querySelector('.scrollable-container');
    if (!c) return null;
    const r = c.getBoundingClientRect();
    return {cx: Math.round(r.x + r.width / 2), cy: Math.round(r.y + 200)};
}
"""

_UUID_RE = re.compile(r"^[0-9a-f-]{36}$")

_HOME_MARKERS = ("Что вы хотите узнать?", "What do you want to know")


def parse_sidebar_items(raw) -> list[dict]:
    """Validate + normalize raw LIST_JS output.

    Drops entries without a real uuid ``id`` (never an index-based id —
    ``perplexity-0`` style ids would become false Stable IDs downstream).
    """
    out = []
    seen = set()
    for it in raw or []:
        if not isinstance(it, dict):
            continue
        cid = str(it.get("id") or "")
        if not _UUID_RE.fullmatch(cid) or cid in seen:
            continue
        seen.add(cid)
        out.append({
            "id": cid,
            "title": str(it.get("title") or "")[:200],
            "url": str(it.get("url") or ""),
            "_index": it.get("_index", len(out)),
        })
    return out


def merge_same_role(messages) -> list[dict]:
    """Merge consecutive same-role messages (split ``.prose`` answers).

    Keeps the first message's timestamp. Order is preserved.
    """
    merged = []
    for m in messages or []:
        content = str(m.get("content") or "").strip()
        if not content:
            continue
        if merged and merged[-1]["role"] == m.get("role", "assistant"):
            merged[-1]["content"] += "\n\n" + content
        else:
            merged.append({
                "role": m.get("role", "assistant"),
                "content": content,
                **({"timestamp": m["timestamp"]} if m.get("timestamp") else {}),
            })
    return merged


def fp_key(fp) -> tuple | None:
    """History-stability signature: ``(nb, np, head_first, head_last)``.

    Used by the climb loop: identical keys across polls mean no new turns
    arrived. Returns None for garbage input (counts as unstable).
    """
    if not isinstance(fp, dict):
        return None
    try:
        return (int(fp.get("nb", -1)), int(fp.get("np", -1)),
                str(fp.get("b0") or "")[:80], str(fp.get("plast") or "")[:80])
    except (TypeError, ValueError):
        return None


def is_home_screen(page) -> bool:
    """True when the page shows the Perplexity home (empty/deleted thread)."""
    try:
        return bool(page.evaluate(PERPLEXITY_HOME_JS))
    except Exception:
        return False


def has_turns(page) -> bool:
    """True when at least one user bubble or assistant block is rendered."""
    try:
        return bool(page.evaluate(PERPLEXITY_WAIT_TURNS_JS))
    except Exception:
        return False


def extract_perplexity_dom(page, url, log_progress=None, cancel_check=None) -> dict | None:
    """Single-pass DOM extraction (no scrolling — history is fully rendered).

    Returns a raw dict compatible with ``IRBuilder._from_generic("perplexity")``
    or None when nothing extractable (caller treats it as honest "no data").
    """
    if cancel_check and cancel_check():
        return None
    page.wait_for_timeout(2500)
    try:
        data = page.evaluate(PERPLEXITY_EXTRACT_JS)
    except Exception as e:
        if log_progress:
            log_progress(f"[PERPLEXITY] evaluate failed: {e}")
        return None
    if not isinstance(data, dict):
        return None

    messages = merge_same_role(data.get("messages", []))
    if not messages:
        return None

    citations = [c for c in (data.get("citations") or []) if c]
    related = [r for r in (data.get("related") or []) if r]
    if citations or related:
        for m in reversed(messages):
            if m["role"] == "assistant":
                if related:
                    m["content"] += "\n\nRelated:\n" + "\n".join(f"- {r}" for r in related)
                if citations:
                    m["content"] += "\n\n[sources: " + ", ".join(citations[:15]) + "]"
                break

    chat_id = ""
    m = re.search(r"/search/([0-9a-f-]{36})", url or "")
    if m:
        chat_id = m.group(1)

    title = (data.get("title") or "").strip()
    if title == "Perplexity":
        title = ""
    return {
        "schema_version": 1,
        "source": "perplexity",
        "chat_id": chat_id,
        "title": title or "Perplexity Chat",
        "source_url": url,
        "messages": [
            {"role": m["role"], "content": m["content"],
             **({"timestamp": m["timestamp"]} if m.get("timestamp") else {})}
            for m in messages
        ],
    }
