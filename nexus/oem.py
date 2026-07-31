"""Nexus OEM 账号层：注册 / 登录 / 会话 + KEY 认领 + 自有资源查询。

这是「角色分权」的 OEM 一侧（模块6 P1 拍板）：
    - 平台超管 = 现有 ``NEXUS_ADMIN_TOKEN``（看全部、签发 KEY、充值）——见 service.py；
    - OEM 客户 = 邮箱+密码独立账号，登录拿会话令牌，**只能看/操作自己认领的
      KEY 及其实例**（服务端强制，前端只是配合）。

纯函数层：每个函数收一个 SQLAlchemy Session，不自管事务（HTTP 层一请求一提交），
错误统一抛 ``FleetError``（复用 fleet 那套，HTTP 层已能翻成 JSON）。密码用标准库
pbkdf2 派生，不引三方库（与项目「栈越少越好」一致）。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select

from nexus.db import (
    NexusInstance,
    NexusKey,
    NexusKeyClaim,
    NexusKeyRequest,
    NexusOem,
    NexusOemFile,
    NexusOemInvite,
    NexusOemProfile,
    NexusOemShare,
    NexusSession,
    NexusUserAttribution,
    NexusWallet,
)
from nexus.fleet import FleetError
from nexus.keys import hash_key, looks_like_key, normalize_key

# 会话有效期：7 天（OEM 门户是低频配置场景，不需要长会话；到期重登）
_SESSION_TTL_MS = 7 * 24 * 3600 * 1000
# pbkdf2 迭代次数：兼顾安全与单机 CPU（同步服务，别把登录搞太慢）
_PBKDF2_ITERS = 200_000
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _now_ms() -> int:
    return int(time.time() * 1000)


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
        raise FleetError("NEXUS_INVITER_REQUIRED", "请填写邀请人邮箱（平台直接客户填 GUDUU）")
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
        raise FleetError("NEXUS_INVITER_INVALID", "邀请人不存在或不可用，请与邀请你的人确认", 400)
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
        "name": (profile.company if profile and profile.company else owner.name) or "OEM 客户",
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


def share_summary(s, oem_id: int, portal_base: str) -> Dict[str, Any]:
    """生成 OEM 门户的分享链接、二维码目标与层级人数统计。"""
    owner = s.get(NexusOem, int(oem_id))
    if owner is None:
        raise FleetError("NEXUS_OEM_NOT_FOUND", "OEM 不存在", 404)
    share = _share_for(s, owner.id)
    instances = my_instances(s, owner.id)
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


def qr_target(s, oem_id: int, portal_base: str, kind: str, instance_id: int = 0) -> str:
    """按当前登录 OEM 重新计算二维码目标，拒绝把二维码端点当任意 URL 生成器。"""
    summary = share_summary(s, oem_id, portal_base)
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
        raise FleetError("NEXUS_REFERRAL_INSTANCE_MISMATCH", "邀请链接与注册实例不匹配", 403)
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
            raise FleetError("NEXUS_USER_ALREADY_ATTRIBUTED", "用户已经归属其他 OEM", 409)
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
    rows = s.execute(
        select(NexusKey).where(NexusKey.id.in_(ids)).order_by(NexusKey.id.desc())
    ).scalars().all()
    return [
        {
            "id": r.id,
            "tail": r.key_tail,
            "status": r.status,
            "token_grant": int(r.token_grant),
            "instance_id": r.instance_id,
            "redeemed_ts": r.redeemed_ts,
            "created_ts": r.created_ts,
        }
        for r in rows
    ]


def my_instances(s, oem_id: int) -> List[Dict[str, Any]]:
    """该 OEM 名下已开通的实例 + 钱包余额（门户"我的实例"数据源）。"""
    ids = _owned_key_ids(s, oem_id)
    if not ids:
        return []
    rows = s.execute(
        select(NexusInstance)
        .where(NexusInstance.key_id.in_(ids))
        .order_by(NexusInstance.id.desc())
    ).scalars().all()
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


def list_oems(s) -> List[Dict[str, Any]]:
    """全部 OEM 账号 + 认领的 KEY 数（**超管**控制台"客户列表"数据源）。

    只给超管端点用（service.py 里挂在 /nexus/admin/ 下、走 NEXUS_ADMIN_TOKEN 鉴权），
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
        select(NexusUserAttribution.oem_id, func.count(NexusUserAttribution.id))
        .group_by(NexusUserAttribution.oem_id)
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
    users = s.execute(
        select(NexusUserAttribution).order_by(NexusUserAttribution.id.desc())
    ).scalars().all()
    return {
        "oems": nodes,
        "oem_edges": [
            {"oem_id": row["id"], "parent_oem_id": row["inviter_id"]}
            for row in nodes
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


# ---------- 授权码申请闭环（OEM 申请 → 超管签发 → 门户交付明文）----------

# 同一 OEM 最多同时挂起的申请数（防手滑/刷单；正常客户一次买一两把）
_MAX_PENDING_REQUESTS = 3


def request_key(s, oem_id: int, note: str = "") -> Dict[str, Any]:
    """OEM 在门户提交一张授权码申请单（一单=一把 KEY）。"""
    pending = s.execute(
        select(NexusKeyRequest).where(
            NexusKeyRequest.oem_id == int(oem_id),
            NexusKeyRequest.status == "pending",
        )
    ).scalars().all()
    if len(pending) >= _MAX_PENDING_REQUESTS:
        raise FleetError(
            "NEXUS_TOO_MANY_REQUESTS",
            f"已有 {len(pending)} 张待处理申请，请等待平台处理后再提交",
            429,
        )
    row = NexusKeyRequest(oem_id=int(oem_id), note=(note or "").strip()[:500])
    s.add(row)
    s.flush()
    return _public_request(row)


def my_requests(s, oem_id: int) -> List[Dict[str, Any]]:
    """该 OEM 的申请单列表（含已批准单的 KEY 明文——这就是交付通道）。"""
    rows = s.execute(
        select(NexusKeyRequest)
        .where(NexusKeyRequest.oem_id == int(oem_id))
        .order_by(NexusKeyRequest.id.desc())
    ).scalars().all()
    return [_public_request(r) for r in rows]


def _public_request(r: NexusKeyRequest) -> Dict[str, Any]:
    return {
        "id": r.id,
        "oem_id": r.oem_id,
        "note": r.note,
        "status": r.status,
        "created_ts": r.created_ts,
        "decided_ts": r.decided_ts,
        "key_id": r.key_id,
        # 明文只在「已批准且尚未装机兑换」窗口内可见，兑换后被清空
        "key": r.key_plain or None,
        "decide_note": r.decide_note,
    }


def list_requests(s, status: str = "pending") -> List[Dict[str, Any]]:
    """超管视角的申请列表（默认只看待处理；带申请人邮箱便于辨认）。"""
    q = select(NexusKeyRequest).order_by(NexusKeyRequest.id.desc())
    if status:
        q = q.where(NexusKeyRequest.status == status)
    rows = s.execute(q).scalars().all()
    emails: Dict[int, str] = {}
    for r in rows:
        if r.oem_id not in emails:
            acc = s.get(NexusOem, r.oem_id)
            emails[r.oem_id] = acc.email if acc else f"#{r.oem_id}"
    out = []
    for r in rows:
        item = _public_request(r)
        item.pop("key", None)  # 超管列表不需要明文（交付走 OEM 门户）
        item["oem_email"] = emails.get(r.oem_id, "")
        out.append(item)
    return out


def decide_request(
    s, request_id: int, approve: bool, token_grant: int = 0, decide_note: str = ""
) -> Dict[str, Any]:
    """超管裁决申请：批准=签发一把 KEY 并自动认领到申请人名下 + 明文存单交付。

    延迟导入 fleet 避免模块级循环依赖（fleet 不知道 oem 层，反向单向依赖）。
    """
    from nexus import fleet

    row = s.get(NexusKeyRequest, int(request_id))
    if row is None:
        raise FleetError("NEXUS_REQUEST_NOT_FOUND", f"申请 #{request_id} 不存在", 404)
    if row.status != "pending":
        raise FleetError("NEXUS_REQUEST_DECIDED", "该申请已处理过", 409)
    row.decided_ts = _now_ms()
    row.decide_note = (decide_note or "").strip()[:200]
    if not approve:
        row.status = "rejected"
        return _public_request(row)
    issued = fleet.issue_keys(
        s, count=1, note=f"申请单#{row.id} · {row.note[:60]}", token_grant=token_grant
    )[0]
    row.status = "approved"
    row.key_id = issued["id"]
    row.key_plain = issued["key"]
    # 自动认领到申请人名下：申请→签发→归属一步到位，OEM 无需再手动认领
    s.add(NexusKeyClaim(key_id=issued["id"], oem_id=row.oem_id))
    return _public_request(row)


def clear_plain_by_key(s, raw_key: str) -> None:
    """按明文 KEY 清空交付明文（申请单 + 订单，实例兑换成功后调用，幂等）。"""
    if not looks_like_key(raw_key):
        return
    key = s.execute(
        select(NexusKey).where(NexusKey.key_hash == hash_key(raw_key))
    ).scalar_one_or_none()
    if key is None:
        return
    for r in s.execute(
        select(NexusKeyRequest).where(NexusKeyRequest.key_id == key.id)
    ).scalars():
        r.key_plain = ""
    # 在线购买的订单同策略销毁明文（延迟导入避免 oem↔pay 环）
    from nexus import pay
    pay.clear_order_plain_by_key_id(s, key.id)


# ---------- 客户档案详情 / 合同附件（超管专用）----------

# 附件白名单（合同/资质常见格式）与单文件上限
_FILE_EXT_OK = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".jpeg", ".png", ".zip"}
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
    "qr_target",
    "record_user_attribution",
    "hierarchy_snapshot",
    "claim_key",
    "my_keys",
    "my_instances",
    "list_oems",
    "set_oem_status",
    "oem_detail",
    "set_admin_note",
    "add_oem_file",
    "get_oem_file",
    "delete_oem_file",
    "request_key",
    "my_requests",
    "list_requests",
    "decide_request",
    "clear_plain_by_key",
    "owns_instance",
    "normalize_key",
]
