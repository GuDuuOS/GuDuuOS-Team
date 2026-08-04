"""Nexus 支付层：商品定价 / 订单 / 支付渠道抽象（模块6 P3）。

商业定调（负责人 2026-08-01 更新）：
    - 国内市场：支付宝 + 微信；海外市场：Stripe + PayPal + USDT；
    - 节点授权统一走“申请 + 付款方式”：在线验签自动签发、企业转账到账确认
      后签发、合同/免费客户人工审批；
    - Token 充值继续使用独立订单，不需要重复提交部署资料。

分层：
    - 定价（NexusSetting.pricing）：超管控制台可改、即改即生效；
    - 订单（NexusOrder）：金额一律人民币**分**；
    - 渠道（PayProvider）：五个真实渠道都是**占位骨架**——`available()` 只表示
      所需凭据是否配齐，不代表 API 已联调；凭据未配时舰队总览明确显示“待接 API”。
      海外渠道正式开工前还要扩展订单的多币种字段，不能把外币冒充人民币收入；
    - mock 渠道：`NEXUS_PAY_MOCK=1` 的环境（开发机）可用，一键"模拟支付成功"
      走通 下单→回调→履约 全链路，不碰真钱。

履约（mark_paid，**幂等**）：
    - kind=key   → 新流程必须关联授权申请，回调验签后自动批准并把 KEY
      加密交付给所属 OEM；仅保留旧订单的明文兼容路径；
    - kind=topup → fleet.topup 入钱包（备注带订单号，流水可对账）。
"""

from __future__ import annotations

import json
import os
import secrets
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import case, func, select

from nexus.db import (
    NexusKeyRequest,
    NexusLicensePayment,
    NexusManualTransfer,
    NexusOrder,
    NexusOrderCommercial,
    NexusSetting,
    NexusTopupPayment,
)
from nexus.fleet import FleetError

# ---------- 定价 ----------

_PRICING_KEY = "pricing"
# 默认定价：KEY 未定价(0=门户不开放购买,引导走申请通道)；充值包为空
_PRICING_DEFAULT: Dict[str, Any] = {
    "key_price_cents": 0,  # 授权码买断价(分)。0=暂不开放在线购买
    # OEM 结算价缺省随零售价，升级旧配置后不会凭空产生历史外的新收益。
    "key_oem_cost_cents": -1,
    "key_token_grant": 100_000_000,  # 在线购买的 KEY 附赠 token
    # 充值包：客户价、OEM 结算价、Token 数。
    "topup_packs": [],
    "settlement_days": 7,
    "withdraw_min_cents": 10_000,
}


def get_pricing(s) -> Dict[str, Any]:
    """读定价（缺省回默认值；字段级兜底，超管存过旧格式也不炸）。"""
    row = s.get(NexusSetting, _PRICING_KEY)
    data: Dict[str, Any] = {}
    if row is not None:
        try:
            data = json.loads(row.v or "{}")
        except Exception:
            data = {}
    out = dict(_PRICING_DEFAULT)
    out.update({k: data[k] for k in _PRICING_DEFAULT if k in data})
    # 旧生产配置没有结算价：安全解释为结算价=零售价（零价差），只有超管明确
    # 设置更低成本后才开始产生 OEM 收益。
    retail = max(0, int(out.get("key_price_cents") or 0))
    try:
        key_cost = int(out.get("key_oem_cost_cents", -1))
    except (TypeError, ValueError):
        key_cost = -1
    out["key_price_cents"] = retail
    out["key_oem_cost_cents"] = (
        retail if key_cost < 0 or key_cost > retail else key_cost
    )
    try:
        out["settlement_days"] = max(0, min(int(out["settlement_days"]), 90))
    except (TypeError, ValueError):
        out["settlement_days"] = 7
    try:
        out["withdraw_min_cents"] = max(100, int(out["withdraw_min_cents"]))
    except (TypeError, ValueError):
        out["withdraw_min_cents"] = 10_000
    clean_packs: List[Dict[str, int]] = []
    packs = out.get("topup_packs")
    if isinstance(packs, list):
        for item in packs[:10]:
            if not isinstance(item, dict):
                continue
            try:
                cents = int(item.get("cents") or 0)
                tokens = int(item.get("tokens") or 0)
                cost = int(item.get("oem_cost_cents", cents))
            except (TypeError, ValueError):
                continue
            if cents > 0 and tokens > 0:
                clean_packs.append(
                    {
                        "cents": cents,
                        "oem_cost_cents": (cost if 0 <= cost <= cents else cents),
                        "tokens": tokens,
                    }
                )
    out["topup_packs"] = clean_packs
    return out


