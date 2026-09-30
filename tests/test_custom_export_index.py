"""Tests: _export_provider dedup + _index preservation (real code, not inline).

Tests the actual App._export_provider method with mocked dependencies.
Verifies:
- _index is passed through to adapter.open_chat for each chat
- Dedup keeps multiple {"url": "", "_index": N} entries (different indices)
- Plain URL strings still work
"""

from unittest.mock import patch, MagicMock, call
from main import App


def _make_enrich_stats():
    s = MagicMock()
    s.partial = 0
    s.cdp_strict = 0
    s.cdp_temporal = 0
    s.runtime = 0
    return s


def _make_mock_adapter():
    adapter = MagicMock()
    adapter.healthcheck.return_value = True
    adapter.open_chat.return_value = True
    adapter.extract_chat.return_value = MagicMock()
    return adapter


class TestExportProviderDedupWithIndex:
    """_export_provider dedup must not collapse dicts with different _index."""

    @patch("main.Enricher")
    @patch("main.ExportWriter")
    @patch("main.capture_cdp_if_needed")
    @patch("main._check_cdp_alive", return_value=True)
    def test_two_empty_url_dicts_with_different_index_both_pass_to_open_chat(
        self, mock_cdp_alive, mock_capture, mock_writer_cls, mock_enricher
    ):
        mock_enricher.enrich.return_value = (MagicMock(), _make_enrich_stats())
        mock_capture.return_value = MagicMock(cdp_assets=[], runtime=MagicMock(blobs=[]), anchor=None)

        mock_app = object.__new__(App)
        mock_app._check_cancel = lambda: None
        mock_app._push_log = MagicMock()
        mock_app._locks = {"custom1": MagicMock()}
        mock_app._locks["custom1"].acquire.return_value = True
        mock_app._sync_state = {}
        mock_app.set_sync_state = lambda n, s: mock_app._sync_state.update({n: s})
        mock_app.log = MagicMock()
        mock_app._output_dir = "/tmp/test/raw"
        mock_app._config_path = "/tmp/test/config.json"
        mock_app._cancel_flag = False

        mock_page = MagicMock()
        mock_adapter = _make_mock_adapter()

        with patch.object(App, "_page_for", return_value=mock_page), \
             patch.object(App, "_adapter_for", return_value=mock_adapter), \
             patch("main.load_custom_config", return_value={"mode": "web", "url": "https://x"}):
            App._export_provider(
                mock_app,
                "custom1",
                urls=[{"url": "", "_index": 3}, {"url": "", "_index": 7}],
            )

        assert mock_adapter.open_chat.call_count == 2
        calls = mock_adapter.open_chat.call_args_list
        assert calls[0][0][0]["_index"] == 3
        assert calls[1][0][0]["_index"] == 7

    @patch("main.Enricher")
    @patch("main.ExportWriter")
    @patch("main.capture_cdp_if_needed")
    @patch("main._check_cdp_alive", return_value=True)
    def test_dedup_collapses_same_url(
        self, mock_cdp_alive, mock_capture, mock_writer_cls, mock_enricher
    ):
        mock_enricher.enrich.return_value = (MagicMock(), _make_enrich_stats())
        mock_capture.return_value = MagicMock(cdp_assets=[], runtime=MagicMock(blobs=[]), anchor=None)

        mock_app = object.__new__(App)
        mock_app._check_cancel = lambda: None
        mock_app._push_log = MagicMock()
        mock_app._locks = {"custom1": MagicMock()}
        mock_app._locks["custom1"].acquire.return_value = True
        mock_app._sync_state = {}
        mock_app.set_sync_state = lambda n, s: mock_app._sync_state.update({n: s})
        mock_app.log = MagicMock()
        mock_app._output_dir = "/tmp/test/raw"
        mock_app._config_path = "/tmp/test/config.json"
        mock_app._cancel_flag = False

        mock_adapter = _make_mock_adapter()

        with patch.object(App, "_page_for", return_value=MagicMock()), \
             patch.object(App, "_adapter_for", return_value=mock_adapter), \
             patch("main.load_custom_config", return_value={"mode": "web", "url": "https://x"}):
            App._export_provider(
                mock_app,
                "custom1",
                urls=[{"url": "https://same", "_index": 1}, {"url": "https://same", "_index": 99}],
            )

        assert mock_adapter.open_chat.call_count == 1

    @patch("main.Enricher")
    @patch("main.ExportWriter")
    @patch("main.capture_cdp_if_needed")
    @patch("main._check_cdp_alive", return_value=True)
    def test_mixed_urls_and_dicts(
        self, mock_cdp_alive, mock_capture, mock_writer_cls, mock_enricher
    ):
        mock_enricher.enrich.return_value = (MagicMock(), _make_enrich_stats())
        mock_capture.return_value = MagicMock(cdp_assets=[], runtime=MagicMock(blobs=[]), anchor=None)

        mock_app = object.__new__(App)
        mock_app._check_cancel = lambda: None
        mock_app._push_log = MagicMock()
        mock_app._locks = {"custom1": MagicMock()}
        mock_app._locks["custom1"].acquire.return_value = True
        mock_app._sync_state = {}
        mock_app.set_sync_state = lambda n, s: mock_app._sync_state.update({n: s})
        mock_app.log = MagicMock()
        mock_app._output_dir = "/tmp/test/raw"
        mock_app._config_path = "/tmp/test/config.json"
        mock_app._cancel_flag = False

        mock_adapter = _make_mock_adapter()

        with patch.object(App, "_page_for", return_value=MagicMock()), \
             patch.object(App, "_adapter_for", return_value=mock_adapter), \
             patch("main.load_custom_config", return_value={"mode": "web", "url": "https://x"}):
            App._export_provider(
                mock_app,
                "custom1",
                urls=["https://a", {"url": "https://b", "_index": 2}],
            )

        assert mock_adapter.open_chat.call_count == 2

    @patch("main.Enricher")
    @patch("main.ExportWriter")
    @patch("main.capture_cdp_if_needed")
    @patch("main._check_cdp_alive", return_value=True)
    def test_plain_url_strings_still_work(
        self, mock_cdp_alive, mock_capture, mock_writer_cls, mock_enricher
    ):
        mock_enricher.enrich.return_value = (MagicMock(), _make_enrich_stats())
        mock_capture.return_value = MagicMock(cdp_assets=[], runtime=MagicMock(blobs=[]), anchor=None)

        mock_app = object.__new__(App)
        mock_app._check_cancel = lambda: None
        mock_app._push_log = MagicMock()
        mock_app._locks = {"custom1": MagicMock()}
        mock_app._locks["custom1"].acquire.return_value = True
        mock_app._sync_state = {}
        mock_app.set_sync_state = lambda n, s: mock_app._sync_state.update({n: s})
        mock_app.log = MagicMock()
        mock_app._output_dir = "/tmp/test/raw"
        mock_app._config_path = "/tmp/test/config.json"
        mock_app._cancel_flag = False

        mock_adapter = _make_mock_adapter()

        with patch.object(App, "_page_for", return_value=MagicMock()), \
             patch.object(App, "_adapter_for", return_value=mock_adapter), \
             patch("main.load_custom_config", return_value={"mode": "web", "url": "https://x"}):
            App._export_provider(
                mock_app,
                "custom1",
                urls=["https://x", "https://y"],
            )

        assert mock_adapter.open_chat.call_count == 2
        assert mock_adapter.open_chat.call_args_list[0][0][0] == {"url": "https://x"}
        assert mock_adapter.open_chat.call_args_list[1][0][0] == {"url": "https://y"}


