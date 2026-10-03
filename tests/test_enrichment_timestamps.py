"""Tests: Enricher tolerates non-numeric message timestamps.

Regression for the production crash:
`unsupported operand type(s) for -: 'str' and 'float'`
(Perplexity supplies display-only "HH:MM" strings; Enricher did arithmetic
on them at `first_ts - anchor.perf_zero`).

String timestamps must behave like missing ones (no temporal windowing),
numeric behavior must stay unchanged.
"""

import pytest

from conversation.enrichment import AnchorData, Enricher, RuntimeData, _num
from conversation.models import ConversationModel, Message


def _model(*timestamps):
    return ConversationModel(
        source="perplexity",
        stable_id="x",
        title="t",
        source_url="https://www.perplexity.ai/search/x",
        messages=[Message(role="user" if i % 2 == 0 else "assistant",
                           content=f"m{i}", timestamp=ts)
                  for i, ts in enumerate(timestamps)],
        tree=None,
        metadata={},
    )


def _ctx():
    return [], RuntimeData(trace=[], blobs=[]), AnchorData(perf_zero=1000.0, epoch_zero=0.0)


class TestNumGuard:
    def test_floats_pass(self):
        assert _num(1720000000.0) == 1720000000.0
        assert _num(5) == 5

    def test_strings_and_none_become_none(self):
        assert _num("05:48") is None
        assert _num("2024-01-15 14:30") is None
        assert _num(None) is None


class TestStringTimestamps:
    def test_repro_production_crash(self):
        """Exact prod shape: first message carries "HH:MM" — must not raise."""
        model = _model("05:48", None)
        cdp, runtime, anchor = _ctx()
        out, stats = Enricher.enrich(model, cdp, runtime, anchor)
        assert [m.content for m in out.messages] == ["m0", "m1"]
        # timestamps preserved untouched for display (_fmt_ts handles strings)
        assert out.messages[0].timestamp == "05:48"

    def test_all_strings_no_crash(self):
        model = _model("03:18", "03:19", "03:20")
        cdp, runtime, anchor = _ctx()
        out, stats = Enricher.enrich(model, cdp, runtime, anchor)
        assert len(out.messages) == 3
        assert stats.total == 0

    def test_mixed_none_str_float(self):
        model = _model(None, "05:48", 1720000000.0)
        cdp, runtime, anchor = _ctx()
        out, stats = Enricher.enrich(model, cdp, runtime, anchor)
        assert len(out.messages) == 3


class TestNumericUnchanged:
    def test_float_windows_still_work(self):
        from exporters.attachment_capture import CapturedAsset
        model = _model(1000.0, 2000.0)
        cdp = [CapturedAsset(url="https://x/img.png", content_type="image/png",
                             body=b"123", timestamp=1500.0)]
        anchor = AnchorData(perf_zero=0.0, epoch_zero=0.0)
        out, stats = Enricher.enrich(model, cdp, RuntimeData(trace=[], blobs=[]), anchor)
        # asset at 1500.0 falls in [1000.0, 2000.0) — but no attachments to bind;
        # it must simply not crash and stay unbound
        assert stats.total == 0
        assert len(out.messages) == 2
