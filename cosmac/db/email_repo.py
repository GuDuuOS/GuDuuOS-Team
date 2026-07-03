"""「邮箱 ↔ 用户名」映射的数据访问（给找回密码 / 邮箱登录按邮箱定位账号用）。

一邮一号（铁律）：一个邮箱**只能**绑一个账号。
  · 注册时先 `set_email` 占位（邮箱空闲才占得到），占位成功再去 Synapse 建号；建号失败用
    `clear_email` 回滚占位。占位放建号**之前**，就把"同邮箱建出多个账号、映射只留最后一个"
    的历史 bug 从根上堵死（那会导致找回密码只能重置其中一个）。
  · `set_email` **绝不改绑**：邮箱已绑到别的账号时抛 `EmailAlreadyBound`，而不是把先注册的
    账号从映射里挤掉——挤掉 = 那个账号从此无法用邮箱登录/找回，属静默数据损坏。
  · 老账号注册时没存这条 → 暂不能用邮箱找回；账号极少，可接受（历史存量，不在此处理）。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from cosmac.db.models import RegisteredEmail


class EmailAlreadyBound(Exception):
    """邮箱已绑到**别的**账号——一邮一号铁律下拒绝改绑。

    ``existing`` 是当前已绑的用户名 localpart，方便调用方判断/日志（比如注册流程据此回
    「该邮箱已注册」）。
    """

    def __init__(self, existing: str) -> None:
        super().__init__(f"email already bound to {existing}")
        self.existing = existing


def set_email(session: Session, *, email: str, username: str) -> bool:
    """登记「邮箱→用户名」映射。邮箱小写存。

    返回值：
      · ``True``  —— 邮箱原本空闲，**新占位成功**（注册流程据此判定"占到了"）。
      · ``False`` —— 邮箱已绑到**同一个** username（幂等：重复写不报错，也不新增行）。
    抛出：
      · ``EmailAlreadyBound`` —— 邮箱已绑到**别的** username（拒绝改绑，护住先注册的账号）。

    并发说明：`email` 列有唯一约束。两个请求同时都没查到、都去 insert 时，第二个会在**提交**
    时撞唯一约束抛 `IntegrityError`——本函数不在这里 catch（这里没有 SAVEPOINT，硬吞会留下
    脏事务）；交给上层 `registration._claim_email` 在 `session_scope` 外层统一按"已被占"处理
    （那层的事务只做这一条 insert，回滚无副作用）。
    """
    email = (email or "").strip().lower()
    username = (username or "").strip().lower()
    if not email or not username:
        return False
    row = session.execute(
        select(RegisteredEmail).where(RegisteredEmail.email == email)
    ).scalar_one_or_none()
    if row is not None:
        if row.username == username:
            return False                       # 幂等：本就绑这个账号
        raise EmailAlreadyBound(row.username)   # 一邮一号：绝不改绑到别的账号
    session.add(RegisteredEmail(email=email, username=username))
    return True


def clear_email(session: Session, *, email: str, username: str = "") -> bool:
    """删除「邮箱→用户名」映射。返回是否真的删了一行。

    用途：① 注册"占位成功但建号失败"时回滚占位；② 解绑邮箱（管理员/本人操作）。
    ``username`` 给了则**只在当前绑定确实是它时才删**（防止误删掉别人的映射——回滚只该回滚
    自己刚占的那条）；不给（空串）则无条件删该邮箱的映射。
    """
    email = (email or "").strip().lower()
    username = (username or "").strip().lower()
    if not email:
        return False
    row = session.execute(
        select(RegisteredEmail).where(RegisteredEmail.email == email)
    ).scalar_one_or_none()
    if row is None:
        return False
    if username and row.username != username:
        return False                            # 绑的是别人的账号，不动
    session.delete(row)
    return True


def get_email_by_username(session: Session, username: str) -> Optional[str]:
    """按用户名 localpart 反查邮箱（登录二次验证给绑定邮箱发码用）。没有返回 None。

    注：username 列没建索引（表小、注册时才写），全表扫描在当前量级可忽略；上量再补索引。
    """
    username = (username or "").strip().lower()
    if not username:
        return None
    row = session.execute(
        select(RegisteredEmail).where(RegisteredEmail.username == username)
    ).scalar_one_or_none()
    return row.email if row else None


def get_username_by_email(session: Session, email: str) -> Optional[str]:
    """按邮箱反查用户名 localpart；没有返回 None。"""
    email = (email or "").strip().lower()
    if not email:
        return None
    row = session.execute(
        select(RegisteredEmail).where(RegisteredEmail.email == email)
    ).scalar_one_or_none()
    return row.username if row else None
