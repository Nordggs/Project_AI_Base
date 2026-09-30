"""Shared fixtures: create a mock App without triggering heavy __init__.

The real App.__init__ launches threads, creates webview windows, and resolves
storage paths.  We bypass all of that and hand-build an object that has the
same attributes the methods under test touch.
"""

import sys
import threading
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_app():
    """Build a minimal App-like object with real attributes, no side effects."""
    # ── Import the module without triggering __main__ guard ──
    import importlib
    import main as main_mod

    # Create App instance WITHOUT calling __init__
    app = object.__new__(main_mod.App)

    # ── Replicate __init__ state (see main.py:386-489) ──

    # Logging
    app.log = MagicMock()
    app.log.add = MagicMock()
    app._push_log = MagicMock()

    # Window
    app.window = MagicMock()

    # Playwright (DeepSeek)
    app.pw = None

    # URL tracking
    app._auto_reconnecting = False
    app._seen_urls = set()

    # Per-provider locks
    app._locks = {
        "deepseek": threading.Lock(),
        "gemini": threading.Lock(),
        "qwen": threading.Lock(),
        "chatgpt": threading.Lock(),
        "claude": threading.Lock(),
        "custom1": threading.Lock(),
        "custom2": threading.Lock(),
    }

    # Sync state
    app._sync_state = {
        "gemini": "idle", "qwen": "idle",
        "chatgpt": "idle", "claude": "idle", "deepseek": "idle",
        "custom1": "idle", "custom2": "idle",
    }
    app._sync_done_events = {}
    app._sync_results = {}

    # Queues
    app._pw_queue = MagicMock()
    app._gw_queue = MagicMock()

    # Connect events
    app._connect_done = threading.Event()
    app._connect_error = None
    app._last_watched_url = ""
    app._export_active = False
    app._cancel_flag = False
    app._cancel_version = 0
    app._close_pw_done = threading.Event()
    app._close_gw_done = threading.Event()

    # CDP provider pages (gemini/qwen/chatgpt/claude + custom)
    app.gemini_page = None
    app.qwen_page = None
    app.chatgpt_page = None
    app.claude_page = None
    app.custom1_page = None
    app.custom2_page = None

    # GW browser + playwright
    app._gw_browser = None
    app._gw_pw = MagicMock()

    # Connect state flags for CDP providers
    app._gemini_connect_state = "idle"
    app._qwen_connected = False
    app._chatgpt_connected = False
    app._claude_connected = False
    app._gemini_connect_lock = False
    app._qwen_connect_lock = False
    app._chatgpt_connect_lock = False
    app._claude_connect_lock = False
    app._connect_gemini_done = threading.Event()
    app._connect_qwen_done = threading.Event()
    app._connect_chatgpt_done = threading.Event()
    app._connect_claude_done = threading.Event()
    app._gemini_export_active = False
    app._qwen_export_active = False
    app._chatgpt_export_active = False
    app._claude_export_active = False

    # Custom provider connected flags
    app._custom1_connected = False
    app._custom2_connected = False

    # CDP lock
    app._cdp_lock = threading.Lock()

    # Paths
    app._config_path = "/tmp/test/config.json"
    app._output_dir = "/tmp/test/raw"
    app._storage_dir = "/tmp/test"

    # CDP manager
    app.cdp = MagicMock()
    app.cdp.state = "running"
    app._file_log = None
    app._cdp_start_thread = None

    # Helpers
    app._check_cancel = lambda: None
    app.set_sync_state = lambda name, state: app._sync_state.update({name: state})

    return app