def set_pricing(s, data: Dict[str, Any]) -> Dict[str, Any]:
    """超管改定价。只收白名单字段并做类型/边界校验。"""
    cur = get_pricing(s)
    old_key_retail = int(cur["key_price_cents"])
    old_key_cost = int(cur["key_oem_cost_cents"])
    if "key_price_cents" in data:
        v = int(data["key_price_cents"])
        if v < 0:
            raise FleetError("NEXUS_BAD_PRICE", "价格不能为负")
        cur["key_price_cents"] = v
        if "key_oem_cost_cents" not in data and old_key_cost == old_key_retail:
            # 旧配置只有客户价、从未设置过价差时，改零售价继续保持零价差；
            # 防止升级后一次普通调价意外把全部销售额都记成 OEM 收益。
            cur["key_oem_cost_cents"] = v
    if "key_oem_cost_cents" in data:
        v = int(data["key_oem_cost_cents"])
        if v < 0:
            raise FleetError("NEXUS_BAD_OEM_PRICE", "OEM 授权结算价不能为负")
        cur["key_oem_cost_cents"] = v
    if "key_token_grant" in data:
        v = int(data["key_token_grant"])
        if v < 0:
            raise FleetError("NEXUS_BAD_PRICE", "附赠 token 不能为负")
        cur["key_token_grant"] = v
    if "topup_packs" in data:
        packs = data["topup_packs"]
        if not isinstance(packs, list) or len(packs) > 10:
            raise FleetError("NEXUS_BAD_PACKS", "充值包须为列表且最多 10 档")
        clean = []
        for p in packs:
            cents, tokens = int(p.get("cents", 0)), int(p.get("tokens", 0))
            cost = int(p.get("oem_cost_cents", cents))
            if cents <= 0 or tokens <= 0:
                raise FleetError("NEXUS_BAD_PACKS", "充值包金额与 token 都必须为正")
            if cost < 0 or cost > cents:
                raise FleetError(
                    "NEXUS_BAD_OEM_PRICE", "充值包 OEM 结算价不能高于客户售价"
                )
            clean.append({"cents": cents, "oem_cost_cents": cost, "tokens": tokens})
        cur["topup_packs"] = clean
    if "settlement_days" in data:
        days = int(data["settlement_days"])
        if not 0 <= days <= 90:
            raise FleetError("NEXUS_BAD_SETTLEMENT", "结算等待天数必须在 0 到 90 之间")
        cur["settlement_days"] = days
    if "withdraw_min_cents" in data:
        minimum = int(data["withdraw_min_cents"])
        if minimum < 100:
            raise FleetError("NEXUS_BAD_WITHDRAW_AMOUNT", "最低提现金额不能低于 1 元")
        cur["withdraw_min_cents"] = minimum
    if int(cur["key_oem_cost_cents"]) > int(cur["key_price_cents"]):
        raise FleetError("NEXUS_BAD_OEM_PRICE", "OEM 授权结算价不能高于客户售价")
    row = s.get(NexusSetting, _PRICING_KEY)
    if row is None:
        row = NexusSetting(k=_PRICING_KEY)
        s.add(row)
    row.v = json.dumps(cur, ensure_ascii=False)
    row.updated_ts = int(time.time() * 1000)
    return cur


def public_pricing(s) -> Dict[str, Any]:
    """返回买家购买所需价格；OEM 结算价通过收益端点单独展示。"""
    pricing = get_pricing(s)
    result = {
        "key_price_cents": int(pricing["key_price_cents"]),
        "key_token_grant": int(pricing["key_token_grant"]),
        "topup_packs": [
            {"cents": int(item["cents"]), "tokens": int(item["tokens"])}
            for item in pricing["topup_packs"]
        ],
    }
    return result


# ---------- 支付渠道抽象 ----------


class PayProvider:
    """渠道基类。子类只需实现三件事：available / create / verify_notify。"""

    name = "base"

    def available(self) -> bool:  # 凭据是否配齐（决定门户按钮亮/灰）
        raise NotImplementedError

    def create(self, order: NexusOrder) -> Dict[str, Any]:
        """发起支付：返回给前端的支付参数（跳转 URL / 二维码串 / mock 确认口）。"""
        raise NotImplementedError

    def verify_notify(self, headers: Dict[str, str], body: bytes) -> Dict[str, str]:
        """校验支付回调，返回 {order_no, provider_txn}。验签失败必须抛 FleetError。"""
        raise NotImplementedError


class MockProvider(PayProvider):
    """模拟渠道：开发环境全链路联调用（NEXUS_PAY_MOCK=1 才可用）。

    "支付"动作 = 已登录买家自己调 /nexus/pay/mock/confirm。生产环境不开。
    """

    name = "mock"

    def available(self) -> bool:
        return os.environ.get("NEXUS_PAY_MOCK", "").strip() == "1"

    def create(self, order: NexusOrder) -> Dict[str, Any]:
        return {
            "type": "mock",
            "hint": "开发环境模拟支付：点击「模拟支付成功」完成本单",
        }


class AlipayProvider(PayProvider):
    """支付宝（电脑网站支付）。⚠️ 占位骨架：等负责人拿到开放平台凭据后补两处 TODO。

    所需 env（拿到 API 后配进 /etc/nexus.env）：
        NEXUS_PAY_ALIPAY_APPID        开放平台应用 APPID
        NEXUS_PAY_ALIPAY_PRIVATE_KEY  应用私钥（RSA2）
        NEXUS_PAY_ALIPAY_PUBLIC_KEY   支付宝公钥（验签用）
    """

    name = "alipay"

    def _env(self) -> Dict[str, str]:
        return {
            "appid": os.environ.get("NEXUS_PAY_ALIPAY_APPID", "").strip(),
            "private_key": os.environ.get("NEXUS_PAY_ALIPAY_PRIVATE_KEY", "").strip(),
            "public_key": os.environ.get("NEXUS_PAY_ALIPAY_PUBLIC_KEY", "").strip(),
        }

    def available(self) -> bool:
        return all(self._env().values())

    def create(self, order: NexusOrder) -> Dict[str, Any]:
        if not self.available():
            raise FleetError("NEXUS_PAY_UNAVAILABLE", "支付宝渠道开通中，敬请期待", 503)
        # TODO(等 API)：alipay.trade.page.pay 组参 + RSA2 签名 → 返回跳转 URL
        raise FleetError(
            "NEXUS_PAY_UNAVAILABLE", "支付宝下单尚未接入（凭据已配，待联调）", 503
        )

    def verify_notify(self, headers: Dict[str, str], body: bytes) -> Dict[str, str]:
        # TODO(等 API)：表单参数按支付宝规则拼串 → 支付宝公钥 RSA2 验签 →
        # 校验 app_id/trade_status=TRADE_SUCCESS → 返回 out_trade_no/trade_no
        raise FleetError("NEXUS_PAY_UNAVAILABLE", "支付宝回调尚未接入", 503)


