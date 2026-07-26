"""GuDuu Nexus —— LLM 网关（模块6 的技术核心）。

铁律（方案拍板，绝不破坏）：**原厂 LLM key 只存在于本进程的 env，永不下发**。
各 OEM 实例的 AI 调用全部打到这里：

    实例侧                          网关（本模块）                原厂
    ANTHROPIC_API_KEY=<OEM KEY> →  校验 KEY/实例/钱包余额  →  换真 key 转发
    base_url=https://<网关>/gw/anthropic                      ← 响应原样回传
                                    ← 解析 usage → 扣钱包（流水入账）

这一条链路同时给了我们三样东西：计费依据、断供抓手（唯一技术缰绳）、
大屏的实时用量数据源。

安全设计：
    - 实例凭 OEM KEY 鉴权（x-api-key 或 Authorization: Bearer 都认——
      对应 anthropic / openai 两种 SDK 的送法），库里只存哈希；
    - **路径白名单**：每个厂商只放行对话端点，防止原厂 key 被实例拿去调
      files / fine-tune / batch 等任意接口；
    - 转发时只带白名单请求头，实例的其他头（cookie 等）一律丢弃。

计量口径（P1 简化，记入 DEVLOG）：扣费 = 输入 token + 输出 token（1:1 记账）；
不同模型价差、倍率表是 P2/P3 定价问题，流水里已记 provider/model/用量，可回溯重算。
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Tuple

import requests
from sqlalchemy import select

from nexus import db, fleet
from nexus.db import NexusInstance, NexusKey, NexusWallet
from nexus.keys import hash_key, looks_like_key

logger = logging.getLogger("nexus.gateway")

# ---------- 厂商表 ----------
# base 可用 env NEXUS_GW_<名>_BASE 覆盖（测试指向假上游/换区域）；
# key_env 是原厂 key 的环境变量名；allow 是路径白名单（相对 base 的后缀）。
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "anthropic": {
        "base": "https://api.anthropic.com",
        "base_env": "NEXUS_GW_ANTHROPIC_BASE",
        "key_env": "NEXUS_GW_ANTHROPIC_KEY",
        "style": "anthropic",  # 原厂鉴权头：x-api-key
        "allow": {"v1/messages"},
    },
    "openai": {
        "base": "https://api.openai.com",
        "base_env": "NEXUS_GW_OPENAI_BASE",
        "key_env": "NEXUS_GW_OPENAI_KEY",
        "style": "bearer",  # 原厂鉴权头：Authorization: Bearer
        "allow": {"v1/chat/completions"},
    },
    # 火山方舟（DeepSeek 等）：openai 兼容协议，base 自带 /api/v3
    "ark": {
        "base": "https://ark.cn-beijing.volces.com/api/v3",
        "base_env": "NEXUS_GW_ARK_BASE",
        "key_env": "NEXUS_GW_ARK_KEY",
        "style": "bearer",
        "allow": {"chat/completions"},
    },
}

# 转发到原厂时保留的请求头白名单（小写比对）；鉴权头由网关重写，不在此列
_FWD_HEADERS = {"content-type", "accept", "anthropic-version", "anthropic-beta"}


class GatewayError(Exception):
    """网关拒绝：code/HTTP 状态与 fleet 风格一致，handler 翻译成 JSON。"""

    def __init__(self, code: str, message: str, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


# ---------- 鉴权 ----------

def extract_client_key(headers) -> str:
    """从请求头拿实例的 OEM KEY：anthropic SDK 送 x-api-key，openai SDK 送 Bearer。"""
    key = (headers.get("x-api-key") or "").strip()
    if key:
        return key
    auth = headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return ""


def authorize(s, raw_key: str) -> Tuple[int, int]:
    """校验 OEM KEY 并检查余额，返回 (instance_id, balance)。

    拒绝矩阵（对应商业规则）：
        KEY 无效/吊销 → 403（授权问题，联系 GuDuu）
        未兑换        → 403（先装机开通）
        实例被停用    → 403（P2 大后台一键停用的执行点）
        余额 ≤ 0      → 402（**唯一续费抓手**：充值即恢复，无需重启实例）
    """
    if not looks_like_key(raw_key):
        raise GatewayError("NEXUS_GW_BAD_KEY", "无效的平台授权码", 403)
    key = s.execute(
        select(NexusKey).where(NexusKey.key_hash == hash_key(raw_key))
    ).scalar_one_or_none()
    if key is None or key.status != "active":
        raise GatewayError("NEXUS_GW_BAD_KEY", "授权码不存在或已吊销", 403)
    if key.instance_id is None:
        raise GatewayError("NEXUS_GW_NOT_REDEEMED", "授权码尚未兑换开通", 403)
    inst = s.get(NexusInstance, key.instance_id)
    if inst is None or inst.status != "active":
        raise GatewayError("NEXUS_GW_SUSPENDED", "实例已被停用，请联系 GuDuu", 403)
    wallet = s.get(NexusWallet, inst.id)
    balance = int(wallet.balance_tokens) if wallet else 0
    if balance <= 0:
        raise GatewayError(
            "NEXUS_GW_NO_BALANCE",
            "token 余额已用尽，请充值后继续使用 AI 服务",
            402,
        )
    return inst.id, balance


# ---------- 上游解析 ----------

def resolve_upstream(provider: str, suffix: str) -> Tuple[str, Dict[str, str]]:
    """厂商名 + 路径后缀 → (完整上游 URL, 鉴权头)。

    白名单不命中一律 403——这是保护**我们的**原厂 key 不被滥用的关键闸门。
    """
    conf = PROVIDERS.get(provider)
    if conf is None:
        raise GatewayError("NEXUS_GW_UNKNOWN_PROVIDER", f"不支持的厂商 {provider}", 404)
    suffix = suffix.strip("/")
    if suffix not in conf["allow"]:
        raise GatewayError("NEXUS_GW_PATH_DENIED", "该接口不在网关白名单内", 403)
    vendor_key = os.environ.get(conf["key_env"], "").strip()
    if not vendor_key:
        # 原厂 key 没配 = 平台侧故障，给 503 让实例侧知道"不是自己的问题"
        raise GatewayError(
            "NEXUS_GW_PROVIDER_DOWN", f"平台未配置 {provider} 通道", 503
        )
    base = os.environ.get(conf["base_env"], "").strip() or conf["base"]
    if conf["style"] == "anthropic":
        auth = {"x-api-key": vendor_key}
    else:
        auth = {"Authorization": f"Bearer {vendor_key}"}
    return f"{base.rstrip('/')}/{suffix}", auth


# ---------- 用量解析 ----------

def usage_from_json(obj: Any) -> Tuple[int, int]:
    """从完整响应 JSON 里取 (输入, 输出) token。

    anthropic：usage.input_tokens / output_tokens
    openai 系：usage.prompt_tokens / completion_tokens
    """
    if not isinstance(obj, dict):
        return 0, 0
    u = obj.get("usage") or {}
    if not isinstance(u, dict):
        return 0, 0
    t_in = u.get("input_tokens") or u.get("prompt_tokens") or 0
    t_out = u.get("output_tokens") or u.get("completion_tokens") or 0
    try:
        return max(int(t_in), 0), max(int(t_out), 0)
    except Exception:
        return 0, 0


def usage_from_sse(lines) -> Tuple[int, int]:
    """从 SSE 事件流的 data 行里累计 (输入, 输出) token。

    anthropic 流式：message_start 带 input_tokens，message_delta 带累计
    output_tokens（取 max 即终值）；openai 流式：末块可带完整 usage
    （实例侧 SDK 开 include_usage 时）。两种混着解析，取各自最大值。
    """
    t_in = 0
    t_out = 0
    for line in lines:
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except Exception:
            continue
        # anthropic message_start：{"message": {"usage": {...}}}
        msg = obj.get("message")
        if isinstance(msg, dict):
            i, o = usage_from_json(msg)
            t_in, t_out = max(t_in, i), max(t_out, o)
        i, o = usage_from_json(obj)
        t_in, t_out = max(t_in, i), max(t_out, o)
    return t_in, t_out


# ---------- 主处理（由 service.NexusHandler 调用）----------

def _record_stat(instance_id: int, *, ok: bool, started: float) -> None:
    """把一次网关请求记进分钟桶（成功率/延迟/峰值的数据源）。

    **best-effort**：统计只是观测,失败绝不能影响转发或计费——整体吞异常、只记日志。
    单开短连接：与计费一样,不抱着 DB 连接等 LLM。
    """
    latency_ms = int((time.monotonic() - started) * 1000)
    s = db.session()
    try:
        fleet.record_request(s, instance_id, ok=ok, latency_ms=latency_ms)
        s.commit()
    except Exception:
        s.rollback()
        logger.debug("记录网关请求统计失败（忽略）", exc_info=True)
    finally:
        s.close()


def handle_post(handler, provider: str, suffix: str) -> None:
    """处理一次网关转发。handler 是 NexusHandler（复用其读体/回包工具）。

    流程：鉴权（短连 DB）→ 转发上游（可能耗时数分钟，期间**不占** DB 连接）
    → 回传响应（流式则边收边发）→ 解析用量 → 扣钱包（新开短连 DB）。
    """
    # 先把请求体读干净（HTTP/1.1 keep-alive：错误提前返回时若不读完请求体，
    # 复用连接上的下一个请求会被残留字节打乱——这类 bug 极难排查，先绝后患）
    body = b""
    try:
        n = int(handler.headers.get("Content-Length") or 0)
        body = handler.rfile.read(min(n, 4 * 1024 * 1024)) if n else b""
    except Exception:
        pass

    raw_key = extract_client_key(handler.headers)
    if not raw_key:
        handler._err(401, "NEXUS_GW_NO_KEY", "缺少平台授权码")
        return

    # ① 鉴权：短事务，查完就还连接（LLM 请求动辄几十秒，绝不能抱着连接等）
    s = db.session()
    try:
        instance_id, _balance = authorize(s, raw_key)
        s.commit()
    except GatewayError as e:
        s.rollback()
        handler._err(e.http_status, e.code, e.message)
        return
    finally:
        s.close()

    # ② 组装转发
    try:
        url, auth_headers = resolve_upstream(provider, suffix)
    except GatewayError as e:
        handler._err(e.http_status, e.code, e.message)
        return

    # 从请求体里薅出 model 名（记账用；解析失败不影响转发）
    model = ""
    try:
        model = str(json.loads(body.decode("utf-8")).get("model", ""))[:64]
    except Exception:
        pass

    fwd_headers = dict(auth_headers)
    for name in _FWD_HEADERS:
        val = handler.headers.get(name)
        if val:
            fwd_headers[name] = val

    # ③ 请求上游。连接 10s / 读 600s（长推理），stream=True 统一处理两种形态
    started = time.monotonic()
    try:
        upstream = requests.post(
            url, data=body, headers=fwd_headers, stream=True, timeout=(10, 600)
        )
    except requests.RequestException as e:
        logger.warning("上游不可达 %s: %s", url, e)
        # 上游打不通也是一次**失败请求**——必须记,否则成功率永远 100%(见 fleet.record_request)
        _record_stat(instance_id, ok=False, started=started)
        handler._err(502, "NEXUS_GW_UPSTREAM", "上游模型服务不可达")
        return

    t_in = t_out = 0
    ctype = upstream.headers.get("Content-Type", "application/json")
    try:
        if "text/event-stream" in ctype:
            # —— 流式：chunked 边收边发，同时截留 data 行解析用量 ——
            handler.send_response(upstream.status_code)
            handler.send_header("Content-Type", ctype)
            handler.send_header("Transfer-Encoding", "chunked")
            handler.end_headers()
            collected = []
            for chunk in upstream.iter_content(chunk_size=None):
                if not chunk:
                    continue
                collected.append(chunk)
                handler.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
            handler.wfile.write(b"0\r\n\r\n")
            try:
                text = b"".join(collected).decode("utf-8", "replace")
                t_in, t_out = usage_from_sse(text.splitlines())
            except Exception:
                pass
        else:
            # —— 非流式：整包读完，解析 usage 后原样回传 ——
            content = upstream.content
            try:
                t_in, t_out = usage_from_json(json.loads(content.decode("utf-8")))
            except Exception:
                pass
            handler.send_response(upstream.status_code)
            handler.send_header("Content-Type", ctype)
            handler.send_header("Content-Length", str(len(content)))
            handler.end_headers()
            handler.wfile.write(content)
    except (BrokenPipeError, ConnectionResetError):
        # 实例侧断线：响应发不出去了，但上游已产生消耗——照常走下面的扣账
        logger.info("实例侧断开连接（instance=%s）", instance_id)
    finally:
        upstream.close()

    # 请求统计（成功率/延迟/峰值的唯一数据源）：**成败都记**。
    # 与计费口径一致：上游 2xx 记成功,4xx/5xx 记失败(但不扣钱)。
    _record_stat(instance_id, ok=upstream.status_code < 400, started=started)

    # ④ 记账：上游 2xx 且有用量才扣（4xx/5xx 不该让 OEM 买单）。新开短连。
    total = t_in + t_out
    if upstream.status_code < 400 and total > 0:
        s2 = db.session()
        try:
            fleet.debit(
                s2,
                instance_id,
                total,
                note=f"{provider}/{model or '?'} in={t_in} out={t_out}",
            )
            s2.commit()
        except Exception:
            s2.rollback()
            # 记账失败绝不能丢：这是钱。记 ERROR 级日志，人工对账兜底。
            logger.exception(
                "扣账失败 instance=%s tokens=%s（需人工对账）", instance_id, total
            )
        finally:
            s2.close()
    elif upstream.status_code < 400 and total == 0:
        logger.warning(
            "上游成功但未解析到用量（provider=%s model=%s）——本次未计费",
            provider,
            model,
        )
