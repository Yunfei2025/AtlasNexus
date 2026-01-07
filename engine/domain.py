from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Iterable


class InstrumentType(str, Enum):
    EQUITY = "equity"
    ETF = "etf"
    FUTURE = "future"
    FX = "fx"
    BOND = "bond"
    SWAP = "swap"
    OPTION = "option"
    INDEX = "index"
    OTHER = "other"


@dataclass(frozen=True)
class Instrument:
    """Minimal normalized instrument representation.

    Keep this small: it’s used as the cross-module identifier.
    Individual modules can attach their own richer metadata as needed.
    """

    id: str
    type: InstrumentType = InstrumentType.OTHER
    currency: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Universe:
    asof: datetime
    instruments: list[Instrument]
    groups: dict[str, list[str]] = field(default_factory=dict)  # group -> list[instrument_id]
    constraints: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Signal:
    """Single-instrument signal.

    score: numeric strength
    direction: +1 long / -1 short / 0 flat
    horizon: e.g. 'intraday', '1d', '1w'
    """

    strategy: str
    instrument_id: str
    timestamp: datetime
    score: float
    direction: int
    horizon: str = "1d"
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Target:
    """Desired target outcome.

    Use either target_weight (portfolio weight) or target_risk (risk units).
    Keep both optional to support multiple sizing styles.
    """

    instrument_id: str
    timestamp: datetime
    target_weight: float | None = None
    target_risk: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Ticket:
    """Manual execution-friendly trade ticket."""

    instrument_id: str
    action: str  # BUY/SELL/REBALANCE/HEDGE/etc.
    size: float | None = None
    unit: str | None = None  # shares, contracts, notional, DV01, etc.
    timestamp: datetime = field(default_factory=datetime.utcnow)
    strategy: str | None = None
    rationale: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def as_instrument_ids(items: Iterable[Instrument | str]) -> list[str]:
    out: list[str] = []
    for x in items:
        out.append(x.id if isinstance(x, Instrument) else str(x))
    return out
