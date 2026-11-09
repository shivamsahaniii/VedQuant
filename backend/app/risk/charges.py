"""Round-trip trading charges for NSE equity (md/RISK.md "Charges check").

All money is Decimal, rounded to paise. Rates are data with an effective date because they change.
TODO(verify): confirm every rate against Dhan's pricing page and NSE/SEBI circulars before live
trading; rates below are the published structure as understood on 2026-11-09.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

Product = Literal["intraday", "delivery"]
PAISE = Decimal("0.01")
PCT = Decimal("0.01")  # 1 % as a fraction


@dataclass(frozen=True)
class ChargeRates:
    name: str
    effective_from: date
    brokerage_pct: Decimal  # per executed order, as a percentage of turnover
    brokerage_cap: Decimal | None  # rupees per executed order (None = no cap)
    stt_buy_pct: Decimal
    stt_sell_pct: Decimal
    exchange_pct: Decimal  # NSE transaction charge, both sides
    sebi_pct: Decimal  # Rs 10 per crore = 0.0001 %
    stamp_buy_pct: Decimal
    gst_pct: Decimal  # on brokerage + exchange + SEBI
    dp_per_sell: Decimal = Decimal(0)  # depository charge per delivery sell (before GST)


RATES: dict[Product, ChargeRates] = {
    "intraday": ChargeRates(
        name="Dhan equity intraday",
        effective_from=date(2024, 10, 1),
        brokerage_pct=Decimal("0.03"),
        brokerage_cap=Decimal("20"),
        stt_buy_pct=Decimal("0"),
        stt_sell_pct=Decimal("0.025"),
        exchange_pct=Decimal("0.00297"),
        sebi_pct=Decimal("0.0001"),
        stamp_buy_pct=Decimal("0.003"),
        gst_pct=Decimal("18"),
    ),
    "delivery": ChargeRates(
        name="Dhan equity delivery",
        effective_from=date(2024, 10, 1),
        brokerage_pct=Decimal("0"),
        brokerage_cap=None,
        stt_buy_pct=Decimal("0.1"),
        stt_sell_pct=Decimal("0.1"),
        exchange_pct=Decimal("0.00297"),
        sebi_pct=Decimal("0.0001"),
        stamp_buy_pct=Decimal("0.015"),
        gst_pct=Decimal("18"),
        dp_per_sell=Decimal("12.5"),  # TODO(verify)
    ),
}


@dataclass(frozen=True)
class Charges:
    brokerage: Decimal
    stt: Decimal
    exchange: Decimal
    sebi: Decimal
    stamp: Decimal
    dp: Decimal
    gst: Decimal

    @property
    def total(self) -> Decimal:
        return (
            self.brokerage + self.stt + self.exchange + self.sebi + self.stamp + self.dp + self.gst
        )

    def as_dict(self) -> dict[str, str]:
        d = {k: str(v) for k, v in self.__dict__.items()}
        d["total"] = str(self.total)
        return d


def _p(x: Decimal) -> Decimal:
    return x.quantize(PAISE, rounding=ROUND_HALF_UP)


def _brokerage(turnover: Decimal, r: ChargeRates) -> Decimal:
    b = turnover * r.brokerage_pct * PCT
    return min(b, r.brokerage_cap) if r.brokerage_cap is not None else b


def round_trip(
    buy_price: Decimal, sell_price: Decimal, qty: int, product: Product = "intraday"
) -> Charges:
    """Charges for one buy and one sell of `qty` shares (a short: same, sell first)."""
    r = RATES[product]
    buy, sell = buy_price * qty, sell_price * qty
    brokerage = _brokerage(buy, r) + _brokerage(sell, r)
    exchange = (buy + sell) * r.exchange_pct * PCT
    sebi = (buy + sell) * r.sebi_pct * PCT
    gst = (brokerage + exchange + sebi + r.dp_per_sell) * r.gst_pct * PCT
    return Charges(
        brokerage=_p(brokerage),
        stt=_p((buy * r.stt_buy_pct + sell * r.stt_sell_pct) * PCT),
        exchange=_p(exchange),
        sebi=_p(sebi),
        stamp=_p(buy * r.stamp_buy_pct * PCT),
        dp=_p(r.dp_per_sell),
        gst=_p(gst),
    )


def cost_pct_estimate(product: Product = "intraday") -> Decimal:
    """Round-trip cost as a % of one side's value, ignoring the brokerage cap (worst case for
    small orders). Used before the quantity is known; the exact check uses round_trip()."""
    r = RATES[product]
    brokerage = 2 * r.brokerage_pct
    exchange = 2 * r.exchange_pct
    sebi = 2 * r.sebi_pct
    gst = (brokerage + exchange + sebi) * r.gst_pct * PCT
    return brokerage + exchange + sebi + gst + r.stt_buy_pct + r.stt_sell_pct + r.stamp_buy_pct
