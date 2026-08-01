"""工作流聊天命令 + 运行记录入库的单元测试（mock 连接器执行，不联网）。

运行：.venv/bin/python -m unittest cosmac.tests.test_wf_cmd
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import WORKFLOWS_EVENT_TYPE, CosmacConfig
from cosmac.members import GatingStore, MembersStore
from cosmac.db import init_engine, session_scope
from cosmac.db.wf_repo import recent_runs

CTRL = "!ctrl:host"
ROOM = "!grp:host"
WF = {"slug": "cover", "name": "封面生成", "platform": "webhook",
      "url": "https://n8n/x", "input_hint": "描述封面", "enabled": True}


class FakeClient:
    def __init__(self, workflows):
        self._wf = workflows
        self.sent = []  # 记录发出的文本(给回调测试看)

    def set_displayname(self, *_a, **_k): pass
    def send_text(self, room, text, txn_id=None):
        self.sent.append((room, text))
        return "$e"
    def resolve_alias(self, _a): return CTRL
    def joined_member_count(self, _r): return 5
    def get_state_event(self, _room, etype, _sk="") -> Any:
        if etype == WORKFLOWS_EVENT_TYPE:
            return {"workflows": self._wf}
        if etype == "m.room.power_levels":
            # 默认把测试发送者都当管理员（这些用例验证执行逻辑，不验权限）
            return {"users_default": 100}
        return None


def _bot(workflows=None) -> CosmacBot:
    # control_room_alias 非空：run_workflow 工具据此找控制室（FakeClient.resolve_alias 忽略实参）
    # public_url 非空：异步连接器据此拼回调地址
    bot = CosmacBot(CosmacConfig(
        llm_provider="echo", control_room_alias="#cosmac-ctrl:host",
        public_url="https://hs.example.invalid",
    ))
    bot.client = FakeClient(workflows if workflows is not None else [WF])
    bot._reply_pool = None  # 同步模式:事件路径测试要立刻看到回复(并发修复后默认线程池)
    bot.toolbox = bot.toolbox.__class__(bot.client, control_room_alias="#cosmac-ctrl:host")
    # 测试里的权限/门控都走同一个假 client，禁止误连本机 Synapse。
    bot.members = MembersStore(bot.client, bot.config.control_room_alias)
    bot.gating = GatingStore(bot.client, bot.config.control_room_alias, ttl=0)
    return bot


class TestWfCommand(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        # 同步连接器现在走有界后台池（#4/#5）。测试里让 submit_background **同步**执行，
        # 便于断言结果（否则线程异步、不确定）。
        p = mock.patch("cosmac.wf.submit_background",
                       lambda fn, **_k: (fn(), True)[1])
        p.start()
        self.addCleanup(p.stop)

    def test_detect(self) -> None:
        b = _bot()
        self.assertTrue(b._is_wf_command("工作流 列表"))
        self.assertTrue(b._is_wf_command("/wf run x"))
        self.assertFalse(b._is_wf_command("工作 安排"))

    def test_list(self) -> None:
        out = _bot()._run_wf_command(ROOM, "@u:host", "工作流 列表")
        self.assertIn("cover", out)
        self.assertIn("封面生成", out)

    def test_run_requires_admin(self) -> None:
        # #1/#2 越权：非平台管理员(控制室 power<50)跑工作流被挡（DM 也不放行）；列表仍可看
        bot = _bot()
        bot.client.get_state_event = lambda _r, etype, _sk="": (
            {"workflows": [WF]} if etype == WORKFLOWS_EVENT_TYPE
            else {"users": {"@u:host": 0}, "users_default": 0}  # 非管理员
        )
        out = bot._run_wf_command(ROOM, "@u:host", "工作流 跑 cover 测试")
        # workflow_run 门控默认「仅平台管理员」，非管理员被挡（文案由门控统一生成）
        self.assertIn("仅平台管理员", out)
        # 查看不受限
        self.assertIn("cover", bot._run_wf_command(ROOM, "@u:host", "工作流 列表"))

    def test_run_success_and_records(self) -> None:
        bot = _bot()
        with mock.patch("cosmac.wf.run_connector",
                        return_value={"ok": True, "output": "封面已生成: http://img"}):
            out = bot._run_wf_command(ROOM, "@u:host", "工作流 跑 cover 科技感蓝色")
        self.assertIn("已开始", out)  # 立即返回"已开始"
        # 结果由后台发回群（setUp 让后台同步执行）
        self.assertTrue(any("封面已生成" in t for _r, t in bot.client.sent))
        # 运行记录入库
        with session_scope() as s:
            runs = recent_runs(s, slug="cover")
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0].status, "ok")
            self.assertIn("科技感蓝色", runs[0].input)

    def test_same_event_workflow_command_not_submitted_twice(self) -> None:
        # appservice 事务重放同一 Matrix event 时，外部工作流不能重复提交。
        bot = _bot()
        with mock.patch(
            "cosmac.wf.run_connector",
            return_value={"ok": True, "output": "ok"},
        ) as m:
            bot._run_wf_command(
                ROOM, "@u:host", "工作流 跑 cover x", source_key="event:$same:cmd:wf"
            )
            bot._run_wf_command(
                ROOM, "@u:host", "工作流 跑 cover x", source_key="event:$same:cmd:wf"
            )
        self.assertEqual(m.call_count, 1)

    def test_run_failure_records_error(self) -> None:
        bot = _bot()
        with mock.patch("cosmac.wf.run_connector",
                        return_value={"ok": False, "error": "平台返回 500", "output": ""}):
            out = bot._run_wf_command(ROOM, "@u:host", "工作流 跑 cover x")
        self.assertIn("已开始", out)
        # 失败由后台发回群
        self.assertTrue(any("执行失败" in t for _r, t in bot.client.sent))
        with session_scope() as s:
            self.assertEqual(recent_runs(s, slug="cover")[0].status, "error")

    def test_run_unknown_slug(self) -> None:
        out = _bot()._run_wf_command(ROOM, "@u:host", "工作流 跑 nope hi")
        self.assertIn("没找到", out)

    def test_no_connectors(self) -> None:
        out = _bot(workflows=[])._run_wf_command(ROOM, "@u:host", "工作流 列表")
        self.assertIn("还没有", out)

    def test_async_submit_creates_pending(self) -> None:
        bot = _bot(workflows=[{**WF, "async": True}])
        with mock.patch("cosmac.wf.run_connector", return_value={"ok": True}) as m:
            out = bot._run_wf_command(ROOM, "@u:host", "工作流 跑 cover 蓝色")
        self.assertIn("已提交", out)
        # 提交时带了回调 URL
        self.assertIn("/cosmac/wf/callback/", m.call_args[1]["callback_url"])
        # 落了一条 pending 记录(带 token)
        with session_scope() as s:
            runs = recent_runs(s, slug="cover")
            self.assertEqual(runs[0].status, "pending")
            self.assertTrue(runs[0].token)

    def test_callback_posts_result_and_completes(self) -> None:
        bot = _bot(workflows=[{**WF, "async": True}])
        with mock.patch("cosmac.wf.run_connector", return_value={"ok": True}) as m:
            bot._run_wf_command(ROOM, "@u:host", "工作流 跑 cover x")
        # #2：回调 URL **完全不含 token**；明文 token 在 payload 的 callback_token 里
        self.assertNotIn("token", m.call_args[1]["callback_url"])
        tok = m.call_args[1]["callback_token"]
        with session_scope() as s:
            run = recent_runs(s, slug="cover")[0]
            rid = run.id
            self.assertNotEqual(run.token, tok)  # DB 存的是哈希、不是明文
        # 正确 token → 200，结果发回原群，状态结清
        code = bot.handle_wf_callback(rid, tok, {"output": "成片已生成: http://v"})
        self.assertEqual(code, 200)
        self.assertTrue(any("成片已生成" in t for _r, t in bot.client.sent))
        with session_scope() as s:
            self.assertEqual(recent_runs(s, slug="cover")[0].status, "ok")
        # 重放(已 ok)→ **幂等 200**，不重复发
        before = len(bot.client.sent)
        self.assertEqual(bot.handle_wf_callback(rid, tok, {"output": "再来"}), 200)
        self.assertEqual(len(bot.client.sent), before)  # 没有再发一条

    def test_callback_send_fail_keeps_pending(self) -> None:
        # #6：回调发消息失败时**不能结清** run（否则 token 清空、平台重试得 404、结果永久丢）
        bot = _bot(workflows=[{**WF, "async": True}])
        with mock.patch("cosmac.wf.run_connector", return_value={"ok": True}) as m:
            bot._run_wf_command(ROOM, "@u:host", "工作流 跑 cover x")
        tok = m.call_args[1]["callback_token"]
        with session_scope() as s:
            rid = recent_runs(s, slug="cover")[0].id
        bot.client.send_text = lambda *_a, **_k: None  # 模拟发送失败
        code = bot.handle_wf_callback(rid, tok, {"output": "成片"})
        self.assertEqual(code, 500)
        with session_scope() as s:
            self.assertEqual(recent_runs(s, slug="cover")[0].status, "pending")  # 仍可重试

    def test_txn_dedup_persists_across_restart(self) -> None:
        # #2/#3：重启(新 bot 实例、内存空)后，DB 去重仍能识别 Synapse 重放的事务
        bot1 = _bot()
        self.assertTrue(bot1.handle_transaction("txn-xyz", []))  # 处理一次 → 落库 done
        bot2 = _bot()  # 模拟重启：内存 _seen_txns 空
        self.assertNotIn("txn-xyz", bot2._seen_txns)
        # 重放：claim 应判定 done → 跳过且回 200(True)，绝不重处理
        self.assertEqual(bot2._claim_txn("txn-xyz"), "done")
        self.assertTrue(bot2.handle_transaction("txn-xyz", []))

    def test_txn_event_error_is_not_marked_done(self) -> None:
        # 单条事件异常时不能 finish_txn；否则 Synapse 不再重试，失败事件永久丢。
        bot = _bot()
        bot._handle_event = mock.Mock(side_effect=RuntimeError("boom"))  # type: ignore
        self.assertFalse(bot.handle_transaction("txn-fail", [{"event_id": "$e"}]))
        self.assertEqual(bot._claim_txn("txn-fail"), "inflight")

    def test_txn_claim_is_atomic(self) -> None:
        # #2：claim_txn 原子抢占——同一 txn 第一次 claimed、第二次（未过期）inflight，不会双claimed
        from cosmac.db.dedup import claim_txn

        with session_scope() as s:
            self.assertEqual(claim_txn(s, "t-atomic"), "claimed")
        with session_scope() as s:
            self.assertEqual(claim_txn(s, "t-atomic"), "inflight")  # 处理中、未过期 → 让位

    def test_txn_stale_reclaim(self) -> None:
        # #3：处理中途崩溃留下的 processing 过期后可被重新抢占（不永久丢）
        from datetime import datetime, timedelta

        from cosmac.db.dedup import _STALE_SECONDS, claim_txn
        from cosmac.db.models import SeenTxn

        with session_scope() as s:
            self.assertEqual(claim_txn(s, "t-stale"), "claimed")
        # 手动把 claimed_at 推到过期（模拟崩溃后久未完成）
        with session_scope() as s:
            row = s.get(SeenTxn, "t-stale")
            row.claimed_at = datetime.utcnow() - timedelta(seconds=_STALE_SECONDS + 10)
        with session_scope() as s:
            self.assertEqual(claim_txn(s, "t-stale"), "claimed")  # 过期残留 → 重新抢到

    def test_dedup_schema_self_heals(self) -> None:
        # 升级路径：老库 cosmac_seen_txn 只有 txn_id 列 → 自愈应 DROP 重建出新列
        from sqlalchemy import inspect, text

        from cosmac.db import get_engine
        from cosmac.db.engine import _heal_ephemeral_schema

        eng = get_engine()
        with eng.begin() as c:  # 伪造老库（仅 txn_id）
            c.execute(text("DROP TABLE IF EXISTS cosmac_seen_txn"))
            c.execute(text("CREATE TABLE cosmac_seen_txn (txn_id VARCHAR(255) PRIMARY KEY)"))
        have = {col["name"] for col in inspect(eng).get_columns("cosmac_seen_txn")}
        self.assertNotIn("done", have)  # 老库缺列
        _heal_ephemeral_schema(eng)  # 自愈
        cols = {col["name"] for col in inspect(eng).get_columns("cosmac_seen_txn")}
        self.assertIn("done", cols)
        self.assertIn("claimed_at", cols)

    def test_workflow_schema_adds_new_columns_without_drop(self) -> None:
        # 老库 workflow_run 缺 token/source_key 时应补列，并保留已有历史行。
        from sqlalchemy import inspect, text

        from cosmac.db import get_engine
        from cosmac.db.engine import _heal_business_schema

        eng = get_engine()
        with eng.begin() as c:
            c.execute(text("DROP TABLE IF EXISTS cosmac_workflow_run"))
            c.execute(text(
                "CREATE TABLE cosmac_workflow_run ("
                "id INTEGER PRIMARY KEY, slug VARCHAR(128) NOT NULL, "
                "platform VARCHAR(32) NOT NULL, room_id VARCHAR(255) NOT NULL, "
                "sender VARCHAR(255) NOT NULL, input TEXT NOT NULL, "
                "output TEXT NOT NULL, error TEXT NOT NULL, "
                "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
            ))
            c.execute(text(
                "INSERT INTO cosmac_workflow_run "
                "(id, slug, platform, room_id, sender, input, output, error, created_at, updated_at) "
                "VALUES (1, 'old', 'webhook', '!r', '@u', 'i', 'o', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
        _heal_business_schema(eng)
        cols = {col["name"] for col in inspect(eng).get_columns("cosmac_workflow_run")}
        self.assertIn("token", cols)
        self.assertIn("source_key", cols)
        with eng.connect() as c:
            rows = list(c.execute(text("SELECT slug FROM cosmac_workflow_run WHERE id=1")))
        self.assertEqual(rows[0][0], "old")

    def test_recover_interrupted_runs(self) -> None:
        # 启动时把上次遗留的久未执行 queued 结清为 error 并通知群。
        from datetime import datetime, timedelta

        from cosmac.db.models import WorkflowRun
        from cosmac.db.wf_repo import _ORPHAN_GRACE_SECONDS, create_pending, get_run

        with session_scope() as s:
            r = create_pending(
                s, slug="cover", platform="webhook", room_id=ROOM,
                sender="@u:host", user_input="x", token="h",
            )
            rid = r.id
        # 推到宽限期外，模拟"上次进程久前留下的遗孤"（#1：新近的不该被回收）
        with session_scope() as s:
            s.get(WorkflowRun, rid).updated_at = (
                datetime.utcnow() - timedelta(seconds=_ORPHAN_GRACE_SECONDS + 60)
            )
        bot = _bot()
        bot.recover_interrupted_runs()
        with session_scope() as s:
            self.assertEqual(get_run(s, rid).status, "error")
        self.assertTrue(any("提交队列中断" in t for _r, t in bot.client.sent))

    def test_release_pending_source_allows_retry(self) -> None:
        # 池满提交失败时回滚来源预约：删掉 queued 占位，让同一事件能重新预约。
        from cosmac.db.wf_repo import (
            create_pending,
            find_by_source_key,
            release_pending_source,
        )

        SK = "event:$same:ai"
        with session_scope() as s:
            create_pending(
                s, slug="cover", platform="webhook", room_id=ROOM,
                sender="@u:host", user_input="x", token="", source_key=SK,
            )
        # 预约已登记 → 再查得到（不回滚的话重试会被误判"已触发过"）
        with session_scope() as s:
            self.assertIsNotNone(find_by_source_key(s, SK))
        # 回滚后 → queued 占位被删，来源键可重新预约
        with session_scope() as s:
            release_pending_source(s, SK)
        with session_scope() as s:
            self.assertIsNone(find_by_source_key(s, SK))

    def test_release_pending_source_spares_started_run(self) -> None:
        # 只删 queued：已开始外呼(pending/processing)或已结清的绝不能删，否则丢回调/重复结算。
        from cosmac.db.wf_repo import (
            create_pending,
            find_by_source_key,
            mark_submission_started,
            release_pending_source,
        )

        SK = "event:$started:ai"
        with session_scope() as s:
            r = create_pending(
                s, slug="cover", platform="webhook", room_id=ROOM,
                sender="@u:host", user_input="x", token="tok", source_key=SK,
            )
            mark_submission_started(s, r.id)  # queued → pending（已外呼）
        with session_scope() as s:
            release_pending_source(s, SK)  # 不该删 pending
        with session_scope() as s:
            self.assertIsNotNone(find_by_source_key(s, SK))

    def test_reclaim_orphans_grace_spares_recent(self) -> None:
        # #1：新近的 pending 不回收（外部平台可能仍在跑、稍后回调；回收会误杀+双扣费）
        from datetime import datetime, timedelta

        from cosmac.db.models import WorkflowRun
        from cosmac.db.wf_repo import (
            _ORPHAN_GRACE_SECONDS, create_pending, get_run, mark_submission_started,
            reclaim_orphans,
        )

        with session_scope() as s:
            recent = create_pending(
                s, slug="recent", platform="webhook", room_id=ROOM,
                sender="@u:host", user_input="x", token="h1",
            )
            old = create_pending(
                s, slug="old", platform="webhook", room_id=ROOM,
                sender="@u:host", user_input="x", token="h2",
            )
            waiting = create_pending(
                s, slug="waiting", platform="webhook", room_id=ROOM,
                sender="@u:host", user_input="x", token="h3",
            )
            mark_submission_started(s, waiting.id)
            recent_id, old_id, waiting_id = recent.id, old.id, waiting.id
        with session_scope() as s:  # 只把 old 推到宽限期外
            s.get(WorkflowRun, old_id).updated_at = (
                datetime.utcnow() - timedelta(seconds=_ORPHAN_GRACE_SECONDS + 60)
            )
            # 外部平台已接收的 pending 即使同样很旧，也必须继续等合法回调。
            s.get(WorkflowRun, waiting_id).updated_at = (
                datetime.utcnow() - timedelta(days=2)
            )
        with session_scope() as s:
            ids = {rid for rid, _slug, _room, _reason in reclaim_orphans(s)}
        self.assertIn(old_id, ids)          # 久的被回收
        self.assertNotIn(recent_id, ids)    # 新的留着等回调
        self.assertNotIn(waiting_id, ids)   # 已提交的慢任务绝不按固定时长误杀
        with session_scope() as s:
            self.assertEqual(get_run(s, old_id).status, "error")
            self.assertEqual(get_run(s, recent_id).status, "queued")
            self.assertEqual(get_run(s, waiting_id).status, "pending")

    def test_pending_callback_timeout_is_configurable(self) -> None:
        """超过配置期限的 pending 会收口，避免平台永不回调时永久残留。"""
        from datetime import datetime, timedelta

        from cosmac.db.models import WorkflowRun
        from cosmac.db.wf_repo import (
            create_pending, get_run, mark_submission_started, reclaim_orphans,
        )

        with session_scope() as s:
            run = create_pending(
                s, slug="lost", platform="webhook", room_id=ROOM,
                sender="@u:host", user_input="x", token="h",
            )
            mark_submission_started(s, run.id)
            rid = run.id
        with session_scope() as s:
            s.get(WorkflowRun, rid).updated_at = datetime.utcnow() - timedelta(hours=2)
        with mock.patch.dict("os.environ", {"COSMAC_WF_CALLBACK_TIMEOUT": "3600"}):
            with session_scope() as s:
                rows = reclaim_orphans(s)
        self.assertEqual(rows[0][3], "等待外部平台回调超时")
        with session_scope() as s:
            self.assertEqual(get_run(s, rid).status, "error")

    def test_seen_txn_lru_bounded(self) -> None:
        # #2：内存去重有界，不会无限增长
        bot = _bot()
        for i in range(bot._SEEN_TXN_MAX + 200):
            bot._remember_txn(f"t{i}")
        self.assertLessEqual(len(bot._seen_txns), bot._SEEN_TXN_MAX)

    def test_async_non_webhook_not_dispatched(self) -> None:
        # #3：async=true 但平台 comfyui → 不走回调协议(不挂 pending)，按后台跑
        wf2 = {"slug": "img", "name": "图", "platform": "comfyui",
               "url": "http://c", "graph": "{}", "async": True, "enabled": True}
        bot = _bot(workflows=[wf2])
        with mock.patch("cosmac.wf.run_connector",
                        return_value={"ok": True, "output": ""}):
            out = bot._run_wf_command(ROOM, "@u:host", "工作流 跑 img x")
        self.assertIn("已开始", out)  # 后台，不是"已提交"
        with session_scope() as s:
            pend = [r for r in recent_runs(s, slug="img") if r.status == "pending"]
            self.assertEqual(pend, [])  # 没有永久等不到回调的 pending

    def test_async_submit_exception_keeps_pending_and_warns(self) -> None:
        # 外呼异常可能发生在平台接单之后，保留 pending/token，避免立即重试导致双扣费。
        bot = _bot(workflows=[{**WF, "async": True}])
        with mock.patch("cosmac.wf.run_connector", side_effect=RuntimeError("boom")):
            bot._run_wf_command(ROOM, "@u:host", "工作流 跑 cover x")
        with session_scope() as s:
            self.assertEqual(recent_runs(s, slug="cover")[0].status, "pending")
        self.assertTrue(any("提交结果未知" in t for _r, t in bot.client.sent))

    def test_atomic_claim_only_once(self) -> None:
        # #3：claim_pending 原子 CAS——只有一个并发回调能把 pending 抢成 processing
        from cosmac.db.wf_repo import claim_pending, create_pending, mark_submission_started
        with session_scope() as s:
            rid = create_pending(s, slug="x", platform="webhook", room_id=ROOM,
                                 sender="@u:host", user_input="i", token="h").id
            mark_submission_started(s, rid)
        with session_scope() as s:
            self.assertTrue(claim_pending(s, rid))   # 抢到
        with session_scope() as s:
            self.assertFalse(claim_pending(s, rid))  # 再抢失败（已 processing）

    def test_stale_processing_reclaimable(self) -> None:
        # #2：卡在 processing 超时的运行（上次半途崩了）可被后续回调重抢，不会永久卡死
        from datetime import datetime, timedelta

        from cosmac.db.models import WorkflowRun
        from cosmac.db.wf_repo import claim_pending, create_pending, mark_submission_started
        with session_scope() as s:
            rid = create_pending(s, slug="x", platform="webhook", room_id=ROOM,
                                 sender="@u:host", user_input="i", token="h").id
            mark_submission_started(s, rid)
        with session_scope() as s:
            self.assertTrue(claim_pending(s, rid))   # pending→processing
        with session_scope() as s:
            self.assertFalse(claim_pending(s, rid))  # 刚抢的不可立刻重抢
        with session_scope() as s:  # 把它做旧 → 视为卡死
            s.get(WorkflowRun, rid).updated_at = datetime.utcnow() - timedelta(hours=1)
        with session_scope() as s:
            self.assertTrue(claim_pending(s, rid))   # 卡死的可被重抢（崩溃恢复）

    def test_callback_bad_token_403(self) -> None:
        bot = _bot(workflows=[{**WF, "async": True}])
        with mock.patch("cosmac.wf.run_connector", return_value={"ok": True}):
            bot._run_wf_command(ROOM, "@u:host", "工作流 跑 cover x")
        with session_scope() as s:
            rid = recent_runs(s, slug="cover")[0].id
        self.assertEqual(bot.handle_wf_callback(rid, "wrong", {"output": "x"}), 403)

    def test_callback_unknown_run_404(self) -> None:
        self.assertEqual(_bot().handle_wf_callback(999999, "t", {"output": "x"}), 404)

    def test_ai_tool_async_delegates_to_dispatch(self) -> None:
        # #1：async 连接器经 AI 工具走回调协议(dispatch_async)，不是当普通后台任务跑
        from cosmac.ai.base import ToolCall
        from cosmac.ai.tools import ToolContext
        bot = _bot(workflows=[{**WF, "async": True}])
        called = []
        bot.toolbox.dispatch_async = lambda *a: (called.append(a), "⏳ 已提交")[1]
        out = bot.toolbox.execute(
            ToolCall(id="t", name="run_workflow",
                     arguments={"slug": "cover", "input": "x"}),
            ToolContext(ROOM, "@u:host"))
        self.assertIn("已提交", out)
        self.assertEqual(len(called), 1)  # 走了异步分派，没当普通后台任务

    def test_run_workflow_ai_tool(self) -> None:
        # 主 AI 工具路径：现在**所有连接器都后台跑**（#1），工具立即返回"已开始"，
        # 结果由后台发回群（setUp 让 submit_background 同步执行）。
        from cosmac.ai.base import ToolCall
        from cosmac.ai.tools import ToolContext
        bot = _bot()
        ctx = ToolContext(ROOM, "@u:host")
        with mock.patch("cosmac.wf.run_connector",
                        return_value={"ok": True, "output": "图已生成"}):
            out = bot.toolbox.execute(
                ToolCall(id="t", name="run_workflow",
                         arguments={"slug": "cover", "input": "蓝色"}), ctx)
        self.assertIn("已开始", out)
        self.assertTrue(any("图已生成" in t for _r, t in bot.client.sent))
        # 不带 slug → 返回可用列表
        out2 = bot.toolbox.execute(
            ToolCall(id="t2", name="run_workflow", arguments={}), ctx)
        self.assertIn("cover", out2)


if __name__ == "__main__":
    unittest.main()
