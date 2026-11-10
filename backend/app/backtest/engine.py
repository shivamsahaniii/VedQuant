"""Backtester: the same agents as live paper trading, run over past real candles, in memory.

For every 5-minute candle of every past trading day, in time order across all symbols:
  1. open trades: the candle's price path (open -> low/high -> close) is checked against the stop
     and target, stop first (same `exit_hit` rule as the paper broker); 15:15 squares off;
  2. the candle closes: market mood (NIFTY), Scanner (template rule or the user's own rules),
     Entry Timer, Exit Planner, Odds, Risk + Sizer, then a paper fill with slippage.
Nothing is written to the database. Each strategy gets its own fresh paper account.

The agent code is shared with live trading (app.engine.*, app.risk.*, app.orders.paper), so a
backtest shows what the live agents would have done on those days, with Dhan's charges.
Limits: candles only (no ticks inside a candle), no partial fills, entry at the candle close.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd

from app.engine.builder import scan_builder
from app.engine.context import compute_context
from app.engine.entry import EntryParams, decide_entry, trigger_key
from app.engine.exit_plan import Refused, plan_exit
from app.engine.nse import IST, SESSION, TradingCalendar, to_dec
from app.engine.odds import NoOdds, build_pool, simulate
from app.engine.pipeline import CANDLE_LOOKBACK, ODDS_LOOKBACK, exit_params, risk_limits
from app.engine.setups import scan
from app.orders.paper import exit_hit, market_fill
from app.risk.charges import round_trip
from app.risk.engine import AccountState, Approved, check_entry

BAR = timedelta(minutes=5)
DECIDE_AFTER = timedelta(seconds=20)  # the live engine decides ~20 s after a candle closes


@dataclass
class Spec:
    """What to test: a template rule (`template_key`) or own rules (`params['builder']`)."""

    name: str
    template_key: str | None
    params: dict[str, Any]
    symbols: list[str]
    odds_gate: bool = False  # skip trades the odds say lean toward the stop


@dataclass
class BtTrade:
    day: date
    symbol: str
    side: str
    qty: int
    entry: Decimal
    entry_at: datetime
    stop: Decimal
    target: Decimal
    tick: Decimal
    odds: str = ""  # target / stop / even / none
    exit: Decimal | None = None
    exit_at: datetime | None = None
    reason: str = ""
    gross: Decimal = Decimal(0)
    charges: Decimal = Decimal(0)
    net: Decimal = Decimal(0)

    def close(self, price: Decimal, at: datetime, reason: str) -> None:
        sign = 1 if self.side == "buy" else -1
        self.exit, self.exit_at, self.reason = price, at, reason
        self.gross = (price - self.entry) * self.qty * sign
        buy, sell = (self.entry, price) if self.side == "buy" else (price, self.entry)
        self.charges = round_trip(buy, sell, self.qty, "intraday").total
        self.net = self.gross - self.charges


@dataclass
class Result:
    spec: Spec
    days: list[date]
    trades: list[BtTrade] = field(default_factory=list)
    decisions: Counter = field(default_factory=Counter)  # why setups were not traded

    def summary(self) -> dict[str, Any]:
        t = self.trades
        wins = [x for x in t if x.net > 0]
        losses = [x for x in t if x.net <= 0]
        net = sum((x.net for x in t), Decimal(0))
        gross_win = sum((x.net for x in wins), Decimal(0))
        gross_loss = -sum((x.net for x in losses), Decimal(0))
        by_day: dict[date, Decimal] = {d: Decimal(0) for d in self.days}
        for x in t:
            by_day[x.day] += x.net
        equity, peak, dd = Decimal(0), Decimal(0), Decimal(0)
        for d in sorted(by_day):
            equity += by_day[d]
            peak = max(peak, equity)
            dd = max(dd, peak - equity)
        odds = {}
        for k in ("target", "even", "stop", "none"):
            g = [x for x in t if x.odds == k]
            if g:
                odds[k] = {
                    "trades": len(g),
                    "win_rate": round(100 * sum(1 for x in g if x.net > 0) / len(g)),
                    "net": float(sum((x.net for x in g), Decimal(0))),
                }
        return {
            "strategy": self.spec.name,
            "days": len(self.days),
            "trades": len(t),
            "win_rate": round(100 * len(wins) / len(t)) if t else None,
            "net": float(net),
            "charges": float(sum((x.charges for x in t), Decimal(0))),
            "avg_win": float(gross_win / len(wins)) if wins else 0.0,
            "avg_loss": float(-gross_loss / len(losses)) if losses else 0.0,
            "profit_factor": round(float(gross_win / gross_loss), 2) if gross_loss else None,
            "max_drawdown": float(dd),
            "green_days": sum(1 for v in by_day.values() if v > 0),
            "red_days": sum(1 for v in by_day.values() if v < 0),
            "exits": dict(Counter(x.reason for x in t)),
            "odds": odds,
            "not_taken": dict(self.decisions.most_common(6)),
        }


def _path(o: float, h: float, lo: float, c: float) -> list[float]:
    """Price path inside a candle: green candles dip first, red ones rise first."""
    return [o, lo, h, c] if c >= o else [o, h, lo, c]


def _ist_t(ts: pd.Timestamp) -> time:
    return ts.tz_convert(IST).time()


def run(
    spec: Spec,
    candles: dict[str, pd.DataFrame],
    nifty: pd.DataFrame,
    days: list[date],
    calendar: TradingCalendar | None = None,
    exchange: str = "NSE",
) -> Result:
    """`candles`: symbol -> 5m frame (ts UTC, open/high/low/close/volume floats), all history.
    `days`: the IST trading days to trade (earlier history feeds indicators and odds)."""
    cal = calendar or TradingCalendar()
    p = spec.params
    lim = risk_limits(p)
    xp = exit_params(p)
    entry_params = EntryParams(timeframe_minutes=5)
    res = Result(spec, days)
    realised_total = Decimal(0)
    syms = [s for s in spec.symbols if s in candles]
    frames = {s: candles[s].reset_index(drop=True) for s in syms}
    ts_index = {s: pd.DatetimeIndex(frames[s]["ts"]) for s in syms}
    nifty = nifty.reset_index(drop=True)
    nifty_ts = pd.DatetimeIndex(nifty["ts"])

    for day in days:
        start = pd.Timestamp(datetime(day.year, day.month, day.day, tzinfo=IST)).tz_convert("UTC")
        end = start + timedelta(days=1)
        rows: dict[pd.Timestamp, list[tuple[str, int]]] = {}
        for s in syms:
            idx = ts_index[s]
            for i in range(idx.searchsorted(start), idx.searchsorted(end)):
                rows.setdefault(idx[i], []).append((s, i))
        if not rows:
            continue
        open_trades: list[BtTrade] = []
        decided: set[str] = set()
        realised_today, trades_today = Decimal(0), 0
        day_open: dict[str, float] = {}
        last: dict[str, float] = {}
        pools: dict[str, tuple[list, int]] = {}

        for ts in sorted(rows):
            closes_at = ts + BAR
            now = closes_at + DECIDE_AFTER
            # 1) exits during this candle
            for s, i in rows[ts]:
                r = frames[s].iloc[i]
                if _ist_t(ts) >= SESSION.square_off:
                    for tr in [x for x in open_trades if x.symbol == s]:
                        tr.close(to_dec(r["open"]), ts.to_pydatetime(), "square_off")
                        open_trades.remove(tr)
                        realised_today += tr.net
                        realised_total += tr.net
                    continue
                for k, price in enumerate(_path(r["open"], r["high"], r["low"], r["close"])):
                    for tr in [x for x in open_trades if x.symbol == s]:
                        hit = exit_hit(tr, to_dec(price))  # type: ignore[arg-type]
                        if hit:
                            tr.close(
                                hit[1], (ts + timedelta(minutes=k + 1)).to_pydatetime(), hit[0]
                            )
                            open_trades.remove(tr)
                            realised_today += tr.net
                            realised_total += tr.net
            if _ist_t(ts) >= SESSION.square_off:
                continue
            for s, i in rows[ts]:
                r = frames[s].iloc[i]
                day_open.setdefault(s, float(r["open"]))
                last[s] = float(r["close"])
            # 2) market mood from NIFTY up to this close
            j = nifty_ts.searchsorted(closes_at)
            k0 = nifty_ts.searchsorted(closes_at - timedelta(days=4))
            ctx = compute_context(
                nifty.iloc[max(k0, j - 400) : j],
                {s: (day_open[s], last[s]) for s in last},
                now.to_pydatetime(),
                "5m",
                cal,
            )
            # 3) the agent chain per symbol
            for s, i in rows[ts]:
                f = frames[s]
                lo = ts_index[s].searchsorted(ts - CANDLE_LOOKBACK)
                df = f.iloc[lo : i + 1]
                if spec.template_key:
                    hits = scan(s, df, ctx, {spec.template_key: p.get("rule")})
                else:
                    hits = scan_builder(s, df, ctx, p["builder"])
                for hit in hits:
                    key = trigger_key(hit)
                    if key in decided:
                        continue
                    decided.add(key)
                    ltp = to_dec(df["close"].iloc[-1])
                    d = decide_entry(
                        hit, now.to_pydatetime(), ltp, params=entry_params, calendar=cal
                    )
                    if d.status == "skip":
                        res.decisions[_bucket(d.reason)] += 1
                        continue
                    plan = plan_exit(hit.setup, d.entry_price, df, xp)
                    if isinstance(plan, Refused):
                        res.decisions["exit plan refused"] += 1
                        continue
                    if s not in pools:
                        olo = ts_index[s].searchsorted(start - ODDS_LOOKBACK)
                        pools[s] = build_pool(f.iloc[olo : ts_index[s].searchsorted(start)], start)
                    pool, n = pools[s]
                    odds = simulate(
                        pool,
                        n,
                        hit.setup.side,
                        plan.entry,
                        plan.stop,
                        plan.target,
                        now.to_pydatetime(),
                        key=key,
                        replays=1000,
                    )
                    leaning = "none" if isinstance(odds, NoOdds) else odds.lean
                    if (spec.odds_gate or p.get("odds_filter")) and leaning == "stop":
                        res.decisions["odds lean to the stop"] += 1
                        continue
                    acct = AccountState(
                        cash=lim.capital
                        + realised_total
                        - sum((x.entry * x.qty for x in open_trades), Decimal(0)),
                        open_positions=len(open_trades),
                        open_symbols=frozenset(x.symbol for x in open_trades),
                        trades_today=trades_today,
                        loss_today=max(Decimal(0), -realised_today),
                        committed_risk=sum(
                            (abs(x.entry - x.stop) * x.qty for x in open_trades), Decimal(0)
                        ),
                    )
                    v = check_entry(plan, s, lim, acct, now.to_pydatetime())
                    if not isinstance(v, Approved):
                        res.decisions[f"risk: {v.check}"] += 1
                        continue
                    fill = market_fill(hit.setup.side, d.entry_price, plan.tick)
                    tr = BtTrade(
                        day,
                        s,
                        hit.setup.side,
                        v.qty,
                        fill,
                        now.to_pydatetime(),
                        plan.stop,
                        plan.target,
                        plan.tick,
                        leaning or "none",
                    )
                    open_trades.append(tr)
                    res.trades.append(tr)
                    trades_today += 1
        for tr in open_trades:  # safety net: nothing stays open overnight
            # Dhan's stock history stops at the 15:10 candle: its close is the 15:15 price.
            tr.close(to_dec(last.get(tr.symbol, float(tr.entry))), tr.entry_at, "square_off")
            realised_total += tr.net
    return res


def _bucket(reason: str) -> str:
    if reason.startswith("Market mood"):
        return "market mood"
    if reason.startswith("Before the entry window") or reason.startswith("After the entry"):
        return "outside 09:30-14:30"
    if reason.startswith("Price ran") or "chas" in reason.lower():
        return "price ran away"
    return reason.split(":")[0][:40]


def frame_from_rows(rows: list[Any]) -> pd.DataFrame:
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