class WechatProvider(PayProvider):
    """微信支付（Native 扫码，APIv3）。⚠️ 占位骨架，同支付宝。

    所需 env：
        NEXUS_PAY_WECHAT_MCHID       商户号
        NEXUS_PAY_WECHAT_APPID       关联公众号/小程序 APPID
        NEXUS_PAY_WECHAT_API_V3_KEY  APIv3 密钥
        NEXUS_PAY_WECHAT_CERT_SERIAL 商户证书序列号
        NEXUS_PAY_WECHAT_PRIVATE_KEY 商户私钥
    """

    name = "wechat"

    def _env(self) -> Dict[str, str]:
        keys = ["MCHID", "APPID", "API_V3_KEY", "CERT_SERIAL", "PRIVATE_KEY"]
        return {k: os.environ.get(f"NEXUS_PAY_WECHAT_{k}", "").strip() for k in keys}

    def available(self) -> bool:
        return all(self._env().values())

    def create(self, order: NexusOrder) -> Dict[str, Any]:
        if not self.available():
            raise FleetError(
                "NEXUS_PAY_UNAVAILABLE", "微信支付渠道开通中，敬请期待", 503
            )
        # TODO(等 API)：POST /v3/pay/transactions/native（商户私钥签名请求头）
        # → 返回 code_url，前端渲染成二维码
        raise FleetError(
            "NEXUS_PAY_UNAVAILABLE", "微信下单尚未接入（凭据已配，待联调）", 503
        )

    def verify_notify(self, headers: Dict[str, str], body: bytes) -> Dict[str, str]:
        # TODO(等 API)：平台证书验签 + APIv3 密钥解密 resource → 返回订单号/流水号
        raise FleetError("NEXUS_PAY_UNAVAILABLE", "微信回调尚未接入", 503)


class StripeProvider(PayProvider):
    """Stripe 海外银行卡收款占位骨架。

    所需 env（正式联调时配置到 ``/etc/nexus.env``）：
        NEXUS_PAY_STRIPE_SECRET_KEY      Stripe Secret key
        NEXUS_PAY_STRIPE_WEBHOOK_SECRET Webhook 签名密钥

    当前只向舰队总览报告凭据状态，不开放 OEM 下单按钮。正式接入前必须先给订单模型
    增加 currency 与原币金额，避免 USD 被现有人民币分字段错误汇总。
    """

    name = "stripe"

    def available(self) -> bool:
        return all(
            os.environ.get(name, "").strip()
            for name in (
                "NEXUS_PAY_STRIPE_SECRET_KEY",
                "NEXUS_PAY_STRIPE_WEBHOOK_SECRET",
            )
        )

    def create(self, order: NexusOrder) -> Dict[str, Any]:
        raise FleetError("NEXUS_PAY_UNAVAILABLE", "Stripe 支付尚未接入", 503)

    def verify_notify(self, headers: Dict[str, str], body: bytes) -> Dict[str, str]:
        raise FleetError("NEXUS_PAY_UNAVAILABLE", "Stripe 回调尚未接入", 503)


class PaypalProvider(PayProvider):
    """PayPal Checkout 海外收款占位骨架。

    所需 env：``NEXUS_PAY_PAYPAL_CLIENT_ID``、``NEXUS_PAY_PAYPAL_CLIENT_SECRET``
    与 ``NEXUS_PAY_PAYPAL_WEBHOOK_ID``。三个值齐全时总览显示“凭据已配置”，但在
    下单/回调实现并经过沙箱验收前仍拒绝真实交易。
    """

    name = "paypal"

    def available(self) -> bool:
        return all(
            os.environ.get(name, "").strip()
            for name in (
                "NEXUS_PAY_PAYPAL_CLIENT_ID",
                "NEXUS_PAY_PAYPAL_CLIENT_SECRET",
                "NEXUS_PAY_PAYPAL_WEBHOOK_ID",
            )
        )

    def create(self, order: NexusOrder) -> Dict[str, Any]:
        raise FleetError("NEXUS_PAY_UNAVAILABLE", "PayPal 支付尚未接入", 503)

    def verify_notify(self, headers: Dict[str, str], body: bytes) -> Dict[str, str]:
        raise FleetError("NEXUS_PAY_UNAVAILABLE", "PayPal 回调尚未接入", 503)


class UsdtProvider(PayProvider):
    """USDT 稳定币收款服务商占位骨架。

    链上支付不能只配置一个钱包地址后靠人工猜单。这里要求服务商 API 地址、API key
    和 webhook 密钥全部存在，未来通过“一单一地址/唯一金额 + 确认数 + webhook
    验签”完成自动对账。具体支持哪条链由后续服务商选择决定，当前不提前写死网络。
    """

    name = "usdt"

    def available(self) -> bool:
        return all(
            os.environ.get(name, "").strip()
            for name in (
                "NEXUS_PAY_USDT_API_BASE",
                "NEXUS_PAY_USDT_API_KEY",
                "NEXUS_PAY_USDT_WEBHOOK_SECRET",
            )
        )

    def create(self, order: NexusOrder) -> Dict[str, Any]:
        raise FleetError("NEXUS_PAY_UNAVAILABLE", "USDT 支付尚未接入", 503)

    def verify_notify(self, headers: Dict[str, str], body: bytes) -> Dict[str, str]:
        raise FleetError("NEXUS_PAY_UNAVAILABLE", "USDT 回调尚未接入", 503)


_PROVIDERS: Dict[str, PayProvider] = {
    "mock": MockProvider(),
    "alipay": AlipayProvider(),
    "wechat": WechatProvider(),
    "stripe": StripeProvider(),
    "paypal": PaypalProvider(),
    "usdt": UsdtProvider(),
}


def channels(s=None) -> Dict[str, bool]:
    """返回国内与海外渠道凭据状态，门户据此展示“已配置/待接 API”。"""
    return {name: p.available() for name, p in _PROVIDERS.items()}


# ---------- 订单 ----------


def _gen_order_no() -> str:
    """订单号：NX + 秒级时间 + 6 位随机。传给支付渠道的商户单号。"""
    return "NX%d%s" % (int(time.time()), secrets.token_hex(3).upper())


