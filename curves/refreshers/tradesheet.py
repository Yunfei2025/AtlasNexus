"""Daily semi-systematic trade sheet for manual execution.

Consumes the regime-enriched Alpha candidates from alpha.py and produces
a concise, action-oriented daily summary grouped by conviction tier.

Usage:
    from curves.refreshers.tradesheet import generate_daily_tradesheet
    sheet = generate_daily_tradesheet(candidates_df)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd


# ── Conviction thresholds ───────────────────────────────────────────────────
_TIER1_SCORE = 1.5        # high-conviction threshold (score ≥ 1.5)
_TIER2_SCORE = 0.8        # medium-conviction threshold
_MIN_SCORE = 0.3          # below this → filtered out entirely

# Regime-alignment bonus: trending regime + trend signal agreement
_REGIME_ALIGNED_LABEL = "regime-aligned"


@dataclass
class TradeAction:
    """Single actionable trade recommendation."""
    rank: int
    trade_id: str
    category: str
    style: str
    direction: str               # BUY or SELL
    regime: str                  # trending / mean_reverting / uncertain
    score: float
    zscore: float
    spread_now: float
    target_spread: float         # reg_mean or trend target
    carry_H: float               # carry over horizon
    risk: float                  # risk_vol in return space
    conviction: str              # Tier1 / Tier2 / Tier3
    notes: str = ""


@dataclass
class DailyTradeSheet:
    """Container for the daily trade sheet output."""
    asof: date
    tier1: list[TradeAction] = field(default_factory=list)
    tier2: list[TradeAction] = field(default_factory=list)
    tier3: list[TradeAction] = field(default_factory=list)

    @property
    def all_actions(self) -> list[TradeAction]:
        return self.tier1 + self.tier2 + self.tier3

    def to_dataframe(self) -> pd.DataFrame:
        if not self.all_actions:
            return pd.DataFrame()
        records = []
        for a in self.all_actions:
            records.append({
                "rank": a.rank,
                "ID": a.trade_id,
                "category": a.category,
                "style": a.style,
                "direction": a.direction,
                "regime": a.regime,
                "score": round(a.score, 3),
                "Zscore": round(a.zscore, 2),
                "spread": round(a.spread_now, 4),
                "target": round(a.target_spread, 4),
                "carry_H": round(a.carry_H, 4),
                "risk": round(a.risk, 4),
                "conviction": a.conviction,
                "notes": a.notes,
            })
        return pd.DataFrame(records)

    def summary(self) -> str:
        lines = [f"═══ Daily Trade Sheet — {self.asof} ═══"]
        lines.append(f"  Tier 1 (high conviction): {len(self.tier1)} trades")
        lines.append(f"  Tier 2 (medium):          {len(self.tier2)} trades")
        lines.append(f"  Tier 3 (low):             {len(self.tier3)} trades")
        return "\n".join(lines)


def _build_notes(row: pd.Series) -> str:
    """Generate human-readable notes for a candidate row."""
    parts = []
    regime = str(row.get("regime", ""))
    trend_st = float(row.get("trend_state", 0.0)) if pd.notna(row.get("trend_state")) else 0.0
    regime_boost = float(row.get("regime_boost", 1.0)) if pd.notna(row.get("regime_boost")) else 1.0
    er = row.get("efficiency_ratio", np.nan)

    if regime == "trending":
        trend_dir = "UP" if trend_st > 0 else "DOWN" if trend_st < 0 else "FLAT"
        parts.append(f"trending({trend_dir})")
        if regime_boost > 1.0:
            parts.append(_REGIME_ALIGNED_LABEL)
    elif regime == "mean_reverting":
        hl = row.get("halflife", np.nan)
        if pd.notna(hl) and float(hl) > 0:
            parts.append(f"MR(hl={float(hl):.0f}d)")
    elif regime == "uncertain":
        parts.append("low-conviction regime")

    if pd.notna(er):
        parts.append(f"ER={float(er):.2f}")

    stationary = str(row.get("stationary", ""))
    if stationary.upper() == "YES":
        parts.append("stationary")

    return "; ".join(parts)


def generate_daily_tradesheet(
    candidates: pd.DataFrame,
    *,
    min_score: float = _MIN_SCORE,
    tier1_score: float = _TIER1_SCORE,
    tier2_score: float = _TIER2_SCORE,
    asof: Optional[date] = None,
) -> DailyTradeSheet:
    """Generate a tiered daily trade sheet from regime-enriched candidates.

    Parameters
    ----------
    candidates : pd.DataFrame
        Output of ``build_alpha_candidates()["candidates"]`` — must include
        regime, regime_confidence, trend_state, score, direction columns.
    min_score : float
        Minimum score to include in any tier.
    tier1_score, tier2_score : float
        Score thresholds for conviction tiers.
    asof : date, optional
        Override date stamp (defaults to today).

    Returns
    -------
    DailyTradeSheet
        Tiered trade actions ready for display or export.
    """
    sheet = DailyTradeSheet(asof=asof or date.today())

    if candidates is None or candidates.empty:
        return sheet

    df = candidates.copy()

    # Ensure numeric columns
    for col in ["score", "Zscore", "spread", "reg_mean", "mean", "carry_H", "risk",
                "trend_state", "regime_boost", "efficiency_ratio", "halflife"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Filter by minimum score
    score_col = df["score"] if "score" in df.columns else pd.Series(0.0, index=df.index)
    df = df[score_col.abs() >= min_score].copy()
    if df.empty:
        return sheet

    # Sort by score descending
    df = df.sort_values("score", ascending=False).reset_index(drop=True)

    rank = 0
    for _, row in df.iterrows():
        rank += 1
        score_val = float(row.get("score", 0.0)) if pd.notna(row.get("score")) else 0.0
        zscore_val = float(row.get("Zscore", 0.0)) if pd.notna(row.get("Zscore")) else 0.0
        spread_val = float(row.get("spread", 0.0)) if pd.notna(row.get("spread")) else 0.0
        # Target: use reg_mean if available, else OU mean
        target_val = float(row.get("reg_mean", np.nan))
        if not np.isfinite(target_val):
            target_val = float(row.get("mean", 0.0)) if pd.notna(row.get("mean")) else 0.0
        carry_val = float(row.get("carry_H", 0.0)) if pd.notna(row.get("carry_H")) else 0.0
        risk_val = float(row.get("risk", 0.0)) if pd.notna(row.get("risk")) else 0.0

        if score_val >= tier1_score:
            tier = "Tier1"
        elif score_val >= tier2_score:
            tier = "Tier2"
        else:
            tier = "Tier3"

        action = TradeAction(
            rank=rank,
            trade_id=str(row.get("ID", "")),
            category=str(row.get("category", "")),
            style=str(row.get("style", "")),
            direction=str(row.get("direction", "")),
            regime=str(row.get("regime", "unknown")),
            score=score_val,
            zscore=zscore_val,
            spread_now=spread_val,
            target_spread=target_val,
            carry_H=carry_val,
            risk=risk_val,
            conviction=tier,
            notes=_build_notes(row),
        )

        if tier == "Tier1":
            sheet.tier1.append(action)
        elif tier == "Tier2":
            sheet.tier2.append(action)
        else:
            sheet.tier3.append(action)

    return sheet
