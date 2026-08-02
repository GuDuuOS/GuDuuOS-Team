"""Nexus OEM 账号层：注册 / 登录 / 会话 + KEY 认领 + 自有资源查询。

这是「角色分权」的 OEM 一侧（模块6 P1 拍板）：
    - 平台超管 = 数据库具名管理员短会话（看全部、签发 KEY、充值）；
    - OEM 客户 = 邮箱+密码独立账号，登录拿会话令牌，**只能看/操作自己认领的
      KEY 及其实例**（服务端强制，前端只是配合）。

纯函数层：每个函数收一个 SQLAlchemy Session，不自管事务（HTTP 层一请求一提交），
错误统一抛 ``FleetError``（复用 fleet 那套，HTTP 层已能翻成 JSON）。密码用标准库
pbkdf2 派生，不引三方库（与项目「栈越少越好」一致）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import time
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, select

from nexus import audit
from nexus.db import (
    NexusInstance,
    NexusKey,
    NexusKeyBinding,
    NexusKeyClaim,
    NexusKeyRequest,
    NexusKeyRequestDelivery,
    NexusKeyRequestProfile,
    NexusKeyRequestNetwork,
    NexusLicensePayment,
    NexusManualTransfer,
    NexusOem,
    NexusOemFile,
    NexusOemInvite,
    NexusOemProfile,
    NexusOemShare,
    NexusSession,
    NexusOrder,
    NexusUserAttribution,
    NexusWallet,
)
from nexus.fleet import FleetError
from nexus.keys import hash_key, looks_like_key, normalize_key
from nexus import network_binding

# 会话有效期：7 天（OEM 门户是低频配置场景，不需要长会话；到期重登）
_SESSION_TTL_MS = 7 * 24 * 3600 * 1000
# pbkdf2 迭代次数：兼顾安全与单机 CPU（同步服务，别把登录搞太慢）
_PBKDF2_ITERS = 200_000
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,253}[a-z0-9])?$")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _delivery_fernet() -> Fernet:
    """从 Nexus 主密钥派生授权交付专用 Fernet；缺失时绝不明文降级。"""
    raw = os.environ.get("NEXUS_SECRET_KEY", "").strip()
    if len(raw) < 32:
        raise FleetError(
            "NEXUS_SECRET_KEY_MISSING",
            "授权码交付加密主密钥未配置，请先设置 NEXUS_SECRET_KEY",
            503,
        )
    derived = base64.urlsafe_b64encode(hashlib.sha256(raw.encode("utf-8")).digest())
    return Fernet(derived)


# ---------- 密码哈希（pbkdf2，标准库）----------


def hash_password(password: str) -> str:
    """派生密码存储串：``pbkdf2$<迭代>$<salt_hex>$<hash_hex>``。"""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERS)
    return f"pbkdf2${_PBKDF2_ITERS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码。用 compare_digest 常数时间比对，防计时侧信道。"""
    try:
        scheme, iters_s, salt_hex, hash_hex = stored.split("$", 3)
        if scheme != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters_s)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def password_problem(password: str) -> Optional[str]:
    """密码强度校验：返回问题描述（中文），合格返回 None。"""
    if not password or len(password) < 8:
        return "密码至少 8 位"
    if len(password) > 128:
        return "密码过长"
    if password.isdigit() or password.isalpha():
        return "密码需同时包含字母和数字"
    return None


# ---------- 账号注册 / 登录 / 会话 ----------

# 平台官方邀请码：平台直属（一级）OEM 注册时填它，层级树挂在平台根节点下
_ROOT_INVITE_CODE = "GUDUU"


def _resolve_inviter(s, inviter: str) -> Optional[int]:
    """把注册表单里的「邀请人」解析成 inviter_id。

    规则（负责人 2026-07-23 拍板：必填、填错不能注册）：
      - 空 → 拒绝（层级必须完整，大屏星球图不允许悬空节点）；
      - 官方码 GUDUU（不分大小写）→ None（平台直属）；
      - 其他 → 可填已存在 OEM 的邮箱，也可填其门户分享链接里的随机分享码；
        两者都要求邀请方状态正常，否则拒绝。
    """
    inviter = (inviter or "").strip()
    if not inviter:
        raise FleetError(
            "NEXUS_INVITER_REQUIRED", "请填写邀请人邮箱（平台直接客户填 GUDUU）"
        )
    if inviter.upper() == _ROOT_INVITE_CODE:
        return None
    # 分享链接会把随机码自动回填到 OEM 注册表单；保留邮箱输入兼容既有客户和线下邀请。
    share = s.execute(
        select(NexusOemShare).where(NexusOemShare.code == inviter)
    ).scalar_one_or_none()
    if share is not None:
        owner = s.get(NexusOem, share.oem_id)
        if owner is not None and owner.status == "active":
            return int(owner.id)
        raise FleetError(
            "NEXUS_INVITER_INVALID", "邀请人不存在或不可用，请与邀请你的人确认", 400
        )
    row = s.execute(
        select(NexusOem).where(NexusOem.email == inviter.lower())
    ).scalar_one_or_none()
    if row is None or row.status != "active":
        # 不存在与被停用同文案：不给探测账号存在性的口子
        raise FleetError(
            "NEXUS_INVITER_INVALID", "邀请人不存在或不可用，请与邀请你的人确认", 400
        )
    return int(row.id)


def register(
    s,
    email: str,
    password: str,
    name: str = "",
    inviter: str = "",
    company: str = "",
    contact_name: str = "",
    phone: str = "",
) -> Dict[str, Any]:
    """OEM 自助注册。邮箱唯一、密码有强度、邀请人必填有效、**企业档案三项强制**。

    档案三项（负责人 2026-07-23 拍板强制采集）：企业名称 / 联系人姓名 / 联系方式。
    """
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        raise FleetError("NEXUS_BAD_EMAIL", "邮箱格式不正确")
    problem = password_problem(password)
    if problem:
        raise FleetError("NEXUS_WEAK_PASSWORD", problem)
    company = (company or "").strip()
    contact_name = (contact_name or "").strip()
    phone = (phone or "").strip()
    if not (2 <= len(company) <= 160):
        raise FleetError("NEXUS_PROFILE_REQUIRED", "请填写企业/团队名称（至少 2 个字）")
    if not (2 <= len(contact_name) <= 80):
        raise FleetError("NEXUS_PROFILE_REQUIRED", "请填写联系人姓名")
    if not (5 <= len(phone) <= 60):
        raise FleetError("NEXUS_PROFILE_REQUIRED", "请填写有效的联系方式（手机/微信）")
    # 邀请人先于"邮箱已注册"校验：填错邀请人时不泄露目标邮箱是否已注册
    inviter_id = _resolve_inviter(s, inviter)
    exists = s.execute(
        select(NexusOem).where(NexusOem.email == email)
    ).scalar_one_or_none()
    if exists is not None:
        raise FleetError("NEXUS_EMAIL_TAKEN", "该邮箱已注册", 409)
    oem = NexusOem(
        email=email,
        password_hash=hash_password(password),
        # name 列沿用为"显示名"：优先取注册填的企业名（列表页直接可读）
        name=((name or "").strip() or company)[:120],
    )
    s.add(oem)
    s.flush()  # 拿自增 id
    # 落邀请边：每个账号恰一条（层级树数据源；inviter_id=None = 平台直属）
    s.add(NexusOemInvite(oem_id=oem.id, inviter_id=inviter_id))
    # 落客户档案（超管详情页数据源）
    s.add(
        NexusOemProfile(
            oem_id=oem.id, company=company, contact_name=contact_name, phone=phone
        )
    )
    return public_oem(oem)


def login(s, email: str, password: str) -> Dict[str, Any]:
    """邮箱+密码登录。成功则签发一个会话令牌（明文仅此一次）。

    安全：账号不存在与密码错误返回同一个错误码/文案，不泄露"邮箱是否注册"。
    """
    email = (email or "").strip().lower()
    oem = s.execute(
        select(NexusOem).where(NexusOem.email == email)
    ).scalar_one_or_none()
    if oem is None or not verify_password(password, oem.password_hash):
        raise FleetError("NEXUS_BAD_CREDENTIALS", "邮箱或密码不正确", 401)
    if oem.status != "active":
        raise FleetError("NEXUS_OEM_DISABLED", "账号已被停用，请联系 GuDuu", 403)
    token = _issue_session(s, oem.id)
    return {"oem": public_oem(oem), "token": token}


