"""Custom Web Chat adapter — universal browser exporter for any chat service.

Uses CSS selectors or user-provided JS to list chats, open them, and extract
messages from any web-based chat interface.
"""

from typing import Optional

from adapters.base import BaseAdapter
from conversation.models import ConversationModel, Message


def _normalize_navigation(value) -> str:
    """Navigation mode for open_chat. Unknown values fall back to "goto"."""
    return value if value in ("goto", "click") else "goto"


class SelectorStrategy:
    """CSS selector-based strategy for chat extraction."""

    def __init__(self, page, config, log_func=None, navigation="goto"):
        self.page = page
        self.config = dict(config or {})
        self.log = log_func or (lambda msg: None)
        self._navigation = _normalize_navigation(navigation)

    def list_chats(self) -> list[dict]:
        container_sel = self.config.get("scroll_container_selector", "")
        chat_list_sel = self.config.get("chat_list_selector", "")
        if not chat_list_sel:
            return []
        if container_sel:
            self._scroll_to_load(container_sel, chat_list_sel)
        title_sel = self.config.get("title_selector", "")
        js = """
        (arg) => {
            const {listSel, titleSel} = arg;
            const items = [];
            document.querySelectorAll(listSel).forEach((el, i) => {
                let title = '';
                if (titleSel) {
                    const t = el.querySelector(titleSel);
                    title = t ? (t.textContent || '').trim() : '';
                }
                if (!title) title = (el.textContent || '').trim();
                let href = el.getAttribute('href') || '';
                if (href && !href.startsWith('http')) {
                    try { href = new URL(href, location.href).href; } catch(e) {}
                }
                if (title && title.length > 0) {
                    items.push({
                        id: 'custom-' + i,
                        title: title.substring(0, 200),
                        url: href,
                        _index: i,
                    });
                }
            });
            return items;
        }"""
        try:
            result = self.page.evaluate(js, {"listSel": chat_list_sel, "titleSel": title_sel})
        except Exception as e:
            self.log(f"[CUSTOM] list_chats evaluate error: {e}")
            return []
        return result if isinstance(result, list) else []

    def _open_by_click(self, chat: dict) -> bool:
        """Click-FSM for SPA without deep-link hydration (Qwen-minimum).

        Clicks the sidebar item by _index, waits for messages to appear,
        then applies wait_after_click_ms. Honest False on timeout.
        """
        index = chat.get("_index")
        chat_list_sel = self.config.get("chat_list_selector", "")
        if index is None or not chat_list_sel:
            return False
        try:
            js = """(arg) => {
                const {sel, idx} = arg;
                const els = document.querySelectorAll(sel);
                if (els[idx]) { els[idx].click(); return true; }
                return false;
            }"""
            clicked = self.page.evaluate(js, {"sel": chat_list_sel, "idx": index})
            if not clicked:
                return False
            msg_sel = self.config.get("message_selector", "")
            if msg_sel:
                try:
                    # NOTE: arg is keyword-only in this Playwright version.
                    self.page.wait_for_function(
                        "(sel) => document.querySelectorAll(sel).length > 0",
                        arg=msg_sel,
                        timeout=10000,
                    )
                except Exception as e:
                    self.log(f"[CUSTOM] open_chat click wait error: {e}")
                    return False
            wait_ms = self.config.get("wait_after_click_ms", 2000)
            self.page.wait_for_timeout(wait_ms)
            return True
        except Exception as e:
            self.log(f"[CUSTOM] open_chat click error: {e}")
            return False

    def open_chat(self, chat: dict) -> bool:
        # TICKET-002-D: click-first navigation for SPA without hydration.
        if self._navigation == "click":
            return self._open_by_click(chat)
        url = chat.get("url", "")
        if url:
            if not url.startswith("http"):
                try:
                    url = self.page.evaluate(
                        "(href) => new URL(href, location.href).href", url
                    )
                except Exception:
                    pass
            if url and url.startswith("http"):
                try:
                    self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    self.page.wait_for_load_state("domcontentloaded")
                    return True
                except Exception as e:
                    self.log(f"[CUSTOM] open_chat goto error: {e}")
                    return False
        index = chat.get("_index")
        chat_list_sel = self.config.get("chat_list_selector", "")
        if index is not None and chat_list_sel:
            try:
                js = """(arg) => {
                    const {sel, idx} = arg;
                    const els = document.querySelectorAll(sel);
                    if (els[idx]) { els[idx].click(); return true; }
                    return false;
                }"""
                self.page.evaluate(js, {"sel": chat_list_sel, "idx": index})
                wait_ms = self.config.get("wait_after_click_ms", 2000)
                self.page.wait_for_timeout(wait_ms)
                return True
            except Exception as e:
                self.log(f"[CUSTOM] open_chat click error: {e}")
                return False
        return False

    def extract_chat(self, chat: dict) -> Optional[ConversationModel]:
        msg_sel = self.config.get("message_selector", "")
        user_sel = self.config.get("user_message_selector", "")
        asst_sel = self.config.get("assistant_message_selector", "")
        if not msg_sel:
            return None
        js = """
        (arg) => {
            const {msgSel, userSel, asstSel} = arg;
            const msgs = [];
            document.querySelectorAll(msgSel).forEach(el => {
                let role = 'assistant';
                if (userSel && el.matches(userSel)) role = 'user';
                else if (asstSel && el.matches(asstSel)) role = 'assistant';
                const clone = el.cloneNode(true);
                clone.querySelectorAll('button, .avatar, .timestamp, svg').forEach(e => e.remove());
                const content = clone.innerText.trim();
                if (content) msgs.push({ role, content });
            });
            return msgs;
        }"""
        try:
            raw_msgs = self.page.evaluate(js, {"msgSel": msg_sel, "userSel": user_sel, "asstSel": asst_sel})
        except Exception as e:
            self.log(f"[CUSTOM] extract_chat evaluate error: {e}")
            return None
        if not raw_msgs or not isinstance(raw_msgs, list):
            return None
        messages = [
            Message(role=m.get("role", "assistant"), content=m.get("content", ""))
            for m in raw_msgs
            if m.get("content")
        ]
        if not messages:
            return None
        title = self.page.title() or "Custom chat"
        return ConversationModel(
            source="custom",
            stable_id=chat.get("id") or chat.get("title") or "unknown",
            title=title,
            source_url=self.page.url,
            messages=messages,
            tree=None,
        )

    def _scroll_to_load(self, container_sel: str, chat_list_sel: str):
        for _ in range(50):
            prev_count = self.page.evaluate(
                "(sel) => document.querySelectorAll(sel).length", chat_list_sel
            )
            self.page.evaluate(
                "(sel) => { const el = document.querySelector(sel); if (el) el.scrollTop += 400; }",
                container_sel,
            )
            self.page.wait_for_timeout(800)
            new_count = self.page.evaluate(
                "(sel) => document.querySelectorAll(sel).length", chat_list_sel
            )
            if new_count == prev_count:
                break


