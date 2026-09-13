"""Tests: custom1_page / custom2_page attributes missing from App.__init__.

PROBLEM: Plan says to use getattr/setattr for custom pages, but they should be
explicitly initialized like gemini_page, qwen_page, etc.  Without explicit
initialization, getattr(self, "custom1_page", None) silently returns None
instead of failing when the attribute is forgotten.
"""


class TestCustomPageAttributes:
    """custom1_page and custom2_page must exist as explicit attributes."""

    def test_custom1_page_attr_exists(self, mock_app):
        """custom1_page should be an explicit attribute on App."""
        assert hasattr(mock_app, "custom1_page"), (
            "custom1_page is not an explicit attribute on App. "
            "Plan relies on getattr fallback — fragile."
        )

    def test_custom2_page_attr_exists(self, mock_app):
        """custom2_page should be an explicit attribute on App."""
        assert hasattr(mock_app, "custom2_page"), (
            "custom2_page is not an explicit attribute on App."
        )

    def test_custom_pages_initialized_to_none(self, mock_app):
        """Both custom pages must be None after init, like gemini_page."""
        # gemini_page is always None after init — baseline
        assert mock_app.gemini_page is None

        # custom1/custom2 should also be explicit None
        c1 = getattr(mock_app, "custom1_page", "__MISSING__")
        c2 = getattr(mock_app, "custom2_page", "__MISSING__")
        assert c1 is None, f"custom1_page should be None, got {c1!r}"
        assert c2 is None, f"custom2_page should be None, got {c2!r}"
