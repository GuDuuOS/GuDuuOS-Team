"""会员等级（cosmac.members）的回归测试。

覆盖：
  - 纯逻辑：normalize/label/level/parse 的脏数据兜底；
  - MembersStore：读 map / 查等级 / 授予 / 撤销（用假 client，断言写回的 state 内容）；
  - bot 会员命令：普通人查自己、非管理员被挡、管理员设置/撤销/列表。
"""

from __future__ import annotations

import os
import unittest
from typing import Any, Dict, Optional

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig
from cosmac.config import GATING_EVENT_TYPE, MEMBERS_EVENT_TYPE, PLANS_EVENT_TYPE
from cosmac.db import init_engine
from cosmac.members import (
    DEFAULT_TIER,
    GATE_ADMIN,
    TIER_CREATOR,
    TIER_FREE,
    TIER_PAID,
    GatingStore,
    MembersStore,
    gate_rank,
    normalize_tier,
    parse_gates,
    parse_members,
    tier_label,
    tier_level,
)

CTRL = "!ctrl:guduu.local"
BOT = "@guduu:guduu.local"
ADMIN = "@admin:guduu.local"
ALICE = "@alice:guduu.local"
BOB = "@bob:guduu.local"


def setUpModule() -> None:
    # manual 渠道现在 fail-closed：没配密钥就不可用。给测试配一个，才能验签跑通业务链。
    os.environ["COSMAC_PAY_MANUAL_SECRET"] = "test-manual-secret"


class FakeClient:
    """假 client：内存存 state event + power_levels，记录写入，便于断言。"""

    def __init__(self, alias_room: Optional[str], ctrl_admin: bool = True):
        self._alias_room = alias_room
        # 控制室成员谁有 power（_is_platform_admin 读这个）
        self._power = {BOT: 100}
        if ctrl_admin:
            self._power[ADMIN] = 50
        self._state: Dict[str, Dict[str, Any]] = {}  # event_type → content
        self.sent: list = []

    def resolve_alias(self, _alias: str) -> Optional[str]:
        return self._alias_room

    def whoami(self, access_token):
        # 测试里把 token 当 user_id 用：非空且像 user_id 就认；"bad" 视为无效
        return access_token if (access_token or "").startswith("@") else None

    def get_state_event(self, _room, event_type, _state_key=""):
        if event_type == "m.room.power_levels":
            return {"users": dict(self._power)}
        return self._state.get((event_type, _state_key), self._state.get(event_type))

    def get_room_state(self, _room):
        """把内存 state 展开成 Matrix room state 数组，覆盖单用户 state_key 场景。"""
        events = []
        for key, content in self._state.items():
            if isinstance(key, tuple):
                event_type, state_key = key
            else:
                event_type, state_key = key, ""
            events.append({"type": event_type, "state_key": state_key, "content": content})
        return events

    def set_state_event(self, _room, event_type, content, _state_key="") -> bool:
        # 模拟 Matrix 硬规则：state_key 以 @ 开头的事件只有本人能写——bot(@guduu)写别人的会 403。
        # （会员等级若用 @uid 当 state_key 就会撞这条；故用去 @ 的 key，见 member_state_key）
        if _state_key.startswith("@"):
            return False
        self._state[(event_type, _state_key)] = content
        return True

    def send_text(self, _room, text, txn_id=None):
        self.sent.append(text)
        return "$evt"

    def joined_member_count(self, _room) -> int:
        return 2  # 当私聊处理（不影响会员命令）

    def set_displayname(self, *_a, **_k):
        pass


def _store(alias_room=CTRL) -> MembersStore:
    return MembersStore(FakeClient(alias_room), "#cosmac-ctrl:guduu.local")


def _bot(ctrl_admin=True, alias_room=CTRL, gates=None) -> CosmacBot:
    bot = CosmacBot(CosmacConfig(llm_provider="echo"))
    fake = FakeClient(alias_room, ctrl_admin=ctrl_admin)
    if gates is not None:
        fake._state[GATING_EVENT_TYPE] = {"gates": gates}
    bot.client = fake
    # MembersStore/GatingStore 持有的是构造时的 client，要替换成同一个 fake。
    # GatingStore ttl=0：测试里每次都重读，避免缓存掩盖刚设的门控。
    bot.members = MembersStore(fake, bot.config.control_room_alias)
    bot.gating = GatingStore(fake, bot.config.control_room_alias, ttl=0)
    return bot