def create_order(
    s,
    oem_id: int,
    kind: str,
    channel: str,
    instance_id: Optional[int] = None,
    pack_index: int = -1,
) -> Dict[str, Any]:
    """创建订单并向渠道发起支付。返回 {order, pay}（pay=渠道支付参数）。

    归属校验（topup 的实例必须属于买家）由 service 层做——那里有 oem 会话上下文。
    """
    provider = _PROVIDERS.get(channel)
    if provider is None:
        raise FleetError("NEXUS_BAD_CHANNEL", "不支持的支付渠道")
    if not provider.available():
        raise FleetError("NEXUS_PAY_UNAVAILABLE", "该支付渠道开通中，敬请期待", 503)
    pricing = get_pricing(s)

    if kind == "key":
        cents = int(pricing["key_price_cents"])
        if cents <= 0:
            raise FleetError(
                "NEXUS_NOT_FOR_SALE", "授权码暂未开放在线购买，请走申请通道"
            )
        tokens = int(pricing["key_token_grant"])
        settlement_cents = int(pricing["key_oem_cost_cents"])
        instance_id = None
    elif kind == "topup":
        packs = pricing["topup_packs"]
        if not (0 <= pack_index < len(packs)):
            raise FleetError("NEXUS_BAD_PACK", "充值套餐不存在")
        if not instance_id:
            raise FleetError("NEXUS_BAD_INSTANCE", "请选择要充值的实例")
        cents = int(packs[pack_index]["cents"])
        tokens = int(packs[pack_index]["tokens"])
        settlement_cents = int(packs[pack_index]["oem_cost_cents"])
    else:
        raise FleetError("NEXUS_BAD_KIND", "未知的订单类型")

    order = NexusOrder(
        order_no=_gen_order_no(),
        oem_id=int(oem_id),
        kind=kind,
        instance_id=int(instance_id) if instance_id else None,
        channel=channel,
        amount_cents=cents,
        tokens=tokens,
    )
    s.add(order)
    s.flush()
    # 商业归属必须与订单同事务冻结，不能等支付回调时再读取可能已经改变的
    # 上下级关系或价格。
    from nexus import oem_finance

    oem_finance.snapshot_order(s, order, pricing, settlement_cents)
    pay = provider.create(order)
    return {"order": public_order(order, owner=True), "pay": pay}


def create_topup_transfer(
    s,
    oem_id: int,
    instance_id: int,
    pack_index: int,
    *,
    image_data: bytes,
    content_type: str,
    filename: str,
    transfer_details: Dict[str, Any],
) -> Dict[str, Any]:
    """创建 Token 充值企业转账订单与待核对凭证。

    金额和 Token 完全来自服务端套餐；凭证确认前订单保持 ``pending``，超管核对
    银行到账后才调用 :func:`mark_paid` 原子充值并产生 OEM 价差收益。
    """
    from nexus import manual_transfer, oem_finance

    pricing = get_pricing(s)
    packs = pricing["topup_packs"]
    if not (0 <= int(pack_index) < len(packs)):
        raise FleetError("NEXUS_BAD_PACK", "充值套餐不存在")
    if not int(instance_id):
        raise FleetError("NEXUS_BAD_INSTANCE", "请选择要充值的实例")
    pack = packs[int(pack_index)]
    details = transfer_details if isinstance(transfer_details, dict) else {}
    payer_company = str(details.get("payer_company", "") or "").strip()
    if not payer_company:
        raise FleetError("NEXUS_TRANSFER_PAYER_REQUIRED", "请填写付款企业")
    order = NexusOrder(
        order_no=_gen_order_no(),
        oem_id=int(oem_id),
        kind="topup",
        instance_id=int(instance_id),
        channel="corporate_transfer",
        amount_cents=int(pack["cents"]),
        tokens=int(pack["tokens"]),
    )
    s.add(order)
    s.flush()
    oem_finance.snapshot_order(s, order, pricing, int(pack["oem_cost_cents"]))
    transfer = manual_transfer.create_transfer(
        s,
        amount_cents=int(pack["cents"]),
        image_data=image_data,
        content_type=content_type,
        filename=filename,
        oem_id=int(oem_id),
        purpose=f"Token 充值订单 {order.order_no}",
        details={**details, "payer_company": payer_company},
        confirmed=False,
    )
    s.add(
        NexusTopupPayment(
            order_id=int(order.id), transfer_id=int(transfer["transfer_id"])
        )
    )
    s.flush()
    public = _public_order_with_link(s, order, owner=True)
    return {"order": public, "transfer": transfer}


def decide_topup_transfer(s, order_no: str, approve: bool, note: str) -> Dict[str, Any]:
    """超管核对 Token 企业转账，批准时立即充值并确认销售收益。"""
    from nexus import manual_transfer

    located = s.execute(
        select(NexusOrder).where(NexusOrder.order_no == str(order_no))
    ).scalar_one_or_none()
    if located is None:
        raise FleetError("NEXUS_ORDER_NOT_FOUND", "充值订单不存在", 404)
    order = s.execute(
        select(NexusOrder).where(NexusOrder.id == int(located.id)).with_for_update()
    ).scalar_one()
    link = s.execute(
        select(NexusTopupPayment)
        .where(NexusTopupPayment.order_id == int(order.id))
        .with_for_update()
    ).scalar_one_or_none()
    if link is None or order.kind != "topup" or order.channel != "corporate_transfer":
        raise FleetError("NEXUS_TRANSFER_NOT_FOUND", "该订单没有待核对转账", 404)
    transfer = s.execute(
        select(NexusManualTransfer)
        .where(NexusManualTransfer.id == int(link.transfer_id))
        .with_for_update()
    ).scalar_one_or_none()
    if transfer is None:
        raise FleetError("NEXUS_TRANSFER_NOT_FOUND", "转账凭证不存在", 404)
    clean_note = (note or "").strip()[:500]
    if approve:
        if order.status == "paid":
            return {
                "order": _public_order_with_link(s, order),
                "transfer": manual_transfer.public_transfer(transfer),
            }
        manual_transfer.decide_submission(s, int(transfer.id), True)
        paid = mark_paid(
            s,
            order.order_no,
            transfer.transfer_no,
            paid_amount_cents=int(transfer.amount_cents),
        )
    else:
        if not clean_note:
            raise FleetError("NEXUS_DECIDE_NOTE_REQUIRED", "拒绝转账凭证必须填写原因")
        if order.status == "paid":
            raise FleetError("NEXUS_ORDER_CLOSED", "充值已经完成，不能拒绝", 409)
        manual_transfer.decide_submission(s, int(transfer.id), False)
        order.status = "closed"
        paid = _public_order_with_link(s, order)
    return {"order": paid, "transfer": manual_transfer.public_transfer(transfer)}


