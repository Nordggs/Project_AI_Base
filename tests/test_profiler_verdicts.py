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


class TestCandidateVerdict:
    """Single rollup per candidate (TICKET-003). Save button ⟺ Compatible."""

    def test_all_compatible(self):
        assert verdicts.candidate_verdict(
            {"total": 5, "Compatible": 5, "Partial": 0,
             "Incompatible": 0, "Blocked": 0}) == "Compatible"

    def test_single_compatible(self):
        assert verdicts.candidate_verdict(
            {"total": 1, "Compatible": 1, "Partial": 0,
             "Incompatible": 0, "Blocked": 0}) == "Compatible"

    def test_mixed_partial(self):
        assert verdicts.candidate_verdict(
            {"total": 5, "Compatible": 4, "Partial": 1,
             "Incompatible": 0, "Blocked": 0}) == "Partial"

    def test_incompatible_beats_partial(self):
        assert verdicts.candidate_verdict(
            {"total": 5, "Compatible": 3, "Partial": 1,
             "Incompatible": 1, "Blocked": 0}) == "Incompatible"

    def test_blocked_beats_all(self):
        assert verdicts.candidate_verdict(
            {"total": 5, "Compatible": 3, "Partial": 1,
             "Incompatible": 1, "Blocked": 1}) == "Blocked"

    def test_empty_summary_is_incompatible(self):
        assert verdicts.candidate_verdict(
            {"total": 0, "Compatible": 0, "Partial": 0,
             "Incompatible": 0, "Blocked": 0}) == "Incompatible"

    def test_none_and_garbage_are_incompatible(self):
        assert verdicts.candidate_verdict(None) == "Incompatible"
        assert verdicts.candidate_verdict({}) == "Incompatible"
        assert verdicts.candidate_verdict("nope") == "Incompatible"
