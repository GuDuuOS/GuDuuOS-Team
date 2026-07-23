"""Nexus 支付层：商品定价 / 订单 / 支付渠道抽象（模块6 P3）。

商业定调（负责人 2026-07-23 拍板）：
    - 国内市场：渠道 = **支付宝 + 微信**（Stripe/PayPal 不做）；
    - 门户直接购买授权码（付款即出码）+ token 充值；
    - 人工「申请→批准」通道保留（谈价/定制客户走它）。

分层：
    - 定价（NexusSetting.pricing）：超管控制台可改、即改即生效；
    - 订单（NexusOrder）：金额一律人民币**分**；
    - 渠道（PayProvider）：alipay/wechat 是**占位骨架**——`available()` 按 env
      判断，凭据未配时门户按钮置灰"开通中"；真实 API 到手后只需补
      `create()` 的下单参数与 `verify_notify()` 的验签两处；
    - mock 渠道：`NEXUS_PAY_MOCK=1` 的环境（开发机）可用，一键"模拟支付成功"
      走通 下单→回调→履约 全链路，不碰真钱。

履约（mark_paid，**幂等**）：
    - kind=key   → 签发 KEY + 自动归属买家 + 明文挂单交付（装机兑换后清空，
      与申请单同策略，见 oem.clear_plain_by_key）；
    - kind=topup → fleet.topup 入钱包（备注带订单号，流水可对账）。
"""

from __future__ import annotations

import json
import os
import secrets
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from nexus.db import NexusOrder, NexusSetting
from nexus.fleet import FleetError

# ---------- 定价 ----------

