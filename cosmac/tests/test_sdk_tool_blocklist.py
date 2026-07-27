"""SDK 引擎内置工具黑名单 —— 安全回归测试。

背景：`permission_mode="bypassPermissions"` 会放行 CLI 自带的全部内置工具
（Bash / Read / Write…），而 Toolbox 的门控/配额层**只管得到 mcp__cosmac__\* 这些
自定义工具**，对内置工具毫无约束。2026-07-27 线上实报：主 AI 真的在 bot 容器里跑了
十几条 Bash 去下载解压外部包——而那个容器里放着 .env（模型 key / 管理员令牌 /
数据库密码）。

这组测试把黑名单钉死，防止有人日后"顺手删一行"又把口子放开。

运行：.venv/bin/python -m unittest cosmac.tests.test_sdk_tool_blocklist
"""

from __future__ import annotations

import unittest

from cosmac.ai.engine import _SDK_BLOCKED_TOOLS


class SdkToolBlocklistTest(unittest.TestCase):
    def test_shell_execution_is_blocked(self) -> None:
        """能执行命令的工具一个都不能漏——这是最高危的一类。"""
        for name in ("Bash", "BashOutput", "KillShell"):
            self.assertIn(name, _SDK_BLOCKED_TOOLS, f"{name} 必须在黑名单里")

    def test_filesystem_access_is_blocked(self) -> None:
        """读写宿主文件系统同样致命：Read 一个就足以读走 .env 里的全部密钥。"""
        for name in ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit"):
            self.assertIn(name, _SDK_BLOCKED_TOOLS, f"{name} 必须在黑名单里")

    def test_recon_and_escape_hatches_are_blocked(self) -> None:
        """踩点类（Glob/Grep）与可能绕开限制的旁路（Task/SlashCommand/Skill）。

        Skill 会加载并执行 ~/.claude/skills 下的技能，正是本次事故里被误用的那个；
        它对 GuDuu OS 也没有意义——本产品的技能存 DB/state event，不读那个目录。
        """
        for name in ("Glob", "Grep", "Skill", "Task", "SlashCommand"):
            self.assertIn(name, _SDK_BLOCKED_TOOLS, f"{name} 必须在黑名单里")

    def test_web_tools_remain_available(self) -> None:
        """负责人明确要保留联网查资料的能力，别把它们一起误封。

        ⚠️ WebFetch 仍有 SSRF 面（能抓容器内网与云元数据地址），已记 TODO 单独处理；
        这里断言"没被封"是为了忠实反映当前决策，不是说它没有风险。
        """
        for name in ("WebSearch", "WebFetch"):
            self.assertNotIn(name, _SDK_BLOCKED_TOOLS)

    def test_blocklist_is_wired_into_options(self) -> None:
        """光有常量不算数——必须真的传进了 ClaudeAgentOptions。

        直接读源码断言接线，避免"常量定义了、options 里忘了用"这种最容易发生的疏漏
        （构造 options 需要真跑 SDK 子进程，单测里跑不起来）。
        """
        import inspect

        from cosmac.ai import engine

        src = inspect.getsource(engine)
        self.assertIn("disallowed_tools=_SDK_BLOCKED_TOOLS", src)

    def test_no_duplicates(self) -> None:
        self.assertEqual(len(_SDK_BLOCKED_TOOLS), len(set(_SDK_BLOCKED_TOOLS)))


if __name__ == "__main__":
    unittest.main()