def create_license_checkout(
    s,
    oem_id: int,
    method: str,
    *,
    channel: str = "",
    note: str = "",
    deployment_domain: str = "",
    purpose: str = "",
    expected_date: str = "",
    requested_tokens: int = 0,
    expected_public_ip: str = "",
    strict_ip: bool = False,
    image_data: bytes = b"",
    content_type: str = "",
    filename: str = "",
    transfer_details: Optional[Dict[str, Any]] = None,
    source_ip: str = "",
) -> Dict[str, Any]:
    """创建“授权申请 + 付款方式”的原子购买流程。

    在线支付和企业转账的金额/Token 都取当前定价快照，不信任浏览器
    传入的金额。任何一步失败由 HTTP 层回滚整个事务，不留孤儿申请。
    """
    from nexus import audit, features, manual_transfer, oem as oem_svc

    selected = (method or "").strip().lower()
    if selected not in ("online", "corporate_transfer", "manual_review"):
        raise FleetError("NEXUS_BAD_PAYMENT_METHOD", "请选择有效的付款方式")
    pricing = get_pricing(s)
    price = int(pricing["key_price_cents"])
    grant = int(pricing["key_token_grant"])
    if selected in ("online", "corporate_transfer") and price <= 0:
        raise FleetError(
            "NEXUS_NOT_FOR_SALE",
            "节点授权尚未设置售价，请选择合同/免费授权申请",
        )
    # OEM 使用自有 API 接入方时，授权和平台 Token 必须解耦。
    # 服务端在开关关闭时强制归零，不信任浏览器隐藏字段。
    token_grant_enabled = features.get_flags(s)[
        "oem_token_grant_request_visible"
    ]
    effective_tokens = 0
    if token_grant_enabled:
        effective_tokens = (
            grant if selected != "manual_review" else int(requested_tokens or 0)
        )
    request = oem_svc.request_key(
        s,
        int(oem_id),
        note,
        deployment_domain=deployment_domain,
        purpose=purpose,
        expected_date=expected_date,
        requested_tokens=effective_tokens,
        expected_public_ip=expected_public_ip,
        strict_ip=strict_ip,
        source_ip=source_ip,
    )
    request_id = int(request["id"])
    now = int(time.time() * 1000)
    result: Dict[str, Any] = {"request": request, "pay": None}
    if selected == "online":
        if not channel:
            raise FleetError("NEXUS_BAD_CHANNEL", "请选择在线支付渠道")
        checkout = create_order(s, int(oem_id), "key", channel)
        order = s.execute(
            select(NexusOrder).where(
                NexusOrder.order_no == checkout["order"]["order_no"]
            )
        ).scalar_one()
        link = NexusLicensePayment(
            request_id=request_id,
            oem_id=int(oem_id),
            method="online",
            status="pending_payment",
            order_id=order.id,
            amount_cents=price,
            currency="CNY",
            created_ts=now,
            updated_ts=now,
        )
        s.add(link)
        s.flush()
        checkout["order"]["request_id"] = request_id
        result.update(checkout)
    elif selected == "corporate_transfer":
        if not image_data:
            raise FleetError(
                "NEXUS_TRANSFER_VOUCHER_REQUIRED", "企业转账必须上传付款凭证"
            )
        clean_transfer_details = transfer_details or {}
        payer_company = str(
            clean_transfer_details.get("payer_company", "") or ""
        ).strip()
        if not payer_company:
            # 浏览器的 required 只能改善交互，接口仍须独立校验，防止绕过页面
            # 提交一张无法关联付款主体的图片给财务审核。
            raise FleetError(
                "NEXUS_TRANSFER_PAYER_REQUIRED", "请填写银行回单上的付款企业"
            )
        transfer = manual_transfer.create_transfer(
            s,
            amount_cents=price,
            image_data=image_data,
            content_type=content_type,
            filename=filename,
            oem_id=int(oem_id),
            purpose=f"节点授权申请 #{request_id}",
            details={**clean_transfer_details, "payer_company": payer_company},
            confirmed=False,
        )
        s.add(
            NexusLicensePayment(
                request_id=request_id,
                oem_id=int(oem_id),
                method="corporate_transfer",
                status="pending_review",
                transfer_id=int(transfer["transfer_id"]),
                amount_cents=price,
                currency="CNY",
                created_ts=now,
                updated_ts=now,
            )
        )
        # 企业转账没有在线订单表，因此按申请号单独冻结直属销售 OEM 与价差。
        from nexus import oem_finance

        oem_finance.snapshot_license(s, request_id, int(oem_id), pricing)
        result["transfer"] = transfer
    else:
        s.add(
            NexusLicensePayment(
                request_id=request_id,
                oem_id=int(oem_id),
                method="manual_review",
                status="pending_review",
                amount_cents=0,
                currency="CNY",
                created_ts=now,
                updated_ts=now,
            )
        )
    audit.record(
        s,
        object_type="key_request",
        object_id=request_id,
        action="checkout_created",
        actor_type="oem",
        actor_label=f"OEM #{oem_id}",
        source_ip=source_ip,
        from_state="pending",
        to_state="pending",
        metadata={
            "method": selected,
            "channel": channel if selected == "online" else "",
            "amount_cents": price if selected != "manual_review" else 0,
        },
    )
    s.flush()
    result["request"] = oem_svc.request_detail(s, request_id)
    return result


