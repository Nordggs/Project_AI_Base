"""Perplexity adapter (TICKET-004).

Strategy (verified on live DOM, Iteration 1):
- list: sidebar scan ``a[href^="/search/"]`` + ``aria-label`` titles
  (the ``<a>`` has empty content — title MUST come from ``aria-label``).
- open: ``goto()`` on the deep link (hydrates fine on Perplexity, unlike
  Gemini/Qwen); click-FSM on the landing sidebar as fallback.
- extract: single-pass DOM via :mod:`exporters.perplexity_extract`
  (no scroll engine — full history renders at once).
- empty/deleted threads render the home screen → honest ``False``/``None``.
"""

from adapters.base import BaseAdapter
from conversation.irbuilder import IRBuilder, Provider
from conversation.models import ConversationModel
from exporters.perplexity_extract import (
    PERPLEXITY_LIST_JS,
    PERPLEXITY_WAIT_TURNS_JS,
    has_turns,
    is_home_screen,
    parse_sidebar_items,
    extract_perplexity_dom,
)

PERPLEXITY_HOME_URL = "https://www.perplexity.ai/"

PERPLEXITY_CLICK_JS = """
(idx) => {
    const els = [...document.querySelectorAll('a')]
        .filter(a => (a.getAttribute('href') || '').startsWith('/search/'));
    if (els[idx]) { els[idx].click(); return true; }
    return false;
}
"""


class PerplexityAdapter(BaseAdapter):
    name = "perplexity"

    def __init__(self, page, cdp_lock, log_func, cancel_check):
        self.page = page
        self.cdp_lock = cdp_lock
        self.log = log_func
        self.cancel_check = cancel_check

    def healthcheck(self) -> bool:
        try:
            self.page.url
            return True
        except Exception:
            return False

    def list_chats(self) -> list[dict]:
        with self.cdp_lock:
            try:
                self.page.goto(PERPLEXITY_HOME_URL,
                               wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass
            self.page.wait_for_timeout(4000)
            items = parse_sidebar_items(self.page.evaluate(PERPLEXITY_LIST_JS))
            if not items:
                self.page.wait_for_timeout(4000)
                try:
                    items = parse_sidebar_items(self.page.evaluate(PERPLEXITY_LIST_JS))
                except Exception:
                    items = []
        s = self._snapshot_sidebar_state('a[href^="/search/"]')
        self._log_sidebar_snapshot("list_chats end", s, provider="PERPLEXITY")
        return items

    def _wait_turns(self, timeout=12000) -> bool:
        try:
            self.page.wait_for_function(PERPLEXITY_WAIT_TURNS_JS, timeout=timeout)
            return True
        except Exception:
            try:
                return has_turns(self.page)
            except Exception:
                return False

    def open_chat(self, chat: dict) -> bool:
        url = chat.get("url", "")
        if url:
            if url.startswith("/"):
                url = "https://www.perplexity.ai" + url
            if url.startswith("http"):
                with self.cdp_lock:
                    try:
                        self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    except Exception as e:
                        self.log(f"[PERPLEXITY] open_chat goto error: {e}")
                    self.page.wait_for_timeout(2500)
                if self._wait_turns():
                    return True
                try:
                    if is_home_screen(self.page):
                        self.log("[PERPLEXITY] open_chat: home screen (empty thread)")
                        return False
                except Exception:
                    pass
                # goto succeeded but no turns and not home — fall through to click-FSM
        index = chat.get("_index")
        if index is None:
            return False
        with self.cdp_lock:
            try:
                self.page.goto(PERPLEXITY_HOME_URL,
                               wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass
            self.page.wait_for_timeout(3000)
            try:
                clicked = self.page.evaluate(PERPLEXITY_CLICK_JS, index)
            except Exception as e:
                self.log(f"[PERPLEXITY] open_chat click error: {e}")
                return False
            if not clicked:
                return False
            try:
                self.page.wait_for_function(
                    "() => location.href.includes('/search/')", timeout=15000)
            except Exception as e:
                self.log(f"[PERPLEXITY] open_chat click wait error: {e}")
                return False
            self.page.wait_for_timeout(2500)
        return self._wait_turns()

    def extract_chat(self, chat: dict) -> ConversationModel | None:
        url = self.page.url
        data = extract_perplexity_dom(
            self.page, url,
            log_progress=self.log,
            cancel_check=self.cancel_check,
        )
        if not data or not data.get("messages"):
            return None
        if not data.get("title") or data["title"] in ("", "Perplexity Chat"):
            fallback = (chat.get("title") or "").strip()
            if fallback:
                data["title"] = fallback

        model = IRBuilder.build(Provider.PERPLEXITY, data)
        model.metadata["provider"] = "perplexity"
        model.metadata["source"] = "dom"
        return model
