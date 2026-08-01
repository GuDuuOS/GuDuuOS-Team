"""Nexus 企业转账人工入账与凭证 AI 识别。

业务边界：
    - 平台超管可直接登记已确认收款；OEM 也可在授权购买中上传待审凭证；
    - 凭证图片必须上传并通过真实图片魔数检查，图片和银行详情均加密入库；
    - AI 只负责从凭证中提取候选字段，绝不自动确认收入；
    - 超管核对银行实际到账并提交表单后，记录才以 ``confirmed`` 计入营收；
    - AI 未配置或识别失败时，人工登记仍然可用。

AI 适配器当前实现 OpenAI Responses API。模型、密钥分别由
``NEXUS_RECEIPT_AI_MODEL`` 和 ``NEXUS_RECEIPT_AI_KEY`` 配置；为复用 Nexus 已有
网关密钥，后者为空时回退 ``NEXUS_GW_OPENAI_KEY``。凭证只有在管理员明确点击
“AI 识别”后才会发给模型，保存人工单本身不会隐式调用第三方。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import PurePath
from typing import Any, Dict, List, Optional, Tuple

import requests
from cryptography.fernet import InvalidToken
from sqlalchemy import case, func, select

from nexus.db import NexusManualTransfer
from nexus.fleet import FleetError
from nexus.payment_config import _fernet


VOUCHER_MAX_BYTES = 8 * 1024 * 1024
_AI_TIMEOUT_SECONDS = 45
_OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
_DETAIL_FIELDS = (
    "payer_company",
    "payer_account",
    "payee_company",
    "payee_account",
    "bank_name",
    "transaction_id",
    "transfer_time",
    "note",
)


def _now_ms() -> int:
    """返回与 Nexus 其它表一致的毫秒时间戳。"""
    return int(time.time() * 1000)


def _gen_transfer_no() -> str:
    """生成 ``BT`` 开头的人工企业转账单号，便于在订单列表中一眼区分。"""
    return "BT%d%s" % (int(time.time()), secrets.token_hex(3).upper())


def _image_type(data: bytes, claimed: str) -> str:
    """按文件魔数确认图片类型，拒绝伪装成图片的 HTML/SVG/脚本文件。

    Args:
        data: 浏览器上传的原始文件字节。
        claimed: 浏览器声明的 MIME，仅用于报错上下文，不作为可信依据。

    Returns:
        经过魔数确认的安全 MIME（JPEG/PNG/WebP）。
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    raise FleetError(
        "NEXUS_TRANSFER_BAD_VOUCHER",
        "转账凭证必须是 JPG、PNG 或 WebP 图片",
    )


def decode_image(image_base64: str, claimed_type: str) -> Tuple[bytes, str]:
    """解码前端 Base64 图片并执行大小、类型双重校验。"""
    if not image_base64:
        raise FleetError("NEXUS_TRANSFER_VOUCHER_REQUIRED", "必须上传转账凭证图片")
    try:
        data = base64.b64decode(image_base64, validate=True)
    except (ValueError, TypeError):
        raise FleetError("NEXUS_TRANSFER_BAD_VOUCHER", "转账凭证编码不正确")
    if not data or len(data) > VOUCHER_MAX_BYTES:
        raise FleetError(
            "NEXUS_TRANSFER_BAD_VOUCHER",
            "转账凭证不能为空且不能超过 8MB",
            413,
        )
    return data, _image_type(data, claimed_type)


def ai_status() -> Dict[str, Any]:
    """返回无密钥的 AI 识别公开状态，供超管界面决定是否点亮识别按钮。"""
    configured = bool(
        os.environ.get("NEXUS_RECEIPT_AI_KEY", "").strip()
        or os.environ.get("NEXUS_GW_OPENAI_KEY", "").strip()
    )
    return {
        "configured": configured,
        "provider": "openai",
        "model": os.environ.get("NEXUS_RECEIPT_AI_MODEL", "gpt-5-mini").strip()
        or "gpt-5-mini",
    }


