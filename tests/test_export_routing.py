"""Tests: _export_provider() always routes custom to API generate path.

PROBLEM: When a custom slot is in 'web' mode, _export_provider() should use
the standard browser pipeline (list_chats -> open_chat -> extract_chat),
but currently it unconditionally calls _export_custom_generate().
"""

from unittest.mock import patch, MagicMock

from main import App


class TestExportRouting:
    """_export_provider() must distinguish API vs Web for custom slots."""

    def test_custom_api_routes_to_generate(self, mock_app):
        """PASS: custom1 in API mode routes to _export_custom_generate."""
        with patch("main.load_custom_config", return_value={
            "mode": "api", "endpoint": "https://api.example.com",
            "model": "gpt-4",
        }):
            with patch.object(App, "_export_custom_generate",
                              return_value={"ok": 1}) as mock_gen:
                try:
                    App._export_provider(mock_app, "custom1", prompt="test")
                except Exception:
                    pass
                mock_gen.assert_called_once()

    def test_custom_web_should_not_route_to_generate(self, mock_app):
        """FAIL: custom1 in 'web' mode still calls _export_custom_generate."""
        with patch("main.load_custom_config", return_value={
            "mode": "web", "url": "https://chat.mistral.ai",
        }):
            with patch.object(App, "_export_custom_generate") as mock_gen, \
                 patch.object(App, "_page_for") as mock_page_fn, \
                 patch.object(App, "_adapter_for") as mock_adapter_fn:
                page = MagicMock()
                page.evaluate.return_value = "ok"
                mock_page_fn.return_value = page

                adapter = MagicMock()
                adapter.healthcheck.return_value = True
                adapter.list_chats.return_value = [{"url": "https://x", "title": "t"}]
                adapter.open_chat.return_value = True
                model = MagicMock()
                model.messages = [MagicMock()]
                adapter.extract_chat.return_value = model
                mock_adapter_fn.return_value = adapter

                with patch("main.Enricher") as mock_enricher, \
                     patch("main.ExportWriter"):
                    mock_enricher.enrich.return_value = (MagicMock(), MagicMock(partial=0))
                    try:
                        App._export_provider(mock_app, "custom1", urls=["https://x"])
                    except Exception:
                        pass

                    # FAIL: _export_custom_generate is called even in web mode
                    mock_gen.assert_not_called(), (
                        "_export_custom_generate should NOT be called in web mode"
                    )

    def test_custom_web_uses_adapter_list_chats(self, mock_app):
        """FAIL: custom1 web mode should call adapter.list_chats, not generate."""
        with patch("main.load_custom_config", return_value={
            "mode": "web", "url": "https://chat.mistral.ai",
        }):
            with patch.object(App, "_export_custom_generate") as mock_gen, \
                 patch.object(App, "_page_for") as mock_page_fn, \
                 patch.object(App, "_adapter_for") as mock_adapter_fn:
                page = MagicMock()
                page.evaluate.return_value = "ok"
                mock_page_fn.return_value = page

                adapter = MagicMock()
                adapter.healthcheck.return_value = True
                adapter.list_chats.return_value = [{"url": "https://x", "title": "t"}]
                adapter.open_chat.return_value = True
                model = MagicMock()
                model.messages = [MagicMock()]
                adapter.extract_chat.return_value = model
                mock_adapter_fn.return_value = adapter

                with patch("main.Enricher") as mock_enricher, \
                     patch("main.ExportWriter"):
                    mock_enricher.enrich.return_value = (MagicMock(), MagicMock(partial=0))
                    try:
                        App._export_provider(mock_app, "custom1", urls=["https://x"])
                    except Exception:
                        pass

                    # FAIL: generate was called instead of browser pipeline
                    mock_gen.assert_not_called()
                    # list_chats is also not called because generate short-circuits
                    adapter.list_chats.assert_not_called()
