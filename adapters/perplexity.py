"""Perplexity adapter (TICKET-004).

Strategy (verified on live DOM, Iteration 1):
- list: sidebar scan ``a[href^="/search/"]`` + ``aria-label`` titles
  (the ``<a>`` has empty content — title MUST come from ``aria-label``).
- open: ``goto()`` on the deep link (hydrates fine on Perplexity, unlike
  Gemini/Qwen); click-FSM on the landing sidebar as fallback. After opening,
  ``_climb_history()`` wheels up with trusted input until the turn signature
  stabilizes (fresh renders contain the latest turn only — server-side window).
- extract: single-pass DOM via :mod:`exporters.perplexity_extract`
  (selectors proven; no scroll engine — history arrives via climb-triggered
  fetch, then sits fully rendered in DOM).
- empty/deleted threads render the home screen → honest ``False``/``None``.
"""

import time

from adapters.base import BaseAdapter
from conversation.irbuilder import IRBuilder, Provider
from conversation.models import ConversationModel
from exporters.perplexity_extract import (
    PERPLEXITY_CONTAINER_RECT_JS,
    PERPLEXITY_LIST_JS,
    PERPLEXITY_TURNS_FP_JS,
    PERPLEXITY_WAIT_TURNS_JS,
    fp_key,
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

    def _turns_fp(self):
        """Current history signature dict or None on evaluate failure."""
        try:
            fp = self.page.evaluate(PERPLEXITY_TURNS_FP_JS)
            return fp if isinstance(fp, dict) else None
        except Exception:
            return None

    def _climb_history(self, budget_s=25, interval_ms=2000, need_stable=3,
                       wheel_px=-2000, top_eps=5) -> None:
        """Wheel up until the turn signature stabilizes (Phase 0 mechanism).

        Fresh renders contain the latest turn only; older turns are fetched when
        the user climbs up with trusted wheel events (Phase 0h/0i: a single big
        wheel crossing the sentinel triggers the fetch; passive waiting,
        programmatic scrollTop, focus, reload, re-click all inert).
        Polls ``fp_key()`` after each step; stops at top + ``need_stable``
        identical signatures, or when ``budget_s`` expires (honest partial —
        caller still extracts). The mouse MUST be positioned over the scroll
        container first (unpositioned wheel is a silent no-op).
        Research-step cards are excluded at extraction (see EXTRACT_JS).
        """
        try:
            rect = self.page.evaluate(PERPLEXITY_CONTAINER_RECT_JS)
        except Exception as e:
            self.log(f"[PERPLEXITY] climb: container rect failed: {e}")
            rect = None
        if isinstance(rect, dict) and rect.get("cx", -1) >= 0 and rect.get("cy", -1) >= 0:
            try:
                self.page.mouse.move(rect["cx"], rect["cy"])
            except Exception as e:
                self.log(f"[PERPLEXITY] climb: mouse.move failed: {e}")
        else:
            self.log("[PERPLEXITY] climb: no container rect, wheel may no-op")

        stable, last_key = 0, object()
        deadline = time.monotonic() + budget_s
        while True:
            if self.cancel_check and self.cancel_check():
                self.log("[PERPLEXITY] climb: cancelled")
                break
            fp = self._turns_fp()
            key = fp_key(fp)
            if key is not None and key == last_key:
                stable += 1
            elif key is not None:
                stable, last_key = 1, key
            else:
                stable = 0
            top = fp.get("top", -1) if isinstance(fp, dict) else -1
            if stable >= need_stable and top is not None and top <= top_eps:
                self.log(f"[PERPLEXITY] climb: stable x{stable} at top (nb={fp.get('nb')}, np={fp.get('np')})")
                break
            if time.monotonic() >= deadline:
                self.log(f"[PERPLEXITY] climb: budget {budget_s}s exhausted "
                         f"(stable={stable}, top={top})")
                break
            try:
                self.page.mouse.wheel(0, wheel_px)
            except Exception as e:
                self.log(f"[PERPLEXITY] climb: wheel failed: {e}")
                break
            self.page.wait_for_timeout(interval_ms)

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
                    self._climb_history()
                    return has_turns(self.page)
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
        if self._wait_turns():
            self._climb_history()
        return has_turns(self.page)

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
