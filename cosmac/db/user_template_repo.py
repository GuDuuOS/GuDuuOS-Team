# -*- coding: utf-8 -*-
"""「用户 ↔ 入驻模板」映射的数据访问(资源级权限的"指定模板可用"据此判定)。

写:注册引导完成时 bot 端点调 set_user_template(就地覆盖,幂等)。
读:bot 判定某技能/智能体(access=tpl:...)对某用户是否可用时调 get_user_template。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from cosmac.db.models import UserTemplate


def set_user_template(session: Session, *, user_id: str, template_slug: str) -> None:
    """记录(或覆盖)某用户选择的入驻模板。user_id 必须是完整 @user:domain。"""
    row = session.execute(
        select(UserTemplate).where(UserTemplate.user_id == user_id)
    ).scalar_one_or_none()
    if row is None:
        session.add(UserTemplate(user_id=user_id, template_slug=template_slug))
    else:
        row.template_slug = template_slug


def get_user_template(session: Session, user_id: str) -> Optional[str]:
    """查某用户选的模板 slug;没选过返回 None。"""
    row = session.execute(
        select(UserTemplate).where(UserTemplate.user_id == user_id)
    ).scalar_one_or_none()
    return row.template_slug if row else None