def _issue_session(s, oem_id: int) -> str:
    """创建会话：库里只存 token 的 sha256，返回明文 token。"""
    token = secrets.token_urlsafe(32)
    s.add(
        NexusSession(
            token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            oem_id=int(oem_id),
            expires_ts=_now_ms() + _SESSION_TTL_MS,
        )
    )
    return token


def resolve_session(s, token: str) -> Optional[NexusOem]:
    """令牌 → OEM 账号（校验存在/未过期/账号仍启用）。无效返回 None。"""
    if not token:
        return None
    th = hashlib.sha256(token.encode("utf-8")).hexdigest()
    sess = s.get(NexusSession, th)
    if sess is None or sess.expires_ts < _now_ms():
        return None
    oem = s.get(NexusOem, sess.oem_id)
    if oem is None or oem.status != "active":
        return None
    return oem


def logout(s, token: str) -> None:
    """登出：删除该会话（幂等）。"""
    if not token:
        return
    th = hashlib.sha256(token.encode("utf-8")).hexdigest()
    sess = s.get(NexusSession, th)
    if sess is not None:
        s.delete(sess)
        s.flush()  # 立即落 DELETE：同一会话内后续 resolve 不再命中 identity map


def public_oem(oem: NexusOem) -> Dict[str, Any]:
    """账号对外表示（绝不含 password_hash）。"""
    return {
        "id": oem.id,
        "email": oem.email,
        "name": oem.name,
        "status": oem.status,
        "created_ts": oem.created_ts,
    }


# ---------- 分享码、无限层级与普通用户归属 ----------


def _share_for(s, oem_id: int) -> NexusOemShare:
    """读取或首次生成某 OEM 的稳定随机分享码。"""
    row = s.get(NexusOemShare, int(oem_id))
    if row is not None:
        return row
    # 96 bit 随机量足够防枚举；去掉 URL 不友好的符号，方便口头/纸面传播。
    while True:
        code = secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:16]
        exists = s.execute(
            select(NexusOemShare.oem_id).where(NexusOemShare.code == code)
        ).first()
        if exists is None:
            row = NexusOemShare(oem_id=int(oem_id), code=code)
            s.add(row)
            s.flush()
            return row


def referral_info(s, code: str) -> Dict[str, Any]:
    """公开校验分享码并返回最小邀请方信息，供实例注册页展示。

    不返回邮箱、联系人和上级链，避免一条公开链接变成客户资料查询接口。
    """
    normalized = (code or "").strip()
    if not normalized:
        raise FleetError("NEXUS_REFERRAL_REQUIRED", "邀请链接缺少分享码")
    share = s.execute(
        select(NexusOemShare).where(NexusOemShare.code == normalized)
    ).scalar_one_or_none()
    owner = s.get(NexusOem, share.oem_id) if share is not None else None
    if owner is None or owner.status != "active":
        raise FleetError("NEXUS_REFERRAL_INVALID", "邀请链接已失效，请联系邀请方", 404)
    profile = s.get(NexusOemProfile, owner.id)
    return {
        "code": share.code,
        "oem_id": owner.id,
        "name": (profile.company if profile and profile.company else owner.name)
        or "OEM 客户",
    }


def _hierarchy_maps(s) -> tuple:
    """一次读取 OEM 树，返回 ``父映射、子映射、账号映射``。"""
    rows = s.execute(select(NexusOem)).scalars().all()
    accounts = {int(row.id): row for row in rows}
    parents: Dict[int, Optional[int]] = {oid: None for oid in accounts}
    children: Dict[int, List[int]] = {oid: [] for oid in accounts}
    for child_id, parent_id in s.execute(
        select(NexusOemInvite.oem_id, NexusOemInvite.inviter_id)
    ).all():
        child = int(child_id)
        parent = int(parent_id) if parent_id is not None else None
        parents[child] = parent
        if parent is not None:
            children.setdefault(parent, []).append(child)
    return parents, children, accounts


def _ancestor_ids(parents: Dict[int, Optional[int]], oem_id: int) -> List[int]:
    """从直属上级向平台根部取祖先 id；带环检测，坏数据不会拖死请求。"""
    out: List[int] = []
    seen = {int(oem_id)}
    current = parents.get(int(oem_id))
    while current is not None and current not in seen:
        out.append(current)
        seen.add(current)
        current = parents.get(current)
    return out


def _descendant_ids(children: Dict[int, List[int]], oem_id: int) -> List[int]:
    """广度遍历全部下级，不限制深度；异常环通过 seen 收敛。"""
    out: List[int] = []
    queue = list(children.get(int(oem_id), []))
    seen = {int(oem_id)}
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        out.append(current)
        queue.extend(children.get(current, []))
    return out


def share_links(s, oem_id: int, portal_base: str) -> Dict[str, Any]:
    """生成 OEM 门户始终可用的分享码、注册链接与二维码目标。

    这部分不包含层级或用户统计，因此即使平台暂时隐藏网络数据，OEM 仍可
    邀请普通用户和合作伙伴。二维码端点也复用这份服务端重算结果，禁止把
    客户传入的任意网址编码进二维码。
    """
    owner = s.get(NexusOem, int(oem_id))
    if owner is None:
        raise FleetError("NEXUS_OEM_NOT_FOUND", "OEM 不存在", 404)
    share = _share_for(s, owner.id)
    instances = my_instances(s, owner.id)
    return {
        "code": share.code,
        "partner_link": f"{portal_base.rstrip('/')}/portal/?invite={share.code}",
        "user_links": [
            {
                "instance_id": int(item["id"]),
                "domain": item["domain"],
                "url": f"https://{item['domain']}/#/login?mode=register&ref={share.code}",
            }
            for item in instances
        ],
    }


def share_summary(s, oem_id: int, portal_base: str) -> Dict[str, Any]:
    """生成 OEM 分享能力以及受平台开关控制的层级人数统计。"""
    owner = s.get(NexusOem, int(oem_id))
    if owner is None:
        raise FleetError("NEXUS_OEM_NOT_FOUND", "OEM 不存在", 404)
    result = share_links(s, owner.id, portal_base)
    parents, children, accounts = _hierarchy_maps(s)
    descendants = _descendant_ids(children, owner.id)
    network_ids = [owner.id] + descendants
    direct_users = int(
        s.execute(
            select(func.count(NexusUserAttribution.id)).where(
                NexusUserAttribution.oem_id == owner.id
            )
        ).scalar_one()
    )
    network_users = int(
        s.execute(
            select(func.count(NexusUserAttribution.id)).where(
                NexusUserAttribution.oem_id.in_(network_ids)
            )
        ).scalar_one()
    )
    ancestor_ids = _ancestor_ids(parents, owner.id)
    result.update(
        {
            "level": len(ancestor_ids) + 1,
            "ancestors": [
                {
                    "id": oid,
                    "name": accounts[oid].name or accounts[oid].email,
                }
                for oid in reversed(ancestor_ids)
                if oid in accounts
            ],
            "direct_oems": len(children.get(owner.id, [])),
            "total_downline_oems": len(descendants),
            "direct_users": direct_users,
            "network_users": network_users,
        }
    )
    return result


