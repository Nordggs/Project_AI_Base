"""Pure verdict layer (TICKET-002-L, Phase 4). No page, no Playwright.

Deliberately NOT a literal copy of ``main._diagnose_verdict`` (BUILD fix):
``check_custom_web`` judges ONE current page (diagnostics), while the
profiler validates N chats with per-chat evidence and then aggregates.
Only the verdict *semantics* (thresholds, reason vocabulary) are shared;
the contracts differ, so this module owns its function.

Verdicts: Compatible / Partial / Incompatible / Blocked.
``Blocked`` is only emitted with an explicit reason + evidence
(Perplexity lesson: product-filter, not a silent fallback).
"""

VALID_VERDICTS = ("Compatible", "Partial", "Incompatible", "Blocked")

REASONS = (
    "ok",
    "no_match",
    "wrong_page",
    "wrong_target",
    "timeout",
    "page_dead",
    "format_invalid",
    "product-filter",
)

MAX_UNKNOWN_FRACTION = 0.2


def _domain_of(url: str) -> str:
    try:
        from urllib.parse import urlparse

        host = (urlparse(url or "").hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def per_chat_verdict(chats, messages, user, asst, page_url="", default_url="",
                     blocked_reason: str = "") -> "tuple[str, str]":
    """Verdict for ONE validated chat (pure).

    Same role-threshold semantics as diagnostics: roles_ok requires
    user>0, asst>0 and unknown share <= 20% (min allowance 1). ``blocked_reason``
    forces Blocked (only with explicit reason + caller-side evidence).
    """
    if blocked_reason:
        reason = blocked_reason if blocked_reason in REASONS else "product-filter"
        return "Blocked", reason
    try:
        chats_n = int(chats or 0)
    except Exception:
        chats_n = 0
    try:
        messages_n = int(messages or 0)
        user_n = int(user or 0)
        asst_n = int(asst or 0)
    except Exception:
        return "Partial", "no_match"
    unknown = max(0, messages_n - user_n - asst_n)
    roles_ok = (
        user_n > 0
        and asst_n > 0
        and unknown <= max(1, int(messages_n * MAX_UNKNOWN_FRACTION))
    )
    if chats_n <= 0:
        if default_url and _domain_of(page_url) and _domain_of(page_url) != _domain_of(default_url):
            return "Incompatible", "wrong_page"
        return "Incompatible", "no_match"
    if messages_n <= 0 or not roles_ok:
        return "Partial", "no_match" if messages_n <= 0 else "ok"
    return "Compatible", "ok"


def aggregate_report(per_chat: list) -> dict:
    """Aggregate N per-chat verdicts into a ticket-style summary (pure).

    Input: list of {"verdict": ...}. Output: counts + total.
    Unknown verdict strings are ignored (never raise).
    """
    summary = {"total": 0, "Compatible": 0, "Partial": 0,
               "Incompatible": 0, "Blocked": 0}
    for item in per_chat or []:
        verdict = (item or {}).get("verdict") if isinstance(item, dict) else None
        if verdict in VALID_VERDICTS:
            summary[verdict] += 1
            summary["total"] += 1
    return summary
