"""The agent chain, run on every closed candle for every user's running strategies.

  Scanner (setups) -> Entry Timer -> Exit Planner -> Odds -> Risk + Sizer -> Paper Broker

Every setup a strategy finds becomes one `signals` row with its outcome and the reason:
  skipped (entry timer), refused (exit planner), blocked (risk), suggested (passed, mode=suggest),
  taken (passed, mode=auto, a paper trade was opened).
Each user's strategies are isolated: their own limits, their own trades, their own signals.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import record_event
from app.engine.entry import EntryParams, decide_entry, trigger_key
from app.engine.exit_plan import ExitParams, ExitPlan, Refused, plan_exit
from app.engine.nse import TradingCalendar, ist, to_dec
from app.engine.odds import NoOdds, build_pool, simulate
from app.engine.setups import ScanHit, scan
from app.models import Candle, Signal, Strategy
from app.orders.paper import OpenRequest, day_stats, open_trade
from app.risk.engine import AccountState, Approved, RiskLimits, check_entry

TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
CANDLE_LOOKBACK = timedelta(days=5)
ODDS_LOOKBACK = timedelta(days=45)
SIGNALS_CHANNEL = "vq:signals"


@dataclass
class Mood:
    trend: str
    strength: str
    volatility: str
    bias: str


def mood_from(raw: str | None) -> tuple[Mood | None, dict[str, Any]]:
    if not raw:
        return None, {}
    c = json.loads(raw)
    return Mood(c["trend"], c["strength"], c["volatility"], c["bias"]), {
        "summary": c.get("summary"),
        "bias": c.get("bias"),
        "warming_up": c.get("warming_up"),
    }


async def load_candles(
    db: AsyncSession, exchange: str, symbol: str, tf: str, since: datetime
) -> pd.DataFrame:
    rows = (
        await db.scalars(
            select(Candle)
            .where(
                Candle.exchange == exchange,
                Candle.symbol == symbol,
                Candle.timeframe == tf,
                Candle.ts >= since,
            )
            .order_by(Candle.ts)
        )
    ).all()
    return pd.DataFrame(
        [
            {
                "ts": pd.Timestamp(r.ts),
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": float(r.volume),
            }
            for r in rows
        ],
        columns=["ts", "open", "high", "low", "close", "volume"],
    )


class OddsPools:
    """Per symbol per day cache of the time machine's candle pool (it only changes daily)."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str, Any], tuple[list, int]] = {}

    async def get(self, db: AsyncSession, exchange: str, symbol: str, now: datetime):
        key = (exchange, symbol, ist(now).date())
        if key not in self._cache:
            df = await load_candles(db, exchange, symbol, "5m", now - ODDS_LOOKBACK)
            self._cache = {k: v for k, v in self._cache.items() if k[2] == key[2]}
            self._cache[key] = build_pool(df, now)
        return self._cache[key]


def exit_params(p: dict[str, Any]) -> ExitParams:
    rule = p.get("stop_rule", "auto")
    if rule == "atr":
        rule = f"atr:{p.get('atr_mult', '1.5')}"
    elif rule == "pct":
        rule = f"pct:{p.get('stop_loss_pct', '1')}"
    return ExitParams(stop=rule, target_r=to_dec(p.get("target_r", "2")))


def risk_limits(p: dict[str, Any]) -> RiskLimits:
    # TODO: per-user section capital and limits (sections table); defaults until then.
    return RiskLimits(risk_per_trade_pct=to_dec(p.get("risk_per_trade_pct", "1")))


async def running_strategies(
    db: AsyncSession, symbol: str, tf: str, only_user: uuid.UUID | None = None
) -> list[Strategy]:
    q = select(Strategy).where(
        Strategy.status == "paper",
        Strategy.section.is_not(None),
        Strategy.template_key.is_not(None),
    )
    if only_user is not None:  # a user's real feed trades only that user's strategies
        q = q.where(Strategy.user_id == only_user)
    rows = (await db.scalars(q)).all()
    out = []
    for s in rows:
        p = s.params or {}
        syms = p.get("symbols") or []
        if p.get("timeframe", "5m") == tf and (not syms or symbol in syms):
            out.append(s)
    return out


