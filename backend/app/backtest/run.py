"""Run backtests over the real candles stored in the database.

    python -m app.backtest.run            # all built-in intraday strategies, all stored days

Read-only: it loads candles and prints a report; nothing is saved.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date

from sqlalchemy import select

from app.backtest.engine import Spec, frame_from_rows, run
from app.core.db import get_sessionmaker
from app.data.source import load_calendar
from app.engine.nse import IST
from app.models import Candle

STOCKS = [
    "RELIANCE",
    "TCS",
    "INFY",
    "HDFCBANK",
    "ICICIBANK",
    "SBIN",
    "ITC",
    "LT",
    "AXISBANK",
    "KOTAKBANK",
]
VWAP_VOLUME_RULES = {
    "mood": "trend",
    "buy": {
        "match": "all",
        "conditions": [
            {"left": {"kind": "close"}, "op": "crosses_above", "right": {"kind": "vwap"}},
            {
                "left": {"kind": "volume"},
                "op": "above",
                "right": {"kind": "avg_volume", "period": 20, "mult": 1.5},
            },
        ],
    },
    "sell": {
        "match": "all",
        "conditions": [
            {"left": {"kind": "close"}, "op": "crosses_below", "right": {"kind": "vwap"}},
            {
                "left": {"kind": "volume"},
                "op": "above",
                "right": {"kind": "avg_volume", "period": 20, "mult": 1.5},
            },
        ],
    },
}


def specs() -> list[Spec]:
    base = {"timeframe": "5m", "mode": "auto"}
    out = []
    for key, name in (
        ("orb", "Opening Range Breakout"),
        ("vwap_cross", "VWAP Cross"),
        ("supertrend", "Supertrend (5m)"),
    ):
        out.append(Spec(name, key, dict(base), STOCKS))
        out.append(Spec(f"{name} + odds filter", key, dict(base), STOCKS, odds_gate=True))
    out.append(
        Spec(
            "Own rule: VWAP cross + 1.5x volume",
            None,
            {**base, "builder": VWAP_VOLUME_RULES},
            STOCKS,
        )
    )
    out.append(
        Spec(
            "Own rule: VWAP cross + 1.5x volume + odds filter",
            None,
            {**base, "builder": VWAP_VOLUME_RULES},
            STOCKS,
            odds_gate=True,
        )
    )
    return out


async def load(symbols: list[str]):
    async with get_sessionmaker()() as db:
        cal = await load_calendar(db)
        frames = {}
        for s in [*symbols, "NIFTY50"]:
            rows = (
                await db.scalars(
                    select(Candle)
                    .where(Candle.symbol == s, Candle.timeframe == "5m")
                    .order_by(Candle.ts)
                )
            ).all()
            frames[s] = frame_from_rows(rows)
    return frames, cal


async def main() -> None:
    frames, cal = await load(STOCKS)
    nifty = frames.pop("NIFTY50")
    all_days = sorted(
        {
            t.tz_convert(IST).date()
            for t in nifty["ts"]
            if cal.is_trading_day(t.tz_convert(IST).date())
        }
    )
    days = [d for d in all_days[5:] if d < date.today()]  # first days only warm the indicators
    out = []
    for spec in specs():
        r = run(spec, frames, nifty, days, cal)
        out.append(r.summary())
        print(f"done: {spec.name}", file=sys.stderr)
    print(json.dumps({"from": str(days[0]), "to": str(days[-1]), "results": out}, default=str))


if __name__ == "__main__":
    asyncio.run(main())