class PureLogicTests(unittest.TestCase):
    def test_normalize_unknown_to_free(self):
        self.assertEqual(normalize_tier("paid"), TIER_PAID)
        self.assertEqual(normalize_tier("nonsense"), DEFAULT_TIER)
        self.assertEqual(normalize_tier(None), DEFAULT_TIER)
        self.assertEqual(normalize_tier(""), DEFAULT_TIER)

    def test_label_and_level(self):
        self.assertEqual(tier_label("paid"), "付费会员")
        self.assertEqual(tier_label("bogus"), "免费会员")
        self.assertGreater(tier_level(TIER_CREATOR), tier_level(TIER_PAID))
        self.assertGreater(tier_level(TIER_PAID), tier_level(DEFAULT_TIER))

    def test_parse_drops_free_and_garbage(self):
        content = {
            "members": {
                ALICE: {"tier": "paid"},
                BOB: {"tier": "free"},        # 免费=默认，丢弃
                "not-a-user": {"tier": "paid"},  # 非法 key，丢弃
                "@c:guduu.local": {"tier": "junk"},  # 非法 tier → 规整成 free → 丢弃
            }
        }
        out = parse_members(content)
        self.assertEqual(set(out.keys()), {ALICE})
        self.assertEqual(out[ALICE]["tier"], TIER_PAID)

    def test_parse_empty(self):
        self.assertEqual(parse_members(None), {})
        self.assertEqual(parse_members({}), {})
        self.assertEqual(parse_members({"members": "x"}), {})


class MembersStoreTests(unittest.TestCase):
    def test_grant_writes_state(self):
        s = _store()
        self.assertTrue(s.grant(ALICE, TIER_PAID, now_ts=123))
        mp = s.get_all()
        self.assertEqual(mp[ALICE]["tier"], TIER_PAID)
        self.assertEqual(mp[ALICE]["updated_ts"], 123)
        self.assertEqual(s.get_tier(ALICE), TIER_PAID)
        # 未授予的人默认免费
        self.assertEqual(s.get_tier(BOB), DEFAULT_TIER)

    def test_grant_invalid_tier_rejected(self):
        s = _store()
        self.assertFalse(s.grant(ALICE, "vip"))
        self.assertEqual(s.get_tier(ALICE), DEFAULT_TIER)

    def test_free_grant_is_revoke(self):
        s = _store()
        s.grant(ALICE, TIER_CREATOR)
        self.assertEqual(s.get_tier(ALICE), TIER_CREATOR)
        self.assertTrue(s.revoke(ALICE))
        self.assertEqual(s.get_tier(ALICE), DEFAULT_TIER)
        self.assertNotIn(ALICE, s.get_all())

    def test_no_control_room(self):
        s = _store(alias_room=None)
        self.assertFalse(s.grant(ALICE, TIER_PAID))
        self.assertEqual(s.get_all(), {})

    def test_grant_does_not_need_legacy_read(self):
        # 单用户 state 写入不再依赖读取旧整表；即使旧聚合读取失败也不会覆盖其他会员。
        fake = FakeClient(CTRL)
        fake._state[MEMBERS_EVENT_TYPE] = {
            "members": {ALICE: {"tier": "paid"}, BOB: {"tier": "creator"}}
        }
        store = MembersStore(fake, "#cosmac-ctrl:guduu.local")
        real_get = fake.get_state_event

        def boom(room, et, sk=""):  # 让"读会员"瞬时失败（区别于 404→None）
            if et == MEMBERS_EVENT_TYPE:
                raise RuntimeError("network down")
            return real_get(room, et, sk)

        fake.get_state_event = boom
        self.assertTrue(store.grant("@c:guduu.local", TIER_PAID))
        fake.get_state_event = real_get  # 恢复读，确认原数据没被覆盖
        self.assertEqual(set(store.get_all().keys()), {ALICE, BOB, "@c:guduu.local"})

    def test_grant_first_member_when_absent(self):
        # 事件不存在(get_state_event→None) 是合法空表，正常写入第一个会员（不被 #2 误伤）
        s = _store()  # 全新、还没写过 members
        self.assertTrue(s.grant(ALICE, TIER_PAID))
        self.assertEqual(s.get_tier(ALICE), TIER_PAID)


