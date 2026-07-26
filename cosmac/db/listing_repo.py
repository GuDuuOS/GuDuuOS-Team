"""创作者商城上架/收益的数据访问（模块4 Token 经济 P2）。

只管 cosmac_market_listing / cosmac_creator_earning 两张表的读写；分账业务
（扣用户→创作者入账→记流水）在 cosmac/wallet.py 的 charge_agent_use 编排。
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from cosmac.db.models import CreatorEarning, MarketListing


class SlugTaken(Exception):
    """同一创作者已用该 slug 上架过**另一类**资源（见 MarketListing 唯一键说明）。"""


def upsert_listing(
    session: Session,
    *,
    creator: str,
    agent_slug: str,
    name: str,
    description: str,
    price_tokens: int,
    kind: str = "agent",
) -> Optional[MarketListing]:
    """上架/更新一条 listing（同 (creator, agent_slug) 幂等更新）。

    **P3 起任何上架/更新都进 pending 待审**（负责人定稿：任何更新都重审）——原在售的
    改价/改文案也立即变待审（待审期间下架，不再可购可用），审核通过才恢复在售。
    被管理员 banned 的条目创作者不可经此复活/修改（返回 None，调用方转提示）。
    同 slug 已被自己**另一类**资源占用时抛 :class:`SlugTaken`（唯一键不含 kind）。
    """
    row = session.execute(
        select(MarketListing).where(
            MarketListing.creator == creator,
            MarketListing.agent_slug == agent_slug,
        )
    ).scalar_one_or_none()
    if row is not None and str(row.kind or "agent") != kind:
        raise SlugTaken(str(row.kind or "agent"))
    if row is not None and row.status == "banned":
        return None  # 管理员强制下架的不允许创作者自行复活
    if row is None:
        row = MarketListing(creator=creator, agent_slug=agent_slug, kind=kind)
        session.add(row)
    row.kind = kind
    row.name = name
    row.description = description
    row.price_tokens = max(0, int(price_tokens))
    row.status = "pending"      # 任何上架/更新一律待审
    row.review_reason = ""
    session.flush()
    return row


def set_status(
    session: Session, listing_id: int, status: str, *, creator: str = ""
) -> bool:
    """改上架状态。creator 非空=创作者本人操作：只能把自己的**下架(off)**——重新上架
    必须走 upsert 进待审（审核通过才能在售），不能自置 on。空=管理员操作（banned/恢复）。
    成功返回 True。"""
    row = session.get(MarketListing, int(listing_id))
    if row is None:
        return False
    if creator:
        if row.creator != creator or row.status == "banned":
            return False
        if status != "off":
            return False  # 创作者只能下架；上架必经审核
    row.status = status
    session.flush()
    return True


def review_listing(
    session: Session, listing_id: int, *, approve: bool, reason: str = ""
) -> Optional[MarketListing]:
    """管理员审核上架：approve=True → on（在售）；False → rejected（记原因）。

    只审 pending 的（防止把在售/banned 的误操作）；状态不符返回 None。
    """
    row = session.get(MarketListing, int(listing_id))
    if row is None or row.status != "pending":
        return None
    row.status = "on" if approve else "rejected"
    row.review_reason = "" if approve else (reason or "")[:500]
    session.flush()
    return row


def list_pending(session: Session, *, limit: int = 200) -> List[MarketListing]:
    """全部待审 listing（管理员后台，旧→新：先来先审）。"""
    return list(session.execute(
        select(MarketListing).where(MarketListing.status == "pending")
        .order_by(MarketListing.id.asc()).limit(max(1, min(int(limit), 500)))
    ).scalars())


def get_listing(session: Session, listing_id: int) -> Optional[MarketListing]:
    """按 id 取一条 listing。"""
    return session.get(MarketListing, int(listing_id))


def list_on_sale(session: Session, *, kind: str = "") -> List[MarketListing]:
    """全部在售（status=on）——商城货架用，新→旧。kind 非空则只列该类。"""
    stmt = select(MarketListing).where(MarketListing.status == "on")
    if kind:
        stmt = stmt.where(MarketListing.kind == kind)
    return list(session.execute(stmt.order_by(MarketListing.id.desc())).scalars())


def has_purchased(session: Session, buyer: str, listing_id: int) -> bool:
    """该买家是否**曾经为这条 listing 付过费**（买断制的"已购"判据）。

    用收益流水反查，不另建购买表：买断只在首次获取时扣款，之后移除再获取都免费
    （已买断=永久拥有；否则用户移除一下就要重复付钱）。
    """
    row = session.execute(
        select(CreatorEarning.id).where(
            CreatorEarning.buyer == buyer,
            CreatorEarning.listing_id == int(listing_id),
        ).limit(1)
    ).first()
    return row is not None


def list_by_creator(session: Session, creator: str) -> List[MarketListing]:
    """某创作者的全部上架（含 off/banned，给工坊「我的上架」回显）。"""
    return list(session.execute(
        select(MarketListing).where(MarketListing.creator == creator)
        .order_by(MarketListing.id.desc())
    ).scalars())


def record_earning(
    session: Session,
    *,
    listing: MarketListing,
    buyer: str,
    gross: int,
    fee: int,
    net: int,
    room_id: str = "",
) -> CreatorEarning:
    """记一笔分成流水，并同步累计 listing.uses/earned（同一事务）。"""
    row = CreatorEarning(
        listing_id=listing.id, creator=listing.creator, buyer=buyer,
        agent_slug=listing.agent_slug, gross=int(gross), fee=int(fee),
        net=int(net), room_id=room_id or "",
    )
    session.add(row)
    # 原子自增累计（不读改写）
    session.execute(
        update(MarketListing).where(MarketListing.id == listing.id)
        .values(uses=MarketListing.uses + 1, earned=MarketListing.earned + int(net))
    )
    session.flush()
    return row


def list_earnings(
    session: Session, creator: str, *, limit: int = 50, offset: int = 0
) -> List[CreatorEarning]:
    """某创作者的分成明细（新→旧分页）。"""
    lim = max(1, min(int(limit), 200))
    return list(session.execute(
        select(CreatorEarning).where(CreatorEarning.creator == creator)
        .order_by(CreatorEarning.id.desc()).limit(lim).offset(max(0, int(offset)))
    ).scalars())


def earnings_summary(session: Session, creator: str) -> dict:
    """某创作者收益汇总：{total_net, total_gross, count}。"""
    row = session.execute(
        select(
            func.coalesce(func.sum(CreatorEarning.net), 0),
            func.coalesce(func.sum(CreatorEarning.gross), 0),
            func.count(CreatorEarning.id),
        ).where(CreatorEarning.creator == creator)
    ).one()
    return {"total_net": int(row[0]), "total_gross": int(row[1]), "count": int(row[2])}
