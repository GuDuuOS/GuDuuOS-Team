"""CosMac 发行版 —— 全新实例引导脚本（在 bot 容器内运行）。

install.sh 在全栈起来后调用：``docker compose exec -T bot python /app/distro/bootstrap.py``

职责（全部幂等，重跑无害）：
    1. 注册主 AI 账号 @guduu:<域名>（appservice 专用注册通道）并设置显示名；
    2. 用 registration_shared_secret 注册初始管理员 admin（Synapse 服务器管理员）；
    3. 以 bot 身份创建控制室 #cosmac-ctrl:<域名>（bot 建房 = power 100，
       与生产控制室权限模型一致），并邀请管理员（power 50）。

为什么控制室必须在这里建：bot 运行时只"解析别名+读 state"，从不自己建房
（见 appservice_bot 的 _control_room 缓存逻辑）；全新实例没有这个房间，
后台 AI 配置/技能/门控等所有「控制室 state event」体系都会失灵。

配置全部来自容器环境变量（compose 注入，与 bot 正常运行同一套）。
只依赖 requests（bot 镜像必带），不 import cosmac 包——引导脚本要能在
业务代码有 bug 时也跑得动，越独立越好。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sys
import time

import requests


def _env(suffix: str, default: str = "") -> str:
    """读环境变量：优先 COSMAC_ 前缀，回退 GUDUU_（与 cosmac/config.py 同规则）。"""
    return (
        os.environ.get(f"COSMAC_{suffix}")
        or os.environ.get(f"GUDUU_{suffix}")
        or default
    )


HS = _env("HS_URL", "http://synapse:8008").rstrip("/")
SERVER_NAME = _env("SERVER_NAME")
BOT_USER_ID = _env("BOT_USER_ID", f"@guduu:{SERVER_NAME}")
AS_TOKEN = _env("AS_TOKEN")
REG_SECRET = _env("REGISTRATION_SHARED_SECRET")
ADMIN_USER = _env("ADMIN_USER", "admin")
ADMIN_EMAIL = _env("ADMIN_EMAIL")
BOT_DISPLAYNAME = _env("BOT_DISPLAYNAME", "CosMac Star")

CTRL_ALIAS = f"#cosmac-ctrl:{SERVER_NAME}"
ADMIN_MXID = f"@{ADMIN_USER}:{SERVER_NAME}"


def wait_synapse(timeout_s: int = 120) -> None:
    """等 Synapse 的 client API 可用（install.sh 已等过一轮，这里兜底）。"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = requests.get(f"{HS}/_matrix/client/versions", timeout=5)
            if r.ok:
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    raise SystemExit("Synapse 未就绪，引导中止。")


def ensure_bot_user() -> None:
    """注册主 AI 账号（appservice 注册通道）。已存在则跳过。

    虽然 Synapse 会在 appservice 首次代理操作时懒注册 sender，但显式注册
    可以确保 profiles 表有行——生产曾因 @guduu 无 profile 行导致改显示名 500
    （见 memory bot-displayname-500-fix），发行版从第一天就把这个坑填掉。
    """
    r = requests.post(
        f"{HS}/_matrix/client/v3/register",
        json={"type": "m.login.application_service", "username": "guduu"},
        headers={"Authorization": f"Bearer {AS_TOKEN}"},
        timeout=10,
    )
    if r.ok:
        print(f"[bootstrap] 已注册主 AI 账号 {BOT_USER_ID}")
    elif r.status_code == 400 and r.json().get("errcode") == "M_USER_IN_USE":
        print(f"[bootstrap] 主 AI 账号已存在，跳过")
    else:
        raise SystemExit(f"注册主 AI 账号失败：HTTP {r.status_code} {r.text[:200]}")

    # 设置显示名（品牌名；OEM 换皮后可在后台改）。失败不致命，警告即可。
    r = requests.put(
        f"{HS}/_matrix/client/v3/profile/{BOT_USER_ID}/displayname",
        json={"displayname": BOT_DISPLAYNAME},
        headers={"Authorization": f"Bearer {AS_TOKEN}"},
        timeout=10,
    )
    if not r.ok:
        print(f"[bootstrap][警告] 设置主 AI 显示名失败：{r.status_code}")