class BotCommandTests(unittest.TestCase):
    def test_self_check_default_free(self):
        bot = _bot()
        out = bot._run_member_command(ALICE, "会员")
        self.assertIn("免费会员", out)

    def test_non_admin_cannot_set(self):
        bot = _bot()
        out = bot._run_member_command(ALICE, "会员 设置 @bob:guduu.local 付费")
        self.assertIn("只有平台管理员", out)
        self.assertEqual(bot.members.get_tier(BOB), DEFAULT_TIER)

    def test_admin_set_and_revoke(self):
        bot = _bot()
        out = bot._run_member_command(ADMIN, "会员 设置 @alice:guduu.local 创作者")
        self.assertIn("创作者会员", out)
        self.assertEqual(bot.members.get_tier(ALICE), TIER_CREATOR)
        # 自查反映新等级
        self.assertIn("创作者会员", bot._run_member_command(ALICE, "会员"))
        # 撤销
        out = bot._run_member_command(ADMIN, "会员 撤销 @alice:guduu.local")
        self.assertIn("免费会员", out)
        self.assertEqual(bot.members.get_tier(ALICE), DEFAULT_TIER)

    def test_admin_set_unknown_tier(self):
        bot = _bot()
        out = bot._run_member_command(ADMIN, "会员 设置 @alice:guduu.local 钻石")
        self.assertIn("未知等级", out)

    def test_admin_list(self):
        bot = _bot()
        bot.members.grant(ALICE, TIER_PAID)
        out = bot._run_member_command(ADMIN, "会员 列表")
        self.assertIn(ALICE, out)
        self.assertIn("付费会员", out)

    def test_command_detection(self):
        bot = _bot()
        self.assertTrue(bot._is_member_command("会员"))
        self.assertTrue(bot._is_member_command("我的会员"))
        self.assertTrue(bot._is_member_command("member"))
        self.assertFalse(bot._is_member_command("会议安排"))

    def test_grant_member_tier_reserved_entry(self):
        bot = _bot()
        self.assertTrue(bot.grant_member_tier(BOB, TIER_PAID))
        self.assertEqual(bot.members.get_tier(BOB), TIER_PAID)
        # 来源记为 purchase（区别于管理员手动）
        self.assertEqual(bot.members.get_all()[BOB]["source"], "purchase")


class GatingPureTests(unittest.TestCase):
    def test_gate_rank_order(self):
        self.assertLess(gate_rank(TIER_FREE), gate_rank(TIER_PAID))
        self.assertLess(gate_rank(TIER_PAID), gate_rank(TIER_CREATOR))
        self.assertLess(gate_rank(TIER_CREATOR), gate_rank(GATE_ADMIN))
        self.assertEqual(gate_rank("junk"), 0)

    def test_parse_gates_validates(self):
        content = {"gates": {
            "ai_chat": "paid",        # ok
            "knowledge": "diamond",   # 非法门槛 → 丢
            "bogus_cap": "paid",      # 非法能力 → 丢
            "workflow_run": "admin",  # ok
        }}
        out = parse_gates(content)
        self.assertEqual(out, {"ai_chat": "paid", "workflow_run": "admin"})

    def test_gating_store_defaults_and_override(self):
        fake = FakeClient(CTRL)
        store = GatingStore(fake, "#cosmac-ctrl:guduu.local", ttl=0)
        # 默认：ai_chat 免费、workflow_run 仅管理员
        self.assertEqual(store.required("ai_chat"), TIER_FREE)
        self.assertEqual(store.required("workflow_run"), GATE_ADMIN)
        # 覆盖后生效
        fake._state[GATING_EVENT_TYPE] = {"gates": {"ai_chat": "creator"}}
        self.assertEqual(store.required("ai_chat"), TIER_CREATOR)

    def test_gating_retries_after_read_failure(self):
        # 首读失败 fail-closed，并在短退避后重试；故障期不会放开也不会每条消息打服务器。
        fake = FakeClient(CTRL)
        real = fake.get_state_event
        calls = {"n": 0}

        def flaky(room, et, sk=""):
            if et == GATING_EVENT_TYPE:
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("blip")          # 首读失败
                return {"gates": {"ai_chat": "paid"}}   # 之后成功
            return real(room, et, sk)

        fake.get_state_event = flaky
        store = GatingStore(
            fake, "#cosmac-ctrl:guduu.local", ttl=60, retry_backoff=0
        )
        self.assertEqual(store.required("ai_chat"), GATE_ADMIN)
        self.assertEqual(store.required("ai_chat"), TIER_PAID)

    def test_gating_failure_backoff_avoids_request_storm(self):
        """退避期内重复读取不再访问 Matrix，并持续使用保守策略。"""
        fake = FakeClient(CTRL)
        calls = {"n": 0}

        def boom(*_args):
            calls["n"] += 1
            raise RuntimeError("down")

        fake.get_state_event = boom
        store = GatingStore(fake, "#cosmac-ctrl:guduu.local", ttl=0, retry_backoff=60)
        self.assertEqual(store.required("ai_chat"), GATE_ADMIN)
        self.assertEqual(store.required("ai_chat"), GATE_ADMIN)
        self.assertEqual(calls["n"], 1)

    def test_gating_warm(self):
        # #3：启动预热建立缓存
        fake = FakeClient(CTRL)
        fake._state[GATING_EVENT_TYPE] = {"gates": {"ai_chat": "paid"}}
        store = GatingStore(fake, "#cosmac-ctrl:guduu.local", ttl=60)
        self.assertTrue(store.warm())
        self.assertEqual(store.required("ai_chat"), TIER_PAID)


