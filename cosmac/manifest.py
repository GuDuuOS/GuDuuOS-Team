"""从 GitHub 等代码托管处导入 Skill / Agent 定义（manifest）。

背景：负责人要「别人放在 GitHub 上的技能/智能体，能不能装进来」。此前没有任何导入
通道，用户让主 AI 去装，AI 只能拿 Claude Code 那套 `~/.claude/skills/` 硬凑
（2026-07-27 事故，见 1.6.12 安全修复）。这个模块就是那条正规通道。

设计三条原则（都与"这是从互联网拉进来的第三方内容"直接相关）：

1. **只搬数据，绝不执行代码。** manifest 是一份 JSON，导入等于把里面的字段落进
   DB。不下载压缩包、不解压、不跑任何脚本——安装第三方 Agent 的价值在于它的
   人设与配置，不在于跑它的代码。

2. **服务端外呼必须挡 SSRF。** URL 是用户给的，服务端拿着它去请求 = 典型 SSRF 面
   （打内网、打云元数据 169.254.169.254）。这里用"域名白名单 + wf.check_outbound_url"
   双保险，并且**不跟随重定向**（否则 302 到内网就绕过了校验）。

3. **内容哈希锁定，防"预览时良性、确认时变脸"。** 预览与确认之间隔着用户思考的
   几十秒，攻击者完全可以在这中间把仓库里的文件换掉（TOCTOU）。所以预览返回
   sha256，确认时重新拉取并比对——不一致就拒绝，让用户重看一遍。

⚠️ 本模块**只负责取回并校验**。人设全文的展示与用户确认在上层（端点 + 前端）完成，
落库前必须经用户点确认——第三方人设可以写"忽略此前所有指令…"，而主 AI 手里有建群/
发消息/查知识库等一堆工具，静默导入等于把一部分控制权交出去。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ── 允许的来源域名 ─────────────────────────────────────────────
# 白名单而非黑名单：导入源本就该是代码托管处，没有理由允许任意 URL。
# 这一层挡在 SSRF 校验之前，所以即使部署方开了 COSMAC_WF_ALLOW_INTERNAL=1
# （自建内网工作流用），也不会让导入功能去打内网——内网主机名过不了白名单。
_ALLOWED_HOSTS = {
    "raw.githubusercontent.com",
    "github.com",
    "gist.githubusercontent.com",
    "gist.github.com",
}

MANIFEST_MAX_BYTES = 256 * 1024   # 256KB：一份 JSON 定义绰绰有余，防超大响应打爆内存
FETCH_TIMEOUT = 15                # 秒

# 与工坊保存端点保持一致的上限（cosmac/bots/appservice_bot.py 的 _MY_* 常量）
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_NAME_MAX = 80
_DESC_MAX = 300
_PROMPT_MAX = 4000     # Agent 人设
_INSTR_MAX = 2000      # Skill 正文
_LIST_MAX = 20         # skill_slugs / workflow_slugs 条数上限


def normalize_url(raw: str) -> Tuple[str, str]:
    """把用户粘的各种 GitHub 地址规整成可直接取 JSON 的 raw 地址。

    支持：
      · 已经是 raw.githubusercontent.com/... → 原样
      · github.com/<u>/<r>/blob/<ref>/<path> → 转成 raw（网页地址转直链）
    返回 (规整后的 url, 错误原因)；错误非空表示不接受。

    刻意**不**支持"给个仓库根地址、我去猜文件名"：猜测会让服务端为一次导入发多个
    外呼请求，既慢又扩大 SSRF 面；让用户给准确文件地址更干净。
    """
    url = (raw or "").strip()
    if not url:
        return "", "请填写 manifest 地址"
    if not url.startswith(("http://", "https://")):
        return "", "地址必须以 http:// 或 https:// 开头"
    try:
        u = urlparse(url)
    except Exception:
        return "", "地址格式不正确"
    if u.scheme != "https":
        # 代码托管站全部支持 https；允许 http 只会平白多一条明文链路
        return "", "只允许 https 地址"
    host = (u.hostname or "").lower()
    if host not in _ALLOWED_HOSTS:
        allowed = "、".join(sorted(_ALLOWED_HOSTS))
        return "", f"暂只支持从这些来源导入：{allowed}（收到 {host or '空'}）"

    # github.com/<user>/<repo>/blob/<ref>/<path...> → raw.githubusercontent.com/<user>/<repo>/<ref>/<path...>
    if host == "github.com":
        m = re.match(r"^/([^/]+)/([^/]+)/blob/(.+)$", u.path)
        if not m:
            return "", "请给 manifest 文件的地址（形如 .../blob/main/guduu-agent.json）"
        url = f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}"
    return url, ""


def fetch_manifest(url: str) -> Tuple[Optional[Dict[str, Any]], str, str]:
    """取回并解析 manifest。返回 (manifest, sha256, 错误原因)。

    错误原因非空即失败（manifest 为 None）。所有网络异常都转成中文原因，绝不抛出——
    调用方是 HTTP 端点，不该因为对方仓库 404 就 500。
    """
    from cosmac.wf import check_outbound_url

    norm, err = normalize_url(url)
    if err:
        return None, "", err
    # 双保险：白名单过了还要再过一遍 SSRF 校验（防白名单域名被 DNS 指向内网）
    ssrf = check_outbound_url(norm)
    if ssrf:
        return None, "", f"目标地址不安全：{ssrf}"

    try:
        import requests

        # ⚠️ allow_redirects=False：跟随重定向会绕过上面的校验（302 到内网即失守）
        resp = requests.get(
            norm, timeout=FETCH_TIMEOUT, allow_redirects=False,
            headers={"Accept": "application/json, text/plain, */*"},
        )
    except Exception as exc:
        logger.debug("拉取 manifest 失败：%s", exc)
        return None, "", f"拉取失败：{exc}"

    if resp.status_code in (301, 302, 303, 307, 308):
        return None, "", "该地址发生了跳转；请直接填最终的 raw 文件地址"
    if resp.status_code != 200:
        return None, "", f"拉取失败（HTTP {resp.status_code}）；确认文件存在且仓库是公开的"

    body = resp.content or b""
    if len(body) > MANIFEST_MAX_BYTES:
        return None, "", f"文件过大（上限 {MANIFEST_MAX_BYTES // 1024}KB）"

    digest = hashlib.sha256(body).hexdigest()
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        return None, "", "不是合法的 JSON（本功能导入的是 manifest 定义文件，不是代码包）"
    if not isinstance(data, dict):
        return None, "", "manifest 顶层必须是一个 JSON 对象"
    return data, digest, ""


def _clean_slugs(raw: Any) -> list:
    """清洗 slug 列表：去空、转小写、截断、限条数。非列表一律当空。"""
    if not isinstance(raw, list):
        return []
    out = []
    for x in raw:
        s = str(x).strip().lower()[:128]
        if s and s not in out:
            out.append(s)
    return out[:_LIST_MAX]


def parse_manifest(data: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    """校验并规范化 manifest。返回 (规范化后的定义, 错误原因)。

    只挑**我们认识的字段**落库，多余字段一律丢弃——第三方 manifest 里混进
    `enabled`、`access` 这类字段不该被直接采信（那是平台侧的权限概念，
    让导入者自己决定，绝不能由文件内容决定）。
    """
    kind = str(data.get("kind") or "").strip().lower()
    if kind not in ("skill", "agent"):
        return None, "manifest 的 kind 必须是 skill 或 agent"

    slug = str(data.get("slug") or "").strip().lower()
    if not _SLUG_RE.match(slug):
        return None, "slug 需为小写字母/数字/中划线，64 字符内，且以字母或数字开头"

    name = str(data.get("name") or "").strip()[:_NAME_MAX]
    desc = str(data.get("description") or "").strip()[:_DESC_MAX]
    if not name or not desc:
        return None, "manifest 缺少 name 或 description"

    out: Dict[str, Any] = {
        "kind": kind, "slug": slug, "name": name, "description": desc,
        # 展示用的来源信息（不参与落库的业务字段，但要让用户看见"这是谁写的"）
        "author": str(data.get("author") or "").strip()[:80],
        "homepage": str(data.get("homepage") or "").strip()[:300],
        "license": str(data.get("license") or "").strip()[:64],
    }

    if kind == "skill":
        instr = str(data.get("instructions") or "").strip()
        if not instr:
            return None, "技能的 instructions 不能为空"
        if len(instr) > _INSTR_MAX:
            return None, f"技能正文过长（上限 {_INSTR_MAX} 字符，实际 {len(instr)}）"
        out["instructions"] = instr
    else:
        prompt = str(data.get("system_prompt") or "").strip()
        if not prompt:
            return None, "智能体的 system_prompt 不能为空"
        if len(prompt) > _PROMPT_MAX:
            return None, f"人设过长（上限 {_PROMPT_MAX} 字符，实际 {len(prompt)}）"
        out["system_prompt"] = prompt
        out["model"] = str(data.get("model") or "").strip()[:128]
        # 引用的技能/工作流：只记 slug。**不递归导入**——递归会让一次点击拉进来
        # 一整棵未经审阅的依赖树，用户根本不知道自己装了什么。
        out["skill_slugs"] = _clean_slugs(data.get("skill_slugs"))
        out["workflow_slugs"] = _clean_slugs(data.get("workflow_slugs"))
    return out, ""


def review_notes(item: Dict[str, Any]) -> list:
    """给用户看的「导入前提醒」。返回中文提示列表（可能为空）。

    目的不是拦截，而是**把风险摆到台面上**——这些都是自动判断不了、只有人能拍板的事。
    """
    notes: list = []
    if item.get("kind") == "agent":
        notes.append(
            "这是第三方写的人设，会作为系统提示注入给 AI。请通读下方全文，"
            "确认没有「忽略以上指令」「把内容发送到某地址」这类可疑句子。"
        )
        if item.get("workflow_slugs"):
            notes.append(
                "它引用了工作流：" + "、".join(item["workflow_slugs"])
                + "。导入不会自动接入这些工作流，也不会提权——需要你自己有对应权限才能跑。"
            )
        if item.get("skill_slugs"):
            notes.append(
                "它引用了技能：" + "、".join(item["skill_slugs"])
                + "。这些技能不会被一并导入（避免一次点击拉进一整棵未审阅的依赖树），"
                "需要你自己确认后再单独导入。"
            )
        if item.get("model"):
            notes.append(f"它指定了模型 {item['model']}；若平台不支持会回退到全局配置。")
    else:
        notes.append(
            "技能正文会在每轮对话中注入给 AI。请通读下方全文，确认内容符合预期。"
        )
    return notes