def mark_paid(
    s,
    order_no: str,
    provider_txn: str = "",
    *,
    paid_amount_cents: Optional[int] = None,
    paid_currency: str = "CNY",
) -> Dict[str, Any]:
    """支付成功履约（渠道回调 / mock 确认统一入口）。**幂等**：已 paid 直接返回。

    履约动作与人工批准（oem.decide_request）同构：付款=自动批准。
    """
    from nexus import features, fleet, oem as oem_svc  # 延迟导入避免环

    # 新授权单涉及申请、付款关联和订单三张表。先无锁定位不可变主键，再统一按
    # “申请 → 付款关联 → 订单”顺序加锁；撤回、拒绝和企业转账确认也遵循同一顺序，
    # 防止支付回调与用户撤回同时到达时互相覆盖或形成数据库死锁。
    located_order = s.execute(
        select(NexusOrder).where(NexusOrder.order_no == order_no)
    ).scalar_one_or_none()
    if located_order is None:
        raise FleetError("NEXUS_ORDER_NOT_FOUND", "订单不存在", 404)
    located_link = s.execute(
        select(NexusLicensePayment).where(
            NexusLicensePayment.order_id == located_order.id
        )
    ).scalar_one_or_none()
    if located_link is not None:
        s.execute(
            select(NexusKeyRequest)
            .where(NexusKeyRequest.id == located_link.request_id)
            .with_for_update()
        ).scalar_one_or_none()
        link = s.execute(
            select(NexusLicensePayment)
            .where(NexusLicensePayment.request_id == located_link.request_id)
            .with_for_update()
        ).scalar_one()
    else:
        link = None
    order = s.execute(
        select(NexusOrder).where(NexusOrder.id == located_order.id).with_for_update()
    ).scalar_one()
    if order is None:
        raise FleetError("NEXUS_ORDER_NOT_FOUND", "订单不存在", 404)
    if order.status == "paid":
        return _public_order_with_link(s, order, owner=True)  # 重复回调幂等放行
    if order.status != "pending":
        raise FleetError("NEXUS_ORDER_CLOSED", "订单已关闭", 409)
    if paid_amount_cents is not None and int(paid_amount_cents) != int(
        order.amount_cents
    ):
        raise FleetError("NEXUS_PAY_AMOUNT_MISMATCH", "支付回调金额与订单不一致", 409)
    if (paid_currency or "CNY").strip().upper() != "CNY":
        raise FleetError("NEXUS_PAY_CURRENCY_MISMATCH", "支付回调币种与订单不一致", 409)

    if order.kind == "key":
        if link is not None:
            if link.status not in ("pending_payment", "paid"):
                raise FleetError(
                    "NEXUS_ORDER_CLOSED", "授权申请已撤回或关闭，不能继续履约", 409
                )
            link.status = "paid"
            link.updated_ts = int(time.time() * 1000)
            # 履约时再读一次开关：下单后、付款前若超管关闭
            # Token 附赠，迟到的支付回调也不能继续发放历史额度。
            grant_tokens = (
                int(order.tokens)
                if features.get_flags(s)["oem_token_grant_request_visible"]
                else 0
            )
            request = oem_svc.approve_paid_request(
                s,
                link.request_id,
                grant_tokens,
                action="payment_auto_approve",
                actor_label=f"支付回调 · {order.channel}",
                note=f"在线订单 {order.order_no} 已验签到账",
            )
            order.key_id = int(request["key_id"])
            order.key_plain = ""
            link.status = "fulfilled"
            link.updated_ts = int(time.time() * 1000)
        else:
            # 兼容 1.12 之前已创建但尚未付款的旧订单，避免升级后无法履约。
            issued = fleet.issue_keys(
                s,
                count=1,
                note=f"在线购买 订单{order.order_no}",
                token_grant=int(order.tokens),
            )[0]
            order.key_id = issued["id"]
            order.key_plain = issued["key"]
            from nexus.db import NexusKeyClaim

            s.add(NexusKeyClaim(key_id=issued["id"], oem_id=order.oem_id))
    else:  # topup
        fleet.topup(
            s,
            int(order.instance_id),
            int(order.tokens),
            note=f"在线充值 订单{order.order_no}",
        )

    order.status = "paid"
    order.provider_txn = (provider_txn or "")[:128]
    order.paid_ts = int(time.time() * 1000)
    # 发码/充值成功后才确认 OEM 收益；若履约抛错，HTTP 层会回滚订单和收益。
    from nexus import oem_finance

    oem_finance.record_paid_order(s, order)
    # 静态检查友好：oem_svc 引用留给将来清明文用（redeem 时统一清 order.key_plain）
    _ = oem_svc
    return _public_order_with_link(s, order, owner=True)


