"""Regression checks for the default OEM-request rejection message."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REASON = "请联系商务或者推荐人"


class PortalRequestRejectDefaultTests(unittest.TestCase):
    def test_dialog_supports_a_default_input_value(self) -> None:
        javascript = (ROOT / "console" / "portal" / "portal.js").read_text()

        self.assertIn("function uiPrompt(text, placeholder, defaultValue)", javascript)
        self.assertIn('inp.value = opts.defaultValue == null ? "" : String(opts.defaultValue)', javascript)
        self.assertIn("defaultValue: defaultValue", javascript)

    def test_oem_request_rejection_starts_with_business_contact_copy(self) -> None:
        javascript = (ROOT / "console" / "portal" / "portal.js").read_text()

        self.assertIn('"拒绝理由（会展示给申请人，必填）"', javascript)
        self.assertIn('"' + DEFAULT_REASON + '"', javascript)


if __name__ == "__main__":
    unittest.main()
