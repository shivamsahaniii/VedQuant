"""Risk Manager + Sizer agent (md/RISK.md). Pure code: no I/O, Decimal money.

`check_entry` runs every check in order and stops at the first BLOCK. It sizes the position with the
risk-percent method, then caps it by position size, cash (x the broker's intraday leverage), and a
max quantity. Exits (closing what you hold) are never blocked: `check_exit` only validates shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal

from app.engine.exit_plan import ExitPlan
from app.engine.nse import SESSION, Session, ist
from app.risk.charges import Charges, Product, round_trip


@dataclass(frozen=True)
class RiskLimits:
    """Per user + section. Defaults are deliberately small for a new paper account."""

    capital: Decimal = Decimal("100000")
    risk_per_trade_pct: Decimal = Decimal("1")  # of capital, lost if the stop fills
    max_loss_per_trade: Decimal | None = None  # rupees; caps the % rule when set
    max_daily_loss: Decimal = Decimal("3000")
    max_trades_per_day: int = 5
    max_open_positions: int = 3
    max_position_pct: Decimal = Decimal("50")  # of capital, by value
    leverage: Decimal = Decimal("1")  # TODO(verify): broker intraday margin; 1 = no leverage
    max_qty: int = 10_000
    min_profit_multiple: Decimal = Decimal("2")  # target profit >= this x round-trip charges
    product: Product = "intraday"


@dataclass(frozen=True)
class AccountState:
    cash: Decimal
    open_positions: int = 0
    open_symbols: frozenset[str] = frozenset()
    trades_today: int = 0
    loss_today: Decimal = Decimal(0)  # realised + unrealised loss today, as a positive number
    committed_risk: Decimal = Decimal(0)  # max loss still open at the stops of open positions
    kill_switch: bool = False
    halted: bool = False


@dataclass(frozen=True)
class Approved:
    qty: int
    max_loss: Decimal
    target_profit: Decimal
    charges: Charges
    sized_by: str
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return True


@dataclass(frozen=True)
class Blocked:
    check: str
    reason: str

    @property
    def ok(self) -> bool:
        return False


def _floor(x: Decimal) -> int:
    return int(x.to_integral_value(rounding=ROUND_FLOOR))


def size(plan: ExitPlan, lim: RiskLimits, cash: Decimal) -> tuple[int, str, dict[str, int]]:
    """Quantity = the smallest of the limits. Returns (qty, which limit decided, all limits)."""
    risk_budget = lim.capital * lim.risk_per_trade_pct / 100
    if lim.max_loss_per_trade is not None:
        risk_budget = min(risk_budget, lim.max_loss_per_trade)
    limits = {
        "risk per trade": _floor(risk_budget / plan.risk_per_share),
        "position size": _floor(lim.capital * lim.max_position_pct / 100 / plan.entry),
        "cash": _floor(cash * lim.leverage / plan.entry),
        "max quantity": lim.max_qty,
    }
    by = min(limits, key=lambda k: limits[k])
    return max(0, limits[by]), by, limits


def check_entry(
    plan: ExitPlan,
    symbol: str,
    lim: RiskLimits,
    acct: AccountState,
    now: datetime,
    session: Session = SESSION,
) -> Approved | Blocked:
    if acct.kill_switch:
        return Blocked("kill switch", "Kill switch is on: no new trades")
    if acct.halted:
        return Blocked("halted", "Section halted for today (daily loss limit)")
    t = ist(now).time()
    if not (session.no_entries_before <= t <= session.no_entries_after):
        return Blocked(
            "window",
            f"Outside the entry window {session.no_entries_before:%H:%M}-"
            f"{session.no_entries_after:%H:%M} IST",
        )
    if acct.loss_today >= lim.max_daily_loss:
        return Blocked(
            "daily loss",
            f"Today's loss {acct.loss_today} reached the limit " f"{lim.max_daily_loss}",
        )
    if acct.trades_today >= lim.max_trades_per_day:
        return Blocked(
            "trades", f"{acct.trades_today} trades today (limit {lim.max_trades_per_day})"
        )
    if acct.open_positions >= lim.max_open_positions:
        return Blocked(
            "open positions",
            f"{acct.open_positions} positions open " f"(limit {lim.max_open_positions})",
        )
    if symbol in acct.open_symbols:
        return Blocked("duplicate", f"Already holding {symbol}")
    if plan.stop <= 0 or plan.risk_per_share <= 0:
        return Blocked("stop", "A stop loss is required")

    qty, by, limits = size(plan, lim, acct.cash)
    if qty < 1:
        return Blocked(
            "size",
            f"Capital too small: the {by} limit allows 0 shares "
            f"(risk {plan.risk_per_share} a share)",
        )
    max_loss = plan.risk_per_share * qty
    # Daily loss: today's loss + what is still at risk + this trade's max loss must fit the limit.
    room = lim.max_daily_loss - acct.loss_today - acct.committed_risk
    if max_loss > room:
        qty_room = _floor(room / plan.risk_per_share) if room > 0 else 0
        if qty_room < 1:
            return Blocked(
                "daily loss",
                f"This trade could lose {max_loss}; only {max(room, 0)} "
                f"of today's loss limit is left",
            )
        qty, by, max_loss = qty_room, "daily loss room", plan.risk_per_share * qty_room

    buy, sell = (plan.entry, plan.target) if plan.side == "buy" else (plan.target, plan.entry)
    charges = round_trip(buy, sell, qty, lim.product)
    profit = plan.reward_per_share * qty
    if profit < lim.min_profit_multiple * charges.total:
        return Blocked(
            "charges",
            f"Target profit {profit} is under {lim.min_profit_multiple}x the "
            f"charges {charges.total}",
        )
    notes = [f"Sized by {by}: " + ", ".join(f"{k} {v}" for k, v in limits.items())]
    stop_charges = round_trip(
        *((plan.entry, plan.stop) if plan.side == "buy" else (plan.stop, plan.entry)),
        qty,
        lim.product,
    )
    notes.append(f"Loss at the stop incl. charges about {max_loss + stop_charges.total}")
    return Approved(qty, max_loss, profit, charges, by, notes)


def check_exit(qty_held: int, qty: int) -> Approved | Blocked:
    """Getting out is always allowed; only the shape is checked."""
    if qty_held == 0:
        return Blocked("nothing to close", "No open position")
    if qty < 1 or qty > abs(qty_held):
        return Blocked("quantity", f"Exit quantity {qty} does not match the position {qty_held}")
    return Approved(qty, Decimal(0), Decimal(0), round_trip(Decimal(0), Decimal(0), 0), "exit")