async def process_hit(
    db: AsyncSession,
    strat: Strategy,
    hit: ScanHit,
    df: pd.DataFrame,
    *,
    now: datetime,
    ltp: Decimal | None,
    mood: dict[str, Any],
    exchange: str,
    tf: str,
    pools: OddsPools,
    calendar: TradingCalendar,
) -> Signal | None:
    key = trigger_key(hit)
    if await db.scalar(
        select(Signal.id).where(Signal.strategy_id == strat.id, Signal.trigger_key == key)
    ):
        return None  # one decision per setup per day
    p = strat.params or {}
    s = hit.setup
    sig = Signal(
        user_id=strat.user_id,
        strategy_id=strat.id,
        section=strat.section,
        exchange=exchange,
        symbol=s.symbol,
        side=s.side,
        rule=s.rule,
        trigger_key=key,
        bar_ts=pd.Timestamp(s.bar_ts).to_pydatetime(),
        price=to_dec(s.price),
        reason=s.reason,
        status="skipped",
        status_reason="",
        mood={**mood, "ok": hit.mood.ok, "reason": hit.mood.reason},
    )

    decision = decide_entry(
        hit, now, ltp, params=EntryParams(timeframe_minutes=TF_MINUTES[tf]), calendar=calendar
    )
    if decision.status == "skip":
        sig.status_reason = decision.reason
    else:
        plan = plan_exit(s, decision.entry_price, df, exit_params(p))
        if isinstance(plan, Refused):
            sig.status, sig.status_reason = "refused", plan.reason
        else:
            sig.plan = plan.as_dict()
            pool, n = await pools.get(db, exchange, s.symbol, now)
            odds = simulate(pool, n, s.side, plan.entry, plan.stop, plan.target, now, key=key)
            sig.odds = (
                {"available": False, "reason": odds.reason}
                if isinstance(odds, NoOdds)
                else {"available": True, **odds.as_dict()}
            )
            await _risk_and_trade(db, strat, sig, plan, p, now, decision.entry_price, key)

    db.add(sig)
    await db.flush()
    await record_event(
        db,
        "signal",
        f"{s.symbol} {s.side} {s.rule}: {sig.status}",
        user_id=strat.user_id,
        level="info",
        signal_id=str(sig.id),
        status=sig.status,
        why=sig.status_reason,
    )
    return sig


async def _risk_and_trade(
    db: AsyncSession,
    strat: Strategy,
    sig: Signal,
    plan: ExitPlan,
    p: dict[str, Any],
    now: datetime,
    ltp: Decimal,
    key: str,
) -> None:
    lim = risk_limits(p)
    st = await day_stats(db, strat.user_id, strat.section, now)
    acct = AccountState(
        cash=lim.capital + st.realised_total - st.open_value,
        open_positions=st.open_positions,
        open_symbols=st.open_symbols,
        trades_today=st.trades_today,
        loss_today=max(Decimal(0), -st.realised_today),
        committed_risk=st.committed_risk,
    )
    verdict = check_entry(plan, sig.symbol, lim, acct, now)
    if not isinstance(verdict, Approved):
        sig.status, sig.status_reason = "blocked", verdict.reason
        sig.risk = {"ok": False, "check": verdict.check, "reason": verdict.reason}
        return
    sig.risk = {
        "ok": True,
        "qty": verdict.qty,
        "max_loss": str(verdict.max_loss),
        "target_profit": str(verdict.target_profit),
        "charges": verdict.charges.as_dict(),
        "sized_by": verdict.sized_by,
        "notes": verdict.notes,
    }
    if p.get("mode") == "auto":
        db.add(sig)
        await db.flush()
        trade = await open_trade(
            db,
            OpenRequest(
                user_id=strat.user_id,
                strategy_id=strat.id,
                signal_id=sig.id,
                section=strat.section,
                exchange=sig.exchange,
                symbol=sig.symbol,
                side=sig.side,
                qty=verdict.qty,
                stop=plan.stop,
                target=plan.target,
                ref=f"{strat.id}:{key}",
                tick=plan.tick,
            ),
            ltp,
            now,
        )
        sig.status = "taken"
        sig.status_reason = f"Paper {sig.side} {trade.qty} at {trade.entry_price}"
    else:
        sig.status = "suggested"
        sig.status_reason = f"Suggested: {sig.side} {verdict.qty} (suggest-only mode)"


async def on_candle(
    db: AsyncSession,
    bar: dict[str, Any],
    *,
    now: datetime,
    ltp: Decimal | None,
    context_raw: str | None,
    pools: OddsPools,
    calendar: TradingCalendar | None = None,
    only_user: uuid.UUID | None = None,
) -> list[Signal]:
    tf, exchange, symbol = bar["timeframe"], bar["exchange"], bar["symbol"]
    if tf not in TF_MINUTES:
        return []
    strategies = await running_strategies(db, symbol, tf, only_user)
    if not strategies:
        return []
    df = await load_candles(db, exchange, symbol, tf, now - CANDLE_LOOKBACK)
    if df.empty:
        return []
    ctx, mood = mood_from(context_raw)
    cal = calendar or TradingCalendar()
    out: list[Signal] = []
    for strat in strategies:
        rule_params = {strat.template_key: (strat.params or {}).get("rule")}
        for hit in scan(symbol, df, ctx, rule_params):
            sig = await process_hit(
                db,
                strat,
                hit,
                df,
                now=now,
                ltp=ltp,
                mood=mood,
                exchange=exchange,
                tf=tf,
                pools=pools,
                calendar=cal,
            )
            if sig is not None:
                out.append(sig)
    return out


def signal_payload(sig: Signal) -> dict[str, Any]:
    return {
        "id": str(sig.id),
        "user_id": str(sig.user_id),
        "strategy_id": str(sig.strategy_id),
        "section": sig.section,
        "symbol": sig.symbol,
        "side": sig.side,
        "rule": sig.rule,
        "price": str(sig.price),
        "reason": sig.reason,
        "status": sig.status,
        "status_reason": sig.status_reason,
        "plan": sig.plan,
        "odds": sig.odds,
        "risk": sig.risk,
        "mood": sig.mood,
        "bar_ts": sig.bar_ts.isoformat(),
        "created_at": (sig.created_at or datetime.now(UTC)).isoformat(),
    }
