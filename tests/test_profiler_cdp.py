"""Tests: --cdp attach vs launch + teardown guard (smoke-only). No browser."""

from unittest.mock import MagicMock

from core.profiler import run as run_mod

CDP = "http://127.0.0.1:9222"


def _pw():
    return MagicMock()


def test_attach_uses_first_context_tab():
    pw = _pw()
    browser = pw.chromium.connect_over_cdp.return_value
    page = browser.contexts[0].new_page.return_value
    out_browser, out_page, owned = run_mod._open_session(pw, CDP)
    pw.chromium.connect_over_cdp.assert_called_once_with(CDP)
    pw.chromium.launch.assert_not_called()
    browser.contexts[0].new_page.assert_called_once_with()
    assert (out_browser, out_page, owned) == (browser, page, False)


def test_attach_without_contexts_falls_back_to_new_page():
    pw = _pw()
    browser = pw.chromium.connect_over_cdp.return_value
    browser.contexts = []
    out_browser, out_page, owned = run_mod._open_session(pw, CDP)
    browser.new_page.assert_called_once_with()
    assert (out_browser, out_page, owned) == (
        browser, browser.new_page.return_value, False)


def test_launch_kept_bit_for_bit_without_cdp():
    pw = _pw()
    browser = pw.chromium.launch.return_value
    out_browser, out_page, owned = run_mod._open_session(pw, "")
    pw.chromium.connect_over_cdp.assert_not_called()
    pw.chromium.launch.assert_called_once_with(headless=False)
    assert (out_browser, out_page, owned) == (
        browser, browser.new_page.return_value, True)


def test_teardown_owned_closes_browser_and_page():
    browser, page = MagicMock(), MagicMock()
    run_mod._close_session(browser, page, True)
    page.close.assert_called_once_with()
    browser.close.assert_called_once_with()


def test_teardown_foreign_closes_page_only():
    browser, page = MagicMock(), MagicMock()
    run_mod._close_session(browser, page, False)
    page.close.assert_called_once_with()
    browser.close.assert_not_called()


def test_teardown_never_raises():
    browser, page = MagicMock(), MagicMock()
    page.close.side_effect = Exception("dead")
    browser.close.side_effect = Exception("dead")
    run_mod._close_session(browser, page, True)
    run_mod._close_session(None, None, False)


def test_attach_failure_is_readable():
    pw = _pw()
    pw.chromium.connect_over_cdp.side_effect = Exception("refused")
    try:
        run_mod._open_session(pw, CDP)
    except RuntimeError as e:
        assert "CDP unavailable at http://127.0.0.1:9222" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


def test_argparse_accepts_cdp():
    args = run_mod._parse_args(["--url", "https://foo.ai/",
                                "--cdp", CDP])
    assert args.cdp == CDP
    assert run_mod._parse_args(["--url", "https://foo.ai/"]).cdp == ""