class GateDecisionTests(unittest.TestCase):
    def test_free_gate_allows_everyone(self):
        bot = _bot(gates={"knowledge": "free"})
        self.assertTrue(bot._gate_allows(ALICE, "knowledge"))

    def test_paid_gate_blocks_free_user(self):
        bot = _bot(gates={"knowledge": "paid"})
        self.assertFalse(bot._gate_allows(ALICE, "knowledge"))  # ALICE 默认免费
        bot.members.grant(ALICE, TIER_PAID)
        self.assertTrue(bot._gate_allows(ALICE, "knowledge"))

    def test_creator_gate_needs_creator(self):
        bot = _bot(gates={"create_room": "creator"})
        bot.members.grant(ALICE, TIER_PAID)
        self.assertFalse(bot._gate_allows(ALICE, "create_room"))  # 付费 < 创作者
        bot.members.grant(ALICE, TIER_CREATOR)
        self.assertTrue(bot._gate_allows(ALICE, "create_room"))

    def test_platform_admin_bypasses_tier_gate(self):
        bot = _bot(gates={"knowledge": "creator"})
        # ADMIN 是平台管理员(power 50)，即便没有会员等级也放行
        self.assertTrue(bot._gate_allows(ADMIN, "knowledge"))

    def test_admin_gate_only_platform_admin(self):
        bot = _bot(gates={"workflow_run": "admin"})
        self.assertTrue(bot._gate_allows(ADMIN, "workflow_run"))
        bot.members.grant(ALICE, TIER_CREATOR)  # 即便创作者也过不了 admin 门
        self.assertFalse(bot._gate_allows(ALICE, "workflow_run"))

    def test_tool_gate_check_maps_and_denies(self):
        bot = _bot(gates={"create_room": "paid"})
        # 免费用户被工具门控拦下（返回拒绝文案）
        denial = bot._tool_gate_check(ALICE, "create_room")
        self.assertIsNotNone(denial)
        self.assertIn("付费会员", denial)
        # 不在映射表里的工具不门控
        self.assertIsNone(bot._tool_gate_check(ALICE, "list_room_members"))
        # 付费后放行
        bot.members.grant(ALICE, TIER_PAID)
        self.assertIsNone(bot._tool_gate_check(ALICE, "create_room"))

    def test_kb_command_gated(self):
        bot = _bot(gates={"knowledge": "paid"})
        out = bot._run_kb_command(CTRL, ALICE, "知识 列表")
        self.assertIn("付费会员", out)  # 免费用户被门控拦下、给升级提示


