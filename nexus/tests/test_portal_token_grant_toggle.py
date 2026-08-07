"""OEM 授权申请 Token 开关的前端静态回归测试。"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class PortalTokenGrantToggleTests(unittest.TestCase):
    """关闭赠送 Token 时，字段必须可见但不可编辑。"""

    def test_manual_token_control_explains_platform_switch(self) -> None:
        html = (ROOT / "console" / "portal" / "index.html").read_text()

        self.assertIn('id="license-manual-tokens"', html)
        self.assertIn('id="license-manual-token-note"', html)
        self.assertIn('name="requested_tokens"', html)
        self.assertIn('/portal/portal.css?v=48', html)
        self.assertIn('/portal/portal.js?v=57', html)

    def test_disabled_switch_greys_field_and_forces_zero(self) -> None:
        javascript = (ROOT / "console" / "portal" / "portal.js").read_text()

        self.assertIn(
            "manualTokenControl.hidden = oemTokenGrantRequestVisible && !manualReview",
            javascript,
        )
        self.assertIn(
            'var tokenGrantDisabled = !manualReview || !oemTokenGrantRequestVisible',
            javascript,
        )
        self.assertIn('manualTokenControl.classList.toggle("is-disabled"', javascript)
        self.assertIn('form.requested_tokens.value = "0"', javascript)
        self.assertIn('form.requested_tokens.disabled = tokenGrantDisabled', javascript)
        self.assertIn('requested_tokens: oemTokenGrantRequestVisible', javascript)

    def test_disabled_control_has_visual_style(self) -> None:
        stylesheet = (ROOT / "console" / "portal" / "portal.css").read_text()

        self.assertIn(".license-token-control.is-disabled", stylesheet)
        self.assertIn("cursor: not-allowed", stylesheet)


if __name__ == "__main__":
    unittest.main()
