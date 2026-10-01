"""Pure probe specifications (TICKET-002-L, Phase 2). No Playwright, no page.

Generalizes PoC constants without copying harness logic one-to-one.
Order anchor -> button is mandatory (Z.ai lesson).
"""

ANCHOR_CHAT_LIST_SLS = [
    "a[href*='/c/']",
    "a[href*='/chat/']",
    "a[href*='/app/']",
    "a[href*='/s/']",
    "a[href*='/search/']",
    '[class*="history"] a',
    "nav a",
    "aside a",
    "a[href]",
]

BUTTON_CHAT_LIST_SLS = [
    "nav button",
    "aside button",
    '[role="button"]',
    '[class*="history"] button',
    "li button",
]

MSG_PROBE_SELS = [
    ".message-bubble",
    ".response-content-markdown",
    '[class*="message"]',
    '[class*="chat-message"]',
    '[class*="user"]',
    '[class*="assistant"]',
    "article",
    "main div",
]

USERSCRIPT_MESSAGE_SEL = '[class*="message"], [class*="chat-message"]'
USERSCRIPT_USER_SEL = '[class*="user"]'
USERSCRIPT_ASST_SEL = '[class*="assistant"], [class*="ai"]'

# Role separation candidates (Phase 2.4): verified triples first, then generic.
ROLE_USER_CANDIDATES = [
    ".message-bubble",
    '[data-role="user"]',
    '[class*="user"]',
    '[class*="question"]',
]
ROLE_ASST_CANDIDATES = [
    ".response-content-markdown",
    '[data-role="assistant"]',
    '[class*="assistant"]',
    '[class*="answer"]',
    '[class*="ai"]',
]

# Child selectors whose *text content* can back a title_selector readable by
# list_chats (custom_web.py:41-45). Attribute-only titles are not usable.
TITLE_CHILD_SELECTORS = ("[title]", "[aria-label]", "[data-title]")

# Scroll containers, in priority order (Phase 2.5).
SCROLL_CONTAINER_CANDIDATES = (
    '[class*="history"]',
    '[class*="conversation"]',
    '[class*="scroll"]',
    "aside",
    "main",
)

# Message presence check for wait_for_function after click / goto (Phase 2.1).
# Deliberately excludes the ultra-broad "main div" miner: it matches chrome
# text on any page and would fake a successful open.
MESSAGE_WAIT_SELECTORS = [
    ".message-bubble",
    ".response-content-markdown",
    '[class*="message"]',
    '[class*="chat-message"]',
    '[data-role="user"]',
    '[data-role="assistant"]',
    '[class*="user"]',
    '[class*="assistant"]',
    "article",
]

MIN_TEXTY_LEN = 20


def chat_list_probe_order() -> list:
    """Mandatory order: anchors first, then buttons."""
    return list(ANCHOR_CHAT_LIST_SLS) + list(BUTTON_CHAT_LIST_SLS)


def message_probe_selectors() -> list:
    return list(MSG_PROBE_SELS)


def role_user_candidates() -> list:
    return list(ROLE_USER_CANDIDATES)


def role_assistant_candidates() -> list:
    return list(ROLE_ASST_CANDIDATES)


def map_profile_navigation_to_strategy(nav_type: str, goto_empty: bool) -> str:
    """Map Profile-level navigation (goto|click|both) to preset strategy (goto|click).

    Rule (Phase 0/3): 'both' lives only in Profile; a candidate must carry
    strict NAVIGATION_TYPES. both -> click when goto SPA-emptiness is proven,
    else goto. Unknown values fall back to goto (same as _normalize_navigation).
    """
    if nav_type == "click":
        return "click"
    if nav_type == "both":
        return "click" if goto_empty else "goto"
    return "goto"