def ensure_admin() -> str | None:
    """用共享密钥注册初始管理员（Synapse 服务器管理员）。

    返回明文初始密码（仅本次生成时；已存在返回 None）。
    流程是 Synapse 标准的 shared-secret 注册：取 nonce → HMAC-SHA1 签名 → 注册。
    """
    r = requests.get(f"{HS}/_synapse/admin/v1/register", timeout=10)
    r.raise_for_status()
    nonce = r.json()["nonce"]

    password = secrets.token_urlsafe(12)
    mac = hmac.new(REG_SECRET.encode(), digestmod=hashlib.sha1)
    # 签名格式（协议规定）：nonce \0 user \0 password \0 admin
    mac.update(nonce.encode())
    mac.update(b"\x00")
    mac.update(ADMIN_USER.encode())
    mac.update(b"\x00")
    mac.update(password.encode())
    mac.update(b"\x00admin")

    r = requests.post(
        f"{HS}/_synapse/admin/v1/register",
        json={
            "nonce": nonce,
            "username": ADMIN_USER,
            "password": password,
            "admin": True,
            "mac": mac.hexdigest(),
        },
        timeout=10,
    )
    if r.ok:
        print(f"[bootstrap] 已创建管理员 {ADMIN_MXID}")
        return password
    if r.status_code == 400 and r.json().get("errcode") == "M_USER_IN_USE":
        print(f"[bootstrap] 管理员 {ADMIN_MXID} 已存在，跳过（密码不变）")
        return None
    raise SystemExit(f"创建管理员失败：HTTP {r.status_code} {r.text[:200]}")


def ensure_control_room() -> None:
    """以 bot 身份创建控制室并邀请管理员。已存在（别名可解析）则跳过。

    bot 是建房者 → 天然 power 100；管理员给 50 —— 与生产控制室权限模型一致
    （50 够写 state event 配 AI/技能/门控；踢人/降权等 100 级操作归 bot）。
    """
    r = requests.get(
        f"{HS}/_matrix/client/v3/directory/room/{requests.utils.quote(CTRL_ALIAS)}",
        headers={"Authorization": f"Bearer {AS_TOKEN}"},
        timeout=10,
    )
    if r.ok:
        print(f"[bootstrap] 控制室 {CTRL_ALIAS} 已存在，跳过")
        return

    r = requests.post(
        f"{HS}/_matrix/client/v3/createRoom",
        json={
            "room_alias_name": "cosmac-ctrl",
            "name": "CosMac 控制室",
            "topic": "实例控制室：AI 配置/技能/门控等 state event 存这里。仅管理员可见。",
            "preset": "private_chat",
            "invite": [ADMIN_MXID],
            "power_level_content_override": {
                "users": {BOT_USER_ID: 100, ADMIN_MXID: 50},
                "users_default": 0,
            },
        },
        headers={"Authorization": f"Bearer {AS_TOKEN}"},
        timeout=15,
    )
    if not r.ok:
        raise SystemExit(f"创建控制室失败：HTTP {r.status_code} {r.text[:200]}")
    print(f"[bootstrap] 已创建控制室 {CTRL_ALIAS}（room_id={r.json().get('room_id')}）")


def main() -> None:
    for name, val in (("SERVER_NAME", SERVER_NAME), ("AS_TOKEN", AS_TOKEN),
                      ("REGISTRATION_SHARED_SECRET", REG_SECRET)):
        if not val:
            raise SystemExit(f"缺少环境变量 COSMAC_{name}，无法引导。")

    wait_synapse()
    ensure_bot_user()
    admin_password = ensure_admin()
    if admin_password:
        # 初始密码只显示这一次。⚠️ 必须在后续步骤**之前**打印——首次 VM 实测
        # 踩坑：打印排在建控制室之后，建房一失败密码就永远丢了。
        print("=" * 46)
        print(f"  初始管理员账号：{ADMIN_USER}")
        print(f"  初始管理员密码：{admin_password}")
        print("  （首次登录后请立即在客户端修改密码）")
        print("=" * 46)
    ensure_control_room()

    print("[bootstrap] 引导完成 ✅")


if __name__ == "__main__":
    sys.exit(main())
