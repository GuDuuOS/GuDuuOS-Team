"""OEM 销售价差、收益账本与人工提现。

平台始终是唯一收款方。本模块不会调用第三方代付或把支付密钥下发给 OEM；它只在
现有支付订单完成真实履约后，把“客户实付－OEM 结算价－渠道手续费”的价差记入
直属销售 OEM 的内部应付账本。当前渠道手续费尚无可靠回调字段，因此固定记 0，
以后接入渠道对账时必须通过反向/调整流水补齐，不能覆盖历史行。

收益默认 T+7 可提现。提现提交时立即写负向流水锁定余额，超管驳回时再写正向退回
流水；所有金额单位均为人民币分，账本只追加不修改。
"""

from __future__ import annotations

import json
import secrets
import time
from typing import Any, Dict, List, Optional

from cryptography.fernet import InvalidToken
from sqlalchemy import select

from nexus.db import (
    NexusLicenseCommercial,
    NexusOem,
    NexusOemCommercialTerms,
    NexusOemIncomeLedger,
    NexusOemInvite,
    NexusOemProfile,
    NexusOemWithdrawal,
    NexusOrder,
    NexusOrderCommercial,
)
from nexus.fleet import FleetError
from nexus.payment_config import _fernet


_MAX_WITHDRAW_CENTS = 100_000_000_00
_PAYOUT_METHODS = {"bank", "alipay", "wechat", "paypal"}


def _now_ms() -> int:
    """返回 Nexus 全库统一使用的毫秒时间戳。"""
    return int(time.time() * 1000)


def _seller_id(s, buyer_oem_id: int) -> Optional[int]:
    """取买家的直属上级作为唯一销售 OEM；平台主管返回 ``None``。"""
    edge = s.get(NexusOemInvite, int(buyer_oem_id))
    return int(edge.inviter_id) if edge is not None and edge.inviter_id else None


def _settlement_days(pricing: Dict[str, Any]) -> int:
    """清洗结算天数；运营配置异常时回退保守的 7 天。"""
    try:
        days = int(pricing.get("settlement_days", 7))
    except (TypeError, ValueError):
        days = 7
    return max(0, min(days, 90))


def effective_settlement_cents(
    s,
    seller_oem_id: Optional[int],
    kind: str,
    retail_cents: int,
    default_cents: int,
) -> int:
    """计算销售 OEM 的专属结算成本；未配置时使用平台主管默认价。

    专属价属于卖方而不是买方：同一个下级客户从哪个直属 OEM 购买，就使用哪个
    OEM 的条款。平台主管客户没有销售方，因此即使传入也只返回默认值。
    """
    cost = int(default_cents)
    if seller_oem_id:
        terms = s.get(NexusOemCommercialTerms, int(seller_oem_id))
        if terms is not None:
            if kind == "key" and terms.key_cost_cents is not None:
                candidate = int(terms.key_cost_cents)
                # 平台若把统一零售价调低到专属成本以下，旧条款不能让购买接口整体
                # 失效；该条款暂时回退平台默认，等待超管重新保存合法专属价。
                if 0 <= candidate <= int(retail_cents):
                    cost = candidate
            elif kind == "topup" and terms.topup_cost_bps is not None:
                cost = int(retail_cents) * int(terms.topup_cost_bps) // 10_000
    if cost < 0 or cost > int(retail_cents):
        raise FleetError("NEXUS_BAD_OEM_PRICE", "OEM 结算价必须介于 0 与客户售价之间")
    return cost


def snapshot_order(
    s,
    order: NexusOrder,
    pricing: Dict[str, Any],
    settlement_cents: int,
) -> NexusOrderCommercial:
    """在创建在线订单时冻结直属销售关系和价差。

    Args:
        s: SQLAlchemy Session。
        order: 已经 flush、具有稳定主键的订单。
        pricing: 当前平台定价快照。
        settlement_cents: 本商品给 OEM 的结算价。

    Returns:
        新建或已存在的商业快照；同一订单重复调用保持幂等。
    """
    existing = s.get(NexusOrderCommercial, int(order.id))
    if existing is not None:
        return existing
    retail = int(order.amount_cents)
    seller = _seller_id(s, int(order.oem_id))
    cost = effective_settlement_cents(
        s, seller, str(order.kind), retail, int(settlement_cents)
    )
    row = NexusOrderCommercial(
        order_id=int(order.id),
        buyer_oem_id=int(order.oem_id),
        seller_oem_id=seller,
        retail_cents=retail,
        settlement_cents=cost,
        margin_cents=(retail - cost) if seller else 0,
        settlement_days=_settlement_days(pricing),
    )
    s.add(row)
    return row