class PayEndpointTests(unittest.TestCase):
    """模块4：bot 的 /cosmac/pay/* 端点处理器（前端「升级会员」走这几个）。"""

    def setUp(self):
        init_engine("sqlite://", create_all=True)

    def _paybot(self):
        from cosmac.trading.service import OrderService

        bot = _bot()  # fake client + members 都在 fake 上
        # bot.orders 是构造时用旧 client 建的，替换成 fake 上的
        bot.orders = OrderService(bot.members, bot.client, bot.config.control_room_alias)
        bot.client._state[(PLANS_EVENT_TYPE, "")] = {"plans": [
            {"slug": "paid-monthly", "name": "月卡", "tier": "paid",
             "period_days": 30, "prices": {"usd": 999}}]}
        return bot

    @staticmethod
    def _body(order_no, token):
        import json
        return json.dumps({"order_no": order_no, "token": token}).encode("utf-8")

    def test_plans_checkout_manual_grant(self):
        import os

        bot = self._paybot()
        self.assertEqual(bot.handle_pay_plans()[0]["slug"], "paid-monthly")  # 公开读

        code, out = bot.handle_pay_checkout(
            ALICE, {"plan_slug": "paid-monthly", "currency": "usd", "provider": "manual"}
        )
        self.assertEqual(code, 200)
        order_no = out["order_no"]
        token = out["checkout"]["extra"]["confirm_token"]

        os.environ.pop("COSMAC_PAY_ALLOW_MANUAL", None)
        # manual 回调默认禁用（防自助白嫖会员）→ 403，会员未开通
        self.assertEqual(bot.handle_pay_callback("manual", {}, self._body(order_no, token)), 403)
        self.assertEqual(bot.members.get_tier(ALICE), DEFAULT_TIER)
        # 开启测试开关后 → 200 且会员真开通
        os.environ["COSMAC_PAY_ALLOW_MANUAL"] = "1"
        try:
            self.assertEqual(
                bot.handle_pay_callback("manual", {}, self._body(order_no, token)), 200
            )
        finally:
            os.environ.pop("COSMAC_PAY_ALLOW_MANUAL", None)
        self.assertEqual(bot.members.get_tier(ALICE), TIER_PAID)

    def test_checkout_bad_token_rejected(self):
        bot = self._paybot()
        code, _out = bot.handle_pay_checkout("bad", {"plan_slug": "paid-monthly", "currency": "usd"})
        self.assertEqual(code, 401)  # whoami 不过 → 拒绝下单

    def test_stats_endpoint(self):
        # 数据看板真实指标：全平台聚合，**仅平台管理员**可读。
        bot = self._paybot()
        bot.members.grant(ALICE, TIER_PAID)
        # 普通登录用户（非控制室管理员）→ 403，不泄露平台运营数据
        self.assertEqual(bot.handle_stats(ALICE)[0], 403)
        # 平台管理员 → 200 且字段齐
        code, out = bot.handle_stats(ADMIN)
        self.assertEqual(code, 200)
        self.assertEqual(out["members_paid"], 1)
        for k in ("members_creator", "workflow_runs", "orders_paid", "kb_docs"):
            self.assertIn(k, out)
        self.assertEqual(bot.handle_stats("bad")[0], 401)  # 无效 token → 401

    def test_tasks_flow(self):
        # AI 任务编排 P1：拆任务工具 → 列表 → 改状态（手动）
        from cosmac.ai.tools import ToolContext

        bot = self._paybot()
        res = bot.toolbox._tool_create_tasks(
            {"goal": "做个爆款视频", "tasks": [
                {"title": "定选题", "assignee": "编剧"},
                {"title": "拍摄", "assignee": "@anqi:host"},
                {"title": "", "assignee": "x"},  # 空标题 → 丢弃
            ]},
            ToolContext(room_id="!r:host", sender=ALICE),
        )
        self.assertIn("2 个任务", res)  # 空标题被丢，落 2 条
        code, out = bot.handle_tasks_list(ALICE)
        self.assertEqual(code, 200)
        self.assertEqual(len(out["tasks"]), 2)
        tid = out["tasks"][0]["id"]
        self.assertEqual(bot.handle_task_update(ALICE, {"id": tid, "status": "done"})[0], 200)
        _c, out2 = bot.handle_tasks_list(ALICE)
        done = next(t for t in out2["tasks"] if t["id"] == tid)
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["progress"], 100)  # done 自动补满进度
        self.assertEqual(bot.handle_tasks_list("bad")[0], 401)  # 无效 token

    def test_tasks_visible_only_to_assignee(self):
        # QA:被拉进专班的成员打开看板看到了所有人的任务——收紧后:
        # 下达者看自己项目全部;执行者只看派给自己的;无关成员(即便同房间)看不到。
        from cosmac.ai.tools import ToolContext

        bot = self._paybot()
        bot.toolbox._tool_create_tasks(
            {"goal": "电影节活动", "tasks": [
                {"title": "写文案", "assignee": "copywriter",
                 "executor_kind": "agent", "executor_ref": "copywriter"},
                {"title": "备物料", "assignee": "chengsp (后勤)",
                 "executor_kind": "human", "executor_ref": "@chengsp:host"},
                {"title": "复盘", "assignee": "planner"},
            ]},
            ToolContext(room_id="!team:host", sender=ALICE),
        )
        # 下达者:全部 3 条
        self.assertEqual(len(bot.handle_tasks_list(ALICE)[1]["tasks"]), 3)
        # 执行者:只有派给自己的那条(executor_ref 精确匹配)
        _c, mine = bot.handle_tasks_list("@chengsp:host")
        self.assertEqual([t["title"] for t in mine["tasks"]], ["备物料"])
        # 无关用户:0 条(不再按"同房间"放行)
        self.assertEqual(len(bot.handle_tasks_list("@stranger:host")[1]["tasks"]), 0)


if __name__ == "__main__":
    unittest.main()
