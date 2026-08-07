"""OEM 客户分类、生命周期状态与搜索入口的静态回归测试。"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class PortalCustomerLifecycleTests(unittest.TestCase):
    """确保客户页不再只显示含义模糊的账号“正常”状态。"""

    def test_customer_page_has_lifecycle_filters_and_search(self) -> None:
        """页面提供完整分类、搜索框及授权/部署数量列。"""
        html = (ROOT / "console" / "portal" / "index.html").read_text()

        self.assertIn('id="customer-search"', html)
        for stage in (
            "all",
            "unlicensed",
            "pending_deploy",
            "deployed",
            "disabled",
        ):
            self.assertIn(f'data-customer-stage="{stage}"', html)
        self.assertIn("授权 / 部署", html)

    def test_customer_lifecycle_is_derived_from_real_progress(self) -> None:
        """停用优先，其余依次按实例数和 KEY 数判断生命周期。"""
        javascript = (ROOT / "console" / "portal" / "portal.js").read_text()

        self.assertIn("function customerLifecycle(oem)", javascript)
        self.assertIn('code: "unlicensed", label: "未获授权"', javascript)
        self.assertIn('code: "pending_deploy", label: "待部署"', javascript)
        self.assertIn('code: "deployed", label: "已部署"', javascript)
        self.assertIn('code: "disabled", label: "已停用"', javascript)
        self.assertIn("oem.instances_deployed", javascript)
        self.assertIn("oem.keys_claimed", javascript)

    def test_search_and_filters_render_without_server_round_trip(self) -> None:
        """搜索与分类使用当前脱敏快照即时重绘。"""
        javascript = (ROOT / "console" / "portal" / "portal.js").read_text()

        self.assertIn("function renderAdminCustomers()", javascript)
        self.assertIn(
            '$("#customer-search").addEventListener("input", renderAdminCustomers)',
            javascript,
        )
        self.assertIn("button.dataset.customerStage", javascript)


if __name__ == "__main__":
    unittest.main()
