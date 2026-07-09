"""人事花名册（HR）演示数据播种脚本。

用途：给「数据智能 / 人事问答」演示灌一批**自洽、像真的**虚拟员工数据，让主 AI 的
``query_hr`` 工具有数据可查。造的是一家虚构科技公司「星澜科技」（约 50 人）：
多部门、职级与薪资挂钩、绩效按分布、入职时间横跨数年且含近期新人/试用期/少量离职。

设计：
- **确定性**：用固定随机种子 ``random.Random(20250709)``，同一天重跑得到同一批人，
  便于反复演示、排查。日期锚定「运行当天」，好让「本月请假/加班」「近半年入离职」有意义。
- **幂等**：按 ``emp_no`` upsert（存在则更新、不存在则插入），重复跑不产生重复人。
- 可直接跑：``python -m cosmac.db.seed_hr``（会先 ``init_db(create_all=True)`` 建表）。

⚠️ 全是**虚拟数据**，姓名/手机/邮箱均为编造，仅供演示。
"""

from __future__ import annotations

import argparse
import logging
import random
from datetime import date, timedelta
from typing import Any, Dict, List

from sqlalchemy import select

from cosmac.db import init_engine, session_scope
from cosmac.db.models import Employee

logger = logging.getLogger(__name__)

# —— 公司抬头（虚构）——
COMPANY = "星澜科技"

# 固定随机种子：保证可复现（同一运行日 → 同一批人）
_RNG = random.Random(20250709)

# 姓氏 / 名字池——组合出中文全名（够多以避免重名）
_SURNAMES = list("王李张刘陈杨黄赵吴周徐孙马朱胡林郭何高罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢")
_GIVEN = [
    "伟", "芳", "娜", "秀英", "敏", "静", "丽", "强", "磊", "洋", "艳", "勇", "军",
    "杰", "娟", "涛", "明", "超", "秀兰", "霞", "平", "刚", "桂英", "浩", "晨", "宇",
    "婷", "雪", "璐", "睿", "楠", "鑫", "博", "轩", "悦", "萌", "琪", "凯", "文", "斌",
]

# 工作城市分布（一线为主 + 少量远程）
_CITIES = ["北京", "上海", "深圳", "杭州", "广州", "成都", "远程"]
# 学历分布
_EDU = ["本科", "本科", "本科", "硕士", "硕士", "大专", "博士"]

# —— 职级 → 基础月薪（元）——
_LEVEL_BASE = {
    "P4": 14000, "P5": 20000, "P6": 28000, "P7": 40000, "P8": 55000,
    "M1": 35000, "M2": 55000, "M3": 82000,
}
# —— 部门 → 薪资系数（体现行业差异：研发偏高、职能偏低）——
_DEPT_MULT = {
    "研发部": 1.12, "产品部": 1.05, "销售部": 1.0, "市场部": 0.95,
    "设计部": 0.92, "运营部": 0.9, "人力资源部": 0.9, "财务部": 0.95,
    "高管办公室": 1.0,
}

# 绩效评级分布权重（S 少、B 多、C 尾部）
_PERF_POOL = (["S"] * 10) + (["A"] * 35) + (["B"] * 45) + (["C"] * 10)

# —— 部门编制表：(部门, [(职位, 职级)...], 需要人数) ——
# 每个部门第一条通常是负责人（M 序列），后面是成员。
_DEPT_PLAN: List[Dict[str, Any]] = [
    {
        "dept": "高管办公室",
        "roster": [
            ("首席执行官 CEO", "M3"),
            ("首席技术官 CTO", "M3"),
            ("首席运营官 COO", "M3"),
            ("首席财务官 CFO", "M3"),
        ],
    },
    {
        "dept": "研发部",
        "roster": [
            ("技术总监", "M2"),
            ("后端研发经理", "M1"),
            ("前端研发经理", "M1"),
            ("资深后端工程师", "P7"),
            ("后端工程师", "P6"),
            ("后端工程师", "P5"),
            ("资深前端工程师", "P7"),
            ("前端工程师", "P6"),
            ("前端工程师", "P5"),
            ("算法工程师", "P7"),
            ("算法工程师", "P6"),
            ("测试工程师", "P5"),
            ("测试工程师", "P4"),
            ("运维工程师", "P6"),
            ("数据工程师", "P6"),
            ("研发工程师", "P4"),
        ],
    },
    {
        "dept": "产品部",
        "roster": [
            ("产品总监", "M2"),
            ("高级产品经理", "P7"),
            ("产品经理", "P6"),
            ("产品经理", "P5"),
            ("产品助理", "P4"),
        ],
    },
    {
        "dept": "设计部",
        "roster": [
            ("设计主管", "M1"),
            ("视觉设计师", "P6"),
            ("UI 设计师", "P5"),
            ("交互设计师", "P5"),
        ],
    },
    {
        "dept": "市场部",
        "roster": [
            ("市场总监", "M2"),
            ("品牌经理", "P6"),
            ("市场专员", "P5"),
            ("内容营销专员", "P4"),
            ("活动策划", "P4"),
        ],
    },
    {
        "dept": "销售部",
        "roster": [
            ("销售总监", "M2"),
            ("大客户经理", "P7"),
            ("大客户经理", "P6"),
            ("销售代表", "P5"),
            ("销售代表", "P4"),
            ("销售运营", "P4"),
        ],
    },
    {
        "dept": "运营部",
        "roster": [
            ("运营经理", "M1"),
            ("内容运营", "P5"),
            ("用户运营", "P5"),
            ("社群运营", "P4"),
            ("运营专员", "P4"),
        ],
    },
    {
        "dept": "人力资源部",
        "roster": [
            ("人力资源经理", "M1"),
            ("招聘专员", "P5"),
            ("HRBP", "P5"),
        ],
    },
    {
        "dept": "财务部",
        "roster": [
            ("财务经理", "M1"),
            ("会计", "P6"),
            ("出纳", "P5"),
        ],
    },
]


