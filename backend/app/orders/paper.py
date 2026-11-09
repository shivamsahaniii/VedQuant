"""Paper Broker / order manager agent (A.7) and square-off (A.8).

Fills are modelled on the real market, not on the plan:
  * entry (MARKET): live price plus slippage against you, rounded to the tick against you,
  * stop (SL-M): triggers when the live price touches the stop and fills at the LIVE price minus
    slippage, so a gap through the stop costs more than the plan said (as it does for real),
  * target (LIMIT): fills at the target price once the live price reaches it,
  * stop and target cancel each other (OCO); square-off closes at market.
Every order has an idempotent `order_ref` derived from the signal, so a retry never doubles a trade.
P&L is net of the real charges (app/risk/charges.py).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.nse import ist, round_to_tick, tick_size
from app.models import Order, Trade
from app.risk.charges import round_trip

SLIPPAGE_BPS = Decimal("5")  # 0.05 % per market fill (paper assumption)


def market_fill(side: str, ltp: Decimal, tick: Decimal, slippage_bps: Decimal = SLIPPAGE_BPS):
    """Price a market order really gets: worse than the last price by the slippage."""
    f = slippage_bps / Decimal(10_000)
    if side == "buy":
        return round_to_tick(ltp * (1 + f), tick, up=True)
    return round_to_tick(ltp * (1 - f), tick, up=False)


def _exit_side(side: str) -> str:
    return "sell" if side == "buy" else "buy"


@dataclass(frozen=True)
class OpenRequest:
    user_id: uuid.UUID
    strategy_id: uuid.UUID | None
    signal_id: uuid.UUID | None
    section: str
    exchange: str
    symbol: str
    side: str
    qty: int
    stop: Decimal
    target: Decimal
    ref: str  # idempotency seed, e.g. "<strategy>:<trigger_key>"
    tick: Decimal | None = None


async def open_trade(db: AsyncSession, req: OpenRequest, ltp: Decimal, now: datetime) -> Trade:
    """Entry at market, then a resting stop (SL-M) and target (LIMIT). Idempotent on `req.ref`."""
    existing = await db.scalar(select(Order).where(Order.order_ref == f"{req.ref}:entry"))
    if existing is not None:
        return await db.get_one(Trade, existing.trade_id)
    tick = req.tick or tick_size(ltp)
    fill = market_fill(req.side, ltp, tick)
    trade = Trade(
        user_id=req.user_id,
        strategy_id=req.strategy_id,
        signal_id=req.signal_id,
        mode="paper",
        section=req.section,
        exchange=req.exchange,
        symbol=req.symbol,
        side=req.side,
        qty=req.qty,
        entry_price=fill,
        entry_at=now,
        stop=req.stop,
        target=req.target,
        tick=tick,
        max_loss=abs(fill - req.stop) * req.qty,
        status="open",
    )
    db.add(trade)
    await db.flush()
    out = _exit_side(req.side)
    common = {
        "user_id": req.user_id,
        "trade_id": trade.id,
        "mode": "paper",
        "symbol": req.symbol,
        "qty": req.qty,
    }
    db.add_all(
        [
            Order(
                order_ref=f"{req.ref}:entry",
                role="entry",
                side=req.side,
                order_type="MARKET",
                status="filled",
                avg_price=fill,
                filled_at=now,
                **common,
            ),
            Order(
                order_ref=f"{req.ref}:stop",
                role="stop",
                side=out,
                order_type="SL-M",
                trigger_price=req.stop,
                status="open",
                **common,
            ),
            Order(
                order_ref=f"{req.ref}:target",
                role="target",
                side=out,
                order_type="LIMIT",
                price=req.target,
                status="open",
                **common,
            ),
        ]
    )
    await db.flush()
    return trade


async def close_trade(
    db: AsyncSession, trade: Trade, price: Decimal, now: datetime, reason: str
) -> Trade:
    """Close at `price`, settle the legs (OCO), and book gross P&L, charges and net P&L."""
    sign = 1 if trade.side == "buy" else -1
    gross = (price - trade.entry_price) * trade.qty * sign
    buy, sell = (trade.entry_price, price) if trade.side == "buy" else (price, trade.entry_price)
    charges = round_trip(buy, sell, trade.qty, "intraday").total
    trade.status, trade.exit_price, trade.exit_at, trade.exit_reason = "closed", price, now, reason
    trade.gross_pnl, trade.charges, trade.net_pnl = gross, charges, gross - charges

    legs = (
        await db.scalars(select(Order).where(Order.trade_id == trade.id, Order.status == "open"))
    ).all()
    for leg in legs:
        if leg.role == reason:  # the stop or target that fired
            leg.status, leg.avg_price, leg.filled_at = "filled", price, now
        else:
            leg.status = "cancelled"
    if reason not in ("stop", "target"):
        ref = legs[0].order_ref.rsplit(":", 1)[0] if legs else str(trade.id)
        db.add(
            Order(
                order_ref=f"{ref}:exit",
                user_id=trade.user_id,
                trade_id=trade.id,
                mode=trade.mode,
                role="exit",
                side=_exit_side(trade.side),
                symbol=trade.symbol,
                qty=trade.qty,
                order_type="MARKET",
                status="filled",
                avg_price=price,
                filled_at=now,
            )
        )
    await db.flush()
    return trade


def exit_hit(trade: Trade, ltp: Decimal) -> tuple[str, Decimal] | None:
    """Does this live price trigger the stop or the target? Stop is checked first."""
    tick = trade.tick
    if trade.side == "buy":
        if ltp <= trade.stop:
            return "stop", market_fill("sell", ltp, tick)
        if ltp >= trade.target:
            return "target", trade.target
    else:
        if ltp >= trade.stop:
            return "stop", market_fill("buy", ltp, tick)
        if ltp <= trade.target:
            return "target", trade.target
    return None


async def on_price(
    db: AsyncSession, exchange: str, symbol: str, ltp: Decimal, now: datetime
) -> list[Trade]:
    """Every live price: close any open paper trade whose stop or target it reaches."""
    trades = (
        await db.scalars(
            select(Trade).where(
                Trade.status == "open",
                Trade.mode == "paper",
                Trade.exchange == exchange,
                Trade.symbol == symbol,
            )
        )
    ).all()
    closed = []
    for t in trades:
        hit = exit_hit(t, ltp)
        if hit:
            closed.append(await close_trade(db, t, hit[1], now, hit[0]))
    return closed


async def square_off(
    db: AsyncSession,
    prices: dict[tuple[str, str], Decimal],
    now: datetime,
    *,
    user_id: uuid.UUID | None = None,
    reason: str = "square_off",
    intraday_only: bool = True,
) -> list[Trade]:
    """Close open paper trades at market: intraday ones at 15:15 IST, or all of a user's
    positions for the kill switch (`intraday_only=False`)."""
    q = select(Trade).where(Trade.status == "open", Trade.mode == "paper")
    if intraday_only:
        q = q.where(Trade.section == "intraday")
    if user_id is not None:
        q = q.where(Trade.user_id == user_id)
    closed = []
    for t in (await db.scalars(q)).all():
        ltp = prices.get((t.exchange, t.symbol))
        if ltp is None:
            continue  # no price: try again on the next pass rather than guess one
        fill = market_fill(_exit_side(t.side), ltp, t.tick)
        closed.append(await close_trade(db, t, fill, now, reason))
    return closed


@dataclass(frozen=True)
class DayStats:
    open_positions: int
    open_symbols: frozenset[str]
    committed_risk: Decimal
    trades_today: int
    realised_today: Decimal
    realised_total: Decimal
    open_value: Decimal


async def day_stats(db: AsyncSession, user_id: uuid.UUID, section: str, now: datetime) -> DayStats:
    rows = (
        await db.scalars(
            select(Trade).where(
                Trade.user_id == user_id, Trade.section == section, Trade.mode == "paper"
            )
        )
    ).all()
    today = ist(now).date()
    open_ = [t for t in rows if t.status == "open"]
    closed = [t for t in rows if t.status == "closed"]
    return DayStats(
        open_positions=len(open_),
        open_symbols=frozenset(t.symbol for t in open_),
        committed_risk=sum((t.max_loss for t in open_), Decimal(0)),
        trades_today=sum(1 for t in rows if ist(t.entry_at).date() == today),
        realised_today=sum(
            (
                t.net_pnl or Decimal(0)
                for t in closed
                if t.exit_at and ist(t.exit_at).date() == today
            ),
            Decimal(0),
        ),
        realised_total=sum((t.net_pnl or Decimal(0) for t in closed), Decimal(0)),
        open_value=sum((t.entry_price * t.qty for t in open_), Decimal(0)),
    )