def decide_license_transfer(
    s,
    request_id: int,
    approve: bool,
    note: str,
    *,
    actor_label: str = "平台超级管理员",
    source_ip: str = "",
) -> Dict[str, Any]:
    """超管核对企业转账真实到账后，原子记收入并签发 KEY。

    凭证、支付关联、申请状态、KEY 与审计事件在同一数据库事务中提交；
    任何一步失败都不会出现“计了收入但没发 KEY”的半完成状态。
    """
    from nexus import audit, features, manual_transfer, oem as oem_svc

    located_link = s.execute(
        select(NexusLicensePayment).where(
            NexusLicensePayment.request_id == int(request_id)
        )
    ).scalar_one_or_none()
    if located_link is None:
        raise FleetError("NEXUS_TRANSFER_NOT_FOUND", "该申请没有待审企业转账", 404)
    # 与支付回调、申请撤回共用锁顺序：申请 → 付款关联 → 凭证。
    s.execute(
        select(NexusKeyRequest)
        .where(NexusKeyRequest.id == int(request_id))
        .with_for_update()
    ).scalar_one_or_none()
    link = s.execute(
        select(NexusLicensePayment)
        .where(NexusLicensePayment.request_id == int(request_id))
        .with_for_update()
    ).scalar_one_or_none()
    if link is None or link.method != "corporate_transfer" or not link.transfer_id:
        raise FleetError("NEXUS_TRANSFER_NOT_FOUND", "该申请没有待审企业转账", 404)
    transfer = s.execute(
        select(NexusManualTransfer)
        .where(NexusManualTransfer.id == int(link.transfer_id))
        .with_for_update()
    ).scalar_one_or_none()
    if transfer is None:
        raise FleetError("NEXUS_TRANSFER_NOT_FOUND", "企业转账凭证不存在", 404)
    clean_note = (note or "").strip()[:500]
    if not approve and not clean_note:
        raise FleetError("NEXUS_DECIDE_NOTE_REQUIRED", "拒绝转账凭证必须填写原因")
    if approve:
        if link.status == "fulfilled":
            return {
                "request": oem_svc.request_detail(s, link.request_id),
                "transfer": manual_transfer.public_transfer(transfer),
            }
        manual_transfer.decide_submission(s, transfer.id, True)
        link.status = "paid"
        link.updated_ts = int(time.time() * 1000)
        request_snapshot = oem_svc.request_detail(s, link.request_id)
        grant_tokens = (
            int(request_snapshot.get("requested_tokens") or 0)
            if features.get_flags(s)["oem_token_grant_request_visible"]
            else 0
        )
        request = oem_svc.approve_paid_request(
            s,
            link.request_id,
            grant_tokens,
            action="transfer_confirm",
            actor_label=actor_label,
            source_ip=source_ip,
            note=clean_note or f"企业转账 {transfer.transfer_no} 已核对到账",
        )
        link.status = "fulfilled"
        link.updated_ts = int(time.time() * 1000)
        audit.record(
            s,
            object_type="manual_transfer",
            object_id=transfer.id,
            action="confirm_and_fulfill",
            actor_type="admin",
            actor_label=actor_label,
            source_ip=source_ip,
            from_state="pending_review",
            to_state="confirmed",
            note=clean_note,
            metadata={"request_id": link.request_id, "key_id": request["key_id"]},
        )
        # 企业转账与在线订单使用同一收益账本，只是来源快照按申请号保存。
        from nexus import oem_finance

        oem_finance.record_paid_license_transfer(
            s, int(link.request_id), transfer.transfer_no
        )
    else:
        manual_transfer.decide_submission(s, transfer.id, False)
        request = oem_svc.decide_request(
            s,
            link.request_id,
            False,
            decide_note=clean_note,
            action="reject",
            actor_label=actor_label,
            source_ip=source_ip,
        )
        link.status = "rejected"
        link.updated_ts = int(time.time() * 1000)
    s.flush()
    return {
        "request": oem_svc.request_detail(s, link.request_id),
        "transfer": manual_transfer.public_transfer(transfer),
    }


def clear_order_plain_by_key_id(s, key_id: int) -> None:
    """装机兑换后清空订单里的交付明文（与申请单的 clear_plain_by_key 配对）。"""
    for o in s.execute(
        select(NexusOrder).where(NexusOrder.key_id == int(key_id))
    ).scalars():
        o.key_plain = ""


def public_order(o: NexusOrder, owner: bool = False) -> Dict[str, Any]:
    """订单对外表示。KEY 明文只给买家本人（owner=True），超管列表不带。"""
    out = {
        "record_type": "online_order",
        "order_no": o.order_no,
        "oem_id": o.oem_id,
        "kind": o.kind,
        "instance_id": o.instance_id,
        "channel": o.channel,
        "amount_cents": int(o.amount_cents),
        "tokens": int(o.tokens),
        "status": o.status,
        "key_id": o.key_id,
        "created_ts": o.created_ts,
        "paid_ts": o.paid_ts,
    }
    if owner:
        out["key"] = o.key_plain or None
    return out


def _public_order_with_link(
    s, order: NexusOrder, owner: bool = False
) -> Dict[str, Any]:
    """在订单公开字段上补充授权申请关联，不暴露任何 KEY 密文。"""
    out = public_order(order, owner=owner)
    link = s.execute(
        select(NexusLicensePayment).where(NexusLicensePayment.order_id == order.id)
    ).scalar_one_or_none()
    if link is not None:
        out["request_id"] = int(link.request_id)
        out["fulfillment_status"] = str(link.status)
        # 新流程的 KEY 只在申请安全交付窗口领取，订单接口永不返回明文。
        out.pop("key", None)
    commercial = s.get(NexusOrderCommercial, int(order.id))
    if commercial is not None:
        out["seller_oem_id"] = commercial.seller_oem_id
    topup_payment = s.get(NexusTopupPayment, int(order.id))
    if topup_payment is not None:
        out["transfer_id"] = int(topup_payment.transfer_id)
    return out


def my_orders(s, oem_id: int) -> List[Dict[str, Any]]:
    """买家自己的订单；新授权单的 KEY 仅走申请安全交付窗口。"""
    rows = (
        s.execute(
            select(NexusOrder)
            .where(NexusOrder.oem_id == int(oem_id))
            .order_by(NexusOrder.id.desc())
            .limit(50)
        )
        .scalars()
        .all()
    )
    return [_public_order_with_link(s, r, owner=True) for r in rows]


