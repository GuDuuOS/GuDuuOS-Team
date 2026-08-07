"""授权码查询页不再暴露手工签发入口的静态回归测试。"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class PortalKeySearchTests(unittest.TestCase):
    """锁住超管授权码区域的查询语义与客户端筛选行为。"""

    def test_page_replaces_manual_issue_form_with_search(self) -> None:
        """页面只能查询已有 KEY，不再呈现数量、额度和签发按钮。"""
        html = (ROOT / "console" / "portal" / "index.html").read_text()

        self.assertIn('id="key-search"', html)
        self.assertIn("授权码查询", html)
        self.assertNotIn('id="form-issue"', html)
        self.assertNotIn('id="issued-box"', html)

    def test_search_uses_only_masked_list_fields(self) -> None:
        """搜索覆盖尾号、企业、邮箱、备注和实例，且不调用签发接口。"""
        javascript = (ROOT / "console" / "portal" / "portal.js").read_text()

        self.assertIn("function renderAdminKeys()", javascript)
        self.assertIn(
            '$("#key-search").addEventListener("input", renderAdminKeys)',
            javascript,
        )
        for field in (
            "key.tail",
            "key.company_name",
            "key.oem_email",
            "key.note",
            "key.instance_id",
        ):
            self.assertIn(field, javascript)
        self.assertNotIn('api("/nexus/admin/keys", {\n      body:', javascript)

    def test_server_rejects_legacy_manual_issue_route(self) -> None:
        """旧 POST 路由必须返回停用错误，不能再调用底层生成函数。"""
        service = (ROOT / "nexus" / "service.py").read_text()
        start = service.rindex('if path == "/nexus/admin/keys":')
        end = service.index('if path == "/nexus/admin/revoke":', start)
        handler = service[start:end]

        self.assertIn("NEXUS_MANUAL_KEY_ISSUE_DISABLED", handler)
        self.assertNotIn("fleet.issue_keys", handler)


if __name__ == "__main__":
    unittest.main()
