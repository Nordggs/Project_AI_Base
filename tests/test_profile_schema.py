"""Tests: ProviderProfile schema (TICKET-002-L, Phase 1). No browser."""

from core.profiler.profile_schema import (
    ProviderProfile,
    profile_to_dict,
    validate_profile,
)


def _good():
    return ProviderProfile(
        provider="fooai",
        provider_url="https://foo.ai/",
        navigation={"type": "both", "spa": True},
        chat_list={},
        chat={},
        messages={},
        title={},
        extraction={},
        scroll={},
        checked_at="2026-10-01",
    )


def test_validate_profile_ok():
    ok, errors = validate_profile(_good())
    assert ok and errors == []


def test_validate_profile_ok_dict():
    ok, _ = validate_profile(profile_to_dict(_good()))
    assert ok


def test_validate_profile_fail_empty_provider():
    p = _good()
    p.provider = "  "
    ok, errors = validate_profile(p)
    assert not ok and any("provider" in e for e in errors)


def test_validate_profile_fail_bad_navigation():
    ok, errors = validate_profile(profile_to_dict(_good()) | {
        "navigation": {"type": "both-bad"}})
    assert not ok


def test_validate_profile_never_raises():
    ok, errors = validate_profile(object())
    assert not ok and errors