class TestPresetContextWriter:
    """Preset-mapped extract flows into ExportWriter (TICKET-002-J gap 5)."""

    def test_preset_extract_writes_custom_md_with_hash(self, tmp_path):
        import re

        from adapters.custom_web import SelectorStrategy
        from conversation.models import ConversationModel, Message
        from exporters.writer import ExportWriter
        from main import _preset_to_web_config

        preset = {
            "id": "grok", "default_url": "https://grok.com/",
            "strategy": {"type": "selector", "selectors": {
                "chat_list_selector": "a[href*='/c/']",
                "message_selector": ".message-bubble, .response-content-markdown",
                "user_message_selector": ".message-bubble",
                "assistant_message_selector": ".response-content-markdown",
            }, "scripts": {}},
        }
        web_cfg = _preset_to_web_config(preset)
        page = MagicMock()
        page.url = "https://grok.com/c/abc"
        page.title.return_value = "Grok chat"
        page.evaluate.return_value = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        model = SelectorStrategy(page, web_cfg).extract_chat({"id": "custom-0"})
        assert isinstance(model, ConversationModel)
        assert model.source == "custom"
        writer = ExportWriter(out_dir=str(tmp_path))
        path = writer.write(model, chat_order=0)
        assert path is not None
        text = path.read_text(encoding="utf-8")
        assert re.search(r"<!-- hash: \w+ title: .* chat_order: 0 -->", text)
        assert path.parent.name == "custom"
        assert re.match(r"custom_\d+_.*_[0-9a-f]{8}\.md", path.name)


