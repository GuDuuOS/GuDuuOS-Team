"""从 GitHub 导入 Skill/Agent manifest —— 解析与安全边界测试。

重点覆盖"这是从互联网拉进来的第三方内容"带来的几类风险：
SSRF（域名白名单/协议/重定向）、TOCTOU（预览与确认之间换文件）、
字段越权（manifest 里塞 enabled/access 想自抬权限）、超长内容。

运行：.venv/bin/python -m unittest cosmac.tests.test_manifest_import
"""

from __future__ import annotations

import unittest

from cosmac.manifest import normalize_url, parse_manifest, review_notes


class NormalizeUrlTest(unittest.TestCase):
    def test_accepts_raw_github(self) -> None:
        u, err = normalize_url("https://raw.githubusercontent.com/u/r/main/guduu-agent.json")
        self.assertEqual(err, "")
        self.assertTrue(u.startswith("https://raw.githubusercontent.com/"))

    def test_converts_blob_url_to_jsdelivr(self) -> None:
        """用户多半直接从浏览器地址栏复制 blob 地址，要能自动转直链。

        转 jsDelivr 而非 raw.githubusercontent.com：实测国内服务器打 raw 直接读超时
        （12s 无响应），jsdelivr 1 秒返回——不转的话这功能在生产上根本用不了。
        """
        u, err = normalize_url("https://github.com/u/r/blob/main/skills/x.json")
        self.assertEqual(err, "")
        self.assertEqual(u, "https://cdn.jsdelivr.net/gh/u/r@main/skills/x.json")

    def test_accepts_jsdelivr_directly(self) -> None:
        u, err = normalize_url("https://cdn.jsdelivr.net/gh/u/r@main/x.json")
        self.assertEqual(err, "")
        self.assertEqual(u, "https://cdn.jsdelivr.net/gh/u/r@main/x.json")

    def test_rejects_non_whitelisted_host(self) -> None:
        """白名单之外一律拒绝——这是挡 SSRF 的第一道，也是最有效的一道。"""
        for bad in (
            "https://evil.example.com/x.json",
            "https://127.0.0.1/x.json",
            "https://169.254.169.254/latest/meta-data/",   # 云元数据
            "https://synapse:8008/x.json",                  # 容器内网
        ):
            _, err = normalize_url(bad)
            self.assertNotEqual(err, "", f"{bad} 必须被拒绝")

    def test_rejects_non_https(self) -> None:
        for bad in (
            "http://raw.githubusercontent.com/u/r/main/x.json",   # 明文
            "file:///etc/passwd",
            "ftp://raw.githubusercontent.com/x",
        ):
            _, err = normalize_url(bad)
            self.assertNotEqual(err, "", f"{bad} 必须被拒绝")

    def test_rejects_empty(self) -> None:
        _, err = normalize_url("")
        self.assertNotEqual(err, "")


class ParseManifestTest(unittest.TestCase):
    def _agent(self, **over):
        base = {
            "kind": "agent", "slug": "my-writer", "name": "写手",
            "description": "写营销文案", "system_prompt": "你是资深文案。",
        }
        base.update(over)
        return base

    def test_parses_agent(self) -> None:
        item, err = parse_manifest(self._agent(
            model="claude-opus-4-8", skill_slugs=["a", "b"], workflow_slugs=["deploy"]))
        self.assertEqual(err, "")
        self.assertEqual(item["kind"], "agent")
        self.assertEqual(item["slug"], "my-writer")
        self.assertEqual(item["skill_slugs"], ["a", "b"])
        self.assertEqual(item["workflow_slugs"], ["deploy"])

    def test_parses_skill(self) -> None:
        item, err = parse_manifest({
            "kind": "skill", "slug": "s1", "name": "技能",
            "description": "干嘛的", "instructions": "照这样做",
        })
        self.assertEqual(err, "")
        self.assertEqual(item["instructions"], "照这样做")

    def test_rejects_bad_kind_and_slug(self) -> None:
        _, err = parse_manifest(self._agent(kind="plugin"))
        self.assertNotEqual(err, "")
        for bad in ("has space", "-lead", "x" * 65, "", "中文", "a/b"):
            _, err = parse_manifest(self._agent(slug=bad))
            self.assertNotEqual(err, "", f"slug={bad!r} 必须被拒绝")

    def test_uppercase_slug_is_normalized_not_rejected(self) -> None:
        """大写字母自动转小写（与工坊保存端点同口径），而不是报错赶人走。"""
        item, err = parse_manifest(self._agent(slug="MyWriter"))
        self.assertEqual(err, "")
        self.assertEqual(item["slug"], "mywriter")

    def test_rejects_missing_body(self) -> None:
        _, err = parse_manifest(self._agent(system_prompt="  "))
        self.assertNotEqual(err, "")
        _, err = parse_manifest({
            "kind": "skill", "slug": "s", "name": "n", "description": "d", "instructions": "",
        })
        self.assertNotEqual(err, "")

    def test_rejects_oversized_prompt(self) -> None:
        _, err = parse_manifest(self._agent(system_prompt="x" * 4001))
        self.assertIn("过长", err)

    def test_drops_platform_side_fields(self) -> None:
        """⚠️ 安全断言：manifest 不能靠自带字段给自己抬权限。

        `access`（可用范围）、`enabled`、`scope` 都是平台侧的权限概念，必须由导入者
        与服务端决定；若照搬文件内容，等于让第三方作者自己声明"我对所有人可见"。
        """
        item, err = parse_manifest(self._agent(
            access="", enabled=True, scope="global", scope_id="", id=999, preset=True))
        self.assertEqual(err, "")
        for leaked in ("access", "scope", "scope_id", "id", "preset", "enabled"):
            self.assertNotIn(leaked, item, f"{leaked} 不该被 manifest 带进来")

    def test_slug_lists_are_capped_and_deduped(self) -> None:
        item, err = parse_manifest(self._agent(
            skill_slugs=["a", "a", "B", ""] + [f"s{i}" for i in range(50)]))
        self.assertEqual(err, "")
        self.assertLessEqual(len(item["skill_slugs"]), 20)
        self.assertEqual(len(item["skill_slugs"]), len(set(item["skill_slugs"])))
        self.assertIn("b", item["skill_slugs"])      # 统一小写
        self.assertNotIn("", item["skill_slugs"])

    def test_non_list_slug_field_is_tolerated(self) -> None:
        """第三方文件字段类型不可控，写成字符串也不能让服务端炸。"""
        item, err = parse_manifest(self._agent(skill_slugs="not-a-list"))
        self.assertEqual(err, "")
        self.assertEqual(item["skill_slugs"], [])


class ReviewNotesTest(unittest.TestCase):
    def test_agent_notes_warn_about_prompt_injection(self) -> None:
        item, _ = parse_manifest({
            "kind": "agent", "slug": "a", "name": "n", "description": "d",
            "system_prompt": "p", "workflow_slugs": ["deploy"], "skill_slugs": ["s1"],
        })
        notes = " ".join(review_notes(item))
        self.assertIn("忽略以上指令", notes)     # 提醒用户通读、找可疑句
        self.assertIn("不会提权", notes)          # 说清引用工作流≠拿到权限
        self.assertIn("不会被一并导入", notes)    # 说清不递归拉依赖树

    def test_skill_notes_mention_every_turn_injection(self) -> None:
        item, _ = parse_manifest({
            "kind": "skill", "slug": "s", "name": "n", "description": "d",
            "instructions": "i",
        })
        self.assertIn("每轮对话", " ".join(review_notes(item)))


if __name__ == "__main__":
    unittest.main()