_PRICING_KEY = "pricing"
# 默认定价：KEY 未定价(0=门户不开放购买,引导走申请通道)；充值包为空
_PRICING_DEFAULT: Dict[str, Any] = {
    "key_price_cents": 0,        # 授权码买断价(分)。0=暂不开放在线购买
    "key_token_grant": 100_000_000,  # 在线购买的 KEY 附赠 token
    "topup_packs": [],           # 充值包列表：[{"cents": 9900, "tokens": 100000000}, ...]
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
    return out


def set_pricing(s, data: Dict[str, Any]) -> Dict[str, Any]:
    """超管改定价。只收白名单字段并做类型/边界校验。"""
    cur = get_pricing(s)
    if "key_price_cents" in data:
        v = int(data["key_price_cents"])
        if v < 0:
            raise FleetError("NEXUS_BAD_PRICE", "价格不能为负")
        cur["key_price_cents"] = v
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
            if cents <= 0 or tokens <= 0:
                raise FleetError("NEXUS_BAD_PACKS", "充值包金额与 token 都必须为正")
            clean.append({"cents": cents, "tokens": tokens})
        cur["topup_packs"] = clean
    row = s.get(NexusSetting, _PRICING_KEY)
    if row is None:
        row = NexusSetting(k=_PRICING_KEY)
        s.add(row)
    row.v = json.dumps(cur, ensure_ascii=False)
    row.updated_ts = int(time.time() * 1000)
    return cur


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
        return {"type": "mock", "hint": "开发环境模拟支付：点击「模拟支付成功」完成本单"}


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
        raise FleetError("NEXUS_PAY_UNAVAILABLE", "支付宝下单尚未接入（凭据已配，待联调）", 503)

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
            raise FleetError("NEXUS_PAY_UNAVAILABLE", "微信支付渠道开通中，敬请期待", 503)
        # TODO(等 API)：POST /v3/pay/transactions/native（商户私钥签名请求头）
        # → 返回 code_url，前端渲染成二维码
        raise FleetError("NEXUS_PAY_UNAVAILABLE", "微信下单尚未接入（凭据已配，待联调）", 503)

    def verify_notify(self, headers: Dict[str, str], body: bytes) -> Dict[str, str]:
        # TODO(等 API)：平台证书验签 + APIv3 密钥解密 resource → 返回订单号/流水号
        raise FleetError("NEXUS_PAY_UNAVAILABLE", "微信回调尚未接入", 503)


_PROVIDERS: Dict[str, PayProvider] = {
    "mock": MockProvider(),
    "alipay": AlipayProvider(),
    "wechat": WechatProvider(),
}


def channels(s=None) -> Dict[str, bool]:
    """各渠道可用性（门户据此亮/灰按钮）。"""
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
            raise FleetError("NEXUS_NOT_FOR_SALE", "授权码暂未开放在线购买，请走申请通道")
        tokens = int(pricing["key_token_grant"])
        instance_id = None
    elif kind == "topup":
        packs = pricing["topup_packs"]
        if not (0 <= pack_index < len(packs)):
            raise FleetError("NEXUS_BAD_PACK", "充值套餐不存在")
        if not instance_id:
            raise FleetError("NEXUS_BAD_INSTANCE", "请选择要充值的实例")
        cents = int(packs[pack_index]["cents"])
        tokens = int(packs[pack_index]["tokens"])
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
    pay = provider.create(order)
    return {"order": public_order(order, owner=True), "pay": pay}


def mark_paid(s, order_no: str, provider_txn: str = "") -> Dict[str, Any]:
    """支付成功履约（渠道回调 / mock 确认统一入口）。**幂等**：已 paid 直接返回。

    履约动作与人工批准（oem.decide_request）同构：付款=自动批准。
    """
    from nexus import fleet, oem as oem_svc  # 延迟导入避免环

    order = s.execute(
        select(NexusOrder).where(NexusOrder.order_no == order_no)
    ).scalar_one_or_none()
    if order is None:
        raise FleetError("NEXUS_ORDER_NOT_FOUND", "订单不存在", 404)
    if order.status == "paid":
        return public_order(order, owner=True)  # 渠道重复回调：幂等放行
    if order.status != "pending":
        raise FleetError("NEXUS_ORDER_CLOSED", "订单已关闭", 409)

    if order.kind == "key":
        issued = fleet.issue_keys(
            s, count=1, note=f"在线购买 订单{order.order_no}", token_grant=int(order.tokens)
        )[0]
        order.key_id = issued["id"]
        order.key_plain = issued["key"]
        # 自动归属买家（与申请批准同一动作），门户即见
        from nexus.db import NexusKeyClaim
        s.add(NexusKeyClaim(key_id=issued["id"], oem_id=order.oem_id))
    else:  # topup
        fleet.topup(
            s, int(order.instance_id), int(order.tokens), note=f"在线充值 订单{order.order_no}"
        )

    order.status = "paid"
    order.provider_txn = (provider_txn or "")[:128]
    order.paid_ts = int(time.time() * 1000)
    # 静态检查友好：oem_svc 引用留给将来清明文用（redeem 时统一清 order.key_plain）
    _ = oem_svc
    return public_order(order, owner=True)


def clear_order_plain_by_key_id(s, key_id: int) -> None:
    """装机兑换后清空订单里的交付明文（与申请单的 clear_plain_by_key 配对）。"""
    for o in s.execute(
        select(NexusOrder).where(NexusOrder.key_id == int(key_id))
    ).scalars():
        o.key_plain = ""


def public_order(o: NexusOrder, owner: bool = False) -> Dict[str, Any]:
    """订单对外表示。KEY 明文只给买家本人（owner=True），超管列表不带。"""
    out = {
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


def my_orders(s, oem_id: int) -> List[Dict[str, Any]]:
    """买家自己的订单（含已支付 KEY 单的明文——交付通道之一）。"""
    rows = s.execute(
        select(NexusOrder)
        .where(NexusOrder.oem_id == int(oem_id))
        .order_by(NexusOrder.id.desc())
        .limit(50)
    ).scalars().all()
    return [public_order(r, owner=True) for r in rows]


def list_orders(s) -> List[Dict[str, Any]]:
    """超管全量订单（近 200 单；不含 KEY 明文）。"""
    rows = s.execute(
        select(NexusOrder).order_by(NexusOrder.id.desc()).limit(200)
    ).scalars().all()
    return [public_order(r) for r in rows]


def get_order_for(s, oem_id: int, order_no: str) -> NexusOrder:
    """按单号取属于该买家的订单（mock 确认的归属守卫）。"""
    order = s.execute(
        select(NexusOrder).where(NexusOrder.order_no == order_no)
    ).scalar_one_or_none()
    if order is None or order.oem_id != int(oem_id):
        raise FleetError("NEXUS_ORDER_NOT_FOUND", "订单不存在", 404)
    return order
