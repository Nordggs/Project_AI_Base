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
- Empty/deleted threads render the home screen ("What do you want to know").
- ``goto()`` on a deep link hydrates fine (== click-FSM) → goto is primary.
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
    document.querySelectorAll('div.prose').forEach(el => items.push({el, role: 'assistant'}));
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
    return {messages, citations: cites, title: document.title || ''};
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
    if citations:
        for m in reversed(messages):
            if m["role"] == "assistant":
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
