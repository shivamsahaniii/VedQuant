"""Market simulator for paper trading and testing (no real data).

A NIFTY 50 index plus 10 stocks. Every stock follows the index (beta) plus its own noise,
so "market-wide" ideas (trend, breadth) behave like a real market. Each trading day gets
one regime, chosen from the date and seed, so a simulated day is repeatable:

- trend_up / trend_down : steady drift through the day
- sideways              : prices pulled back toward the open
- volatile              : big swings, no clear direction

Prices are illustrative only. Internally floats are used (this is simulation, not money
code); ticks leave as Decimal on the 0.05 tick grid.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
TICK = Decimal("0.05")
SESSION_SECONDS = 22_500  # 09:15 -> 15:30
MARKET_OPEN = time(9, 15)

INDEX = ("NSE", "NIFTY50")
REGIMES = ("trend_up", "trend_down", "sideways", "volatile")


@dataclass(frozen=True)
class SimInstrument:
    exchange: str
    symbol: str
    name: str
    base: float
    beta: float  # sensitivity to the index
    idio_vol: float  # own daily volatility (fraction)
    avg_volume: int  # shares per minute, on average


# Illustrative base prices and betas, not real quotes.
SIM_STOCKS: tuple[SimInstrument, ...] = (
    SimInstrument("NSE", "RELIANCE", "Reliance Industries", 2900, 1.0, 0.010, 9000),
    SimInstrument("NSE", "TCS", "Tata Consultancy Services", 4100, 0.7, 0.009, 3000),
    SimInstrument("NSE", "INFY", "Infosys", 1800, 0.8, 0.011, 8000),
    SimInstrument("NSE", "HDFCBANK", "HDFC Bank", 1700, 1.1, 0.009, 12000),
    SimInstrument("NSE", "ICICIBANK", "ICICI Bank", 1250, 1.2, 0.010, 14000),
    SimInstrument("NSE", "SBIN", "State Bank of India", 820, 1.3, 0.013, 20000),
    SimInstrument("NSE", "ITC", "ITC", 470, 0.6, 0.008, 18000),
    SimInstrument("NSE", "LT", "Larsen & Toubro", 3600, 1.1, 0.011, 2500),
    SimInstrument("NSE", "AXISBANK", "Axis Bank", 1150, 1.2, 0.012, 11000),
    SimInstrument("NSE", "KOTAKBANK", "Kotak Mahindra Bank", 1800, 0.9, 0.010, 4000),
)
SIM_INDEX = SimInstrument("NSE", "NIFTY50", "NIFTY 50 (simulated)", 24000, 1.0, 0.0, 0)

# Index behaviour per regime: (total drift over the session, daily volatility, mean reversion)
_REGIME_PARAMS: dict[str, tuple[float, float, float]] = {
    "trend_up": (0.012, 0.006, 0.0),
    "trend_down": (-0.012, 0.006, 0.0),
    "sideways": (0.0, 0.005, 0.0015),
    "volatile": (0.0, 0.016, 0.0),
}


def to_tick(price: float) -> Decimal:
    steps = (Decimal(str(price)) / TICK).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return max(TICK, steps * TICK)


def session_progress(now: datetime) -> float:
    """0.0 at 09:15 IST, 1.0 at 15:30 IST (clamped)."""
    local = now.astimezone(IST)
    start = datetime.combine(local.date(), MARKET_OPEN, IST)
    return min(1.0, max(0.0, (local - start).total_seconds() / SESSION_SECONDS))


def volume_shape(progress: float) -> float:
    """U-shaped intraday activity: 1.8 at open/close, 0.6 at mid-day, average 1.0."""
    return 0.6 + 4.8 * (progress - 0.5) ** 2


@dataclass
class _State:
    price: float
    open: float
    cum_volume: int = 0


@dataclass
class SimTick:
    exchange: str
    symbol: str
    ts: datetime
    ltp: Decimal
    volume: int  # cumulative for the day
    last_qty: int


@dataclass
class MarketSimulator:
    seed: int | None = None
    day: date | None = None
    regime: str | None = None
    stocks: tuple[SimInstrument, ...] = SIM_STOCKS
    _rng: random.Random = field(init=False, repr=False)
    _state: dict[tuple[str, str], _State] = field(init=False, repr=False)
    _last: datetime | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        day = self.day or datetime.now(IST).date()
        self.day = day
        base_seed = 0 if self.seed is None else self.seed
        self._rng = random.Random(f"{base_seed}:{day.isoformat()}")  # noqa: S311 - simulation
        if self.regime is None:
            self.regime = self._rng.choice(REGIMES)
        if self.regime not in REGIMES:
            raise ValueError(f"Unknown regime {self.regime}")
        # Opening gap: trend days tend to open in their direction.
        gap = {"trend_up": 0.003, "trend_down": -0.003}.get(self.regime, 0.0)
        gap += self._rng.gauss(0, 0.002)
        self._state = {}
        for inst in (SIM_INDEX, *self.stocks):
            own_gap = gap * inst.beta + self._rng.gauss(0, inst.idio_vol * 0.3)
            p = inst.base * math.exp(own_gap if inst is not SIM_INDEX else gap)
            self._state[(inst.exchange, inst.symbol)] = _State(price=p, open=p)

    @property
    def instruments(self) -> tuple[SimInstrument, ...]:
        return (SIM_INDEX, *self.stocks)

    def price(self, exchange: str, symbol: str) -> float:
        return self._state[(exchange, symbol)].price

    def step(self, now: datetime, dt: float | None = None) -> list[SimTick]:
        """Advance by `dt` seconds (default: time since the last step, 1s at first, max 60s)."""
        if dt is None:
            dt = 1.0 if self._last is None else (now - self._last).total_seconds()
        dt = min(max(dt, 0.001), 60.0)
        self._last = now
        drift, vol, revert = _REGIME_PARAMS[self.regime or "sideways"]
        frac = dt / SESSION_SECONDS
        prog = session_progress(now)
        activity = volume_shape(prog)

        idx = self._state[INDEX]
        pull = -revert * math.log(idx.price / idx.open) * dt / 60.0
        r_index = (
            drift * frac + pull + vol * math.sqrt(frac) * self._rng.gauss(0, 1) * activity**0.5
        )
        idx.price *= math.exp(r_index)

        ticks = [SimTick(INDEX[0], INDEX[1], now, to_tick(idx.price), 0, 0)]
        for inst in self.stocks:
            st = self._state[(inst.exchange, inst.symbol)]
            r = inst.beta * r_index + inst.idio_vol * math.sqrt(frac) * self._rng.gauss(0, 1)
            st.price *= math.exp(r)
            qty = max(1, int(self._rng.expovariate(1.0) * inst.avg_volume * activity * dt / 60.0))
            st.cum_volume += qty
            ticks.append(
                SimTick(inst.exchange, inst.symbol, now, to_tick(st.price), st.cum_volume, qty)
            )
        return ticks