class ScriptStrategy:
    """User-provided JavaScript strategy for chat extraction."""

    def __init__(self, page, config, log_func=None, navigation="goto"):
        self.page = page
        self.config = dict(config or {})
        self.log = log_func or (lambda msg: None)
        self._navigation = _normalize_navigation(navigation)

    def list_chats(self) -> list[dict]:
        js = self.config.get("list_chats_js", "")
        if not js:
            return []
        try:
            result = self.page.evaluate(js)
        except Exception as e:
            self.log(f"[CUSTOM] list_chats_js error: {e}")
            return []
        return result if isinstance(result, list) else []

    def _open_by_selector(self, chat: dict) -> bool:
        """Click path via chat["selector"]. No goto (TICKET-002-D)."""
        selector = chat.get("selector", "")
        if not selector:
            return False
        try:
            self.page.evaluate(
                "(sel) => { const el = document.querySelector(sel); if (el) el.click(); }",
                selector,
            )
            wait_ms = self.config.get("wait_after_click_ms", 2000)
            self.page.wait_for_timeout(wait_ms)
            return True
        except Exception as e:
            self.log(f"[CUSTOM] open_chat click error: {e}")
            return False

    def _open_by_index(self, chat: dict) -> bool:
        """Click path via chat["_index"]. No goto (TICKET-002-D)."""
        index = chat.get("_index")
        if index is None:
            return False
        try:
            js = """(arg) => {
                const {sel, idx} = arg;
                const els = document.querySelectorAll(sel);
                if (els[idx]) { els[idx].click(); return true; }
                return false;
            }"""
            chat_list_sel = self.config.get("chat_list_selector", "")
            if chat_list_sel:
                self.page.evaluate(js, {"sel": chat_list_sel, "idx": index})
                wait_ms = self.config.get("wait_after_click_ms", 2000)
                self.page.wait_for_timeout(wait_ms)
                return True
        except Exception as e:
            self.log(f"[CUSTOM] open_chat index click error: {e}")
            return False
        return False

    def open_chat(self, chat: dict) -> bool:
        # TICKET-002-D: click-first navigation for SPA without hydration.
        if self._navigation == "click":
            if self._open_by_selector(chat):
                return True
            return self._open_by_index(chat)
        url = chat.get("url", "")
        if url:
            if not url.startswith("http"):
                try:
                    url = self.page.evaluate(
                        "(href) => new URL(href, location.href).href", url
                    )
                except Exception:
                    pass
            if url and url.startswith("http"):
                try:
                    self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    self.page.wait_for_load_state("domcontentloaded")
                    return True
                except Exception as e:
                    self.log(f"[CUSTOM] open_chat goto error: {e}")
                    return False
        selector = chat.get("selector", "")
        if selector:
            try:
                self.page.evaluate(
                    "(sel) => { const el = document.querySelector(sel); if (el) el.click(); }",
                    selector,
                )
                wait_ms = self.config.get("wait_after_click_ms", 2000)
                self.page.wait_for_timeout(wait_ms)
                return True
            except Exception as e:
                self.log(f"[CUSTOM] open_chat click error: {e}")
                return False
        index = chat.get("_index")
        if index is not None:
            try:
                js = """(arg) => {
                    const {sel, idx} = arg;
                    const els = document.querySelectorAll(sel);
                    if (els[idx]) { els[idx].click(); return true; }
                    return false;
                }"""
                chat_list_sel = self.config.get("chat_list_selector", "")
                if chat_list_sel:
                    self.page.evaluate(js, {"sel": chat_list_sel, "idx": index})
                    wait_ms = self.config.get("wait_after_click_ms", 2000)
                    self.page.wait_for_timeout(wait_ms)
                    return True
            except Exception as e:
                self.log(f"[CUSTOM] open_chat index click error: {e}")
                return False
        return False

    def extract_chat(self, chat: dict) -> Optional[ConversationModel]:
        js = self.config.get("extract_messages_js", "")
        if not js:
            return None
        try:
            raw_msgs = self.page.evaluate(js)
        except Exception as e:
            self.log(f"[CUSTOM] extract_messages_js error: {e}")
            return None
        if not raw_msgs or not isinstance(raw_msgs, list):
            return None
        messages = [
            Message(role=m.get("role", "assistant"), content=m.get("content", ""))
            for m in raw_msgs
            if m.get("content")
        ]
        if not messages:
            return None
        title = self.page.title() or "Custom chat"
        return ConversationModel(
            source="custom",
            stable_id=chat.get("id") or chat.get("title") or "unknown",
            title=title,
            source_url=self.page.url,
            messages=messages,
            tree=None,
        )


class CustomWebAdapter(BaseAdapter):
    """Universal browser adapter for any web-based chat service."""

    name = "custom_web"

    def __init__(self, page, config, log_func=None, cancel_check=None, navigation="goto"):
        self.page = page
        self.config = dict(config or {})
        self.log = log_func or (lambda msg: None)
        self.cancel_check = cancel_check or (lambda: None)
        self.navigation = _normalize_navigation(navigation)
        self._strategy = self._build_strategy()

    def _build_strategy(self):
        if self.config.get("list_chats_js", "").strip():
            return ScriptStrategy(self.page, self.config, self.log, self.navigation)
        return SelectorStrategy(self.page, self.config, self.log, self.navigation)

    def healthcheck(self) -> bool:
        try:
            self.page.url
            return True
        except Exception:
            return False

    def list_chats(self) -> list[dict]:
        return self._strategy.list_chats()

    def open_chat(self, chat: dict) -> bool:
        return self._strategy.open_chat(chat)

    def extract_chat(self, chat: dict) -> Optional[ConversationModel]:
        return self._strategy.extract_chat(chat)
