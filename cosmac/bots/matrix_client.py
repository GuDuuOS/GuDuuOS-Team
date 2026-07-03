"""对 Synapse 的最小客户端封装（主 AI 的"手"）。

主 AI 通过这里去操作 IM —— 当前只实现了"加入房间"和"发文本消息"两件事，
后续"创建群、查聊天记录、踢人"等能力都会作为新方法加到这里。

实现方式：用 appservice 的 as_token 直接调用 Synapse 的 Client-Server API。
appservice token 的默认身份就是注册文件里的 sender_localpart（即 @guduu）。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests

logger = logging.getLogger("cosmac.matrix_client")


class MatrixClient:
    """以 appservice 身份调用 Synapse 的轻量客户端。"""

    def __init__(self, homeserver_url: str, as_token: str, bot_user_id: str):
        # 去掉末尾斜杠，避免拼出 http://host//_matrix 这种双斜杠
        self.homeserver_url = homeserver_url.rstrip("/")
        self.as_token = as_token
        self.bot_user_id = bot_user_id
        # 安全：as_token 是高权限凭证，**绝不放进 URL 查询参数**（会进 nginx/代理/错误
        # 日志）。改用 Authorization: Bearer 请求头，用一个 Session 统一带上。
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {as_token}"
        # 每房间已加入成员数缓存：上次成功查到的值。查不到（瞬时抖动/5xx）时回退它，
        # 避免本来 2 人的私聊被误判成群聊→bot 因"没被 @"而沉默（可用性 bug）。
        self._member_count_cache: Dict[str, int] = {}

    def _url(self, path: str) -> str:
        """拼出完整的 API URL，只在查询参数里带 user_id（身份标识，非密钥）。

        - user_id：明确以主 AI（@guduu）的身份操作（appservice 可代理其名下用户）。
        - 鉴权（as_token）走 Authorization 头，见 __init__ 的 Session，不进 URL。
        """
        sep = "&" if "?" in path else "?"
        return f"{self.homeserver_url}{path}{sep}user_id={quote(self.bot_user_id)}"

    def _txn_id(self) -> str:
        """生成一个唯一的事务 id（Matrix 要求发送类请求带上，用于去重）。"""
        # 用纳秒时间戳即可保证单进程内唯一
        return f"cosmac{time.time_ns()}"

    def join_room(self, room_id: str) -> None:
        """让主 AI 加入指定房间（通常是被邀请后调用）。"""
        url = self._url(f"/_matrix/client/v3/rooms/{quote(room_id)}/join")
        resp = self._session.post(url, json={}, timeout=10)
        if resp.status_code == 200:
            logger.info("已加入房间 %s", room_id)
        else:
            logger.warning("加入房间 %s 失败: %s %s", room_id, resp.status_code, resp.text)

    def send_text(
        self, room_id: str, text: str, txn_id: Optional[str] = None
    ) -> Optional[str]:
        """以主 AI 身份往房间发一条纯文本消息。

        ``txn_id``：传**固定**事务 id 时，Synapse 据此去重——同一逻辑消息重发(如崩溃恢复后
        重试回调)不会在群里出现两条。不传则每次生成新 id（普通消息）。
        返回：成功时返回服务器分配的 event_id，失败返回 None。
        """
        txn = txn_id or self._txn_id()
        url = self._url(
            f"/_matrix/client/v3/rooms/{quote(room_id)}/send/m.room.message/{txn}"
        )
        body = {"msgtype": "m.text", "body": text}
        # 发送类请求用 PUT（带事务 id 保证幂等）
        resp = self._session.put(url, json=body, timeout=10)
        if resp.status_code == 200:
            event_id = resp.json().get("event_id")
            logger.info("已向房间 %s 发送消息, event_id=%s", room_id, event_id)
            return event_id
        logger.warning("向房间 %s 发消息失败: %s %s", room_id, resp.status_code, resp.text)
        return None

    def edit_text(self, room_id: str, event_id: str, new_text: str) -> bool:
        """编辑自己发过的一条消息(m.replace)。给「AI 执行过程」状态消息原地滚动更新用——
        一条消息反复编辑,而不是每步刷一条新消息把群刷屏。

        wire 格式与前端 editMessage 完全一致(fallback body 带 "* " 前缀,新内容在
        m.new_content),客户端(含我们自己的 listMessages)按编辑聚合渲染。失败返回 False。
        """
        url = self._url(
            f"/_matrix/client/v3/rooms/{quote(room_id)}/send/m.room.message/{self._txn_id()}"
        )
        body = {
            "msgtype": "m.text",
            "body": f"* {new_text}",
            "m.new_content": {"msgtype": "m.text", "body": new_text},
            "m.relates_to": {"rel_type": "m.replace", "event_id": event_id},
        }
        try:
            resp = self._session.put(url, json=body, timeout=10)
            return resp.status_code == 200
        except requests.RequestException:
            logger.debug("编辑消息失败 room=%s", room_id, exc_info=True)
            return False

    def set_typing(self, room_id: str, typing: bool, timeout_ms: int = 30000) -> None:
        """设置主 AI 在房间里的"正在输入…"状态（③ 流式体感）。

        进入可能较慢的 LLM 生成前打开、回复发出后关闭，让用户看到 bot 在干活而非死寂。
        带 ``timeout``：万一进程在生成途中崩了，服务端也会自动过期清除、不会一直卡着输入中。
        best-effort：失败只记日志、绝不影响回复（typing 只是体验增强，不是关键路径）。
        """
        url = self._url(
            f"/_matrix/client/v3/rooms/{quote(room_id)}/typing/{quote(self.bot_user_id)}"
        )
        body: Dict[str, Any] = {"typing": bool(typing)}
        if typing:
            body["timeout"] = timeout_ms  # 仅打开时需要超时；关闭不带
        try:
            self._session.put(url, json=body, timeout=10)
        except requests.RequestException as exc:
            logger.debug("set_typing 失败 room=%s typing=%s: %s", room_id, typing, exc)

    def upload_media(
        self, data: bytes, content_type: str, filename: str = "file"
    ) -> Optional[str]:
        """把二进制内容上传到 Matrix 媒体库，返回 mxc:// 地址（失败 None）。

        用于把外部工作流（如 ComfyUI）生成的图片/视频回传到 IM。鉴权走 Session 的
        Authorization 头；Content-Type 必须是媒体真实类型（不是 json）。
        """
        url = self._url(f"/_matrix/media/v3/upload?filename={quote(filename)}")
        try:
            resp = self._session.post(
                url, data=data, headers={"Content-Type": content_type}, timeout=60
            )
        except requests.RequestException as exc:
            logger.warning("上传媒体异常: %s", exc)
            return None
        if resp.status_code == 200:
            return resp.json().get("content_uri")
        logger.warning("上传媒体失败: %s %s", resp.status_code, resp.text)
        return None

    def send_image(
        self, room_id: str, mxc_url: str, filename: str = "image",
        info: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """往房间发一条图片消息（url 为 upload_media 拿到的 mxc）。成功返回 event_id。"""
        txn = self._txn_id()
        url = self._url(
            f"/_matrix/client/v3/rooms/{quote(room_id)}/send/m.room.message/{txn}"
        )
        body: Dict[str, Any] = {
            "msgtype": "m.image", "body": filename, "url": mxc_url,
        }
        if info:
            body["info"] = info
        resp = self._session.put(url, json=body, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("event_id")
        logger.warning("发图到 %s 失败: %s %s", room_id, resp.status_code, resp.text)
        return None

    def set_displayname(self, displayname: str) -> None:
        """设置主 AI 在 IM 里的显示名（群里用户看到的就是它，而非用户 id）。

        用 appservice 身份调用 Synapse 的 profile API。失败只记日志、不阻断启动
        （比如品牌名改了、重启 bot 一次就会更新成新名字）。

        关键：设置**自己**的 profile 时**不带 `?user_id=` 伪装参数**——直接以 as_token 的
        本体身份（sender_localpart=@guduu）操作。带 user_id 走的是 appservice「代理某用户」
        的 profile 代码路径，在较新 Synapse(1.15x) 上会 500（M_UNKNOWN）；不带则按「设置本人
        profile」处理，正常生效。其它操作（建群/发消息/代发）才需要 user_id 伪装，故只此处特办。
        """
        # 不经 self._url()（那个会追加 user_id 伪装参数），直接拼裸 URL，仅靠 Authorization 头鉴权。
        url = (
            f"{self.homeserver_url}"
            f"/_matrix/client/v3/profile/{quote(self.bot_user_id)}/displayname"
        )
        try:
            resp = self._session.put(url, json={"displayname": displayname}, timeout=10)
            if resp.status_code == 200:
                logger.info("已设置主 AI 显示名: %s", displayname)
            else:
                logger.warning(
                    "设置显示名失败: %s %s（如仍 500，请抓该时刻 Synapse 端日志看堆栈）",
                    resp.status_code, resp.text,
                )
        except requests.RequestException as exc:
            logger.warning("设置显示名异常: %s", exc)

    # —— 主 AI 操作 IM 的能力（"手"）：建群 / 拉人 / 发富卡 ——

    def create_room(self, name: str, invitees: Optional[List[str]] = None) -> Optional[str]:
        """新建一个房间（专班群），可在创建时直接邀请一批用户。

        参数：
            name:     房间显示名（如"爆款专班·职场"）。
            invitees: 创建时就邀请的用户 id 列表（如 ["@admin:cosmac.cc"]）。
        返回：成功返回新房间 room_id，失败返回 None。
        """
        url = self._url("/_matrix/client/v3/createRoom")
        body: Dict[str, Any] = {"name": name, "preset": "private_chat"}
        if invitees:
            body["invite"] = invitees
        resp = self._session.post(url, json=body, timeout=15)
        if resp.status_code == 200:
            room_id = resp.json().get("room_id")
            logger.info("已创建房间 %s (%s)", name, room_id)
            return room_id
        logger.warning("创建房间失败: %s %s", resp.status_code, resp.text)
        return None

    def invite_user(self, room_id: str, user_id: str) -> bool:
        """把某用户邀请进房间。成功返回 True，失败（账号不存在/网络异常等）返回 False、不抛。

        返回布尔让调用方（如 assemble_team 逐个邀请成员）能"尽力而为"：某个 id 邀不到
        不影响其余流程，而不是让一个坏 id 把整件事搞崩。
        """
        url = self._url(f"/_matrix/client/v3/rooms/{quote(room_id)}/invite")
        try:
            resp = self._session.post(url, json={"user_id": user_id}, timeout=10)
        except requests.RequestException as exc:
            logger.warning("邀请 %s 进 %s 异常: %s", user_id, room_id, exc)
            return False
        if resp.status_code == 200:
            logger.info("已邀请 %s 进 %s", user_id, room_id)
            return True
        logger.warning(
            "邀请 %s 进 %s 失败: %s %s", user_id, room_id, resp.status_code, resp.text
        )
        return False

    def set_power_levels(self, room_id: str, content: Dict[str, Any]) -> bool:
        """整体覆盖某房间的 m.room.power_levels 状态事件（调用方负责传完整内容）。

        用于控制室成员对齐——把非管理员从 users 里删掉（回落 users_default=0）。
        需要 bot 在该房有改 power_levels 的权限（控制室里 bot=100，够）。成功返回 True。
        """
        url = self._url(
            f"/_matrix/client/v3/rooms/{quote(room_id)}/state/m.room.power_levels/"
        )
        resp = self._session.put(url, json=content, timeout=10)
        if resp.status_code == 200:
            return True
        logger.warning("设置 power_levels@%s 失败: %s %s", room_id, resp.status_code, resp.text)
        return False

    def kick(self, room_id: str, user_id: str, reason: str = "") -> bool:
        """把某用户踢出房间（控制室对齐时移除已撤销的管理员）。成功返回 True。

        需要 bot 的 power 高于对方且 ≥ kick 等级（控制室里 bot=100，够）。
        """
        url = self._url(f"/_matrix/client/v3/rooms/{quote(room_id)}/kick")
        body: Dict[str, Any] = {"user_id": user_id}
        if reason:
            body["reason"] = reason
        resp = self._session.post(url, json=body, timeout=10)
        if resp.status_code == 200:
            logger.info("已把 %s 踢出 %s", user_id, room_id)
            return True
        logger.warning("踢出 %s@%s 失败: %s %s", user_id, room_id, resp.status_code, resp.text)
        return False

    def send_card(self, room_id: str, body: str, card: Dict[str, Any]) -> Optional[str]:
        """往房间发一条"富卡"消息。

        Matrix 协议不能改，所以用标准 m.room.message 承载：
        - body：纯文本兜底，Element 等不认识富卡的客户端只显示这段文字。
        - cosmac.card：自定义字段（命名空间 cosmac.*，不与协议的 m.* 冲突），
          CosMac 自己的客户端据此把它渲染成结构化富卡。
        返回 event_id 或 None。
        """
        txn = self._txn_id()
        url = self._url(
            f"/_matrix/client/v3/rooms/{quote(room_id)}/send/m.room.message/{txn}"
        )
        payload: Dict[str, Any] = {
            "msgtype": "m.text",
            "body": body,
            "cosmac.card": card,
        }
        resp = self._session.put(url, json=payload, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("event_id")
        logger.warning("发送富卡失败: %s %s", resp.status_code, resp.text)
        return None

    def resolve_alias(self, alias: str) -> Optional[str]:
        """把房间别名（#cosmac-ctrl:host）解析成 room_id。

        语义区分（让调用方能安全回退、不"失效开放"）：
          - 200 → 返回 room_id；
          - 404 → 别名确实不存在 → 返回 None（控制室还没建，属正常）；
          - 其它状态码 / 网络异常 → **抛异常**，让调用方保留上次配置，
            而不是把"读失败"误当成"控制室不存在"。
        """
        url = self._url(f"/_matrix/client/v3/directory/room/{quote(alias)}")
        resp = self._session.get(url, timeout=10)  # 网络异常向上抛
        if resp.status_code == 200:
            return resp.json().get("room_id")
        if resp.status_code == 404:
            return None
        raise RuntimeError(f"解析别名 {alias} 失败: HTTP {resp.status_code}")

    def whoami(self, access_token: str) -> Optional[str]:
        """用**用户自己的** access token 调 whoami，验明身份拿到 user_id（模块4 下单用）。

        前端「升级会员」把登录用户的 token 传来，bot 据此确认"是谁在买"，再给这个人开会员。
        token 只用于这一次校验、绝不存储。无效/网络失败 → None（拒绝下单）。
        **不用** self._session（那带的是 appservice 高权 token），用独立请求带用户 token。
        """
        if not access_token:
            return None
        try:
            resp = requests.get(
                f"{self.homeserver_url}/_matrix/client/v3/account/whoami",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
        except requests.RequestException as e:
            logger.warning("whoami 请求失败: %s", e)
            return None
        if resp.status_code == 200:
            uid = resp.json().get("user_id")
            return uid if isinstance(uid, str) and uid.startswith("@") else None
        return None

    def get_state_event(
        self, room_id: str, event_type: str, state_key: str = ""
    ) -> Optional[Dict[str, Any]]:
        """读某房间的一个 state event 内容（如 AI 配置）。

        需要 bot 已加入该房间。语义区分（避免读失败被当成"没配置"而失效开放）：
          - 200 → 返回内容 dict；
          - 404 → 该房间确实没有这个 state event → 返回 None（正常，无覆盖）；
          - 403/网络错/5xx 等 → **抛异常**，让调用方保留上次成功的配置。
        """
        url = self._url(
            f"/_matrix/client/v3/rooms/{quote(room_id)}/state/"
            f"{quote(event_type)}/{quote(state_key)}"
        )
        resp = self._session.get(url, timeout=10)  # 网络异常向上抛
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 404:
            return None
        raise RuntimeError(
            f"读 state {event_type}@{room_id} 失败: HTTP {resp.status_code}"
        )

    def get_room_state(self, room_id: str) -> List[Dict[str, Any]]:
        """读取房间当前全部 state events。

        会员后台需要枚举 ``cosmac.member`` 的不同 state_key；单事件接口无法列出这些键，
        因此使用 Matrix 标准 ``/rooms/{roomId}/state``。任何非 200 或网络错误都向上抛，
        调用方不能把权限/网络故障误当成空会员表。
        """
        url = self._url(f"/_matrix/client/v3/rooms/{quote(room_id)}/state")
        resp = self._session.get(url, timeout=10)
        if resp.status_code != 200:
            raise RuntimeError(f"读房间 state {room_id} 失败: HTTP {resp.status_code}")
        data = resp.json()
        if not isinstance(data, list):
            raise RuntimeError(f"读房间 state {room_id} 失败: 响应不是数组")
        return data

    def set_state_event(
        self,
        room_id: str,
        event_type: str,
        content: Dict[str, Any],
        state_key: str = "",
    ) -> bool:
        """写某房间的一个 state event（整体覆盖该 (type,state_key) 的内容）。成功返回 True。

        用于 bot 写控制室的 cosmac.* 配置（如 cosmac.members 会员等级）。需要 bot 在该房
        有写该 state 的权限（控制室里 bot=100，够）。失败只记日志、返回 False（调用方据此提示）。
        与 get_state_event 对称；power_levels 那种「需读改写完整内容」的另有 set_power_levels。
        """
        url = self._url(
            f"/_matrix/client/v3/rooms/{quote(room_id)}/state/"
            f"{quote(event_type)}/{quote(state_key)}"
        )
        try:
            resp = self._session.put(url, json=content, timeout=10)
        except requests.RequestException as exc:
            logger.warning("写 state %s@%s 异常: %s", event_type, room_id, exc)
            return False
        if resp.status_code == 200:
            return True
        logger.warning(
            "写 state %s@%s 失败: %s %s", event_type, room_id, resp.status_code, resp.text
        )
        return False

    def get_members(self, room_id: str) -> List[Dict[str, str]]:
        """查房间已加入的成员列表（主 AI 的"眼睛"之一）。

        返回：[{"user_id": "@a:host", "display_name": "Alice"}, ...]；
        查不到返回空列表。
        """
        url = self._url(f"/_matrix/client/v3/rooms/{quote(room_id)}/joined_members")
        try:
            resp = self._session.get(url, timeout=10)
            if resp.status_code == 200:
                joined = resp.json().get("joined", {})
                return [
                    {"user_id": uid, "display_name": info.get("display_name") or uid}
                    for uid, info in joined.items()
                ]
            logger.warning("查成员失败: %s %s", resp.status_code, resp.text)
        except requests.RequestException as exc:
            logger.warning("查成员异常: %s", exc)
        return []

    def is_joined_member(self, room_id: str, user_id: str) -> bool:
        """判断某用户是否已加入某房间（给 AI 工具做跨房间授权）。

        appservice/bot 可能加入了很多房间，但这不代表当前请求人也有权读写这些房间。工具层在
        接受模型传入的 ``room_id`` 前，会用这个方法确认发起人确实是目标房间成员；任何查询
        失败都按未加入处理（fail closed），避免高权限 bot 被当成越权代理。
        """
        url = self._url(
            f"/_matrix/client/v3/rooms/{quote(room_id)}/state/"
            f"m.room.member/{quote(user_id)}"
        )
        try:
            resp = self._session.get(url, timeout=10)
        except requests.RequestException as exc:
            logger.warning("查成员身份异常: %s", exc)
            return False
        if resp.status_code != 200:
            return False
        return resp.json().get("membership") == "join"

    def get_messages(self, room_id: str, limit: int = 20) -> List[Dict[str, str]]:
        """查房间最近的文本消息（主 AI"读聊天记录"的能力）。

        参数：
            room_id: 房间 id。
            limit:   最多取多少条（从最新往回数）。
        返回：按时间正序（旧→新）排列的 [{"sender", "body"}, ...]；查不到返回空列表。
        """
        # dir=b 表示从最新往回翻；Matrix 返回的是"新→旧"，我们再倒过来给上层
        url = self._url(
            f"/_matrix/client/v3/rooms/{quote(room_id)}/messages?dir=b&limit={int(limit)}"
        )
        try:
            resp = self._session.get(url, timeout=10)
            if resp.status_code != 200:
                logger.warning("查消息失败: %s %s", resp.status_code, resp.text)
                return []
            chunk = resp.json().get("chunk", [])
            msgs: List[Dict[str, str]] = []
            for ev in chunk:
                if ev.get("type") != "m.room.message":
                    continue
                content = ev.get("content", {})
                body = content.get("body")
                if not body:
                    continue
                msgs.append({"sender": ev.get("sender", ""), "body": body})
            msgs.reverse()  # 倒成旧→新，读起来顺
            return msgs
        except requests.RequestException as exc:
            logger.warning("查消息异常: %s", exc)
            return []

    def joined_rooms(self) -> list:
        """列出 bot 已加入的所有房间 id。失败返回空列表、不抛(调用方按"没找到"优雅降级)。

        给「按群名邀人」用:AI 在私人会话里收到"邀请 xx 加入某某群"时,需要把群名解析成
        room_id——bot 是 appservice、加入了所有它服务的群,遍历它的房间找名字即可。
        """
        url = self._url("/_matrix/client/v3/joined_rooms")
        try:
            resp = self._session.get(url, timeout=10)
            if resp.status_code == 200:
                return list(resp.json().get("joined_rooms") or [])
        except requests.RequestException:
            logger.debug("查已加入房间列表失败", exc_info=True)
        return []

    def joined_member_count(self, room_id: str) -> int:
        """查房间当前已加入的成员数（用于区分"私聊"和"群聊"）。

        私聊（只有用户 + 主 AI，共 2 人）里，主 AI 对每句话都回；
        群聊里则只在被 @ 时才回。

        可用性：直接对成员数查询 fail-open 返回 99（按群聊）会让**私聊在服务端瞬时
        抖动/5xx 期间彻底沉默**（最难排查的"bot 不回话"）。两层兜底：
          1) 一次重试，吸收瞬时网络抖动；
          2) 仍失败时回退**上次成功查到的值**——私聊一旦见过就稳定是 2，不会被误判群聊。
        从未成功查过的房间才最终保守按群聊(99)。
        """
        url = self._url(f"/_matrix/client/v3/rooms/{quote(room_id)}/joined_members")
        for attempt in range(2):  # 首次 + 一次重试，覆盖瞬时抖动
            try:
                resp = self._session.get(url, timeout=10)
                if resp.status_code == 200:
                    n = len(resp.json().get("joined", {}))
                    self._member_count_cache[room_id] = n  # 记成功值供下次回退
                    return n
                logger.debug(
                    "查成员数 HTTP %s room=%s (第%d次)",
                    resp.status_code, room_id, attempt + 1,
                )
            except requests.RequestException as exc:
                logger.debug("查成员数异常 room=%s (第%d次): %s", room_id, attempt + 1, exc)
        # 两次都没查到：优先回退上次成功值，避免私聊因瞬时故障被误判成群聊而沉默。
        cached = self._member_count_cache.get(room_id)
        if cached is not None:
            logger.debug("查成员数失败，回退上次缓存值 %s room=%s", cached, room_id)
            return cached
        return 99  # 从未成功查过：保守按群聊（宁可不在群里刷屏）
