"""OEM 终身会员激活码与 Token 购买申请。

两条流程都以“申请≠履约”为底线：激活码需运营审批后生成，
Token 需财务确认真实到账后才写入钱包。
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from typing import Any, Dict, List

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select

from nexus.db import (
    NexusInstance,
    NexusKey,
    NexusKeyClaim,
    NexusLifetimeActivationCode,
    NexusLifetimeActivationRequest,
    NexusOem,
    NexusOemProfile,
    NexusOrder,
    NexusTokenPurchaseRequest,
)
from nexus.fleet import FleetError
from nexus.keys import hash_key, looks_like_key

_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_DELIVERY_TTL_MS = 7 * 24 * 3600 * 1000
_REVEAL_WINDOW_MS = 10 * 60 * 1000


def _now_ms() -> int:
    return int(time.time() * 1000)


def _fernet() -> Fernet:
    raw = os.environ.get("NEXUS_SECRET_KEY", "").strip()
    if len(raw) < 32:
        raise FleetError(
            "NEXUS_SECRET_KEY_MISSING",
            "终身激活码交付需要先配置 NEXUS_SECRET_KEY",
            503,
        )
    # 与节点 KEY/支付配置使用不同派生上下文，避免一类密文被另一领域解密。
    derived = hashlib.sha256(("lifetime-member-v1\0" + raw).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def _generate_code() -> str:
    groups = ["".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(4)]
    return "-".join(["GLM", *groups])


def _normalize_code(raw: str) -> str:
    return (raw or "").strip().upper()


def _hash_code(raw: str) -> str:
    return hashlib.sha256(_normalize_code(raw).encode("utf-8")).hexdigest()


def _looks_like_code(raw: str) -> bool:
    parts = _normalize_code(raw).split("-")
    return len(parts) == 5 and parts[0] == "GLM" and all(len(p) == 4 for p in parts[1:])


def _owned_instance(s, oem_id: int, instance_id: int) -> NexusInstance:
    # 同一节点的申请先锁实例行：PostgreSQL 下可把并发双击串行化，避免两条
    # “待审核”工单同时越过查询。SQLite 测试会安全忽略 FOR UPDATE。
    instance = s.execute(
        select(NexusInstance)
        .where(NexusInstance.id == int(instance_id))
        .with_for_update()
    ).scalar_one_or_none()
    if instance is None:
        raise FleetError("NEXUS_INSTANCE_MISSING", "节点不存在", 404)
    claim = s.get(NexusKeyClaim, int(instance.key_id))
    if claim is None or int(claim.oem_id) != int(oem_id):
        raise FleetError("NEXUS_FORBIDDEN", "该节点不属于你的账号", 403)
    return instance


def _oem_label(s, oem_id: int) -> Dict[str, str]:
    account = s.get(NexusOem, int(oem_id))
    profile = s.get(NexusOemProfile, int(oem_id))
    return {
        "oem_email": account.email if account else f"#{oem_id}",
        "company": profile.company if profile else (account.name if account else ""),
    }


def _request_public(s, row: NexusLifetimeActivationRequest) -> Dict[str, Any]:
    instance = s.get(NexusInstance, int(row.instance_id))
    code = s.execute(
        select(NexusLifetimeActivationCode).where(
            NexusLifetimeActivationCode.request_id == int(row.id)
        )
    ).scalar_one_or_none()
    result: Dict[str, Any] = {
        "id": int(row.id),
        "oem_id": int(row.oem_id),
        "instance_id": int(row.instance_id),
        "domain": instance.domain if instance else "",
        "note": row.note or "",
        "status": row.status,
        "created_ts": int(row.created_ts),
        "decided_ts": int(row.decided_ts) if row.decided_ts else None,
        "decide_note": row.decide_note or "",
        "code": None,
    }
    if code is not None:
        result["code"] = {
            "id": int(code.id),
            "tail": code.code_tail,
            "status": code.status,
            "member_user_id": code.member_user_id or "",
            "device_kind": code.device_kind or "",
            "device_id": code.device_id or "",
            "activated_ts": int(code.activated_ts) if code.activated_ts else None,
        }
    return result


def request_lifetime_code(s, oem_id: int, instance_id: int, note: str = "") -> Dict[str, Any]:
    _owned_instance(s, oem_id, instance_id)
    pending = s.execute(
        select(NexusLifetimeActivationRequest).where(
            NexusLifetimeActivationRequest.oem_id == int(oem_id),
            NexusLifetimeActivationRequest.instance_id == int(instance_id),
            NexusLifetimeActivationRequest.status == "pending",
        )
    ).scalar_one_or_none()
    if pending is not None:
        raise FleetError("NEXUS_LIFETIME_REQUEST_EXISTS", "该节点已有待审核的终身激活码申请", 409)
    row = NexusLifetimeActivationRequest(
        oem_id=int(oem_id),
        instance_id=int(instance_id),
        note=(note or "").strip()[:500],
    )
    s.add(row)
    s.flush()
    return _request_public(s, row)


def my_lifetime_requests(s, oem_id: int) -> List[Dict[str, Any]]:
    rows = s.execute(
        select(NexusLifetimeActivationRequest)
        .where(NexusLifetimeActivationRequest.oem_id == int(oem_id))
        .order_by(NexusLifetimeActivationRequest.id.desc())
        .limit(200)
    ).scalars().all()
    return [_request_public(s, row) for row in rows]


def list_lifetime_requests(s) -> List[Dict[str, Any]]:
    rows = s.execute(
        select(NexusLifetimeActivationRequest)
        .order_by(NexusLifetimeActivationRequest.id.desc())
        .limit(300)
    ).scalars().all()
    result = []
    for row in rows:
        item = _request_public(s, row)
        item.update(_oem_label(s, int(row.oem_id)))
        result.append(item)
    return result


def cancel_lifetime_request(s, oem_id: int, request_id: int) -> Dict[str, Any]:
    row = s.execute(
        select(NexusLifetimeActivationRequest)
        .where(NexusLifetimeActivationRequest.id == int(request_id))
        .with_for_update()
    ).scalar_one_or_none()
    if row is None or int(row.oem_id) != int(oem_id):
        raise FleetError("NEXUS_LIFETIME_REQUEST_NOT_FOUND", "申请不存在", 404)
    if row.status != "pending":
        raise FleetError("NEXUS_LIFETIME_REQUEST_LOCKED", "只有待审核申请可以撤回", 409)
    row.status = "cancelled"
    row.decided_ts = _now_ms()
    return _request_public(s, row)


def decide_lifetime_request(
    s, request_id: int, approve: bool, decide_note: str = ""
) -> Dict[str, Any]:
    row = s.execute(
        select(NexusLifetimeActivationRequest)
        .where(NexusLifetimeActivationRequest.id == int(request_id))
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise FleetError("NEXUS_LIFETIME_REQUEST_NOT_FOUND", "申请不存在", 404)
    if row.status != "pending":
        raise FleetError("NEXUS_LIFETIME_REQUEST_DECIDED", "该申请已经处理", 409)
    row.decide_note = (decide_note or "").strip()[:500]
    row.decided_ts = _now_ms()
    if not approve:
        row.status = "rejected"
        return _request_public(s, row)
    _owned_instance(s, int(row.oem_id), int(row.instance_id))
    plain = _generate_code()
    code = NexusLifetimeActivationCode(
        request_id=int(row.id),
        oem_id=int(row.oem_id),
        instance_id=int(row.instance_id),
        code_hash=_hash_code(plain),
        code_tail=plain[-4:],
        encrypted_code=_fernet().encrypt(plain.encode("utf-8")),
    )
    s.add(code)
    row.status = "approved"
    s.flush()
    return _request_public(s, row)


def reveal_lifetime_code(s, oem_id: int, request_id: int) -> Dict[str, Any]:
    row = s.get(NexusLifetimeActivationRequest, int(request_id))
    if row is None or int(row.oem_id) != int(oem_id):
        raise FleetError("NEXUS_LIFETIME_REQUEST_NOT_FOUND", "申请不存在", 404)
    code = s.execute(
        select(NexusLifetimeActivationCode).where(
            NexusLifetimeActivationCode.request_id == int(row.id)
        )
    ).scalar_one_or_none()
    if code is None or not code.encrypted_code:
        raise FleetError("NEXUS_LIFETIME_CODE_UNAVAILABLE", "激活码已兑换或交付窗口已关闭", 410)
    now = _now_ms()
    if code.first_revealed_ts is None:
        if now > int(code.created_ts) + _DELIVERY_TTL_MS:
            raise FleetError("NEXUS_LIFETIME_CODE_EXPIRED", "激活码领取期已过，请联系平台重置", 410)
        code.first_revealed_ts = now
        code.reveal_until_ts = now + _REVEAL_WINDOW_MS
    elif not code.reveal_until_ts or now > int(code.reveal_until_ts):
        raise FleetError("NEXUS_LIFETIME_CODE_REVEAL_CLOSED", "重复查看窗口已关闭，请使用已安全保存的激活码", 410)
    try:
        plain = _fernet().decrypt(bytes(code.encrypted_code)).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise FleetError("NEXUS_LIFETIME_CODE_INVALID", "激活码无法解密，请联系平台", 500) from exc
    return {
        "activation_code": plain,
        "reveal_until_ts": int(code.reveal_until_ts or 0),
        "warning": "请立即安全保存；页面只提供 10 分钟重复查看窗口。",
    }


def activate_lifetime_code(
    s,
    *,
    raw_node_key: str,
    activation_code: str,
    user_id: str,
    device_kind: str = "node",
    device_id: str = "",
) -> Dict[str, Any]:
    if device_kind != "node":
        raise FleetError("NEXUS_DESKTOP_NOT_RELEASED", "桌面端本地部署尚未开放", 409)
    if not user_id.startswith("@") or ":" not in user_id:
        raise FleetError("NEXUS_BAD_USER_ID", "用户账号不合法")
    if not looks_like_key(raw_node_key):
        raise FleetError("NEXUS_BAD_KEY", "节点授权 KEY 格式不正确")
    node_key = s.execute(
        select(NexusKey).where(NexusKey.key_hash == hash_key(raw_node_key))
    ).scalar_one_or_none()
    if node_key is None or node_key.status != "active" or node_key.instance_id is None:
        raise FleetError("NEXUS_NODE_NOT_ACTIVE", "当前节点授权无效", 403)
    if not _looks_like_code(activation_code):
        raise FleetError("NEXUS_BAD_LIFETIME_CODE", "终身激活码格式不正确")
    code = s.execute(
        select(NexusLifetimeActivationCode).where(
            NexusLifetimeActivationCode.code_hash == _hash_code(activation_code)
        ).with_for_update()
    ).scalar_one_or_none()
    if code is None:
        raise FleetError("NEXUS_LIFETIME_CODE_NOT_FOUND", "终身激活码不存在", 404)
    if int(code.instance_id) != int(node_key.instance_id):
        raise FleetError("NEXUS_LIFETIME_NODE_MISMATCH", "该激活码不属于当前节点", 403)
    clean_device = (device_id or "").strip()[:255]
    if code.status == "activated":
        if code.member_user_id == user_id and code.device_kind == device_kind:
            return {
                "ok": True,
                "already_activated": True,
                "membership": "paid",
                "expires_ts": 0,
            }
        raise FleetError("NEXUS_LIFETIME_CODE_USED", "该终身激活码已被其他账号使用", 409)
    if code.status != "active":
        raise FleetError("NEXUS_LIFETIME_CODE_REVOKED", "该终身激活码已停用", 403)
    code.status = "activated"
    code.member_user_id = user_id
    code.device_kind = device_kind
    code.device_id = clean_device
    code.activated_ts = _now_ms()
    code.encrypted_code = None
    return {
        "ok": True,
        "already_activated": False,
        "membership": "paid",
        "expires_ts": 0,
    }


def request_token_purchase(
    s, oem_id: int, instance_id: int, requested_tokens: int, note: str = ""
) -> Dict[str, Any]:
    _owned_instance(s, oem_id, instance_id)
    tokens = int(requested_tokens)
    if tokens < 10_000 or tokens > 100_000_000_000:
        raise FleetError("NEXUS_BAD_TOKEN_AMOUNT", "申请量需在 10,000 到 100,000,000,000 Token 之间")
    row = NexusTokenPurchaseRequest(
        oem_id=int(oem_id),
        instance_id=int(instance_id),
        requested_tokens=tokens,
        note=(note or "").strip()[:500],
    )
    s.add(row)
    s.flush()
    return _token_request_public(s, row)


def _token_request_public(s, row: NexusTokenPurchaseRequest) -> Dict[str, Any]:
    instance = s.get(NexusInstance, int(row.instance_id))
    return {
        "id": int(row.id),
        "oem_id": int(row.oem_id),
        "instance_id": int(row.instance_id),
        "domain": instance.domain if instance else "",
        "requested_tokens": int(row.requested_tokens),
        "note": row.note or "",
        "status": row.status,
        "amount_cents": int(row.amount_cents) if row.amount_cents is not None else None,
        "order_id": int(row.order_id) if row.order_id else None,
        "created_ts": int(row.created_ts),
        "decided_ts": int(row.decided_ts) if row.decided_ts else None,
        "decide_note": row.decide_note or "",
    }


def my_token_purchase_requests(s, oem_id: int) -> List[Dict[str, Any]]:
    rows = s.execute(
        select(NexusTokenPurchaseRequest)
        .where(NexusTokenPurchaseRequest.oem_id == int(oem_id))
        .order_by(NexusTokenPurchaseRequest.id.desc())
        .limit(200)
    ).scalars().all()
    return [_token_request_public(s, row) for row in rows]


def list_token_purchase_requests(s) -> List[Dict[str, Any]]:
    rows = s.execute(
        select(NexusTokenPurchaseRequest)
        .order_by(NexusTokenPurchaseRequest.id.desc())
        .limit(300)
    ).scalars().all()
    result = []
    for row in rows:
        item = _token_request_public(s, row)
        item.update(_oem_label(s, int(row.oem_id)))
        result.append(item)
    return result


def cancel_token_purchase_request(s, oem_id: int, request_id: int) -> Dict[str, Any]:
    row = s.execute(
        select(NexusTokenPurchaseRequest)
        .where(NexusTokenPurchaseRequest.id == int(request_id))
        .with_for_update()
    ).scalar_one_or_none()
    if row is None or int(row.oem_id) != int(oem_id):
        raise FleetError("NEXUS_TOKEN_REQUEST_NOT_FOUND", "Token 购买申请不存在", 404)
    if row.status != "pending":
        raise FleetError("NEXUS_TOKEN_REQUEST_LOCKED", "只有待处理申请可以撤回", 409)
    row.status = "cancelled"
    row.decided_ts = _now_ms()
    return _token_request_public(s, row)


def decide_token_purchase_request(
    s,
    request_id: int,
    *,
    approve: bool,
    amount_cents: int = 0,
    decide_note: str = "",
) -> Dict[str, Any]:
    row = s.execute(
        select(NexusTokenPurchaseRequest)
        .where(NexusTokenPurchaseRequest.id == int(request_id))
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise FleetError("NEXUS_TOKEN_REQUEST_NOT_FOUND", "Token 购买申请不存在", 404)
    if row.status != "pending":
        raise FleetError("NEXUS_TOKEN_REQUEST_DECIDED", "该申请已经处理", 409)
    row.decide_note = (decide_note or "").strip()[:500]
    row.decided_ts = _now_ms()
    if not approve:
        row.status = "rejected"
        return _token_request_public(s, row)
    cents = int(amount_cents)
    if cents <= 0:
        raise FleetError("NEXUS_PAYMENT_AMOUNT_REQUIRED", "请填写已核对的实际到账金额")
    _owned_instance(s, int(row.oem_id), int(row.instance_id))
    from nexus import fleet

    order = NexusOrder(
        order_no="NXM%d%s" % (int(time.time()), secrets.token_hex(3).upper()),
        oem_id=int(row.oem_id),
        kind="topup",
        instance_id=int(row.instance_id),
        channel="manual_request",
        amount_cents=cents,
        tokens=int(row.requested_tokens),
        status="paid",
        provider_txn=f"TOKEN-REQUEST-{row.id}",
        paid_ts=_now_ms(),
    )
    s.add(order)
    s.flush()
    fleet.topup(
        s,
        int(row.instance_id),
        int(row.requested_tokens),
        f"订单 {order.order_no} | OEM Token 购买申请 #{row.id}",
    )
    row.status = "paid"
    row.amount_cents = cents
    row.order_id = int(order.id)
    return _token_request_public(s, row)


__all__ = [
    "activate_lifetime_code",
    "cancel_lifetime_request",
    "cancel_token_purchase_request",
    "decide_lifetime_request",
    "decide_token_purchase_request",
    "list_lifetime_requests",
    "list_token_purchase_requests",
    "my_lifetime_requests",
    "my_token_purchase_requests",
    "request_lifetime_code",
    "request_token_purchase",
    "reveal_lifetime_code",
]
