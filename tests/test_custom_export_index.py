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
