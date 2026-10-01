"""Preset Matrix construction (TICKET-002-L, Phase 3). Pure, no JS synthesis."""

from core.preset_engine import validate_preset
from core.profiler import probes as probe_specs
from core.profiler.reuse import detect_reuse


def _selector_preset_id(provider: str, chat_sel: str) -> str:
    import hashlib

    digest = hashlib.sha1(f"{provider}|{chat_sel}".encode("utf-8")).hexdigest()[:8]
    return f"{provider}-auto-{digest}"


def _best_message_selector(obs: dict, roles: dict) -> str:
    """Role triple only (R4): without a verified user/assistant triple no
    candidate is emitted, so the message_hits fallback was dead for emit."""
    _ = obs
    if isinstance(roles, dict) and roles.get("found") and roles.get("message"):
        return roles.get("message", "")
    return ""


def _chat_list_kind(chat_sel: str) -> str:
    if chat_sel in probe_specs.ANCHOR_CHAT_LIST_SLS:
        return "links"
    if chat_sel in probe_specs.BUTTON_CHAT_LIST_SLS:
        return "buttons"
    return "mixed"


def build_preset_matrix(provider: str, observations: dict, catalog,
                        goto_empty: bool = False) -> dict:
    """Build 0..N candidates: new selector presets + reuse entries.

    - New selector presets come only from a successfully opened chat with a
      viable message/role triple, and must pass existing validate_preset
      (strategy.navigation strictly goto|click; Profile-level 'both' is mapped).
    - Exactly ONE chat-list selector is eligible for a new preset: the frozen
      best_sel (observations["chat_list_selector"], R10). The remaining
      chat_hits (nav a, aside a, a[href], …) are kept as evidence only, so a
      single provider never yields noisy duplicate candidates.
    - If an existing strategy covers the observations it is listed as reuse
      and no duplicating new preset is proposed for the same chat selector.
    - Never generates list_chats_js / extract_messages_js.
    """
    candidates = []
    obs = observations if isinstance(observations, dict) else {}
    nav_type = str((obs.get("navigation") or {}).get("type", "goto"))
    strategy_nav = probe_specs.map_profile_navigation_to_strategy(nav_type, goto_empty)
    chat_hits = obs.get("chat_list_hits") or {}
    if not isinstance(chat_hits, dict):
        chat_hits = {}
    roles = obs.get("roles") if isinstance(obs.get("roles"), dict) else {}
    best_msg = _best_message_selector(obs, roles)
    blocked = obs.get("blocked") if isinstance(obs.get("blocked"), dict) else {}

    reuse = detect_reuse(catalog if isinstance(catalog, list) else [], obs)
    reuse_ids = {r.get("preset_id") for r in reuse if isinstance(r, dict)}
    reuse_selectors = set()
    for preset in catalog if isinstance(catalog, list) else []:
        if not isinstance(preset, dict) or preset.get("id") not in reuse_ids:
            continue
        try:
            sel = preset.get("strategy", {}).get("selectors", {}).get("chat_list_selector", "")
        except Exception:
            sel = ""
        if sel:
            reuse_selectors.add(sel)
    for r in reuse:
        candidates.append({"kind": "reuse", "preset_id": r.get("preset_id", ""),
                           "probes": {"reason": r.get("reason", "")}})

    title_info = obs.get("title") or {}
    title_sel = title_info.get("selector", "") if isinstance(title_info, dict) else ""
    scroll_info = obs.get("scroll") or {}
    container = scroll_info.get("container", "") if isinstance(scroll_info, dict) else ""
    user_sel = roles.get("user", "") if roles.get("found") else ""
    asst_sel = roles.get("assistant", "") if roles.get("found") else ""

    best_sel = obs.get("chat_list_selector", "") or ""
    try:
        best_n = int(chat_hits.get(best_sel, 0) or 0)
    except Exception:
        best_n = 0
    evidence_hits = {s: n for s, n in chat_hits.items()
                     if s != best_sel}
    for chat_sel, n in [(best_sel, best_n)]:
        try:
            count = int(n or 0)
        except Exception:
            continue
        if not chat_sel or count <= 0:
            continue
        if chat_sel in reuse_selectors:
            continue  # existing strategy works — no duplicate
        probe_info = {
            "chat_list": "ok",
            "messages": "ok" if best_msg else "fail",
            "roles": "ok" if roles.get("found") else "missing",
            "scroll": scroll_info.get("status", "unknown"),
            "chat_list_evidence": evidence_hits,
        }
        if blocked.get("reason"):
            probe_info["blocked"] = blocked.get("reason")
        # A selector candidate without a user/assistant triple can never reach
        # Compatible and risks a bogus "main div" message selector: do not emit.
        if not best_msg or not roles.get("found"):
            continue
        preset = {
            "id": _selector_preset_id(provider or "provider", chat_sel),
            "name": f"{provider} (auto)",
            "description": f"Auto-discovered by Provider Profiler: {chat_sel}",
            "default_url": (obs.get("provider_url", "") or ""),
            "version": 1,
            "strategy": {
                "type": "selector",
                "navigation": strategy_nav,
                "wait_after_click_ms": 2000,
                "selectors": {
                    "chat_list_selector": chat_sel,
                    "title_selector": title_sel or "",
                    "message_selector": best_msg,
                    "user_message_selector": user_sel or "",
                    "assistant_message_selector": asst_sel or "",
                    "scroll_container_selector": container or "",
                },
                "scripts": {"list_chats_js": "", "extract_messages_js": ""},
            },
        }
        ok, _ = validate_preset(preset)
        if not ok:
            continue
        candidates.append({"kind": "selector-new", "preset": preset,
                           "probes": probe_info})
    result = {"provider": provider or "", "candidates": candidates,
              "chat_list_kind": _chat_list_kind(obs.get("chat_list_selector", "") or "")}
    if blocked.get("reason"):
        result["blocked"] = blocked
    return result