def network_directory(s, oem_id: int, limit: int = 500) -> Dict[str, Any]:
    """返回当前 OEM 可见的下属企业与普通用户明细。

    参数 ``oem_id`` 是当前登录企业，``limit`` 是每类明细的最大返回行数；
    返回值包含全量计数、下级 OEM 列表和归属用户列表。服务端只允许查看
    自己及后代网络，并且故意不返回下级企业的邮箱、联系人、电话和密码等
    隐私字段。

    这个目录直接使用 ``NexusOemInvite`` 与 ``NexusUserAttribution``
    的真实关系边，不另建统计表，因此下级新注册或归属上报后会立即
    反映到列表。
    """
    owner_id = int(oem_id)
    owner = s.get(NexusOem, owner_id)
    if owner is None:
        raise FleetError("NEXUS_OEM_NOT_FOUND", "OEM 不存在", 404)

    parents, children, accounts = _hierarchy_maps(s)
    descendants = _descendant_ids(children, owner_id)
    network_ids = [owner_id] + descendants

    # 广度遍历时同步记录相对层数：1=直属下级，2+=间接下级。
    # 带 seen 是为了让历史坏数据即使存在环也不会拖死门户请求。
    relative_depth: Dict[int, int] = {}
    queue = [(child_id, 1) for child_id in children.get(owner_id, [])]
    seen = {owner_id}
    while queue:
        current, depth = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        relative_depth[current] = depth
        queue.extend((child_id, depth + 1) for child_id in children.get(current, []))

    profiles = {
        int(row.oem_id): row
        for row in s.execute(
            select(NexusOemProfile).where(NexusOemProfile.oem_id.in_(network_ids))
        )
        .scalars()
        .all()
    }

    # 直属用户数一次 group by 拉齐，避免每个下级 OEM 再发一条 SQL。
    direct_user_counts: Dict[int, int] = {
        int(oid): int(count)
        for oid, count in s.execute(
            select(
                NexusUserAttribution.oem_id,
                func.count(NexusUserAttribution.id),
            )
            .where(NexusUserAttribution.oem_id.in_(network_ids))
            .group_by(NexusUserAttribution.oem_id)
        ).all()
    }

    def _display_name(target_id: Optional[int]) -> str:
        """返回可向上级展示的企业名；不用邮箱做降级值，避免泄露账号。"""
        if target_id is None:
            return "GuDuu"
        account = accounts.get(int(target_id))
        profile = profiles.get(int(target_id))
        if profile is not None and profile.company:
            return profile.company
        if account is not None and account.name:
            return account.name
        return f"OEM #{int(target_id)}"

    oem_rows: List[Dict[str, Any]] = []
    for child_id in descendants[:limit]:
        account = accounts.get(child_id)
        if account is None:
            continue
        own_descendants = _descendant_ids(children, child_id)
        depth = relative_depth.get(child_id, 1)
        oem_rows.append(
            {
                "id": child_id,
                "company": _display_name(child_id),
                "status": account.status,
                "relation": "direct" if depth == 1 else "indirect",
                "depth": depth,
                "level": len(_ancestor_ids(parents, child_id)) + 1,
                "parent_id": parents.get(child_id),
                "parent_company": _display_name(parents.get(child_id)),
                "direct_users": direct_user_counts.get(child_id, 0),
                "network_users": sum(
                    direct_user_counts.get(network_id, 0)
                    for network_id in [child_id] + own_descendants
                ),
                "direct_oems": len(children.get(child_id, [])),
                "total_downline_oems": len(own_descendants),
                "created_ts": account.created_ts,
            }
        )

    # 用户明细按最新归属倒序。返回的是 Matrix user_id，不是密码、手机号
    # 或聊天内容；它本来就是 Nexus 归属边的业务标识。
    user_rows = (
        s.execute(
            select(NexusUserAttribution)
            .where(NexusUserAttribution.oem_id.in_(network_ids))
            .order_by(NexusUserAttribution.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    instance_ids = list({int(row.instance_id) for row in user_rows})
    instances = {
        int(row.id): row
        for row in (
            s.execute(select(NexusInstance).where(NexusInstance.id.in_(instance_ids)))
            .scalars()
            .all()
            if instance_ids
            else []
        )
    }
    users = []
    for row in user_rows:
        direct_owner_id = int(row.oem_id)
        depth = (
            0 if direct_owner_id == owner_id else relative_depth.get(direct_owner_id, 0)
        )
        instance = instances.get(int(row.instance_id))
        users.append(
            {
                "id": int(row.id),
                "user_id": row.user_id,
                "instance_id": int(row.instance_id),
                "instance_domain": instance.domain if instance is not None else "",
                "oem_id": direct_owner_id,
                "oem_company": _display_name(direct_owner_id),
                "relation": "direct" if direct_owner_id == owner_id else "indirect",
                "depth": depth,
                "created_ts": row.created_ts,
            }
        )

    total_users = sum(direct_user_counts.values())
    return {
        "oem_total": len(descendants),
        "user_total": total_users,
        "oems_truncated": len(descendants) > limit,
        "users_truncated": total_users > limit,
        "oems": oem_rows,
        "users": users,
    }


def qr_target(s, oem_id: int, portal_base: str, kind: str, instance_id: int = 0) -> str:
    """按当前登录 OEM 重新计算二维码目标，拒绝把二维码端点当任意 URL 生成器。"""
    summary = share_links(s, oem_id, portal_base)
    if kind == "partner":
        return str(summary["partner_link"])
    if kind == "user":
        for item in summary["user_links"]:
            if int(item["instance_id"]) == int(instance_id):
                return str(item["url"])
        raise FleetError("NEXUS_INSTANCE_NOT_OWNED", "该实例不属于当前 OEM", 403)
    raise FleetError("NEXUS_BAD_QR_KIND", "二维码类型不合法")


def record_user_attribution(
    s, raw_key: str, referral_code: str, user_id: str
) -> Dict[str, Any]:
    """实例用授权 KEY 幂等上报一条“普通用户→直属 OEM”归属边。

    分享码所属 OEM、KEY 归属 OEM、实例域名与 Matrix user_id 域名必须四者一致，
    防止任意实例把别处用户或别家客户计到自己名下。
    """
    from nexus.fleet import _key_by_plain

    key = _key_by_plain(s, raw_key)
    if key.instance_id is None:
        raise FleetError("NEXUS_NOT_REDEEMED", "授权码尚未兑换开通", 403)
    instance = s.get(NexusInstance, key.instance_id)
    claim = s.get(NexusKeyClaim, key.id)
    if instance is None or claim is None:
        raise FleetError("NEXUS_ATTRIBUTION_OWNER_MISSING", "实例尚未归属 OEM", 403)
    info = referral_info(s, referral_code)
    if int(info["oem_id"]) != int(claim.oem_id):
        raise FleetError(
            "NEXUS_REFERRAL_INSTANCE_MISMATCH", "邀请链接与注册实例不匹配", 403
        )
    normalized_user = (user_id or "").strip()
    if not normalized_user.startswith("@") or ":" not in normalized_user:
        raise FleetError("NEXUS_BAD_USER_ID", "用户 ID 格式不正确")
    if normalized_user.rsplit(":", 1)[-1].lower() != instance.domain.lower():
        raise FleetError("NEXUS_USER_INSTANCE_MISMATCH", "用户不属于该注册实例", 403)
    existing = s.execute(
        select(NexusUserAttribution).where(
            NexusUserAttribution.instance_id == instance.id,
            NexusUserAttribution.user_id == normalized_user,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if int(existing.oem_id) != int(claim.oem_id):
            raise FleetError(
                "NEXUS_USER_ALREADY_ATTRIBUTED", "用户已经归属其他 OEM", 409
            )
        return {"id": existing.id, "already": True, "oem_id": existing.oem_id}
    row = NexusUserAttribution(
        instance_id=instance.id,
        oem_id=claim.oem_id,
        user_id=normalized_user[:255],
        referral_code=(referral_code or "").strip()[:32],
    )
    s.add(row)
    s.flush()
    return {"id": row.id, "already": False, "oem_id": row.oem_id}


# ---------- KEY 认领（把一把 KEY 归到自己名下）----------


def claim_key(s, oem_id: int, raw_key: str) -> Dict[str, Any]:
    """OEM 认领一把 KEY（下单拿到 KEY 后在门户激活绑定到自己账号）。

    与 fleet.redeem 的区别：redeem 是**装机时**把 KEY 绑到域名/实例；claim 是
    把 KEY 的**归属**记到某个 OEM 账号名下（门户"我的实例"据此过滤）。二者独立：
    OEM 可以先认领 KEY 看到它，再在自己服务器装机兑换域名。幂等：自己已认领直接放行。
    """
    if not looks_like_key(raw_key):
        raise FleetError("NEXUS_BAD_KEY", "授权码格式不正确")
    key = s.execute(
        select(NexusKey).where(NexusKey.key_hash == hash_key(raw_key))
    ).scalar_one_or_none()
    if key is None:
        raise FleetError("NEXUS_KEY_NOT_FOUND", "授权码不存在", 404)
    if key.status != "active":
        raise FleetError("NEXUS_KEY_REVOKED", "授权码已被吊销", 403)
    claim = s.get(NexusKeyClaim, key.id)
    if claim is not None:
        if claim.oem_id == int(oem_id):
            return {"key_id": key.id, "tail": key.key_tail, "already": True}
        raise FleetError("NEXUS_KEY_CLAIMED", "该授权码已被其他账号认领", 409)
    s.add(NexusKeyClaim(key_id=key.id, oem_id=int(oem_id)))
    return {
        "key_id": key.id,
        "tail": key.key_tail,
        "token_grant": int(key.token_grant),
        "already": False,
    }


# ---------- 自有资源查询（服务端按 oem_id 过滤，OEM 只见自己）----------


def _owned_key_ids(s, oem_id: int) -> List[int]:
    return [
        int(kid)
        for (kid,) in s.execute(
            select(NexusKeyClaim.key_id).where(NexusKeyClaim.oem_id == int(oem_id))
        ).all()
    ]


def my_keys(s, oem_id: int) -> List[Dict[str, Any]]:
    """该 OEM 认领的所有 KEY（含是否已兑换开通、附赠额度）。"""
    ids = _owned_key_ids(s, oem_id)
    if not ids:
        return []
    rows = (
        s.execute(
            select(NexusKey).where(NexusKey.id.in_(ids)).order_by(NexusKey.id.desc())
        )
        .scalars()
        .all()
    )
    out: List[Dict[str, Any]] = []
    for r in rows:
        binding = s.get(NexusKeyBinding, r.id)
        out.append(
            {
                "id": r.id,
                "tail": r.key_tail,
                "status": r.status,
                "token_grant": int(r.token_grant),
                "instance_id": r.instance_id,
                "redeemed_ts": r.redeemed_ts,
                "created_ts": r.created_ts,
                "approved_domain": binding.approved_domain if binding else "",
                "expected_public_ip_masked": (
                    binding.expected_ip_masked if binding else ""
                ),
                "strict_ip": bool(binding.strict_ip) if binding else False,
                "risk_status": binding.risk_status if binding else "",
            }
        )
    return out


def my_instances(s, oem_id: int) -> List[Dict[str, Any]]:
    """该 OEM 名下已开通的实例 + 钱包余额（门户"我的实例"数据源）。"""
    ids = _owned_key_ids(s, oem_id)
    if not ids:
        return []
    rows = (
        s.execute(
            select(NexusInstance)
            .where(NexusInstance.key_id.in_(ids))
            .order_by(NexusInstance.id.desc())
        )
        .scalars()
        .all()
    )
    out: List[Dict[str, Any]] = []
    for r in rows:
        wallet = s.get(NexusWallet, r.id)
        out.append(
            {
                "id": r.id,
                "domain": r.domain,
                "admin_email": r.admin_email,
                "status": r.status,
                "version": r.version,
                "created_ts": r.created_ts,
                "last_seen_ts": r.last_seen_ts,
                "balance_tokens": int(wallet.balance_tokens) if wallet else 0,
            }
        )
    return out


def my_instance_detail(s, oem_id: int, instance_id: int) -> Dict[str, Any]:
    """返回 OEM 自己某个节点的完整运行快照。

    ``oem_id`` 来自已验证的 OEM 会话，``instance_id`` 来自页面点击。
    函数先沿 ``实例 → KEY 认领记录 → OEM`` 校验归属，通过后才读取
    心跳与账本数据。不属于当前企业时统一返回 403，不区分“节点不存在”
    和“属于别人”，避免把本接口变成节点编号探测器。
    """
    if not owns_instance(s, int(oem_id), int(instance_id)):
        raise FleetError(
            "NEXUS_INSTANCE_NOT_OWNED",
            "该实例不属于当前 OEM",
            403,
        )
    from nexus.fleet import instance_snapshot

    return instance_snapshot(s, int(instance_id))


def list_oems(s) -> List[Dict[str, Any]]:
    """全部 OEM 账号 + 认领的 KEY 数（**超管**控制台"客户列表"数据源）。

    只给超管端点用（service.py 里挂在 /nexus/admin/ 下、走具名短会话鉴权），
    OEM 自己永远看不到别人。
    """
    rows = s.execute(select(NexusOem).order_by(NexusOem.id.desc())).scalars().all()
    # 一次查出每个 OEM 的认领数，避免 N+1
    counts: Dict[int, int] = {}
    for (oid,) in s.execute(select(NexusKeyClaim.oem_id)).all():
        counts[int(oid)] = counts.get(int(oid), 0) + 1
    # 邀请边一次拉全：oem_id → inviter_id（None=平台直属；无边=旧账号,视同直属）
    invites, children, _accounts = _hierarchy_maps(s)
    user_counts: Dict[int, int] = {}
    for oid, count in s.execute(
        select(
            NexusUserAttribution.oem_id, func.count(NexusUserAttribution.id)
        ).group_by(NexusUserAttribution.oem_id)
    ).all():
        user_counts[int(oid)] = int(count)
    emails = {r.id: r.email for r in rows}
    out = []
    for r in rows:
        iid = invites.get(r.id)
        ancestors = _ancestor_ids(invites, r.id)
        descendants = _descendant_ids(children, r.id)
        out.append(
            {
                **public_oem(r),
                "keys_claimed": counts.get(r.id, 0),
                "inviter_id": iid,
                # 展示名：上线邮箱 / GuDuu(平台直属或历史账号)
                "inviter": emails.get(iid, f"#{iid}") if iid is not None else "GuDuu",
                "level": len(ancestors) + 1,
                "direct_oems": len(children.get(r.id, [])),
                "total_downline_oems": len(descendants),
                "direct_users": user_counts.get(r.id, 0),
                "network_users": sum(
                    user_counts.get(oid, 0) for oid in [r.id] + descendants
                ),
            }
        )
    return out


def hierarchy_snapshot(s) -> Dict[str, Any]:
    """超级管理员读取完整 OEM 树和普通用户归属边。

    返回平铺 nodes/edges，前端可按需要画树或表格；不在数据库复制祖先路径，层级调整时
    只需变更 OEM 入边。普通用户仅返回 Matrix user_id 与注册实例，不含邮箱和认证资料。
    """
    nodes = list_oems(s)
    users = (
        s.execute(select(NexusUserAttribution).order_by(NexusUserAttribution.id.desc()))
        .scalars()
        .all()
    )
    return {
        "oems": nodes,
        "oem_edges": [
            {"oem_id": row["id"], "parent_oem_id": row["inviter_id"]} for row in nodes
        ],
        "user_edges": [
            {
                "id": row.id,
                "user_id": row.user_id,
                "instance_id": row.instance_id,
                "oem_id": row.oem_id,
                "created_ts": row.created_ts,
            }
            for row in users
        ],
    }


# ---------- 授权中心 V2（申请 → 审核 → 加密交付 → 审计）----------

# 同一 OEM 最多同时挂起三张申请；needs_info 仍占名额，避免反复开新单绕过审核。
_MAX_PENDING_REQUESTS = 3
# 管理员可调整附赠额度，但服务端必须有硬上限，避免输入错误把钱包写入异常巨量。
_MAX_TOKEN_GRANT = 1_000_000_000_000
# 获批后七天内必须首次领取；首次领取后保留三十分钟重复查看窗口，防网络响应丢失。
_DELIVERY_TTL_MS = 7 * 24 * 3600 * 1000
_REVEAL_WINDOW_MS = 30 * 60 * 1000


def _clean_domain(value: str) -> str:
    """校验申请中的计划域名；新申请必须填写，作为 KEY 的硬绑定边界。"""
    domain = (value or "").strip().lower().rstrip(".")[:255]
    if not domain:
        raise FleetError("NEXUS_DOMAIN_REQUIRED", "请填写计划部署域名")
    if not _DOMAIN_RE.fullmatch(domain) or ".." in domain:
        raise FleetError("NEXUS_BAD_DOMAIN", "计划部署域名格式不正确")
    return domain


def _clean_tokens(value: int) -> int:
    """把申请/审批额度收敛到数据库和产品允许的安全范围。"""
    tokens = int(value or 0)
    if tokens < 0 or tokens > _MAX_TOKEN_GRANT:
        raise FleetError(
            "NEXUS_BAD_GRANT",
            f"Token 额度须在 0~{_MAX_TOKEN_GRANT} 之间",
        )
    return tokens


def request_key(
    s,
    oem_id: int,
    note: str = "",
    *,
    deployment_domain: str = "",
    purpose: str = "",
    expected_date: str = "",
    requested_tokens: int = 0,
    expected_public_ip: str = "",
    strict_ip: bool = False,
    source_ip: str = "",
) -> Dict[str, Any]:
    """OEM 提交一张结构化授权申请（一张申请对应一个节点 KEY）。"""
    pending = (
        s.execute(
            select(NexusKeyRequest).where(
                NexusKeyRequest.oem_id == int(oem_id),
                NexusKeyRequest.status.in_(("pending", "needs_info")),
            )
        )
        .scalars()
        .all()
    )
    if len(pending) >= _MAX_PENDING_REQUESTS:
        raise FleetError(
            "NEXUS_TOO_MANY_REQUESTS",
            f"已有 {len(pending)} 张处理中申请，请等待处理或撤回后再提交",
            429,
        )
    account = s.get(NexusOem, int(oem_id))
    if account is None:
        raise FleetError("NEXUS_OEM_NOT_FOUND", "OEM 账号不存在", 404)
    profile = s.get(NexusOemProfile, int(oem_id))
    clean_purpose = (purpose or note or "").strip()[:255]
    if not clean_purpose:
        raise FleetError("NEXUS_REQUEST_PURPOSE_REQUIRED", "请填写使用场景")
    clean_domain = _clean_domain(deployment_domain)
    # 先把网络策略完整校验并计算成不可逆值，再创建申请主记录，避免脚本调用方
    # 忘记回滚时留下只有主表、没有绑定资料的半成品申请。
    if strict_ip and not (expected_public_ip or "").strip():
        raise FleetError(
            "NEXUS_STRICT_IP_REQUIRED", "启用严格 IP 绑定时必须填写公网 IP"
        )
    expected_ip_hash = network_binding.fingerprint(expected_public_ip)
    expected_ip_masked = network_binding.masked(expected_public_ip)
    row = NexusKeyRequest(oem_id=int(oem_id), note=(note or "").strip()[:500])
    s.add(row)
    s.flush()
    s.add(
        NexusKeyRequestProfile(
            request_id=row.id,
            deployment_domain=clean_domain,
            purpose=clean_purpose,
            expected_date=(expected_date or "").strip()[:16],
            requested_tokens=_clean_tokens(requested_tokens),
            contact_name=(profile.contact_name if profile else account.name)[:80],
            contact_phone=(profile.phone if profile else "")[:60],
        )
    )
    s.add(
        NexusKeyRequestNetwork(
            request_id=row.id,
            expected_ip_hash=expected_ip_hash,
            expected_ip_masked=expected_ip_masked,
            strict_ip=1 if strict_ip else 0,
        )
    )
    audit.record(
        s,
        object_type="key_request",
        object_id=row.id,
        action="submit",
        actor_type="oem",
        actor_label=account.email,
        source_ip=source_ip,
        to_state="pending",
    )
    return _public_request(s, row)


def _delivery_status(
    row: NexusKeyRequest, delivery: Optional[NexusKeyRequestDelivery]
) -> str:
    """把交付记录转换成前端稳定状态，不暴露任何密文。"""
    if row.status != "approved":
        return "none"
    if delivery is None:
        return "legacy_ready" if row.key_plain else "unavailable"
    if delivery.cleared_ts or not delivery.encrypted_key:
        return "used"
    now = _now_ms()
    if delivery.first_revealed_ts and delivery.reveal_until_ts:
        return "revealed" if now <= delivery.reveal_until_ts else "locked"
    return "ready" if now <= delivery.expires_ts else "expired"


def _public_request(s, row: NexusKeyRequest) -> Dict[str, Any]:
    """返回不含 KEY 明文/密文的申请摘要，OEM 与超管共用。"""
    profile = s.get(NexusKeyRequestProfile, row.id)
    network = s.get(NexusKeyRequestNetwork, row.id)
    delivery = s.get(NexusKeyRequestDelivery, row.id)
    delivery_status = _delivery_status(row, delivery)
    payment = s.get(NexusLicensePayment, row.id)
    order = (
        s.get(NexusOrder, payment.order_id) if payment and payment.order_id else None
    )
    transfer = (
        s.get(NexusManualTransfer, payment.transfer_id)
        if payment and payment.transfer_id
        else None
    )
    # 历史版本在节点兑换后只清旧明文，没有 V2 delivery 行；通过 KEY 绑定关系仍能准确
    # 还原“已使用”，避免升级后把老客户的正常节点误标成等待补发。
    if row.key_id:
        key = s.get(NexusKey, row.key_id)
        if key is not None and key.instance_id is not None:
            delivery_status = "used"
    return {
        "id": row.id,
        "oem_id": row.oem_id,
        "note": row.note,
        "status": row.status,
        "created_ts": row.created_ts,
        "decided_ts": row.decided_ts,
        "key_id": row.key_id,
        "decide_note": row.decide_note,
        "deployment_domain": profile.deployment_domain if profile else "",
        "purpose": profile.purpose if profile else (row.note or ""),
        "expected_date": profile.expected_date if profile else "",
        "requested_tokens": int(profile.requested_tokens) if profile else 0,
        "contact_name": profile.contact_name if profile else "",
        "contact_phone": profile.contact_phone if profile else "",
        "expected_public_ip_masked": network.expected_ip_masked if network else "",
        "strict_ip": bool(network.strict_ip) if network else False,
        "delivery_status": delivery_status,
        "delivery_expires_ts": delivery.expires_ts if delivery else None,
        "reveal_until_ts": delivery.reveal_until_ts if delivery else None,
        # 旧申请没有支付关联表，兼容解释为“线下/免费人工审批”。
        "payment_method": payment.method if payment else "manual_review",
        "payment_status": payment.status if payment else "manual_review",
        "payment_amount_cents": int(payment.amount_cents) if payment else 0,
        "payment_currency": payment.currency if payment else "CNY",
        "order_no": order.order_no if order else "",
        "transfer_id": int(transfer.id) if transfer else None,
        "transfer_no": transfer.transfer_no if transfer else "",
    }


def my_requests(s, oem_id: int) -> List[Dict[str, Any]]:
    """返回 OEM 的完整申请历史；授权码须另调 reveal 接口主动领取。"""
    rows = (
        s.execute(
            select(NexusKeyRequest)
            .where(NexusKeyRequest.oem_id == int(oem_id))
            .order_by(NexusKeyRequest.id.desc())
        )
        .scalars()
        .all()
    )
    return [_public_request(s, row) for row in rows]


def request_counts(s) -> Dict[str, int]:
    """返回各申请状态数量，供超管标签和导航角标使用。"""
    counts = {
        "pending": 0,
        "needs_info": 0,
        "approved": 0,
        "rejected": 0,
        "cancelled": 0,
        "all": 0,
    }
    for status, count in s.execute(
        select(NexusKeyRequest.status, func.count(NexusKeyRequest.id)).group_by(
            NexusKeyRequest.status
        )
    ).all():
        counts[str(status)] = int(count)
        counts["all"] += int(count)
    return counts


def list_requests(
    s, status: str = "", query: str = "", limit: int = 200
) -> List[Dict[str, Any]]:
    """超管查询申请历史，支持状态和企业/域名/用途关键词筛选。"""
    allowed = {"pending", "needs_info", "approved", "rejected", "cancelled"}
    q = select(NexusKeyRequest).order_by(NexusKeyRequest.id.desc())
    if status in allowed:
        q = q.where(NexusKeyRequest.status == status)
    rows = s.execute(q.limit(max(1, min(int(limit or 200), 500)))).scalars().all()
    needle = (query or "").strip().lower()[:120]
    out: List[Dict[str, Any]] = []
    for row in rows:
        account = s.get(NexusOem, row.oem_id)
        profile = s.get(NexusOemProfile, row.oem_id)
        item = _public_request(s, row)
        item["oem_email"] = account.email if account else f"#{row.oem_id}"
        item["company"] = profile.company if profile else ""
        haystack = " ".join(
            str(item.get(field) or "")
            for field in (
                "oem_email",
                "company",
                "deployment_domain",
                "purpose",
                "note",
            )
        ).lower()
        if needle and needle not in haystack:
            continue
        out.append(item)
    return out


def request_detail(s, request_id: int) -> Dict[str, Any]:
    """返回申请详情和不可变审计时间线（超管详情弹窗数据源）。"""
    row = s.get(NexusKeyRequest, int(request_id))
    if row is None:
        raise FleetError("NEXUS_REQUEST_NOT_FOUND", f"申请 #{request_id} 不存在", 404)
    account = s.get(NexusOem, row.oem_id)
    profile = s.get(NexusOemProfile, row.oem_id)
    item = _public_request(s, row)
    item.update(
        {
            "oem_email": account.email if account else f"#{row.oem_id}",
            "company": profile.company if profile else "",
            "timeline": audit.timeline(s, "key_request", row.id),
        }
    )
    return item


def update_request(
    s,
    oem_id: int,
    request_id: int,
    *,
    note: str = "",
    deployment_domain: str = "",
    purpose: str = "",
    expected_date: str = "",
    requested_tokens: int = 0,
    expected_public_ip: str = "",
    strict_ip: bool = False,
    source_ip: str = "",
) -> Dict[str, Any]:
    """OEM 补充待审资料；needs_info 补完后自动回到 pending。"""
    row = s.execute(
        select(NexusKeyRequest)
        .where(NexusKeyRequest.id == int(request_id))
        .with_for_update()
    ).scalar_one_or_none()
    if row is None or int(row.oem_id) != int(oem_id):
        raise FleetError("NEXUS_REQUEST_NOT_FOUND", "申请不存在", 404)
    if row.status not in ("pending", "needs_info"):
        raise FleetError("NEXUS_REQUEST_DECIDED", "该申请当前不能修改", 409)
    old_status = row.status
    clean_purpose = (purpose or "").strip()[:255]
    if not clean_purpose:
        raise FleetError("NEXUS_REQUEST_PURPOSE_REQUIRED", "请填写使用场景")
    row.note = (note or "").strip()[:500]
    row.status = "pending"
    row.decide_note = ""
    profile = s.get(NexusKeyRequestProfile, row.id)
    if profile is None:
        profile = NexusKeyRequestProfile(request_id=row.id)
        s.add(profile)
    profile.deployment_domain = _clean_domain(deployment_domain)
    profile.purpose = clean_purpose
    profile.expected_date = (expected_date or "").strip()[:16]
    payment = s.execute(
        select(NexusLicensePayment)
        .where(NexusLicensePayment.request_id == row.id)
        .with_for_update()
    ).scalar_one_or_none()
    # 付款单的 Token 来自下单时的定价快照，付款后不能通过改申请表
    # 篡改商品内容；只有免费/合同人工审批仍允许修改申请额度。
    if payment is None or payment.method == "manual_review":
        profile.requested_tokens = _clean_tokens(requested_tokens)
    profile.updated_ts = _now_ms()
    network = s.get(NexusKeyRequestNetwork, row.id)
    if (
        strict_ip
        and not (expected_public_ip or "").strip()
        and not (network and network.expected_ip_hash)
    ):
        raise FleetError(
            "NEXUS_STRICT_IP_REQUIRED", "启用严格 IP 绑定时必须填写公网 IP"
        )
    if network is None:
        network = NexusKeyRequestNetwork(request_id=row.id)
        s.add(network)
    # 对已存在申请，界面只拿到脱敏网段，无法也不应回填完整 IP；因此留空表示
    # “保留原值”，只有明确输入新地址时才替换 HMAC 与展示网段。
    if (expected_public_ip or "").strip() or not network.expected_ip_hash:
        network.expected_ip_hash = network_binding.fingerprint(expected_public_ip)
        network.expected_ip_masked = network_binding.masked(expected_public_ip)
    network.strict_ip = 1 if strict_ip else 0
    network.updated_ts = _now_ms()
    account = s.get(NexusOem, int(oem_id))
    audit.record(
        s,
        object_type="key_request",
        object_id=row.id,
        action="resubmit" if old_status == "needs_info" else "update",
        actor_type="oem",
        actor_label=account.email if account else f"#{oem_id}",
        source_ip=source_ip,
        from_state=old_status,
        to_state="pending",
    )
    return _public_request(s, row)


def cancel_request(
    s, oem_id: int, request_id: int, source_ip: str = ""
) -> Dict[str, Any]:
    """OEM 撤回尚未签发的申请，已批准申请不能自行撤销 KEY。"""
    row = s.execute(
        select(NexusKeyRequest)
        .where(NexusKeyRequest.id == int(request_id))
        .with_for_update()
    ).scalar_one_or_none()
    if row is None or int(row.oem_id) != int(oem_id):
        raise FleetError("NEXUS_REQUEST_NOT_FOUND", "申请不存在", 404)
    if row.status not in ("pending", "needs_info"):
        raise FleetError("NEXUS_REQUEST_DECIDED", "该申请当前不能撤回", 409)
    old_status = row.status
    row.status = "cancelled"
    row.decided_ts = _now_ms()
    payment = s.execute(
        select(NexusLicensePayment)
        .where(NexusLicensePayment.request_id == row.id)
        .with_for_update()
    ).scalar_one_or_none()
    if payment is not None and payment.status not in ("fulfilled", "rejected"):
        payment.status = "cancelled"
        payment.updated_ts = _now_ms()
        if payment.order_id:
            order = s.execute(
                select(NexusOrder)
                .where(NexusOrder.id == payment.order_id)
                .with_for_update()
            ).scalar_one_or_none()
            if order is not None and order.status == "pending":
                order.status = "closed"
        if payment.transfer_id:
            transfer = s.execute(
                select(NexusManualTransfer)
                .where(NexusManualTransfer.id == payment.transfer_id)
                .with_for_update()
            ).scalar_one_or_none()
            if transfer is not None and transfer.status == "pending_review":
                transfer.status = "cancelled"
    account = s.get(NexusOem, int(oem_id))
    audit.record(
        s,
        object_type="key_request",
        object_id=row.id,
        action="cancel",
        actor_type="oem",
        actor_label=account.email if account else f"#{oem_id}",
        source_ip=source_ip,
        from_state=old_status,
        to_state="cancelled",
    )
    return _public_request(s, row)


def _approve_request_locked(
    s,
    row: NexusKeyRequest,
    token_grant: int,
    *,
    action: str,
    actor_type: str,
    actor_label: str,
    source_ip: str = "",
    note: str = "",
) -> Dict[str, Any]:
    """对已持有行锁的申请签发且加密交付唯一 KEY。

    人工审批、在线支付回调和企业转账确认必须共用同一段履约逻辑，
    否则三条路径容易产生不同的密文清理、归属或审计行为。
    """
    from nexus import fleet

    if row.status != "pending":
        raise FleetError("NEXUS_REQUEST_DECIDED", "该申请已处理", 409)
    grant = _clean_tokens(token_grant)
    request_profile = s.get(NexusKeyRequestProfile, row.id)
    request_network = s.get(NexusKeyRequestNetwork, row.id)
    # 先验证绑定资料，再签发 KEY。这样即使该函数被脚本直接调用且调用方没有
    # 正确回滚事务，也不会在发现资料缺失前留下一个没有归属的临时 KEY。
    if request_profile is None or not request_profile.deployment_domain:
        raise FleetError("NEXUS_DOMAIN_REQUIRED", "授权申请缺少计划部署域名", 409)
    issued = fleet.issue_keys(
        s,
        count=1,
        note=f"申请单#{row.id} · {row.note[:60]}",
        token_grant=grant,
    )[0]
    # 审批时把计划域名与 IP 策略复制成不可由 OEM 再修改的 KEY 绑定快照。
    s.add(
        NexusKeyBinding(
            key_id=issued["id"],
            approved_domain=request_profile.deployment_domain,
            expected_ip_hash=(
                request_network.expected_ip_hash if request_network else ""
            ),
            expected_ip_masked=(
                request_network.expected_ip_masked if request_network else ""
            ),
            strict_ip=(request_network.strict_ip if request_network else 0),
        )
    )
    now = _now_ms()
    row.status = "approved"
    row.decided_ts = now
    row.decide_note = (note or "").strip()[:500]
    row.key_id = issued["id"]
    row.key_plain = ""
    s.add(NexusKeyClaim(key_id=issued["id"], oem_id=row.oem_id))
    s.add(
        NexusKeyRequestDelivery(
            request_id=row.id,
            key_id=issued["id"],
            encrypted_key=_delivery_fernet().encrypt(issued["key"].encode("utf-8")),
            expires_ts=now + _DELIVERY_TTL_MS,
        )
    )
    audit.record(
        s,
        object_type="key_request",
        object_id=row.id,
        action=action,
        actor_type=actor_type,
        actor_label=actor_label,
        source_ip=source_ip,
        from_state="pending",
        to_state="approved",
        note=row.decide_note,
        metadata={
            "token_grant": grant,
            "key_id": issued["id"],
            "approved_domain": request_profile.deployment_domain,
            "expected_public_ip_masked": (
                request_network.expected_ip_masked if request_network else ""
            ),
            "strict_ip": bool(request_network and request_network.strict_ip),
        },
    )
    s.flush()
    return _public_request(s, row)


def approve_paid_request(
    s,
    request_id: int,
    token_grant: int,
    *,
    action: str,
    actor_label: str,
    source_ip: str = "",
    note: str = "",
) -> Dict[str, Any]:
    """支付或转账已被服务端确认后，原子审批并签发授权。"""
    row = s.execute(
        select(NexusKeyRequest)
        .where(NexusKeyRequest.id == int(request_id))
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise FleetError("NEXUS_REQUEST_NOT_FOUND", f"申请 #{request_id} 不存在", 404)
    if row.status == "approved" and row.key_id:
        return _public_request(s, row)
    return _approve_request_locked(
        s,
        row,
        token_grant,
        action=action,
        actor_type="system" if action == "payment_auto_approve" else "admin",
        actor_label=actor_label,
        source_ip=source_ip,
        note=note,
    )


def decide_request(
    s,
    request_id: int,
    approve: bool,
    token_grant: int = 0,
    decide_note: str = "",
    *,
    action: str = "",
    actor_label: str = "平台超级管理员",
    source_ip: str = "",
) -> Dict[str, Any]:
    """超管处理申请，并用行锁保证并发点击只会签发一把 KEY。

    ``action`` 支持 approve/reject/needs_info；保留 ``approve`` 参数兼容旧客户端。
    批准时 KEY 明文只进入 Fernet 加密交付表，管理端响应永远不含明文。
    """
    selected_action = (action or ("approve" if approve else "reject")).strip()
    if selected_action not in ("approve", "reject", "needs_info"):
        raise FleetError("NEXUS_BAD_ACTION", "不支持的申请处理动作")
    row = s.execute(
        select(NexusKeyRequest)
        .where(NexusKeyRequest.id == int(request_id))
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise FleetError("NEXUS_REQUEST_NOT_FOUND", f"申请 #{request_id} 不存在", 404)
    if row.status != "pending":
        raise FleetError("NEXUS_REQUEST_DECIDED", "该申请已处理或正在等待补充资料", 409)
    note = (decide_note or "").strip()[:500]
    old_status = row.status
    payment = s.get(NexusLicensePayment, row.id)
    if (
        selected_action == "approve"
        and payment is not None
        and payment.method in ("online", "corporate_transfer")
    ):
        raise FleetError(
            "NEXUS_PAYMENT_CONFIRM_REQUIRED",
            "付款申请必须由支付回调或企业转账到账确认自动签发",
            409,
        )
    if selected_action == "approve":
        return _approve_request_locked(
            s,
            row,
            token_grant,
            action="approve",
            actor_type="admin",
            actor_label=actor_label,
            source_ip=source_ip,
            note=note,
        )
    row.decided_ts = _now_ms()
    row.decide_note = note
    if selected_action == "needs_info":
        if not note:
            raise FleetError("NEXUS_DECIDE_NOTE_REQUIRED", "请填写需要客户补充的资料")
        row.status = "needs_info"
    elif selected_action == "reject":
        if not note:
            raise FleetError("NEXUS_DECIDE_NOTE_REQUIRED", "拒绝申请必须填写原因")
        row.status = "rejected"
    if payment is not None and selected_action == "reject":
        payment.status = "rejected"
        payment.updated_ts = _now_ms()
        if payment.order_id:
            order = s.get(NexusOrder, payment.order_id)
            if order is not None and order.status == "pending":
                order.status = "closed"
        if payment.transfer_id:
            transfer = s.get(NexusManualTransfer, payment.transfer_id)
            if transfer is not None and transfer.status == "pending_review":
                transfer.status = "rejected"
    audit.record(
        s,
        object_type="key_request",
        object_id=row.id,
        action=selected_action,
        actor_type="admin",
        actor_label=actor_label,
        source_ip=source_ip,
        from_state=old_status,
        to_state=row.status,
        note=note,
        metadata={},
    )
    return _public_request(s, row)


def _migrate_legacy_delivery(
    s, row: NexusKeyRequest
) -> Optional[NexusKeyRequestDelivery]:
    """把升级前 ``key_plain`` 明文原子迁入加密交付表，随后清空旧列。"""
    delivery = s.get(NexusKeyRequestDelivery, row.id)
    if delivery is not None or not row.key_plain or not row.key_id:
        return delivery
    delivery = NexusKeyRequestDelivery(
        request_id=row.id,
        key_id=row.key_id,
        encrypted_key=_delivery_fernet().encrypt(row.key_plain.encode("utf-8")),
        expires_ts=_now_ms() + _DELIVERY_TTL_MS,
    )
    s.add(delivery)
    row.key_plain = ""
    s.flush()
    return delivery


def reveal_request_key(
    s, oem_id: int, request_id: int, source_ip: str = ""
) -> Dict[str, Any]:
    """OEM 主动领取获批 KEY；首次领取后仅可在三十分钟内重复查看。"""
    row = s.get(NexusKeyRequest, int(request_id))
    if row is None or int(row.oem_id) != int(oem_id):
        raise FleetError("NEXUS_REQUEST_NOT_FOUND", "申请不存在", 404)
    if row.status != "approved" or not row.key_id:
        raise FleetError("NEXUS_DELIVERY_NOT_READY", "该申请尚未生成授权码", 409)
    key = s.get(NexusKey, row.key_id)
    if key is None or key.status != "active":
        raise FleetError("NEXUS_KEY_REVOKED", "授权码已失效，请联系平台", 403)
    if key.instance_id is not None:
        raise FleetError("NEXUS_KEY_ALREADY_USED", "授权码已完成节点开通", 409)
    delivery = _migrate_legacy_delivery(s, row)
    if delivery is None or delivery.cleared_ts or not delivery.encrypted_key:
        raise FleetError("NEXUS_DELIVERY_UNAVAILABLE", "授权码已领取或已清除", 410)
    now = _now_ms()
    first_reveal = delivery.first_revealed_ts is None
    if delivery.first_revealed_ts is None:
        if now > delivery.expires_ts:
            raise FleetError(
                "NEXUS_DELIVERY_EXPIRED", "领取期限已过，请联系平台补发", 410
            )
        delivery.first_revealed_ts = now
        delivery.reveal_until_ts = min(delivery.expires_ts, now + _REVEAL_WINDOW_MS)
    elif not delivery.reveal_until_ts or now > delivery.reveal_until_ts:
        raise FleetError(
            "NEXUS_DELIVERY_LOCKED",
            "授权码查看窗口已结束；如未保存，请联系平台补发",
            410,
        )
    try:
        plain = _delivery_fernet().decrypt(delivery.encrypted_key).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError):
        raise FleetError(
            "NEXUS_SECRET_KEY_INVALID",
            "授权码无法解密，请联系平台检查加密主密钥",
            503,
        )
    account = s.get(NexusOem, int(oem_id))
    audit.record(
        s,
        object_type="key_request",
        object_id=row.id,
        action="reveal",
        actor_type="oem",
        actor_label=account.email if account else f"#{oem_id}",
        source_ip=source_ip,
        from_state="approved",
        to_state="approved",
        metadata={"first_reveal": first_reveal},
    )
    return {
        "request_id": row.id,
        "key": plain,
        "reveal_until_ts": delivery.reveal_until_ts,
    }


def clear_plain_by_key(s, raw_key: str) -> None:
    """节点兑换成功后清除申请交付密文和旧版明文；在线订单仍走原有清理逻辑。"""
    if not looks_like_key(raw_key):
        return
    key = s.execute(
        select(NexusKey).where(NexusKey.key_hash == hash_key(raw_key))
    ).scalar_one_or_none()
    if key is None:
        return
    for row in s.execute(
        select(NexusKeyRequest).where(NexusKeyRequest.key_id == key.id)
    ).scalars():
        row.key_plain = ""
        delivery = s.get(NexusKeyRequestDelivery, row.id)
        if delivery is not None and not delivery.cleared_ts:
            delivery.encrypted_key = b""
            delivery.cleared_ts = _now_ms()
            audit.record(
                s,
                object_type="key_request",
                object_id=row.id,
                action="redeem",
                actor_type="system",
                actor_label="节点安装程序",
                from_state="approved",
                to_state="approved",
                metadata={"key_id": key.id, "instance_id": key.instance_id},
            )
    from nexus import pay

    pay.clear_order_plain_by_key_id(s, key.id)


# ---------- 客户档案详情 / 合同附件（超管专用）----------

# 附件白名单（合同/资质常见格式）与单文件上限
_FILE_EXT_OK = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".jpg",
    ".jpeg",
    ".png",
    ".zip",
}
FILE_MAX_BYTES = 20 * 1024 * 1024


def oem_detail(s, oem_id: int) -> Dict[str, Any]:
    """超管点开客户后的完整档案：账号+档案+邀请人+资产汇总+附件清单。"""
    acc = s.get(NexusOem, int(oem_id))
    if acc is None:
        raise FleetError("NEXUS_OEM_NOT_FOUND", f"OEM id={oem_id} 不存在", 404)
    prof = s.get(NexusOemProfile, acc.id)
    edge = s.get(NexusOemInvite, acc.id)
    inviter_email = "GuDuu"
    if edge is not None and edge.inviter_id is not None:
        up = s.get(NexusOem, edge.inviter_id)
        inviter_email = up.email if up else f"#{edge.inviter_id}"
    insts = my_instances(s, acc.id)
    files = [
        {
            "id": f.id,
            "filename": f.filename,
            "size": int(f.size),
            "uploaded_ts": f.uploaded_ts,
        }
        for f in s.execute(
            select(NexusOemFile)
            .where(NexusOemFile.oem_id == acc.id)
            .order_by(NexusOemFile.id.desc())
        ).scalars()
    ]
    return {
        **public_oem(acc),
        "company": prof.company if prof else "",
        "contact_name": prof.contact_name if prof else "",
        "phone": prof.phone if prof else "",
        "admin_note": prof.admin_note if prof else "",
        "profile_missing": prof is None,  # 历史账号未采集档案
        "inviter": inviter_email,
        "keys": my_keys(s, acc.id),
        "instances": insts,
        "balance_total": sum(i["balance_tokens"] for i in insts),
        "files": files,
    }


def set_admin_note(s, oem_id: int, note: str) -> None:
    """超管备注（谈判进展等，客户不可见）。历史账号无档案行则补建空档案。"""
    prof = s.get(NexusOemProfile, int(oem_id))
    if prof is None:
        if s.get(NexusOem, int(oem_id)) is None:
            raise FleetError("NEXUS_OEM_NOT_FOUND", f"OEM id={oem_id} 不存在", 404)
        prof = NexusOemProfile(oem_id=int(oem_id))
        s.add(prof)
    prof.admin_note = (note or "").strip()[:2000]
    prof.updated_ts = _now_ms()


def add_oem_file(
    s, oem_id: int, filename: str, content_type: str, data: bytes
) -> Dict[str, Any]:
    """上传客户附件（合同等）。扩展名白名单 + 20MB 上限；文件名仅取 basename。"""
    if s.get(NexusOem, int(oem_id)) is None:
        raise FleetError("NEXUS_OEM_NOT_FOUND", f"OEM id={oem_id} 不存在", 404)
    # 掐掉路径分隔符，只留纯文件名（防奇怪的下载头/路径注入）
    clean = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()[:255]
    if not clean:
        raise FleetError("NEXUS_BAD_FILE", "文件名不能为空")
    ext = ("." + clean.rsplit(".", 1)[-1].lower()) if "." in clean else ""
    if ext not in _FILE_EXT_OK:
        raise FleetError(
            "NEXUS_BAD_FILE", "只支持合同常用格式：pdf/doc(x)/xls(x)/jpg/png/zip"
        )
    if not data:
        raise FleetError("NEXUS_BAD_FILE", "文件内容为空")
    if len(data) > FILE_MAX_BYTES:
        raise FleetError("NEXUS_FILE_TOO_BIG", "单个文件不能超过 20MB", 413)
    row = NexusOemFile(
        oem_id=int(oem_id),
        filename=clean,
        content_type=(content_type or "application/octet-stream")[:120],
        size=len(data),
        data=data,
    )
    s.add(row)
    s.flush()
    return {"id": row.id, "filename": row.filename, "size": row.size}


def get_oem_file(s, file_id: int) -> NexusOemFile:
    """按 id 取附件行（下载用）。"""
    row = s.get(NexusOemFile, int(file_id))
    if row is None:
        raise FleetError("NEXUS_FILE_NOT_FOUND", "附件不存在", 404)
    return row


def delete_oem_file(s, file_id: int) -> None:
    """删除附件（幂等）。"""
    row = s.get(NexusOemFile, int(file_id))
    if row is not None:
        s.delete(row)
        s.flush()


def set_oem_status(s, oem_id: int, status: str) -> Dict[str, Any]:
    """超管停用/启用某个 OEM 账号（自助注册模式下的唯一管控抓手）。

    disabled 的效果（既有逻辑已生效，这里只负责切状态）：
      - 不能再登录（login 校验 status）；
      - 已发出的会话立即失效（resolve_session 校验 status）；
      - 已认领的 KEY/实例数据保留——误停可无损恢复。
    """
    if status not in ("active", "disabled"):
        raise FleetError("NEXUS_BAD_STATUS", "状态只能是 active 或 disabled")
    row = s.get(NexusOem, int(oem_id))
    if row is None:
        raise FleetError("NEXUS_OEM_NOT_FOUND", f"OEM id={oem_id} 不存在", 404)
    row.status = status
    return public_oem(row)


def owns_instance(s, oem_id: int, instance_id: int) -> bool:
    """校验某实例是否归该 OEM（写操作/充值申请前的归属守卫）。"""
    inst = s.get(NexusInstance, int(instance_id))
    if inst is None:
        return False
    claim = s.get(NexusKeyClaim, inst.key_id)
    return claim is not None and claim.oem_id == int(oem_id)


__all__ = [
    "hash_password",
    "verify_password",
    "password_problem",
    "register",
    "login",
    "resolve_session",
    "logout",
    "public_oem",
    "referral_info",
    "share_summary",
    "network_directory",
    "qr_target",
    "record_user_attribution",
    "hierarchy_snapshot",
    "claim_key",
    "my_keys",
    "my_instances",
    "my_instance_detail",
    "list_oems",
    "set_oem_status",
    "oem_detail",
    "set_admin_note",
    "add_oem_file",
    "get_oem_file",
    "delete_oem_file",
    "request_key",
    "my_requests",
    "request_counts",
    "list_requests",
    "request_detail",
    "update_request",
    "cancel_request",
    "decide_request",
    "reveal_request_key",
    "clear_plain_by_key",
    "owns_instance",
    "normalize_key",
]