def _full_name(used: set) -> str:
    """随机生成一个未用过的中文全名。"""
    for _ in range(200):
        name = _RNG.choice(_SURNAMES) + "".join(
            _RNG.sample(_GIVEN, _RNG.choice([1, 1, 2]))
        )
        if name not in used:
            used.add(name)
            return name
    # 极端兜底：加序号
    n = f"员工{len(used)}"
    used.add(n)
    return n


def _salary(level: str, dept: str) -> int:
    """按 职级基础 × 部门系数 × ±8% 抖动，取整到百元。"""
    base = _LEVEL_BASE.get(level, 15000)
    mult = _DEPT_MULT.get(dept, 1.0)
    jitter = _RNG.uniform(0.92, 1.08)
    val = base * mult * jitter
    return int(round(val / 100.0)) * 100


def build_employees(today: date) -> List[Dict[str, Any]]:
    """按编制表生成全部员工字典（不落库，纯内存构造，便于测试）。"""
    used_names: set = set()
    people: List[Dict[str, Any]] = []
    emp_seq = 1001

    for plan in _DEPT_PLAN:
        dept = plan["dept"]
        roster = plan["roster"]
        head_name = ""  # 该部门负责人姓名（第一条），成员的汇报对象
        for idx, (title, level) in enumerate(roster):
            name = _full_name(used_names)
            emp_no = f"C{emp_seq}"
            emp_seq += 1

            # 入职日期：高管/负责人偏早（1~5 年），成员随机 0~4 年
            if level.startswith("M"):
                days_ago = _RNG.randint(400, 1900)
            else:
                days_ago = _RNG.randint(20, 1500)
            hire = today - timedelta(days=days_ago)

            # 状态：入职 < 75 天算试用期；另有极少数标记为已离职
            status = "active"
            resign_date = ""
            if days_ago < 75:
                status = "probation"

            # 汇报关系：部门负责人（第一条）汇报给 CEO；成员汇报给负责人
            if dept == "高管办公室":
                manager = "" if "CEO" in title else "（CEO）"
                if idx == 0:
                    head_name = name  # CEO
            else:
                if idx == 0:
                    head_name = name
                    manager = "（CEO）"
                else:
                    manager = head_name

            # 绩效：试用期暂无评级
            perf = "" if status == "probation" else _RNG.choice(_PERF_POOL)

            # 年假：按司龄粗略给 5~15 天，已用随机
            al_total = min(15, 5 + days_ago // 365 * 2)
            al_used = _RNG.randint(0, al_total)

            # 本月考勤：请假 0~4 天、加班 0~40 小时（研发/销售偏多）
            ot_bias = 12 if dept in ("研发部", "销售部") else 0
            people.append({
                "emp_no": emp_no,
                "name": name,
                "gender": _RNG.choice(["男", "女"]),
                "department": dept,
                "title": title,
                "level": level,
                "manager": manager,
                "hire_date": hire.isoformat(),
                "status": status,
                "resign_date": resign_date,
                "city": _RNG.choice(_CITIES),
                "salary": _salary(level, dept),
                "perf_rating": perf,
                "annual_leave_total": al_total,
                "annual_leave_used": al_used,
                "leave_days_month": _RNG.choice([0, 0, 0, 1, 1, 2, 3]),
                "overtime_hours_month": max(0, _RNG.randint(0, 30) + ot_bias
                                            - _RNG.randint(0, 8)),
                "education": _RNG.choice(_EDU),
                "birth_date": (today - timedelta(
                    days=_RNG.randint(23, 45) * 365 + _RNG.randint(0, 364)
                )).isoformat(),
                "email": f"{emp_no.lower()}@xinglan.example",
                "phone": f"138{_RNG.randint(10000000, 99999999)}",
            })

    # —— 制造 3 名「近半年离职」样本（从非负责人、非试用期里挑）——
    candidates = [p for p in people
                  if not p["level"].startswith("M")
                  and p["status"] == "active"]
    for p in _RNG.sample(candidates, k=min(3, len(candidates))):
        p["status"] = "resigned"
        p["perf_rating"] = ""
        rd = today - timedelta(days=_RNG.randint(15, 170))
        p["resign_date"] = rd.isoformat()

    return people


def seed(today: date | None = None) -> int:
    """把生成的员工数据 upsert 进 DB；返回写入的总条数。"""
    init_engine(create_all=True)  # 确保 cosmac_employee 表存在
    day = today or date.today()
    people = build_employees(day)
    written = 0
    with session_scope() as s:
        for p in people:
            row = s.scalars(
                select(Employee).where(Employee.emp_no == p["emp_no"]).limit(1)
            ).first()
            if row is None:
                row = Employee(emp_no=p["emp_no"])
                s.add(row)
            for k, v in p.items():
                setattr(row, k, v)
            written += 1
    logger.info("已播种 %d 名员工（公司=%s）", written, COMPANY)
    return written


def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="人事花名册演示数据播种")
    ap.add_argument("--dry-run", action="store_true", help="只打印统计、不写库")
    args = ap.parse_args()

    if args.dry_run:
        people = build_employees(date.today())
        deps: Dict[str, int] = {}
        for p in people:
            deps[p["department"]] = deps.get(p["department"], 0) + 1
        print(f"[dry-run] 将生成 {len(people)} 名员工（{COMPANY}）:")
        for d, c in deps.items():
            print(f"  - {d}: {c} 人")
        return

    n = seed()
    print(f"✅ 已播种 {n} 名员工到 cosmac DB（公司：{COMPANY}）。")


if __name__ == "__main__":
    _main()
