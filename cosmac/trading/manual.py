"""手动/测试支付渠道（模块4 P1）。

没有任何真实支付平台时用它把**整条业务链跑通**：下单 → 拿到一个"待人工确认"的占位 →
管理员/测试用一个签名 token 触发回调 → 订单 paid → 开会员。

回调用 HMAC(订单号, COSMAC_PAY_MANUAL_SECRET) 验签，避免任何人裸 POST 就能白嫖开会员。
真实渠道(Stripe 等)上线后，这个 provider 只保留给测试/线下转账人工确认用。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Dict

from cosmac.trading.base import CheckoutResult, PaymentEvent, PaymentProvider

logger = logging.getLogger("cosmac.trading.manual")


def _secret() -> str:
    """人工确认的验签密钥（只从服务端 env 读）。未配置返回空串 → manual 渠道整体不可用。

    安全默认必须 fail-closed：绝不回退到任何硬编码/公开占位密钥。否则一旦生产误开
    COSMAC_PAY_ALLOW_MANUAL=1 又忘了配密钥，任何人都能用公开常量算出签名白嫖开会员。
    """
    return os.environ.get("COSMAC_PAY_MANUAL_SECRET", "")


def manual_sign(order_no: str) -> str:
    """对订单号做 HMAC 签名——人工确认回调要带上它才算数。未配密钥则拒绝（不签）。"""
    secret = _secret()
    if not secret:
        raise RuntimeError("COSMAC_PAY_MANUAL_SECRET 未配置，manual 渠道不可用")
    return hmac.new(
        secret.encode("utf-8"), (order_no or "").encode("utf-8"), hashlib.sha256
    ).hexdigest()


class ManualProvider(PaymentProvider):
    """人工/测试确认渠道：create_checkout 返回"待确认"占位；parse_callback 校验 HMAC。"""

    name = "manual"

    def create_checkout(
        self, *, order_no: str, amount_cents: int, currency: str,
        title: str, return_url: str = "",
    ) -> CheckoutResult:
        # 安全红线(2026-07-31 修)：confirm_token 是回调验签所需的 HMAC，**绝不能返回给客户端**——
        # 否则任意用户正常下单就能从 HTTP 响应里拿到本单签名，再裸 POST /pay/callback/manual
        # 即可不付一分钱开会员/充 token，HMAC 验签形同虚设(本模块顶部注释声称能防白嫖，靠的正是
        # 签名保密)。改为只把签名打进**服务端日志**，线下人工确认时由管理员从日志/后台取。
        # extra 里只留可公开的占位信息(订单号/提示语)。
        logger.info(
            "manual 渠道待确认: order_no=%s confirm_token=%s (仅服务端可见，勿外泄)",
            order_no, manual_sign(order_no),
        )
        return CheckoutResult(
            kind="manual",
            extra={
                "order_no": order_no,
                "note": "等待人工/测试确认收款后开通",
            },
        )

    def parse_callback(
        self, *, headers: Dict[str, str], body: bytes
    ) -> PaymentEvent:
        """回调体形如 {"order_no": "...", "token": "<hmac>"}；token 不符即抛异常。"""
        data = json.loads(body.decode("utf-8") or "{}")
        order_no = str(data.get("order_no") or "")
        token = str(data.get("token") or "")
        if not order_no or not hmac.compare_digest(token, manual_sign(order_no)):
            raise ValueError("人工确认签名不符，拒绝")  # 验签失败绝不当成功
        return PaymentEvent(order_no=order_no, paid=True, provider_ref="manual")
