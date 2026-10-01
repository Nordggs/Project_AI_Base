"""Tests: pure verdict layer (TICKET-002-L, Phase 4). No browser."""

from core.profiler import verdicts


def test_per_chat_compatible():
    v, r = verdicts.per_chat_verdict(5, 10, 4, 5, "https://foo.ai/c/1",
                                     "https://foo.ai/")
    assert (v, r) == ("Compatible", "ok")


def test_unknown_fraction_threshold():
    # 10 msgs, 1 user + 1 asst, 8 unknown -> Partial (threshold 0.2)
    v, _ = verdicts.per_chat_verdict(3, 10, 1, 1, "", "")
    assert v == "Partial"


def test_incompatible_wrong_page():
    v, r = verdicts.per_chat_verdict(0, 0, 0, 0, "https://evil.com/",
                                     "https://foo.ai/")
    assert (v, r) == ("Incompatible", "wrong_page")


def test_blocked_only_with_reason():
    v, r = verdicts.per_chat_verdict(5, 5, 2, 2, "", "",
                                     blocked_reason="product-filter")
    assert (v, r) == ("Blocked", "product-filter")


def test_aggregate_report_counts():
    per_chat = [{"verdict": "Compatible"}, {"verdict": "Partial"},
                {"verdict": "Blocked"}, {"verdict": "Nope"}]
    summary = verdicts.aggregate_report(per_chat)
    assert summary == {"total": 3, "Compatible": 1, "Partial": 1,
                       "Incompatible": 0, "Blocked": 1}