def list_orders(s) -> List[Dict[str, Any]]:
    """超管统一订单列表（在线订单 + 企业转账，近 200 条）。

    两种记录来自不同表：在线订单会自动履约，企业转账由超管核实后人工登记。统一
    返回只是为了运营列表与数量徽标完整，不改变两者的支付/履约语义。
    """
    from nexus import manual_transfer

    rows = (
        s.execute(select(NexusOrder).order_by(NexusOrder.id.desc()).limit(200))
        .scalars()
        .all()
    )
    combined = [_public_order_with_link(s, r) for r in rows]
    # Token 企业转账会同时拥有充值订单和凭证记录；运营订单表以充值订单为主行，
    # 通过 transfer_id 查看图片，避免同一笔钱重复显示两行。
    linked_transfer_ids = {
        int(row.transfer_id)
        for row in s.execute(select(NexusTopupPayment)).scalars().all()
    }
    combined.extend(
        item
        for item in manual_transfer.list_transfers(s, limit=200)
        if int(item.get("transfer_id") or 0) not in linked_transfer_ids
    )
    combined.sort(key=lambda item: int(item.get("created_ts") or 0), reverse=True)
    return combined[:200]


def finance_summary(s) -> Dict[str, Any]:
    """汇总超级管理员舰队总览需要的真实订单资金数据。

    金额单位全部为人民币分。只有 ``status=paid`` 且已经完成履约的订单才计入收入；
    ``pending`` 单独作为待支付展示，绝不能把“有人下单但没付款”包装成营收。这里直接
    在数据库聚合全部历史订单，不复用控制台近 200 单列表，避免订单多起来后总额失真。

    Returns:
        累计/近 30 天已支付金额、待支付金额与数量、授权码和 Token 充值收入构成，
        以及已交付的充值 Token 数量。
    """
    paid = NexusOrder.status == "paid"
    pending = NexusOrder.status == "pending"
    key_paid = paid & (NexusOrder.kind == "key")
    topup_paid = paid & (NexusOrder.kind == "topup")
    since_30d = int(time.time() * 1000) - 30 * 24 * 3600 * 1000
    recent_paid = paid & (NexusOrder.paid_ts >= since_30d)
    row = s.execute(
        select(
            func.coalesce(func.sum(case((paid, NexusOrder.amount_cents), else_=0)), 0),
            func.coalesce(
                func.sum(case((recent_paid, NexusOrder.amount_cents), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((pending, NexusOrder.amount_cents), else_=0)), 0
            ),
            func.coalesce(func.sum(case((paid, 1), else_=0)), 0),
            func.coalesce(func.sum(case((pending, 1), else_=0)), 0),
            func.coalesce(
                func.sum(case((key_paid, NexusOrder.amount_cents), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((topup_paid, NexusOrder.amount_cents), else_=0)), 0
            ),
            func.coalesce(func.sum(case((key_paid, 1), else_=0)), 0),
            func.coalesce(func.sum(case((topup_paid, 1), else_=0)), 0),
            func.coalesce(func.sum(case((topup_paid, NexusOrder.tokens), else_=0)), 0),
        )
    ).one()
    # 企业转账是已由超管核实银行到账的独立收款单。它计入总营收/总订单数，但必须
    # 单独返回金额和笔数，让界面用专色标出，不能伪装成自动支付订单。
    from nexus import manual_transfer

    manual = manual_transfer.summary(s)
    # Token 企业转账既有一张充值订单，也有一张银行凭证。总营收以充值订单为准，
    # 因此从人工转账汇总中扣除这些已关联凭证，避免同一笔钱算两次；授权企业转账
    # 没有 NexusOrder，仍完整保留在人工转账收入中。
    linked_transfer_ids = {
        int(item.transfer_id)
        for item in s.execute(select(NexusTopupPayment)).scalars().all()
    }
    if linked_transfer_ids:
        linked_transfers = (
            s.execute(
                select(NexusManualTransfer).where(
                    NexusManualTransfer.id.in_(linked_transfer_ids)
                )
            )
            .scalars()
            .all()
        )
        since_30d_ms = int(time.time() * 1000) - 30 * 24 * 3600 * 1000
        for transfer in linked_transfers:
            amount = int(transfer.amount_cents)
            if transfer.status == "confirmed":
                manual["manual_transfer_revenue_cents"] -= amount
                manual["manual_transfer_count"] -= 1
                if int(transfer.confirmed_ts or 0) >= since_30d_ms:
                    manual["manual_transfer_30d_cents"] -= amount
            elif transfer.status == "pending_review":
                manual["manual_transfer_pending_cents"] -= amount
                manual["manual_transfer_pending_count"] -= 1
    online_revenue = int(row[0] or 0)
    online_revenue_30d = int(row[1] or 0)
    online_paid_count = int(row[3] or 0)
    result = {
        "paid_revenue_cents": online_revenue + manual["manual_transfer_revenue_cents"],
        "paid_revenue_30d_cents": online_revenue_30d
        + manual["manual_transfer_30d_cents"],
        "pending_amount_cents": int(row[2] or 0)
        + manual["manual_transfer_pending_cents"],
        "paid_order_count": online_paid_count + manual["manual_transfer_count"],
        "pending_order_count": int(row[4] or 0)
        + manual["manual_transfer_pending_count"],
        "online_paid_revenue_cents": online_revenue,
        "online_paid_order_count": online_paid_count,
        **manual,
        "key_revenue_cents": int(row[5] or 0),
        "topup_revenue_cents": int(row[6] or 0),
        "key_paid_count": int(row[7] or 0),
        "topup_paid_count": int(row[8] or 0),
        "topup_tokens": int(row[9] or 0),
    }
    from nexus import oem_finance

    result.update(oem_finance.platform_summary(s))
    return result


def get_order_for(s, oem_id: int, order_no: str) -> NexusOrder:
    """按单号取属于该买家的订单（mock 确认的归属守卫）。"""
    order = s.execute(
        select(NexusOrder).where(NexusOrder.order_no == order_no)
    ).scalar_one_or_none()
    if order is None or order.oem_id != int(oem_id):
        raise FleetError("NEXUS_ORDER_NOT_FOUND", "订单不存在", 404)
    return order
