"""Reuse detection against the preset catalog (TICKET-002-L, Phase 3). Pure."""


def _observed_selectors(observations: dict) -> set:
    """Every selector the probes actually confirmed on the live page."""
    observed: set = set()
    chat_hits = observations.get("chat_list_hits") or {}
    if isinstance(chat_hits, dict):
        observed.update(chat_hits.keys())
    msg_hits = observations.get("message_hits") or {}
    if isinstance(msg_hits, dict):
        observed.update(msg_hits.keys())
    roles = observations.get("roles") or {}
    if isinstance(roles, dict):
        for key in ("user", "assistant", "message"):
            value = roles.get(key) or ""
            if isinstance(value, str):
                for part in value.split(","):
                    part = part.strip()
                    if part:
                        observed.add(part)
    return observed


def _split_selector(selector: str) -> list:
    if not isinstance(selector, str):
        return []
    return [p.strip() for p in selector.split(",") if p.strip()]





def detect_reuse(catalog, observations: dict) -> list:
    """Return reuse candidates whose selectors are confirmed by observations.

    A catalog preset matches when its chat_list_selector produced hits and its
    OWN message side is confirmed (message selector parts observed, or its
    user/assistant pair observed). Cross-miner confirmation is forbidden
    (N3): a preset whose own triple was never observed (e.g.
    userscript-generic on a page that only fired .message-bubble) is NOT
    reuse, even if some other miner fired. Zero message confirmation is
    never accepted. Never raises, never reads files.
    """
    try:
        if not isinstance(catalog, list) or not isinstance(observations, dict):
            return []
        chat_hits = observations.get("chat_list_hits") or {}
        if not isinstance(chat_hits, dict):
            chat_hits = {}
        observed = _observed_selectors(observations)
        found = []
        for preset in catalog:
            if not isinstance(preset, dict):
                continue
            pid = preset.get("id", "")
            strategy = preset.get("strategy", {})
            if not isinstance(strategy, dict):
                continue
            if strategy.get("type") != "selector":
                continue
            sels = strategy.get("selectors", {})
            if not isinstance(sels, dict):
                continue
            chat_sel = sels.get("chat_list_selector", "") or ""
            msg_sel = sels.get("message_selector", "") or ""
            user_sel = sels.get("user_message_selector", "") or ""
            asst_sel = sels.get("assistant_message_selector", "") or ""
            if not chat_sel:
                continue
            try:
                chat_n = int(chat_hits.get(chat_sel, 0) or 0)
            except Exception:
                chat_n = 0
            if chat_n <= 0:
                continue
            parts = _split_selector(msg_sel)
            message_viable = any(p in observed for p in parts)
            role_viable = bool(user_sel and asst_sel
                               and user_sel in observed and asst_sel in observed)
            if not (message_viable or role_viable):
                continue
            found.append({
                "preset_id": pid,
                "reason": f"chat_list {chat_n}, messages ok",
            })
        return found
    except Exception:
        return []