class TestStableIdAndSkip:
    """5 exports must not collapse into 1 file; unchanged rewrite is skip."""

    def _model(self, stable_id, content):
        from conversation.models import ConversationModel, Message

        return ConversationModel(
            source="custom", stable_id=stable_id, title="T",
            source_url="https://x/", messages=[Message(role="user", content=content)],
        )

    def test_distinct_ids_write_distinct_files(self, tmp_path):
        from exporters.writer import ExportWriter

        writer = ExportWriter(out_dir=str(tmp_path))
        paths = {str(writer.write(self._model(f"custom-{i}", f"content {i}"), chat_order=i))
                 for i in range(5)}
        assert len(paths) == 5

    def test_unchanged_rewrite_is_skipped(self, tmp_path):
        from exporters.writer import ExportWriter

        writer = ExportWriter(out_dir=str(tmp_path))
        first = writer.write(self._model("custom-0", "same"), chat_order=0)
        assert writer.last_skipped is False
        second = writer.write(self._model("custom-0", "same"), chat_order=0)
        assert second == first
        assert writer.last_skipped is True

    def test_changed_content_overwrites_not_skips(self, tmp_path):
        from exporters.writer import ExportWriter

        writer = ExportWriter(out_dir=str(tmp_path))
        first = writer.write(self._model("custom-0", "v1"), chat_order=0)
        second = writer.write(self._model("custom-0", "v2"), chat_order=0)
        assert second == first
        assert writer.last_skipped is False
        assert "v2" in second.read_text(encoding="utf-8")

    def test_extract_stable_id_prefers_id_then_title(self):
        from adapters.custom_web import SelectorStrategy

        page = MagicMock()
        page.url = "https://x/"
        page.title.return_value = "T"
        page.evaluate.return_value = [{"role": "user", "content": "hi"}]
        cfg = {"message_selector": ".m"}
        assert SelectorStrategy(page, cfg).extract_chat(
            {"url": "https://x/", "_index": 0, "id": "custom-3"}).stable_id == "custom-3"
        assert SelectorStrategy(page, cfg).extract_chat(
            {"url": "https://x/", "_index": 0, "title": "My chat"}).stable_id == "My chat"
        assert SelectorStrategy(page, cfg).extract_chat(
            {"url": "https://x/", "_index": 0}).stable_id == "unknown"

    @patch("main.Enricher")
    @patch("main.capture_cdp_if_needed")
    @patch("main._check_cdp_alive", return_value=True)
    def test_provider_counts_skip_not_ok(self, mock_cdp_alive, mock_capture, mock_enricher):
        from exporters.writer import ExportWriter

        from conversation.models import ConversationModel, Message

        mock_enricher.enrich.return_value = (MagicMock(), _make_enrich_stats())
        mock_capture.return_value = MagicMock(cdp_assets=[], runtime=MagicMock(blobs=[]), anchor=None)

        mock_app = object.__new__(App)
        mock_app._check_cancel = lambda: None
        mock_app._push_log = MagicMock()
        mock_app._locks = {"custom1": MagicMock()}
        mock_app._locks["custom1"].acquire.return_value = True
        mock_app._locks["custom1"].release.return_value = None
        mock_app._sync_state = {}
        mock_app.set_sync_state = lambda n, s: mock_app._sync_state.update({n: s})
        mock_app.log = MagicMock()
        mock_app._config_path = "/tmp/test/config.json"
        mock_app._cancel_flag = False

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            mock_app._output_dir = tmp
            model = ConversationModel(
                source="custom", stable_id="custom-0", title="T",
                source_url="https://x/",
                messages=[Message(role="user", content="hi")],
            )
            mock_enricher.enrich.return_value = (model, _make_enrich_stats())
            mock_adapter = _make_mock_adapter()
            mock_adapter.extract_chat.return_value = model
            with patch.object(App, "_page_for", return_value=MagicMock()), \
                    patch.object(App, "_adapter_for", return_value=mock_adapter), \
                    patch("main.load_custom_config", return_value={"mode": "web", "url": "https://x"}), \
                    patch("main.ExportWriter", return_value=ExportWriter(out_dir=tmp)):
                res = App._export_provider(
                    mock_app, "custom1",
                    urls=[{"url": "", "_index": 0}, {"url": "", "_index": 1}],
                )
            assert res["ok"] == 1
            assert res["skipped"] == 1
            assert res["errors"] == 0
