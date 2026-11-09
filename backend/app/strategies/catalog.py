"""Built-in strategy templates (see md/STRATEGIES.md). The signal code arrives in Phase 2/5;
this catalog lets users create and organise strategies from them now."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class TemplateInfo:
    key: str
    name: str
    idea: str
    section: str  # suggested section
    timeframe: str  # suggested timeframe
    phase: int  # roadmap phase that builds its signal logic


TEMPLATES: dict[str, TemplateInfo] = {
    t.key: t
    for t in (
        TemplateInfo(
            "orb",
            "Opening Range Breakout",
            "Trade the break of the first minutes' high or low.",
            "intraday",
            "5m",
            2,
        ),
        TemplateInfo(
            "vwap_cross",
            "VWAP Cross",
            "Price crosses VWAP with strong volume.",
            "intraday",
            "5m",
            2,
        ),
        TemplateInfo(
            "supertrend",
            "Supertrend",
            "Enter when the Supertrend line flips.",
            "intraday",
            "15m",
            2,
        ),
        TemplateInfo(
            "ema_cross", "EMA Crossover", "Fast EMA crosses the slow EMA.", "swing", "1d", 5
        ),
        TemplateInfo(
            "rsi_reversal", "RSI Reversal", "Buy oversold, sell overbought.", "swing", "1d", 5
        ),
        TemplateInfo(
            "breakout_volume",
            "Volume Breakout",
            "New N-day high with high volume.",
            "swing",
            "1d",
            5,
        ),
    )
}


def catalog() -> list[dict[str, Any]]:
    return [asdict(t) for t in TEMPLATES.values()]