def _receipt_schema() -> Dict[str, Any]:
    """构造严格 JSON Schema，防止模型输出散文或遗漏字段导致前端误填。"""
    string_fields = {
        name: {"type": "string"}
        for name in (
            "payer_company",
            "payer_account",
            "payee_company",
            "payee_account",
            "bank_name",
            "transaction_id",
            "transfer_time",
            "currency",
            "note",
        )
    }
    properties: Dict[str, Any] = {
        "amount_cents": {"type": "integer", "minimum": 0},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    }
    properties.update(string_fields)
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties.keys()),
        "additionalProperties": False,
    }


def _output_text(payload: Dict[str, Any]) -> str:
    """从 Responses API 原始响应中提取第一个 ``output_text`` 内容。"""
    for item in payload.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content", []):
            if isinstance(part, dict) and part.get("type") == "output_text":
                return str(part.get("text") or "")
    return ""


def _clean_recognition(data: Dict[str, Any]) -> Dict[str, Any]:
    """限制 AI 字段类型和长度；模型输出永远视为不可信外部输入。"""
    clean: Dict[str, Any] = {}
    try:
        amount = int(data.get("amount_cents", 0) or 0)
    except (TypeError, ValueError):
        amount = 0
    clean["amount_cents"] = max(0, amount)
    try:
        confidence = float(data.get("confidence", 0) or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    clean["confidence"] = max(0.0, min(1.0, confidence))
    for name in _DETAIL_FIELDS + ("currency",):
        clean[name] = str(data.get(name, "") or "").strip()[:500]
    return clean


def recognize_voucher(data: bytes, content_type: str) -> Dict[str, Any]:
    """调用视觉模型提取转账凭证字段，返回仅供人工核对的候选结果。

    该函数不写数据库、不确认收入。调用失败统一转成可操作的业务错误，且不会把
    上游响应体（其中可能复述银行信息）写日志或回传浏览器。
    """
    key = (
        os.environ.get("NEXUS_RECEIPT_AI_KEY", "").strip()
        or os.environ.get("NEXUS_GW_OPENAI_KEY", "").strip()
    )
    if not key:
        raise FleetError(
            "NEXUS_RECEIPT_AI_UNAVAILABLE",
            "凭证 AI 识别尚未配置，请先填写人工字段",
            503,
        )
    model = ai_status()["model"]
    image_url = "data:%s;base64,%s" % (
        content_type,
        base64.b64encode(data).decode("ascii"),
    )
    prompt = (
        "你是企业银行转账凭证识别器。只提取图片中明确可见的信息，不推测、"
        "不补全被遮挡的账号。金额统一换算为人民币分；看不清的字符串返回空串，"
        "无法确认的金额返回 0。payer 是付款方，payee 是收款方。"
    )
    payload = {
        "model": model,
        "store": False,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": image_url, "detail": "high"},
                ],
            }
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "bank_transfer_receipt",
                "strict": True,
                "schema": _receipt_schema(),
            }
        },
        "max_output_tokens": 1200,
    }
    try:
        response = requests.post(
            _OPENAI_RESPONSES_URL,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            json=payload,
            timeout=_AI_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            raise PermissionError("provider rejected request")
        raw = json.loads(_output_text(response.json()))
        if not isinstance(raw, dict):
            raise ValueError("unexpected output")
        return _clean_recognition(raw)
    except requests.RequestException:
        raise FleetError(
            "NEXUS_RECEIPT_AI_FAILED", "暂时无法连接凭证识别服务，请稍后重试"
        )
    except (PermissionError, ValueError, TypeError, json.JSONDecodeError):
        raise FleetError(
            "NEXUS_RECEIPT_AI_FAILED",
            "凭证识别未返回有效结果，请人工核对后填写",
        )


def _encrypt_json(data: Dict[str, Any]) -> bytes:
    """用 Nexus 主密钥加密结构化银行详情。"""
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return _fernet().encrypt(raw)


def _decrypt_json(row: NexusManualTransfer) -> Dict[str, Any]:
    """解密企业转账详情；主密钥不一致时给出明确运维错误。"""
    try:
        raw = _fernet().decrypt(bytes(row.encrypted_details))
        data = json.loads(raw.decode("utf-8"))
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError):
        raise FleetError(
            "NEXUS_SECRET_KEY_INVALID",
            "企业转账资料无法解密，请核对 NEXUS_SECRET_KEY",
            503,
        )
    return data if isinstance(data, dict) else {}


