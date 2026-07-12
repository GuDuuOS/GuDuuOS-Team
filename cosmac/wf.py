"""外部工作流连接器引擎（模块3）。

不自建工作流引擎——把主 AI / 聊天命令的请求，转成对 n8n / Make 等平台 **webhook** 的
一次同步 HTTP 调用，再把结果规范化拿回来发进群。后续再加 Dify/Coze/ComfyUI 专用适配器。

纯 HTTP、不依赖 DB/SQLAlchemy（运行记录由调用方另存），方便单测与降级。
密钥**绝不**来自连接器定义（state event 不加密）：定义里只放"凭据名 cred"，
真值从服务端环境变量 ``COSMAC_WF_<CRED>`` 读，作为 Bearer 头发出（同 LLM key 策略）。
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

logger = logging.getLogger("cosmac.wf")

# —— 有界后台执行：**三个独立池**，按延迟级别隔离，避免队头阻塞（#5）——
#  submit：异步连接器的"提交"动作（POST 完即返回、秒级），单独一池——绝不被长任务堵住，
#          否则用户已收到"已提交"、任务却还排在队尾迟迟发不出去；
#  fast  ：同步 webhook/dify/coze（可达 30s）；
#  slow  ：ComfyUI 生成（轮询可达 120s）。
#  三池互不挤占：长 ComfyUI 占满 slow 时，同步连接器仍跑在 fast、异步提交仍跑在 submit。
_POOL_WORKERS = {"submit": 4, "fast": 4, "slow": 4}
_MAX_INFLIGHT = {"submit": 32, "fast": 16, "slow": 8}  # 各池在跑+排队上限；超了拒绝（背压）
_executors = {
    name: ThreadPoolExecutor(max_workers=w, thread_name_prefix=f"wf-{name}")
    for name, w in _POOL_WORKERS.items()
}
_bg_lock = threading.Lock()
_bg_inflight = {name: 0 for name in _POOL_WORKERS}


def submit_background(fn: Callable[[], None], *, pool: str = "fast") -> bool:
    """把无参任务提交到**有界**后台线程池。达到该池上限时返回 False（拒绝），否则 True。

    ``pool`` 选执行池：``submit`` 异步提交（秒级、独占一池不被堵）/ ``fast`` 同步连接器 /
    ``slow`` ComfyUI 等长任务。三池隔离避免队头阻塞（#5）。未知名退回 ``fast``。
    """
    if pool not in _executors:
        pool = "fast"
    with _bg_lock:
        if _bg_inflight[pool] >= _MAX_INFLIGHT[pool]:
            return False
        _bg_inflight[pool] += 1

    def _wrap() -> None:
        try:
            fn()
        except Exception:
            logger.exception("后台工作流任务异常")
        finally:
            with _bg_lock:
                _bg_inflight[pool] -= 1

    try:
        _executors[pool].submit(_wrap)
    except Exception:
        # submit 本身失败(如 executor 已 shutdown → RuntimeError)：上面已 +1 的 inflight 计数
        # 必须回滚，否则该池计数永久虚高、最终恒 >= _MAX_INFLIGHT 而永久拒绝所有后续任务。
        with _bg_lock:
            _bg_inflight[pool] -= 1
        logger.exception("提交后台工作流任务失败")
        return False
    return True


def check_outbound_url(url: str) -> str:
    """SSRF 防护：校验"服务端将要外呼的 URL"是否安全。放行返回 ""，否则返回拒绝原因。

    管理员可在连接器里填任意 URL，服务端会带着 Bearer 密钥去打它——必须挡住"打内网/
    localhost/云元数据(169.254.169.254)"这类 SSRF + 凭据外泄：
      - 只允许 http/https；
      - 把主机名解析成 IP，**任一**解析结果落在危险段就拒绝：
        · 链路本地(含云 metadata)/保留/组播/未指定 —— **永远拒绝**；
        · 私网/环回 —— 默认拒绝；自建内网工作流可设 COSMAC_WF_ALLOW_INTERNAL=1 放行。
    调用方还须 ``allow_redirects=False``，否则重定向到内网可绕过本校验。
    （残留：getaddrinfo 与 requests 各解析一次，存在 DNS rebinding 的理论窗口；
      要彻底防需把校验过的 IP 钉死再连，本期先挡住绝大多数直球 SSRF。）
    """
    try:
        u = urlparse(url)
    except Exception:
        return "URL 非法"
    if u.scheme not in ("http", "https"):
        return f"只允许 http/https（收到 {u.scheme or '空'}）"
    host = u.hostname
    if not host:
        return "URL 缺少主机名"
    allow_internal = os.environ.get("COSMAC_WF_ALLOW_INTERNAL", "").lower() in (
        "1", "true", "yes",
    )
    try:
        infos = socket.getaddrinfo(host, u.port or 0, proto=socket.IPPROTO_TCP)
    except Exception as exc:
        return f"无法解析主机 {host}：{exc}"
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            return f"解析到非法 IP：{info[4][0]}"
        if (
            addr.is_link_local or addr.is_reserved
            or addr.is_multicast or addr.is_unspecified
        ):
            return f"目标 {addr} 属链路本地/保留段，已拒绝（防 SSRF/云元数据）"
        if (addr.is_private or addr.is_loopback) and not allow_internal:
            return (
                f"目标 {addr} 属内网/环回，已拒绝；自建内网工作流请设 "
                "COSMAC_WF_ALLOW_INTERNAL=1"
            )
    return ""

DEFAULT_TIMEOUT = 30  # 秒；webhook 同步等待上限
_MAX_OUT = 4000       # 结果文本截断，避免把超长内容塞进群/上下文

# 从平台返回 JSON 里按顺序找"主要文本输出"的常见字段
_OUTPUT_KEYS = ("output", "result", "text", "message", "answer", "data", "content")


# 支持异步回调协议的平台：只有 webhook 家族（run_webhook 会塞 callback_url/token）。
# Dify/Coze/ComfyUI 没有回调通道，async=true 对它们无意义，应按同步后台跑（#3）。
_CALLBACK_PLATFORMS = ("webhook", "n8n", "make", "custom", "")


def supports_async_callback(platform: str) -> bool:
    """该平台是否支持异步回调（决定 async=true 是否真能走回调协议）。"""
    return (platform or "webhook").lower() in _CALLBACK_PLATFORMS


def _cred_env(cred: str) -> str:
    """凭据名 → 环境变量名（``COSMAC_WF_<CRED>``）。"""
    return "COSMAC_WF_" + re.sub(r"[^A-Za-z0-9]", "_", cred).upper()


def resolve_credential(cred: str) -> str:
    """凭据名 → 服务端 env 里的密钥值（``COSMAC_WF_<CRED>``）。空/未配返回空串。"""
    if not cred:
        return ""
    return os.environ.get(_cred_env(cred), "")


def credential_host(cred: str) -> str:
    """凭据**绑定的允许域名**（服务端 env ``COSMAC_WF_<CRED>_HOST``）。空=未绑定。"""
    if not cred:
        return ""
    return os.environ.get(_cred_env(cred) + "_HOST", "").strip().lower()


def credential_for(cred: str, url: str) -> Tuple[str, str]:
    """解析凭据并**校验只发往服务端绑定的域名**（#1 防凭据被导出）。返回 (bearer, error)。

    平台管理员能在前端把任意 URL 填进连接器；若直接把密钥发过去，等于把服务端凭据导出到
    管理员控制的任意公网地址。所以密钥的**允许域名也由服务端 env 固定**：
      - cred 为空 / 没配 secret → ("", "")：当作无鉴权（很多 webhook 把令牌带在 URL 里）。
      - 有 secret 但未绑定域名 → 拒绝（提示设 ``COSMAC_WF_<CRED>_HOST``），绝不外发密钥。
      - URL 主机 ≠ 绑定域名 → 拒绝。
      - 匹配 → 返回密钥。
    """
    if not cred:
        return "", ""
    secret = resolve_credential(cred)
    if not secret:
        return "", ""
    bound = credential_host(cred)
    if not bound:
        return "", (
            f"凭据「{cred}」未绑定域名：请在服务端设 {_cred_env(cred)}_HOST=<允许的域名>，"
            "否则拒绝外发密钥（防凭据被导出到任意 URL）"
        )
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host != bound:
        return "", f"凭据「{cred}」只允许发往 {bound}，当前目标主机是 {host or '空'}，已拒绝"
    # #3：带密钥**必须走 HTTPS**，否则 Bearer 会在网络里被明文窃取。
    # 内网 HTTP 才放行，且要求：① 显式开关 COSMAC_WF_ALLOW_INTERNAL=1，
    # **且** ② 主机解析到的 IP 确实属私网/环回——否则"开了内网开关"也不能给公网发明文密钥。
    if parsed.scheme != "https":
        allow_internal = os.environ.get("COSMAC_WF_ALLOW_INTERNAL", "").lower() in (
            "1", "true", "yes",
        )
        if not (allow_internal and _host_is_internal(host)):
            return "", (
                f"凭据「{cred}」不能走明文 HTTP（密钥会被网络窃取）：公网请用 HTTPS；"
                "内网 HTTP 须设 COSMAC_WF_ALLOW_INTERNAL=1 且目标确为私网地址"
            )
    return secret, ""


def _host_is_internal(host: str) -> bool:
    """主机解析到的 **所有** IP 都属私网/环回/链路本地才算"内网"。解析失败/含公网→False。"""
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, 0, proto=socket.IPPROTO_TCP)
    except Exception:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if not (addr.is_private or addr.is_loopback or addr.is_link_local):
            return False
    return True


# —— 响应体大小上限（#5 防恶意/失控平台返回超大内容耗内存）——
_MAX_RESP_BYTES = 2 * 1024 * 1024      # 普通响应体 2MB
_MAX_IMAGE_BYTES = 16 * 1024 * 1024    # ComfyUI 单图 16MB


class _TooBig(Exception):
    """响应体超过上限。"""


def _fetch(
    method: str, url: str, *, headers: Optional[Dict[str, str]] = None,
    json_body: Any = None, params: Optional[Dict[str, Any]] = None,
    timeout: int, max_bytes: int = _MAX_RESP_BYTES,
):
    """发请求并**有上限地**读响应体：`stream=True` + 累计字节封顶 + 看 Content-Length。

    把读到（且已限长）的内容塞回 ``resp._content``，后续 ``resp.text/.json()`` 照常用。
    超限抛 ``_TooBig``；同时 ``allow_redirects=False`` 防重定向绕过 SSRF。
    """
    resp = requests.request(
        method, url, headers=headers, json=json_body, params=params,
        timeout=timeout, allow_redirects=False, stream=True,
    )
    cl = resp.headers.get("Content-Length")
    if cl and cl.isdigit() and int(cl) > max_bytes:
        resp.close()
        raise _TooBig()
    # #4：`timeout` 只是单次读操作超时；慢速持续小块发送能长期占住 worker。
    # 这里加**整体 deadline**：流式读总时长也不得超过 timeout，超了就掐断回收。
    deadline = time.monotonic() + timeout
    buf = bytearray()
    for chunk in resp.iter_content(8192):
        if time.monotonic() > deadline:
            resp.close()
            raise _TooBig()  # 整体超时，按"异常响应"处理（掐断、不占 worker）
        if not chunk:
            continue
        buf += chunk
        if len(buf) > max_bytes:
            resp.close()
            raise _TooBig()
    resp._content = bytes(buf)  # 让 .text/.json() 用已读、已限的内容
    return resp


def run_webhook(
    conn: Dict[str, Any], user_input: str, *,
    callback_url: str = "", callback_token: str = "", timeout: int = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """同步调用一个 webhook 型连接器，返回规范化结果。

    返回 dict：``{"ok": bool, "status": int|None, "output": str, "error": str}``。
    绝不抛异常——网络/超时/非 2xx 都转成 ok=False + error 文案。
    ``callback_url``/``callback_token`` 非空时塞进 payload：异步用——平台跑完反向 POST 回
    callback_url，并把 callback_token 作为 X-Cosmac-Token 头带回来鉴权（token 不进 URL，#2）。
    """
    url = (conn.get("url") or "").strip()
    if not url:
        return {"ok": False, "status": None, "output": "", "error": "连接器未配置 URL"}
    bad = check_outbound_url(url)  # SSRF 防护
    if bad:
        return {"ok": False, "status": None, "output": "", "error": bad}
    method = (conn.get("method") or "POST").upper()
    headers = {"Content-Type": "application/json"}
    token, cred_err = credential_for(conn.get("cred") or "", url)  # #1 凭据绑定域名
    if cred_err:
        return {"ok": False, "status": None, "output": "", "error": cred_err}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # 统一的输入约定：平台侧从 input 取用户这句话；source 标记来源
    payload: Dict[str, Any] = {"input": user_input, "source": "cosmac"}
    if callback_url:
        payload["callback_url"] = callback_url
    if callback_token:
        payload["callback_token"] = callback_token  # 平台据此回传 X-Cosmac-Token 头
    try:
        resp = _fetch(method, url, json_body=payload, headers=headers, timeout=timeout)
    except _TooBig:
        # 已经收到平台响应后才发现响应体过大，任务可能已被平台接受，不能诱导立即重试。
        return {
            "ok": False, "status": None, "output": "",
            "error": "平台响应过大，提交结果未知", "ambiguous": True,
        }
    except requests.RequestException as exc:
        logger.warning("工作流 webhook 调用失败: %s", exc)
        # 超时/断线可能发生在平台已接单之后。保留 pending/token 等回调，避免重复扣费。
        return {
            "ok": False, "status": None, "output": "",
            "error": f"请求失败、提交结果未知：{exc}", "ambiguous": True,
        }

    ok = 200 <= resp.status_code < 300
    text = _extract_text(resp)
    err = "" if ok else f"平台返回 {resp.status_code}"
    return {
        "ok": ok,
        "status": resp.status_code,
        "output": text,
        "error": err,
        # 5xx 也可能是平台接单后内部响应失败；4xx 才能较可靠地视为明确拒绝。
        "ambiguous": resp.status_code >= 500,
    }


def _extract_text(resp: requests.Response) -> str:
    """从响应里抽一段"主要文本"：JSON 命中常见字段则取之，否则整体字符串化。"""
    try:
        data = resp.json()
    except ValueError:
        return (resp.text or "").strip()[:_MAX_OUT]
    if isinstance(data, dict):
        for k in _OUTPUT_KEYS:
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()[:_MAX_OUT]
        return json.dumps(data, ensure_ascii=False)[:_MAX_OUT]
    if isinstance(data, str):
        return data.strip()[:_MAX_OUT]
    return json.dumps(data, ensure_ascii=False)[:_MAX_OUT]


def run_dify(
    conn: Dict[str, Any], user_input: str, *, timeout: int = DEFAULT_TIMEOUT
) -> Dict[str, Any]:
    """调用 Dify 应用：mode=workflow 走 /v1/workflows/run，mode=chat 走 /v1/chat-messages。

    连接器字段：url=Dify 服务地址(默认 https://api.dify.ai)、cred=App API Key、
    mode=workflow|chat、input_key=workflow 输入变量名(默认 input)。
    """
    base = (conn.get("url") or "https://api.dify.ai").rstrip("/")
    bad = check_outbound_url(base)  # SSRF 防护
    if bad:
        return _err(bad)
    key, cred_err = credential_for(conn.get("cred") or "", base)  # #1 凭据绑定域名
    if cred_err:
        return _err(cred_err)
    if not key:
        return _err("Dify 连接器缺凭据（服务端 env COSMAC_WF_<CRED> 未配）")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    mode = (conn.get("mode") or "workflow").lower()
    if mode == "chat":
        url = f"{base}/v1/chat-messages"
        payload: Dict[str, Any] = {
            "query": user_input, "inputs": {},
            "response_mode": "blocking", "user": "cosmac",
        }
    else:
        url = f"{base}/v1/workflows/run"
        ikey = conn.get("input_key") or "input"
        payload = {
            "inputs": {ikey: user_input},
            "response_mode": "blocking", "user": "cosmac",
        }
    try:
        resp = _fetch("POST", url, json_body=payload, headers=headers, timeout=timeout)
    except _TooBig:
        return _err("Dify 响应过大，已拒绝")
    except requests.RequestException as exc:
        logger.warning("Dify 调用失败: %s", exc)
        return _err(f"请求失败：{exc}")
    ok = 200 <= resp.status_code < 300
    text = _extract_dify(resp, mode) if ok else _extract_text(resp)
    return {"ok": ok, "status": resp.status_code, "output": text,
            "error": "" if ok else f"Dify 返回 {resp.status_code}"}


def _extract_dify(resp: "requests.Response", mode: str) -> str:
    try:
        data = resp.json()
    except ValueError:
        return (resp.text or "").strip()[:_MAX_OUT]
    if not isinstance(data, dict):
        return str(data)[:_MAX_OUT]
    if mode == "chat":
        return (data.get("answer") or json.dumps(data, ensure_ascii=False))[:_MAX_OUT]
    outs = (data.get("data") or {}).get("outputs")
    if isinstance(outs, dict) and outs:
        for v in outs.values():
            if isinstance(v, str) and v.strip():
                return v[:_MAX_OUT]
        return json.dumps(outs, ensure_ascii=False)[:_MAX_OUT]
    return json.dumps(data, ensure_ascii=False)[:_MAX_OUT]


def run_coze(
    conn: Dict[str, Any], user_input: str, *, timeout: int = DEFAULT_TIMEOUT
) -> Dict[str, Any]:
    """调用 Coze 工作流：POST {base}/v1/workflow/run。

    连接器字段：url=Coze 服务地址(默认 https://api.coze.cn)、cred=PAT/OAuth token、
    ref_id=workflow_id、input_key=参数名(默认 input)。
    """
    base = (conn.get("url") or "https://api.coze.cn").rstrip("/")
    bad = check_outbound_url(base)  # SSRF 防护
    if bad:
        return _err(bad)
    key, cred_err = credential_for(conn.get("cred") or "", base)  # #1 凭据绑定域名
    if cred_err:
        return _err(cred_err)
    if not key:
        return _err("Coze 连接器缺凭据（服务端 env COSMAC_WF_<CRED> 未配）")
    wfid = (conn.get("ref_id") or "").strip()
    if not wfid:
        return _err("Coze 连接器需填 workflow_id（连接器的 ref_id 字段）")
    ikey = conn.get("input_key") or "input"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {"workflow_id": wfid, "parameters": {ikey: user_input}}
    try:
        resp = _fetch(
            "POST", f"{base}/v1/workflow/run", json_body=payload, headers=headers,
            timeout=timeout,
        )
    except _TooBig:
        return _err("Coze 响应过大，已拒绝")
    except requests.RequestException as exc:
        logger.warning("Coze 调用失败: %s", exc)
        return _err(f"请求失败：{exc}")
    if not (200 <= resp.status_code < 300):
        return {"ok": False, "status": resp.status_code, "output": "",
                "error": f"Coze 返回 {resp.status_code}"}
    try:
        data = resp.json()
    except ValueError:
        return {"ok": True, "status": resp.status_code,
                "output": (resp.text or "")[:_MAX_OUT], "error": ""}
    # Coze 业务码：code==0 才算成功，data 常是 JSON 字符串
    if isinstance(data, dict) and data.get("code") not in (0, None):
        return {"ok": False, "status": resp.status_code, "output": "",
                "error": f"Coze 错误：{data.get('msg') or data.get('code')}"}
    out = data.get("data") if isinstance(data, dict) else data
    text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
    return {"ok": True, "status": resp.status_code, "output": text[:_MAX_OUT], "error": ""}


def _err(msg: str) -> Dict[str, Any]:
    return {"ok": False, "status": None, "output": "", "error": msg}


# —— ComfyUI（图/视频生成：提交工作流图 → 轮询 → 回传媒体到 Matrix）——
COMFY_TIMEOUT = 120   # 轮询等待上限（秒）；超长生成需异步回调(后续)
COMFY_MAX_IMAGES = 4  # 单次最多回传几张

# 文件后缀 → MIME（ComfyUI /view 不一定给可靠的 Content-Type）
_MIME = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "webp": "image/webp", "gif": "image/gif", "mp4": "video/mp4", "webm": "video/webm",
}


def run_comfyui(
    conn: Dict[str, Any], user_input: str, *,
    client: Any = None, room_id: str = "", timeout: int = COMFY_TIMEOUT,
) -> Dict[str, Any]:
    """提交 ComfyUI 工作流图 → 轮询完成 → 把产出的图片回传到本群。

    连接器字段：url=ComfyUI 地址、cred=可选鉴权、graph=API 格式工作流 JSON 模板
    （把要被用户输入替换的地方写成占位符 ``{{input}}``）。需在群里触发（要 client+room_id 发图）。
    """
    if client is None or not room_id:
        return _err("ComfyUI 工作流要在群里触发（需要发图的目标房间）")
    base = (conn.get("url") or "").rstrip("/")
    if not base:
        return _err("ComfyUI 连接器未配置 URL")
    bad = check_outbound_url(base)  # SSRF 防护
    if bad:
        return _err(bad)
    graph_tpl = conn.get("graph") or ""
    if not graph_tpl:
        return _err("ComfyUI 连接器未配置工作流图（graph）")
    # 把 {{input}} 安全注入到图的字符串值里（json.dumps 后去掉外层引号→得到已转义内容）
    safe = json.dumps(user_input or "", ensure_ascii=False)[1:-1]
    try:
        graph = json.loads(graph_tpl.replace("{{input}}", safe))
    except ValueError as exc:
        return _err(f"工作流图 JSON 解析失败：{exc}")

    headers: Dict[str, str] = {}
    key, cred_err = credential_for(conn.get("cred") or "", base)  # #1 凭据绑定域名
    if cred_err:
        return _err(cred_err)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    # 1) 提交
    try:
        resp = _fetch(
            "POST", f"{base}/prompt",
            json_body={"prompt": graph, "client_id": "cosmac"},
            headers=headers, timeout=30,
        )
    except _TooBig:
        return _err("ComfyUI 提交响应过大，已拒绝")
    except requests.RequestException as exc:
        return _err(f"提交失败：{exc}")
    if not (200 <= resp.status_code < 300):
        return _err(f"ComfyUI 提交返回 {resp.status_code}：{(resp.text or '')[:200]}")
    pid = (resp.json() or {}).get("prompt_id")
    if not pid:
        return _err("ComfyUI 未返回 prompt_id")
    # 2) 轮询
    images = _comfy_poll(base, pid, headers, timeout)
    if images is None:
        return _err(f"等待超时（{timeout}s），工作流可能还在跑")
    if not images:
        return _err("ComfyUI 已完成但没有产出图片")
    # 3) 下载 → 上传 Matrix → 发图
    sent = 0
    for img in images[:COMFY_MAX_IMAGES]:
        data, mime, fname = _comfy_download(base, img, headers)
        if not data:
            continue
        mxc = client.upload_media(data, mime, fname)
        if not mxc:
            continue
        if client.send_image(room_id, mxc, fname, {"mimetype": mime, "size": len(data)}):
            sent += 1
    if sent == 0:
        return _err("生成了图但上传/发送失败")
    return {"ok": True, "status": 200, "output": f"已生成 {sent} 张图并发到本群", "error": ""}


def _comfy_poll(
    base: str, pid: str, headers: Dict[str, str], timeout: int
) -> Optional[List[Dict[str, Any]]]:
    """轮询 /history/{pid} 直到出 outputs；返回图片项列表，超时返回 None。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = _fetch("GET", f"{base}/history/{pid}", headers=headers, timeout=15)
            if r.status_code == 200:
                hist = r.json() or {}
                entry = hist.get(pid)
                if entry and entry.get("outputs"):
                    imgs: List[Dict[str, Any]] = []
                    for node_out in entry["outputs"].values():
                        for im in (node_out or {}).get("images", []) or []:
                            if im.get("filename"):
                                imgs.append(im)
                    return imgs
        except (requests.RequestException, _TooBig):
            # #5：_fetch 的 _TooBig（响应过大/整体超时）也要接住，否则会冒泡成静默失败、
            # 不通知群也不记录。这里当一次失败的轮询，继续等到 deadline 再优雅超时。
            pass
        time.sleep(2)
    return None


def _comfy_download(
    base: str, img: Dict[str, Any], headers: Dict[str, str]
) -> Tuple[Optional[bytes], str, str]:
    """从 /view 下载一张产出图，返回 (bytes, mime, filename)。失败 bytes=None。"""
    fname = img.get("filename") or "output.png"
    params = {
        "filename": fname,
        "subfolder": img.get("subfolder", ""),
        "type": img.get("type", "output"),
    }
    ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else "png"
    mime = _MIME.get(ext, "application/octet-stream")
    try:
        # #5 单图也限大小（16MB），防失控平台返回超大图耗内存
        r = _fetch("GET", f"{base}/view", params=params, headers=headers,
                   timeout=60, max_bytes=_MAX_IMAGE_BYTES)
        if r.status_code == 200 and r.content:
            return r.content, mime, fname
    except (requests.RequestException, _TooBig):
        pass
    return None, mime, fname


# 按 platform 分派到各自适配器
def run_connector(
    conn: Dict[str, Any], user_input: str, *,
    client: Any = None, room_id: str = "", callback_url: str = "",
    callback_token: str = "", timeout: int = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """按连接器的 platform 分派执行。未知平台返回 ok=False。

    client/room_id 仅 ComfyUI 用（把生成的图发回群）；callback_url/callback_token 仅
    webhook 异步用（token 放 payload、不进 URL）。
    """
    platform = (conn.get("platform") or "webhook").lower()
    if platform in ("webhook", "n8n", "make", "custom", ""):
        return run_webhook(
            conn, user_input, callback_url=callback_url,
            callback_token=callback_token, timeout=timeout,
        )
    if platform == "dify":
        return run_dify(conn, user_input, timeout=timeout)
    if platform == "coze":
        return run_coze(conn, user_input, timeout=timeout)
    if platform == "comfyui":
        return run_comfyui(conn, user_input, client=client, room_id=room_id)
    return _err(f"暂不支持的平台「{platform}」（当前 webhook/dify/coze/comfyui）")
