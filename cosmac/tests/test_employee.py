"""人事花名册（HR / 数据智能）单元测试：seed 生成 + repo 聚合 + query_hr 工具 + 门控。

内存 SQLite、零 key。运行：.venv/bin/python -m unittest cosmac.tests.test_employee
"""

from __future__ import annotations

import json
import unittest
from datetime import date

from cosmac.ai.base import ToolCall
from cosmac.ai.tools import Toolbox, ToolContext
from cosmac.db import init_engine, session_scope
from cosmac.db import employee_repo as hr
from cosmac.db.seed_hr import build_employees, seed


class TestSeedAndRepo(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        # 锚定固定日期，保证「近期入职/趋势」这类时间相关断言稳定
        self._n = seed(today=date(2026, 7, 9))

    def test_seed_is_deterministic_and_idempotent(self) -> None:
        # 同参生成两次应完全一致（固定随机种子）
        a = build_employees(date(2026, 7, 9))
        b = build_employees(date(2026, 7, 9))
        self.assertEqual([p["emp_no"] for p in a], [p["emp_no"] for p in b])
        # 幂等：重复 seed 不新增人（按工号 upsert）
        again = seed(today=date(2026, 7, 9))
        with session_scope() as s:
            self.assertEqual(len(hr.list_employees(s, limit=999)), self._n)
        self.assertEqual(again, self._n)

    def test_summary_and_headcount(self) -> None:
        with session_scope() as s:
            summ = hr.company_summary(s)
            self.assertGreater(summ["在职人数"], 30)
            self.assertGreater(summ["部门数"], 5)
            hc = hr.headcount(s, group_by="department")
            self.assertEqual(hc["维度"], "department")
            # 研发部人数最多（编制表如此设计）
            self.assertEqual(hc["分组"][0]["名称"], "研发部")

    def test_salary_and_performance(self) -> None:
        with session_scope() as s:
            sal = hr.salary_stats(s, group_by="department")
            self.assertGreater(sal["整体"]["平均月薪"], 0)
            # 高管办公室平均薪资应为各部门最高
            self.assertEqual(sal["分组"][0]["名称"], "高管办公室")
            perf = hr.perf_distribution(s)
            ratings = {b["评级"] for b in perf["分布"]}
            self.assertEqual(ratings, {"S", "A", "B", "C"})

    def test_ranking_and_trend(self) -> None:
        with session_scope() as s:
            top = hr.top_by(s, field="salary", n=3)
            self.assertEqual(len(top["排行榜"]), 3)
            # 榜首月薪 >= 榜末
            self.assertGreaterEqual(
                int(top["排行榜"][0]["指标"].split()[0]),
                int(top["排行榜"][-1]["指标"].split()[0]),
            )
            tr = hr.joins_leaves(s, months=6)
            self.assertLessEqual(len(tr["趋势"]), 6)


class TestQueryHrTool(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        seed(today=date(2026, 7, 9))
        self.tb = Toolbox(None)
        self.ctx = ToolContext("!r:h", "@alice:h", is_dm=True)

    def _call(self, args: dict) -> str:
        return self.tb.execute(ToolCall(id="1", name="query_hr", arguments=args), self.ctx)

    def test_tool_actions_return_valid_json(self) -> None:
        for args in (
            {"action": "summary"},
            {"action": "headcount", "group_by": "city"},
            {"action": "salary", "group_by": "department"},
            {"action": "performance"},
            {"action": "ranking", "field": "salary", "top_n": 3},
            {"action": "trend", "months": 6},
        ):
            out = self._call(args)
            data = json.loads(out)  # 必须是合法 JSON
            self.assertIn("查询", data)

    def test_find_requires_keyword(self) -> None:
        self.assertIn("请给出", self._call({"action": "find"}))
        out = self._call({"action": "find", "keyword": "研发"})
        self.assertIn("按人查档", out)

    def test_gate_denies_when_blocked(self) -> None:
        # 注入门控：拦下 query_hr（映射到 hr_data 能力）
        self.tb.gate_check = lambda sender, tool: "需管理员权限" if tool == "query_hr" else None
        self.assertEqual(self._call({"action": "summary"}), "需管理员权限")


if __name__ == "__main__":
    unittest.main()