def create_transfer(
    s,
    *,
    amount_cents: Any,
    image_data: bytes,
    content_type: str,
    filename: str,
    oem_id: Optional[Any] = None,
    purpose: str = "企业转账收款",
    details: Optional[Dict[str, Any]] = None,
    recognition: Optional[Dict[str, Any]] = None,
    confirmed: bool = True,
) -> Dict[str, Any]:
    """创建一笔企业转账凭证记录。

    Args:
        s: SQLAlchemy Session。
        amount_cents: 人工核对后的人民币分金额，必须大于零。
        image_data/content_type/filename: 必传的银行转账凭证。
        oem_id: 可选关联客户编号；填写时必须真实存在。
        purpose: 收款用途，出现在订单列表中。
        details: 付款/收款企业、账户、银行流水等人工确认字段。
        recognition: 本次 AI 候选结果，仅作为审计辅助一并加密保存。
        confirmed: ``True`` 表示超管已核对真实到账；``False`` 表示 OEM
            只上传了待审凭证，不得计入营收或触发授权。

    Returns:
        不含凭证二进制、但含管理员可见详情的公开记录。
    """
    from nexus.db import NexusOem

    try:
        cents = int(amount_cents)
    except (TypeError, ValueError):
        raise FleetError("NEXUS_TRANSFER_BAD_AMOUNT", "企业转账金额格式不正确")
    if cents <= 0 or cents > 1_000_000_000_000:
        raise FleetError("NEXUS_TRANSFER_BAD_AMOUNT", "企业转账金额必须大于 0")
    safe_type = _image_type(image_data, content_type)
    if len(image_data) > VOUCHER_MAX_BYTES:
        raise FleetError(
            "NEXUS_TRANSFER_BAD_VOUCHER", "转账凭证不能超过 8MB", 413
        )
    try:
        linked_oem: Optional[int] = int(oem_id) if oem_id else None
    except (TypeError, ValueError):
        raise FleetError("NEXUS_OEM_NOT_FOUND", "关联的 OEM 客户编号不正确")
    if linked_oem and s.get(NexusOem, linked_oem) is None:
        raise FleetError("NEXUS_OEM_NOT_FOUND", "关联的 OEM 客户不存在", 404)
    clean_details = {
        name: str((details or {}).get(name, "") or "").strip()[:500]
        for name in _DETAIL_FIELDS
    }
    clean_recognition = _clean_recognition(recognition) if recognition else {}
    clean_details["recognition"] = clean_recognition
    clean_name = PurePath(filename or "transfer-voucher").name[:255]
    voucher_hash = hashlib.sha256(image_data).hexdigest()
    duplicate = s.execute(
        select(NexusManualTransfer).where(
            NexusManualTransfer.voucher_sha256 == voucher_hash
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise FleetError(
            "NEXUS_TRANSFER_DUPLICATE",
            "该转账凭证已登记为 %s，请勿重复入账" % duplicate.transfer_no,
            409,
        )
    now = _now_ms()
    row = NexusManualTransfer(
        transfer_no=_gen_transfer_no(),
        oem_id=linked_oem,
        amount_cents=cents,
        currency="CNY",
        status="confirmed" if confirmed else "pending_review",
        purpose=(purpose or "企业转账收款").strip()[:255],
        encrypted_details=_encrypt_json(clean_details),
        voucher_filename=clean_name,
        voucher_content_type=safe_type,
        voucher_size=len(image_data),
        voucher_sha256=voucher_hash,
        encrypted_voucher=_fernet().encrypt(image_data),
        recognition_status="recognized" if clean_recognition else "not_run",
        created_ts=now,
        confirmed_ts=now if confirmed else 0,
    )
    s.add(row)
    s.flush()
    return public_transfer(row)


def public_transfer(row: NexusManualTransfer) -> Dict[str, Any]:
    """生成超管订单列表记录；银行详情可见，但凭证二进制永不进入 JSON。"""
    details = _decrypt_json(row)
    recognition = details.pop("recognition", {})
    return {
        "record_type": "manual_transfer",
        "transfer_id": int(row.id),
        "order_no": str(row.transfer_no),
        "oem_id": int(row.oem_id) if row.oem_id else None,
        "kind": "manual_transfer",
        "channel": "corporate_transfer",
        "amount_cents": int(row.amount_cents),
        "currency": str(row.currency),
        "status": "paid" if row.status == "confirmed" else str(row.status),
        "purpose": str(row.purpose),
        "details": details,
        "recognition": recognition,
        "recognition_status": str(row.recognition_status),
        "voucher_filename": str(row.voucher_filename),
        "voucher_size": int(row.voucher_size),
        "created_ts": int(row.created_ts),
        "paid_ts": int(row.confirmed_ts) if row.confirmed_ts else None,
    }


def decide_submission(
    s, transfer_id: int, approve: bool
) -> NexusManualTransfer:
    """锁定并处理 OEM 上传的待审转账凭证。

    只允许 ``pending_review`` 进入 confirmed/rejected；已确认记录重复收到
    “确认”时幂等返回，既防双击也防管理端响应丢失后误判。
    """
    row = s.execute(
        select(NexusManualTransfer)
        .where(NexusManualTransfer.id == int(transfer_id))
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise FleetError("NEXUS_TRANSFER_NOT_FOUND", "企业转账凭证不存在", 404)
    target = "confirmed" if approve else "rejected"
    if row.status == target:
        return row
    if row.status != "pending_review":
        raise FleetError("NEXUS_TRANSFER_DECIDED", "该转账凭证已处理", 409)
    row.status = target
    row.confirmed_ts = _now_ms() if approve else 0
    return row


def list_transfers(s, limit: int = 200) -> List[Dict[str, Any]]:
    """按新到旧返回企业转账单，供超管订单列表与计数使用。"""
    rows = s.execute(
        select(NexusManualTransfer)
        .order_by(NexusManualTransfer.id.desc())
        .limit(max(1, min(int(limit), 500)))
    ).scalars().all()
    return [public_transfer(row) for row in rows]


def voucher(s, transfer_id: int) -> Tuple[str, str, bytes]:
    """解密一张凭证，返回（文件名、MIME、原始字节）供超管下载查看。"""
    row = s.get(NexusManualTransfer, int(transfer_id))
    if row is None:
        raise FleetError("NEXUS_TRANSFER_NOT_FOUND", "企业转账单不存在", 404)
    try:
        data = _fernet().decrypt(bytes(row.encrypted_voucher))
    except InvalidToken:
        raise FleetError(
            "NEXUS_SECRET_KEY_INVALID",
            "转账凭证无法解密，请核对 NEXUS_SECRET_KEY",
            503,
        )
    return str(row.voucher_filename), str(row.voucher_content_type), data


def summary(s) -> Dict[str, int]:
    """聚合已确认营收和待核对转账；两种口径严格分开。"""
    since_30d = _now_ms() - 30 * 24 * 3600 * 1000
    # 聚合必须留在数据库侧执行；财务流水增长后不能把全部凭证元数据拉进服务内存。
    row = s.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (
                            NexusManualTransfer.status == "confirmed",
                            NexusManualTransfer.amount_cents,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (NexusManualTransfer.status == "confirmed", 1),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            (NexusManualTransfer.status == "confirmed")
                            & (NexusManualTransfer.confirmed_ts >= since_30d),
                            NexusManualTransfer.amount_cents,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            NexusManualTransfer.status == "pending_review",
                            NexusManualTransfer.amount_cents,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (NexusManualTransfer.status == "pending_review", 1),
                        else_=0,
                    )
                ),
                0,
            ),
        )
    ).one()
    return {
        "manual_transfer_revenue_cents": int(row[0] or 0),
        "manual_transfer_count": int(row[1] or 0),
        "manual_transfer_30d_cents": int(row[2] or 0),
        "manual_transfer_pending_cents": int(row[3] or 0),
        "manual_transfer_pending_count": int(row[4] or 0),
    }
