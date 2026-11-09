from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.strategies.catalog import TEMPLATES

Section = Literal["intraday", "swing", "options", "crypto"]
Timeframe = Literal["1m", "5m", "15m", "1h", "1d"]
_SYMBOL = re.compile(r"^[A-Z0-9&\-]{1,30}$")


class StrategyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeframe: Timeframe = "5m"
    symbols: list[str] = Field(default_factory=list, max_length=50)
    stop_loss_pct: Decimal = Field(
        default=Decimal("1"), gt=0, le=50, max_digits=6, decimal_places=2
    )
    target_pct: Decimal | None = Field(
        default=Decimal("2"), gt=0, le=100, max_digits=6, decimal_places=2
    )
    # Engine settings (agents A.4-A.7)
    mode: Literal["suggest", "auto"] = "suggest"  # auto = the paper broker takes approved signals
    stop_rule: Literal["auto", "or_mid", "or_far", "level", "atr", "pct"] = "auto"
    atr_mult: Decimal = Field(default=Decimal("1.5"), gt=0, le=10, max_digits=4, decimal_places=2)
    target_r: Decimal = Field(default=Decimal("2"), gt=0, le=10, max_digits=4, decimal_places=2)
    risk_per_trade_pct: Decimal = Field(
        default=Decimal("1"), gt=0, le=5, max_digits=4, decimal_places=2
    )

    @field_validator("symbols", mode="before")
    @classmethod
    def _symbols(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.split(",")
        if not isinstance(v, list):
            return v
        out: list[str] = []
        for s in v:
            s = str(s).strip().upper()
            if not s:
                continue
            if not _SYMBOL.match(s):
                raise ValueError(f"Invalid symbol: {s[:30]}")
            if s not in out:
                out.append(s)
        return out


def _clean_name(v: str) -> str:
    v = " ".join(v.split())
    if not v:
        raise ValueError("Name is required")
    return v


class StrategyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    template_key: str
    section: Section | None = None
    params: StrategyParams = Field(default_factory=StrategyParams)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return _clean_name(v)

    @field_validator("template_key")
    @classmethod
    def _known_template(cls, v: str) -> str:
        if v not in TEMPLATES:
            raise ValueError(f"Unknown template: {v[:32]}")
        return v


class StrategyUpdate(BaseModel):
    """Only the fields that are sent are changed. `section: null` removes it from its section."""

    name: str | None = Field(default=None, min_length=1, max_length=60)
    section: Section | None = None
    params: StrategyParams | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return _clean_name(v) if v is not None else v


class StrategyStatusChange(BaseModel):
    status: Literal["paper", "paused"]


class StrategyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    section: Section | None
    kind: str
    template_key: str | None
    params: dict[str, Any]
    status: str
    version: int
    created_at: datetime
    updated_at: datetime
