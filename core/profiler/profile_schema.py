"""Provider Profile schema (TICKET-002-L, Phase 1). Pure, never raises."""

from dataclasses import dataclass, field


PROFILE_VERSION = 1

NAVIGATION_PROFILE_TYPES = ("goto", "click", "both")


@dataclass
class ProviderProfile:
    provider: str
    provider_url: str
    navigation: dict = field(default_factory=dict)
    chat_list: dict = field(default_factory=dict)
    chat: dict = field(default_factory=dict)
    messages: dict = field(default_factory=dict)
    title: dict = field(default_factory=dict)
    extraction: dict = field(default_factory=dict)
    scroll: dict = field(default_factory=dict)
    checked_at: str = ""
    version: int = PROFILE_VERSION


def _is_nonempty_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_profile(profile) -> "tuple[bool, list[str]]":
    """Check a ProviderProfile dict/dataclass. Returns (ok, errors), never raises."""
    try:
        if isinstance(profile, ProviderProfile):
            data = {
                "provider": profile.provider,
                "provider_url": profile.provider_url,
                "navigation": profile.navigation,
                "chat_list": profile.chat_list,
                "chat": profile.chat,
                "messages": profile.messages,
                "title": profile.title,
                "extraction": profile.extraction,
                "scroll": profile.scroll,
                "checked_at": profile.checked_at,
                "version": profile.version,
            }
        elif isinstance(profile, dict):
            data = profile
        else:
            return False, ["profile must be an object"]
        errors: list = []
        if not _is_nonempty_str(data.get("provider")):
            errors.append("provider must be a non-empty string")
        if not _is_nonempty_str(data.get("provider_url")):
            errors.append("provider_url must be a non-empty string")
        nav = data.get("navigation", {})
        if not isinstance(nav, dict):
            errors.append("navigation must be an object")
        elif nav.get("type") not in NAVIGATION_PROFILE_TYPES:
            errors.append(
                f"navigation.type must be one of {list(NAVIGATION_PROFILE_TYPES)}"
            )
        for key in ("chat_list", "chat", "messages", "title", "extraction", "scroll"):
            if not isinstance(data.get(key, {}), dict):
                errors.append(f"{key} must be an object")
        version = data.get("version", PROFILE_VERSION)
        if not isinstance(version, int) or version < 1:
            errors.append("version must be int >= 1")
        return (len(errors) == 0), errors
    except Exception as e:  # never raise by contract
        return False, [f"validate_profile error: {e}"]


def profile_to_dict(profile: ProviderProfile) -> dict:
    return {
        "provider": profile.provider,
        "provider_url": profile.provider_url,
        "navigation": dict(profile.navigation or {}),
        "chat_list": dict(profile.chat_list or {}),
        "chat": dict(profile.chat or {}),
        "messages": dict(profile.messages or {}),
        "title": dict(profile.title or {}),
        "extraction": dict(profile.extraction or {}),
        "scroll": dict(profile.scroll or {}),
        "checked_at": profile.checked_at or "",
        "version": profile.version,
    }