def snapshot_license(
    s,
    request_id: int,
    buyer_oem_id: int,
    pricing: Dict[str, Any],
) -> NexusLicenseCommercial:
    """冻结企业转账授权申请的销售关系和 KEY 结算价。"""
    existing = s.get(NexusLicenseCommercial, int(request_id))
    if existing is not None:
        return existing
    retail = int(pricing.get("key_price_cents") or 0)
    seller = _seller_id(s, int(buyer_oem_id))
    cost = effective_settlement_cents(
        s,
        seller,
        "key",
        retail,
        int(pricing.get("key_oem_cost_cents") or 0),
    )
    row = NexusLicenseCommercial(
        request_id=int(request_id),
        buyer_oem_id=int(buyer_oem_id),
        seller_oem_id=seller,
        retail_cents=retail,
        settlement_cents=cost,
        margin_cents=(retail - cost) if seller else 0,
        settlement_days=_settlement_days(pricing),
    )
    s.add(row)
    return row


def _record_sale(
    s,
    *,
    source_key: str,
    seller_oem_id: Optional[int],
    buyer_oem_id: int,
    kind: str,
    gross_cents: int,
    settlement_cents: int,
    margin_cents: int,
    settlement_days: int,
    order_id: Optional[int] = None,
    note: str = "",
) -> Optional[NexusOemIncomeLedger]:
    """幂等写入一笔正向销售收益；平台主管或零价差不生成空流水。"""
    if not seller_oem_id or int(margin_cents) <= 0:
        return None
    existing = s.execute(
        select(NexusOemIncomeLedger).where(
            NexusOemIncomeLedger.source_key == source_key
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    now = _now_ms()
    row = NexusOemIncomeLedger(
        oem_id=int(seller_oem_id),
        source_key=source_key,
        kind=kind,
        delta_cents=int(margin_cents),
        order_id=int(order_id) if order_id else None,
        buyer_oem_id=int(buyer_oem_id),
        gross_cents=int(gross_cents),
        settlement_cents=int(settlement_cents),
        fee_cents=0,
        available_ts=now + int(settlement_days) * 24 * 3600 * 1000,
        note=(note or "")[:500],
        created_ts=now,
    )
    s.add(row)
    return row


def record_paid_order(s, order: NexusOrder) -> Optional[NexusOemIncomeLedger]:
    """在线订单完成 KEY/Token 履约后，把冻结价差记给直属销售 OEM。"""
    commercial = s.get(NexusOrderCommercial, int(order.id))
    if commercial is None:
        # 升级前历史订单没有商业快照，不能用今天价格倒推历史收益。
        return None
    return _record_sale(
        s,
        source_key=f"sale:order:{int(order.id)}",
        seller_oem_id=commercial.seller_oem_id,
        buyer_oem_id=int(commercial.buyer_oem_id),
        kind="sale_key" if order.kind == "key" else "sale_topup",
        gross_cents=int(commercial.retail_cents),
        settlement_cents=int(commercial.settlement_cents),
        margin_cents=int(commercial.margin_cents),
        settlement_days=int(commercial.settlement_days),
        order_id=int(order.id),
        note=f"{order.order_no} · {'节点授权' if order.kind == 'key' else 'Token 充值'}价差",
    )


def record_paid_license_transfer(
    s, request_id: int, transfer_no: str
) -> Optional[NexusOemIncomeLedger]:
    """企业转账授权核实到账并发码后，按申请商业快照记收益。"""
    commercial = s.get(NexusLicenseCommercial, int(request_id))
    if commercial is None:
        return None
    return _record_sale(
        s,
        source_key=f"sale:license:{int(request_id)}",
        seller_oem_id=commercial.seller_oem_id,
        buyer_oem_id=int(commercial.buyer_oem_id),
        kind="sale_key",
        gross_cents=int(commercial.retail_cents),
        settlement_cents=int(commercial.settlement_cents),
        margin_cents=int(commercial.margin_cents),
        settlement_days=int(commercial.settlement_days),
        note=f"{transfer_no} · 节点授权价差",
    )


def _public_ledger(row: NexusOemIncomeLedger) -> Dict[str, Any]:
    """把收益流水转成 OEM 可查看且不含付款敏感信息的字典。"""
    return {
        "id": int(row.id),
        "kind": row.kind,
        "delta_cents": int(row.delta_cents),
        "order_id": row.order_id,
        "buyer_oem_id": row.buyer_oem_id,
        "gross_cents": int(row.gross_cents),
        "settlement_cents": int(row.settlement_cents),
        "fee_cents": int(row.fee_cents),
        "available_ts": int(row.available_ts),
        "note": row.note,
        "created_ts": int(row.created_ts),
    }


def _public_withdrawal(
    row: NexusOemWithdrawal, *, admin: bool = False
) -> Dict[str, Any]:
    """返回提现记录；只有超管响应包含解密后的完整收款资料。"""
    out: Dict[str, Any] = {
        "id": int(row.id),
        "withdrawal_no": row.withdrawal_no,
        "oem_id": int(row.oem_id),
        "amount_cents": int(row.amount_cents),
        "status": row.status,
        "payout_method": row.payout_method,
        "payout_masked": row.payout_masked,
        "applicant_note": row.applicant_note,
        "admin_note": row.admin_note,
        "created_ts": int(row.created_ts),
        "decided_ts": row.decided_ts,
        "paid_ts": row.paid_ts,
    }
    if admin:
        out["payout"] = _decrypt_payout(row)
    return out


def _balances(rows: List[NexusOemIncomeLedger], now: int) -> Dict[str, int]:
    """从只追加流水计算待结算、可提现、累计收益和累计提现。"""
    sale_rows = [row for row in rows if row.kind.startswith("sale_")]
    pending = sum(
        int(row.delta_cents)
        for row in sale_rows
        if int(row.available_ts) > now
    )
    available = sum(
        int(row.delta_cents) for row in rows if int(row.available_ts) <= now
    )
    return {
        "pending_cents": max(0, pending),
        "available_cents": max(0, available),
        "earned_cents": sum(int(row.delta_cents) for row in sale_rows),
        "withdrawn_cents": abs(
            sum(
                int(row.delta_cents)
                for row in rows
                if row.kind == "withdrawal"
            )
        ),
    }


def finance_snapshot(s, oem_id: int) -> Dict[str, Any]:
    """返回 OEM 的真实收益余额、价差流水、提现历史和当前结算规则。"""
    from nexus import pay

    owner_id = int(oem_id)
    rows = s.execute(
        select(NexusOemIncomeLedger)
        .where(NexusOemIncomeLedger.oem_id == owner_id)
        .order_by(NexusOemIncomeLedger.id.desc())
    ).scalars().all()
    withdrawals = s.execute(
        select(NexusOemWithdrawal)
        .where(NexusOemWithdrawal.oem_id == owner_id)
        .order_by(NexusOemWithdrawal.id.desc())
        .limit(100)
    ).scalars().all()
    pricing = pay.get_pricing(s)
    key_cost = effective_settlement_cents(
        s,
        owner_id,
        "key",
        int(pricing["key_price_cents"]),
        int(pricing["key_oem_cost_cents"]),
    )
    terms = {
        "key_retail_cents": int(pricing["key_price_cents"]),
        "key_settlement_cents": key_cost,
        "key_margin_cents": int(pricing["key_price_cents"])
        - key_cost,
        "topup_packs": [
            {
                "tokens": int(item["tokens"]),
                "retail_cents": int(item["cents"]),
                "settlement_cents": effective_settlement_cents(
                    s,
                    owner_id,
                    "topup",
                    int(item["cents"]),
                    int(item["oem_cost_cents"]),
                ),
                "margin_cents": int(item["cents"])
                - effective_settlement_cents(
                    s,
                    owner_id,
                    "topup",
                    int(item["cents"]),
                    int(item["oem_cost_cents"]),
                ),
            }
            for item in pricing["topup_packs"]
        ],
        "settlement_days": int(pricing["settlement_days"]),
        "withdraw_min_cents": int(pricing["withdraw_min_cents"]),
    }
    return {
        "summary": _balances(rows, _now_ms()),
        "terms": terms,
        "ledger": [_public_ledger(row) for row in rows[:100]],
        "withdrawals": [_public_withdrawal(row) for row in withdrawals],
    }


def list_commercial_terms(s) -> List[Dict[str, Any]]:
    """供超管列出全部 OEM 的有效结算价和是否使用专属配置。"""
    from nexus import pay

    pricing = pay.get_pricing(s)
    oems = s.execute(select(NexusOem).order_by(NexusOem.id.asc())).scalars().all()
    result: List[Dict[str, Any]] = []
    for owner in oems:
        row = s.get(NexusOemCommercialTerms, int(owner.id))
        key_cost = effective_settlement_cents(
            s,
            int(owner.id),
            "key",
            int(pricing["key_price_cents"]),
            int(pricing["key_oem_cost_cents"]),
        )
        result.append(
            {
                "oem_id": int(owner.id),
                "email": owner.email,
                "name": owner.name,
                "custom": row is not None,
                "key_cost_cents": key_cost,
                "topup_cost_bps": (
                    int(row.topup_cost_bps)
                    if row is not None and row.topup_cost_bps is not None
                    else None
                ),
            }
        )
    return result


def set_commercial_terms(s, oem_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    """超管设置或清除一个 OEM 的专属授权成本与 Token 结算比例。"""
    from nexus import pay

    owner = s.get(NexusOem, int(oem_id))
    if owner is None:
        raise FleetError("NEXUS_OEM_NOT_FOUND", "OEM 不存在", 404)
    pricing = pay.get_pricing(s)
    use_default = bool(data.get("use_default"))
    row = s.get(NexusOemCommercialTerms, int(oem_id))
    if use_default:
        if row is not None:
            s.delete(row)
            s.flush()
        return next(
            item for item in list_commercial_terms(s) if item["oem_id"] == int(oem_id)
        )
    key_cost = int(data.get("key_cost_cents", pricing["key_oem_cost_cents"]))
    topup_bps = int(data.get("topup_cost_bps", 10_000))
    if key_cost < 0 or key_cost > int(pricing["key_price_cents"]):
        raise FleetError("NEXUS_BAD_OEM_PRICE", "专属授权结算价不能高于客户售价")
    if not 0 <= topup_bps <= 10_000:
        raise FleetError("NEXUS_BAD_OEM_PRICE", "Token 结算比例必须在 0% 到 100% 之间")
    if row is None:
        row = NexusOemCommercialTerms(oem_id=int(oem_id))
        s.add(row)
    row.key_cost_cents = key_cost
    row.topup_cost_bps = topup_bps
    row.updated_ts = _now_ms()
    s.flush()
    return next(
        item for item in list_commercial_terms(s) if item["oem_id"] == int(oem_id)
    )


def _clean_payout(data: Dict[str, Any]) -> Dict[str, str]:
    """校验并裁剪 OEM 提交的收款账户；账号原文随后立即加密。"""
    if not isinstance(data, dict):
        raise FleetError("NEXUS_BAD_PAYOUT", "请填写收款账户")
    method = str(data.get("method", "")).strip().lower()
    if method not in _PAYOUT_METHODS:
        raise FleetError("NEXUS_BAD_PAYOUT", "请选择有效的收款方式")
    account_name = str(data.get("account_name", "")).strip()[:120]
    account_no = str(data.get("account_no", "")).strip()[:255]
    bank_name = str(data.get("bank_name", "")).strip()[:160]
    if not account_name or not account_no:
        raise FleetError("NEXUS_BAD_PAYOUT", "收款人和收款账号不能为空")
    if method == "bank" and not bank_name:
        raise FleetError("NEXUS_BAD_PAYOUT", "银行卡提现必须填写开户行")
    return {
        "method": method,
        "account_name": account_name,
        "account_no": account_no,
        "bank_name": bank_name,
    }


def _encrypt_payout(data: Dict[str, str]) -> bytes:
    """使用 Nexus 主密钥加密提现账户快照。"""
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return _fernet().encrypt(raw)


def _decrypt_payout(row: NexusOemWithdrawal) -> Dict[str, str]:
    """仅供超管处理提现时解密账户；密钥不匹配时返回可操作错误。"""
    try:
        raw = _fernet().decrypt(bytes(row.encrypted_payout))
        data = json.loads(raw.decode("utf-8"))
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError):
        raise FleetError("NEXUS_PAYOUT_DECRYPT_FAILED", "提现收款账户无法解密", 503)
    if not isinstance(data, dict):
        raise FleetError("NEXUS_PAYOUT_DECRYPT_FAILED", "提现收款账户数据损坏", 500)
    return {str(key): str(value) for key, value in data.items()}


def _mask_account(account_no: str) -> str:
    """生成 OEM 历史列表使用的账号尾号摘要。"""
    clean = account_no.strip()
    return ("****" + clean[-4:]) if len(clean) > 4 else "****"


def request_withdrawal(
    s,
    oem_id: int,
    amount_cents: int,
    payout: Dict[str, Any],
    note: str = "",
) -> Dict[str, Any]:
    """锁定可提现余额并创建人工提现申请。

    读取账本时加行锁，避免同一 OEM 双击或并发请求把同一余额提现两次。
    """
    from nexus import pay

    owner_id = int(oem_id)
    amount = int(amount_cents or 0)
    pricing = pay.get_pricing(s)
    minimum = int(pricing["withdraw_min_cents"])
    if amount < minimum or amount > _MAX_WITHDRAW_CENTS:
        raise FleetError(
            "NEXUS_BAD_WITHDRAW_AMOUNT",
            f"单次提现金额不得低于 {minimum / 100:.2f} 元",
        )
    rows = s.execute(
        select(NexusOemIncomeLedger)
        .where(NexusOemIncomeLedger.oem_id == owner_id)
        .with_for_update()
    ).scalars().all()
    available = _balances(rows, _now_ms())["available_cents"]
    if amount > available:
        raise FleetError("NEXUS_WITHDRAW_BALANCE_LOW", "可提现余额不足", 409)
    clean = _clean_payout(payout)
    now = _now_ms()
    row = NexusOemWithdrawal(
        withdrawal_no="WD%d%s" % (int(time.time()), secrets.token_hex(3).upper()),
        oem_id=owner_id,
        amount_cents=amount,
        status="pending",
        payout_method=clean["method"],
        encrypted_payout=_encrypt_payout(clean),
        payout_masked=f"{clean['account_name']} · {_mask_account(clean['account_no'])}",
        applicant_note=(note or "").strip()[:500],
        created_ts=now,
    )
    s.add(row)
    s.flush()
    s.add(
        NexusOemIncomeLedger(
            oem_id=owner_id,
            source_key=f"withdrawal:{int(row.id)}",
            kind="withdrawal",
            delta_cents=-amount,
            withdrawal_id=int(row.id),
            available_ts=now,
            note=f"提交提现 {row.withdrawal_no}",
            created_ts=now,
        )
    )
    s.flush()
    return _public_withdrawal(row)


def list_admin_withdrawals(s) -> List[Dict[str, Any]]:
    """超管查看提现队列；返回企业名和解密后的付款所需账户。"""
    rows = s.execute(
        select(NexusOemWithdrawal)
        .order_by(NexusOemWithdrawal.id.desc())
        .limit(200)
    ).scalars().all()
    oem_ids = list({int(row.oem_id) for row in rows})
    accounts = {
        int(row.id): row
        for row in s.execute(select(NexusOem).where(NexusOem.id.in_(oem_ids))).scalars()
    } if oem_ids else {}
    profiles = {
        int(row.oem_id): row
        for row in s.execute(
            select(NexusOemProfile).where(NexusOemProfile.oem_id.in_(oem_ids))
        ).scalars()
    } if oem_ids else {}
    out: List[Dict[str, Any]] = []
    for row in rows:
        item = _public_withdrawal(row, admin=True)
        account = accounts.get(int(row.oem_id))
        profile = profiles.get(int(row.oem_id))
        item["oem_email"] = account.email if account is not None else ""
        item["company"] = (
            profile.company if profile is not None and profile.company else
            (account.name if account is not None else f"OEM #{row.oem_id}")
        )
        out.append(item)
    return out


def decide_withdrawal(
    s, withdrawal_id: int, action: str, note: str = ""
) -> Dict[str, Any]:
    """超管批准、确认打款或驳回提现；驳回会用正向流水自动退回余额。"""
    row = s.execute(
        select(NexusOemWithdrawal)
        .where(NexusOemWithdrawal.id == int(withdrawal_id))
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise FleetError("NEXUS_WITHDRAW_NOT_FOUND", "提现申请不存在", 404)
    selected = (action or "").strip().lower()
    clean_note = (note or "").strip()[:500]
    now = _now_ms()
    if selected == "approve":
        if row.status == "approved":
            return _public_withdrawal(row, admin=True)
        if row.status != "pending":
            raise FleetError("NEXUS_WITHDRAW_STATE", "当前状态不能批准", 409)
        row.status = "approved"
        row.decided_ts = now
    elif selected == "paid":
        if row.status == "paid":
            return _public_withdrawal(row, admin=True)
        if row.status != "approved":
            raise FleetError("NEXUS_WITHDRAW_STATE", "请先批准提现再确认打款", 409)
        if not clean_note:
            raise FleetError("NEXUS_WITHDRAW_NOTE_REQUIRED", "确认打款必须填写流水号或备注")
        row.status = "paid"
        row.paid_ts = now
    elif selected == "reject":
        if row.status == "rejected":
            return _public_withdrawal(row, admin=True)
        if row.status not in ("pending", "approved"):
            raise FleetError("NEXUS_WITHDRAW_STATE", "当前状态不能驳回", 409)
        if not clean_note:
            raise FleetError("NEXUS_WITHDRAW_NOTE_REQUIRED", "驳回提现必须填写原因")
        row.status = "rejected"
        row.decided_ts = now
        source_key = f"withdrawal_return:{int(row.id)}"
        existing = s.execute(
            select(NexusOemIncomeLedger).where(
                NexusOemIncomeLedger.source_key == source_key
            )
        ).scalar_one_or_none()
        if existing is None:
            s.add(
                NexusOemIncomeLedger(
                    oem_id=int(row.oem_id),
                    source_key=source_key,
                    kind="withdrawal_return",
                    delta_cents=int(row.amount_cents),
                    withdrawal_id=int(row.id),
                    available_ts=now,
                    note=f"提现驳回退回 {row.withdrawal_no}",
                    created_ts=now,
                )
            )
    else:
        raise FleetError("NEXUS_BAD_WITHDRAW_ACTION", "不支持的提现操作")
    row.admin_note = clean_note
    s.flush()
    return _public_withdrawal(row, admin=True)


def platform_summary(s) -> Dict[str, int]:
    """返回超管需要的 OEM 应付收益和提现队列汇总。"""
    now = _now_ms()
    rows = s.execute(select(NexusOemIncomeLedger)).scalars().all()
    withdrawals = s.execute(select(NexusOemWithdrawal)).scalars().all()
    return {
        "oem_pending_settlement_cents": sum(
            int(row.delta_cents)
            for row in rows
            if row.kind.startswith("sale_") and int(row.available_ts) > now
        ),
        "oem_available_cents": max(
            0,
            sum(int(row.delta_cents) for row in rows if int(row.available_ts) <= now),
        ),
        "withdraw_pending_count": sum(
            1 for row in withdrawals if row.status in ("pending", "approved")
        ),
        "withdraw_paid_cents": sum(
            int(row.amount_cents) for row in withdrawals if row.status == "paid"
        ),
    }


__all__ = [
    "decide_withdrawal",
    "effective_settlement_cents",
    "finance_snapshot",
    "list_admin_withdrawals",
    "list_commercial_terms",
    "platform_summary",
    "record_paid_license_transfer",
    "record_paid_order",
    "request_withdrawal",
    "snapshot_license",
    "snapshot_order",
    "set_commercial_terms",
]
