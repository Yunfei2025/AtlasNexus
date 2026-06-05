"""Standardized artifact contracts for engine runs.

The engine writes results into ``runs/<run_id>/`` so the web layer can read
them instead of recomputing in callbacks. This module defines the *shapes* of
those artifacts as small, versioned dataclasses with explicit JSON
(de)serialization.

Design goals
------------
- **Backward compatible:** :class:`RunManifest` serializes to the exact
  ``run_meta.json`` shape that ``web/services/artifacts.py`` already reads.
- **Domain-agnostic:** every backtest engine (curves, futures, factors,
  multiasset, derivatives) keeps its own logic but can emit a common
  :class:`BacktestResult` so the UI renders results uniformly.
- **Pure-python / no market data:** everything here is testable in CI without
  Wind or a live database.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

# Bump when a field changes meaning or a non-additive change lands.
SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Performance metrics
# ---------------------------------------------------------------------------

@dataclass
class PerformanceMetrics:
    """Standard performance summary for a return stream.

    Conventions match the existing ``futures/backtest/metrics.py``:
    arithmetic annualization for Sharpe (``mean * periods_per_year``) and a
    geometric ``total_return``. All values are plain floats (ratios, not
    percentages) so they round-trip cleanly through JSON.
    """

    total_return: float = 0.0   # geometric: prod(1+r) - 1
    ann_return: float = 0.0     # arithmetic annualized: mean(r) * periods_per_year
    ann_vol: float = 0.0        # std(r, ddof=1) * sqrt(periods_per_year)
    sharpe: float = 0.0         # (ann_return - rf) / ann_vol
    max_drawdown: float = 0.0   # most-negative (equity - cummax)/cummax, <= 0
    calmar: float = 0.0         # ann_return / abs(max_drawdown)
    n_obs: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_return": self.total_return,
            "ann_return": self.ann_return,
            "ann_vol": self.ann_vol,
            "sharpe": self.sharpe,
            "max_drawdown": self.max_drawdown,
            "calmar": self.calmar,
            "n_obs": self.n_obs,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PerformanceMetrics":
        return cls(
            total_return=float(d.get("total_return", 0.0)),
            ann_return=float(d.get("ann_return", 0.0)),
            ann_vol=float(d.get("ann_vol", 0.0)),
            sharpe=float(d.get("sharpe", 0.0)),
            max_drawdown=float(d.get("max_drawdown", 0.0)),
            calmar=float(d.get("calmar", 0.0)),
            n_obs=int(d.get("n_obs", 0)),
        )

    @classmethod
    def from_returns(
        cls,
        returns: Sequence[float],
        *,
        periods_per_year: int = 252,
        risk_free: float = 0.0,
    ) -> "PerformanceMetrics":
        """Compute metrics from a sequence of simple periodic returns.

        Pure python so it stays dependency-light and trivially testable.
        Empty / single-point inputs yield an all-zero summary rather than
        raising, mirroring the defensive style of the existing code.
        """
        rs = [float(r) for r in returns if r is not None and not _isnan(r)]
        n = len(rs)
        if n == 0:
            return cls()

        # Geometric cumulative return + equity curve.
        equity: list[float] = []
        cum = 1.0
        for r in rs:
            cum *= (1.0 + r)
            equity.append(cum)
        total_return = equity[-1] - 1.0

        mean_r = sum(rs) / n
        if n > 1:
            var = sum((r - mean_r) ** 2 for r in rs) / (n - 1)
            std_r = math.sqrt(var)
        else:
            std_r = 0.0

        ann_return = mean_r * periods_per_year
        ann_vol = std_r * math.sqrt(periods_per_year)
        sharpe = (ann_return - risk_free) / ann_vol if ann_vol > 0 else 0.0

        max_drawdown = _max_drawdown(equity)
        calmar = ann_return / abs(max_drawdown) if max_drawdown < 0 else 0.0

        return cls(
            total_return=total_return,
            ann_return=ann_return,
            ann_vol=ann_vol,
            sharpe=sharpe,
            max_drawdown=max_drawdown,
            calmar=calmar,
            n_obs=n,
        )


# ---------------------------------------------------------------------------
# Backtest result
# ---------------------------------------------------------------------------

@dataclass
class BacktestResult:
    """A single strategy/instrument backtest result.

    ``equity_curve`` and ``dates`` are optional so light callers can store
    just the metrics. ``meta`` carries domain-specific extras (e.g. notional,
    instrument type, factor exposures) without bloating the core schema.
    """

    name: str
    asof: str                                   # ISO date
    metrics: PerformanceMetrics = field(default_factory=PerformanceMetrics)
    equity_curve: list[float] | None = None
    dates: list[str] | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "asof": self.asof,
            "metrics": self.metrics.to_dict(),
            "equity_curve": self.equity_curve,
            "dates": self.dates,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BacktestResult":
        return cls(
            name=str(d.get("name", "")),
            asof=str(d.get("asof", "")),
            metrics=PerformanceMetrics.from_dict(d.get("metrics", {}) or {}),
            equity_curve=d.get("equity_curve"),
            dates=d.get("dates"),
            meta=d.get("meta", {}) or {},
            schema_version=int(d.get("schema_version", SCHEMA_VERSION)),
        )

    def write(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        return path

    @classmethod
    def read(cls, path: Path) -> "BacktestResult":
        with Path(path).open("r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


# ---------------------------------------------------------------------------
# Run manifest (backward-compatible run_meta.json)
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    """Status of one pipeline step."""

    name: str
    status: str          # "ok" | "failed" | "skipped"
    detail: str | None = None


@dataclass
class RunManifest:
    """Top-level description of an engine run.

    Serializes to ``run_meta.json``. The ``steps`` field is kept as a
    ``{name: status}`` mapping to preserve the exact shape that
    ``web/services/artifacts.py`` already consumes; richer per-step detail is
    available via :meth:`step_results`.
    """

    run_id: str
    mode: str            # eod | intraday | refresh | data
    asof: str            # ISO date
    generated_at: str | None = None
    status: str = "completed"
    steps: dict[str, str] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        # NOTE: key order/shape kept compatible with the legacy run_meta.json.
        d: dict[str, Any] = {
            "mode": self.mode,
            "run_id": self.run_id,
            "asof": self.asof,
            "generated_at": self.generated_at or datetime.utcnow().isoformat(),
            "status": self.status,
            "steps": self.steps,
        }
        # Additive, optional fields — safe for older readers to ignore.
        if self.artifacts:
            d["artifacts"] = self.artifacts
        d["schema_version"] = self.schema_version
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RunManifest":
        return cls(
            run_id=str(d.get("run_id", "")),
            mode=str(d.get("mode", "")),
            asof=str(d.get("asof", "")),
            generated_at=d.get("generated_at"),
            status=str(d.get("status", "completed")),
            steps=dict(d.get("steps", {}) or {}),
            artifacts=list(d.get("artifacts", []) or []),
            schema_version=int(d.get("schema_version", SCHEMA_VERSION)),
        )

    def step_results(self) -> list[StepResult]:
        return [StepResult(name=k, status=v) for k, v in self.steps.items()]

    def write(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        return path

    @classmethod
    def read(cls, path: Path) -> "RunManifest":
        with Path(path).open("r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _isnan(x: Any) -> bool:
    try:
        return math.isnan(float(x))
    except (TypeError, ValueError):
        return True


def _max_drawdown(equity: Sequence[float]) -> float:
    """Most-negative drawdown of an equity curve. Returns a value <= 0."""
    peak = -math.inf
    mdd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (v - peak) / peak
            if dd < mdd:
                mdd = dd
    return mdd
