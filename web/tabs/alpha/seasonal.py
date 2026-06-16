# -*- coding: utf-8 -*-
"""Seasonal analysis helpers for the Alpha Book Spread subtab.

Three pure, unit-testable functions:
  seasonal_pivot            -- reshape a spread series onto a day-of-year grid
  monthly_seasonal_stats    -- per-month edge table with binomial significance
  build_seasonal_overlay_figure  -- plotly year-overlay chart
"""

from __future__ import annotations

import datetime
from typing import Optional

import numpy as np
import pandas as pd

from .data import THEME

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Cumulative day-of-year at the start of each month (non-leap year baseline).
# Used for x-axis tick placement in the overlay chart.
_MONTH_START_DOY = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]


def _coerce_series(s: pd.Series) -> pd.Series:
    """Return a tz-naive DatetimeIndex copy of *s* with numeric values."""
    s = s.copy()
    s = pd.to_numeric(s, errors="coerce")
    try:
        s.index = pd.to_datetime(s.index)
        if getattr(s.index, "tz", None) is not None:
            s.index = s.index.tz_localize(None)
    except Exception:
        pass
    return s.sort_index()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def seasonal_pivot(s: pd.Series, years: int = 8) -> pd.DataFrame:
    """Reshape a spread series onto a day-of-year (1..366) × year grid.

    Parameters
    ----------
    s :
        Spread level time-series (DatetimeIndex, numeric values in bp or %).
    years :
        How many calendar years to include (most recent *years* years).

    Returns
    -------
    DataFrame with index = day-of-year (1..366, integer), columns = year (int).
    Values are spread levels; days with no trading data are NaN (NOT interpolated).
    Each year's series is **re-based to its own Jan-1 close** (first available
    trading day of the year) so that all years share the same zero starting point
    and the chart shows intra-year moves rather than absolute levels.
    """
    s = _coerce_series(s).dropna()
    if s.empty:
        return pd.DataFrame()

    max_year = s.index[-1].year
    min_year = max_year - years + 1

    result: dict[int, pd.Series] = {}
    for yr in range(min_year, max_year + 1):
        yr_data = s[s.index.year == yr]
        if yr_data.empty:
            continue
        # Re-base: subtract the first available value so intra-year Δ is visible
        base = yr_data.iloc[0]
        yr_data = yr_data - base
        doy = yr_data.index.day_of_year
        # Keep last observation per day-of-year (handles any duplicate dates)
        yr_series = yr_data.groupby(doy).last()
        yr_series.index.name = "day_of_year"
        result[yr] = yr_series

    if not result:
        return pd.DataFrame()

    pivot = pd.DataFrame(result)
    pivot.index = pivot.index.astype(int)
    pivot.columns = pivot.columns.astype(int)
    return pivot.sort_index()


def monthly_seasonal_stats(
    s: pd.Series,
    min_years: int = 3,
) -> pd.DataFrame:
    """Compute per-calendar-month seasonality statistics.

    For each month, the "monthly change" is defined as:
        last trading-day close of that month  −  last trading-day close of prior month.

    Parameters
    ----------
    s :
        Spread level time-series.
    min_years :
        Months observed in fewer than *min_years* calendar years are excluded.

    Returns
    -------
    DataFrame indexed 1..12 (calendar month) with columns:
        month_name   str    abbreviated month name
        n_years      int    number of calendar years with an observation
        avg_chg_bp   float  mean monthly change across years (bp or % units of *s*)
        consistency  float  fraction of years where direction == majority direction
        direction    str    "up" | "down" | "neutral"
        p_value      float  one-sided binomial p-value (H0: consistency ≤ 0.5)
        max_chg_bp   float  max monthly change in majority direction
        min_chg_bp   float  min monthly change in majority direction

    Months with n_years < min_years are omitted.
    """
    from scipy.stats import binomtest

    s = _coerce_series(s).dropna()
    if s.empty:
        return pd.DataFrame()

    # Month-end series: last trading day of each month
    monthly = s.resample("ME").last()
    changes = monthly.diff().dropna()

    rows = []
    for month in range(1, 13):
        obs = changes[changes.index.month == month].dropna()
        if len(obs) < min_years:
            continue
        n = len(obs)
        up_count = int((obs > 0).sum())
        dn_count = int((obs < 0).sum())
        majority_up = up_count >= dn_count

        if up_count > dn_count:
            direction = "up"
            consistency = up_count / n
            n_match = up_count
        elif dn_count > up_count:
            direction = "down"
            consistency = dn_count / n
            n_match = dn_count
        else:
            direction = "neutral"
            consistency = 0.5
            n_match = n // 2

        # One-sided binomial test: P(X >= n_match | p=0.5, n)
        result = binomtest(n_match, n, 0.5, alternative="greater")
        p_value = result.pvalue

        rows.append({
            "month":        month,
            "month_name":   _MONTH_ABBR[month - 1],
            "n_years":      n,
            "avg_chg_bp":   float(obs.mean()),
            "consistency":  float(consistency),
            "direction":    direction,
            "p_value":      float(p_value),
            "max_chg_bp":   float(obs.max()),
            "min_chg_bp":   float(obs.min()),
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).set_index("month")
    return df


def _yearly_seasonal_mean(s: pd.Series) -> pd.Series:
    """Compute a smooth historical-mean seasonal path using completed years only.

    For each day-of-year (1..366) we take the average *re-based* level across all
    completed calendar years in *s*.  A year is "completed" if it is strictly
    before the current calendar year.  Within each completed year the series is
    re-based to its own first available observation (matching seasonal_pivot logic),
    then we average across years at each day-of-year.

    The result is smoothed with a 7-day centred rolling window so the mean line
    reflects a broad seasonal tendency rather than individual-day noise.
    """
    s = _coerce_series(s).dropna()
    if s.empty:
        return pd.Series(dtype=float)

    current_year = datetime.date.today().year
    yearly_rebased: dict[int, pd.Series] = {}
    for yr in s.index.year.unique():
        if yr >= current_year:
            continue
        yr_data = s[s.index.year == yr]
        if yr_data.empty:
            continue
        base = yr_data.iloc[0]
        yr_data = yr_data - base
        doy = yr_data.index.day_of_year
        yearly_rebased[yr] = yr_data.groupby(doy).last()

    if not yearly_rebased:
        return pd.Series(dtype=float)

    frame = pd.DataFrame(yearly_rebased)
    mean_raw = frame.mean(axis=1)
    # 7-day centred rolling average to smooth out noise
    mean_smooth = mean_raw.rolling(window=7, center=True, min_periods=3).mean()
    mean_smooth.index = mean_smooth.index.astype(int)
    return mean_smooth.sort_index()


# Colorful palette for year lines (avoids grey).
# Cycles if more years than colours.
_YEAR_COLORS = [
    "#4e9de3",  # blue
    "#e06c3a",  # orange
    "#3aad6e",  # green
    "#c45cb5",  # purple
    "#d4b84a",  # gold
    "#e05c5c",  # red
    "#40bcd4",  # cyan
    "#9b7fe8",  # lavender
    "#6abf69",  # light green
    "#e87fad",  # pink
]


def build_seasonal_overlay_figure(
    pivot: pd.DataFrame,
    highlight_month: Optional[int],
    stats: Optional[pd.DataFrame],
    title: str = "",
    raw_series: Optional[pd.Series] = None,
) -> "go.Figure":
    """Build a Plotly year-overlay spread chart.

    Parameters
    ----------
    pivot :
        Output of :func:`seasonal_pivot` (index=day-of-year, columns=year).
    highlight_month :
        Calendar month (1-12) to shade with a vertical band, or None.
    stats :
        Output of :func:`monthly_seasonal_stats` (used for shading direction colour).
    title :
        Figure title string.
    raw_series :
        Original (un-pivoted) spread series. When provided the "Mean" line is
        computed as the smoothed average of all *completed* years so it reflects
        a true historical seasonal tendency rather than a day-by-day cross-section
        of whichever years happen to share a given trading day.

    Returns
    -------
    plotly.graph_objects.Figure
    """
    import plotly.graph_objects as go

    empty_layout = dict(
        plot_bgcolor=THEME["bg_main"],
        paper_bgcolor=THEME["bg_main"],
        font=dict(color=THEME["text_main"]),
    )

    if pivot is None or pivot.empty:
        return go.Figure(layout=empty_layout)

    years = sorted(pivot.columns.tolist())
    current_year = datetime.date.today().year
    n_years = len(years)

    traces = []

    for i, yr in enumerate(years):
        col = pivot[yr].dropna()
        if col.empty:
            continue

        is_current = (yr == current_year)

        if is_current:
            color = THEME["accent"]
            width = 2.5
            opacity = 1.0
            dash = "solid"
        else:
            # Assign a distinct colour from the palette; vary opacity slightly
            # so older years are subtler without becoming invisible.
            palette_idx = i % len(_YEAR_COLORS)
            color = _YEAR_COLORS[palette_idx]
            age_frac = i / max(n_years - 1, 1)  # 0=oldest, 1=newest-past
            width = 1.2
            opacity = 0.45 + age_frac * 0.45  # 0.45 → 0.90
            dash = "solid"

        traces.append(go.Scatter(
            x=col.index.tolist(),
            y=col.values.tolist(),
            mode="lines",
            name=str(yr),
            line=dict(color=color, width=width, dash=dash),
            opacity=opacity,
            hovertemplate=f"<b>{yr}</b><br>Day-of-year: %{{x}}<br>Δ: %{{y:.2f}}<extra></extra>",
        ))

    # Historical mean (smoothed over completed years) ± 1σ band
    past_years = [yr for yr in years if yr < current_year]
    if len(past_years) >= 2:
        if raw_series is not None and not raw_series.dropna().empty:
            mean_s = _yearly_seasonal_mean(raw_series)
        else:
            past_pivot = pivot[[yr for yr in pivot.columns if yr < current_year]]
            mean_raw = past_pivot.mean(axis=1)
            mean_s = mean_raw.rolling(window=7, center=True, min_periods=3).mean()
            mean_s.index = mean_s.index.astype(int)

        # ±1σ band from the past-year pivot (day-by-day std, unsmoothed)
        past_pivot_std = pivot[[yr for yr in pivot.columns if yr < current_year]]
        std_s = past_pivot_std.std(axis=1)
        upper = mean_s + std_s
        lower = mean_s - std_s
        common_doys = mean_s.dropna().index
        band_x = common_doys.tolist() + common_doys[::-1].tolist()
        band_y = upper.reindex(common_doys).values.tolist() + lower.reindex(common_doys).iloc[::-1].values.tolist()
        traces.append(go.Scatter(
            x=band_x, y=band_y,
            fill="toself",
            fillcolor="rgba(52,152,219,0.10)",
            line=dict(color="rgba(0,0,0,0)"),
            hoverinfo="skip",
            showlegend=False,
            name="±1σ band",
        ))
        traces.append(go.Scatter(
            x=common_doys.tolist(),
            y=mean_s.reindex(common_doys).values.tolist(),
            mode="lines",
            name="Hist. Mean",
            line=dict(color="rgba(52,152,219,0.80)", width=2.0, dash="dash"),
            hovertemplate="Hist. Mean<br>Day-of-year: %{x}<br>Δ: %{y:.2f}<extra></extra>",
        ))

    layout = go.Layout(
        plot_bgcolor=THEME["bg_main"],
        paper_bgcolor=THEME["bg_main"],
        font=dict(color=THEME["text_main"], size=11),
        title=dict(text=title, font=dict(size=12, color=THEME["text_sub"])) if title else None,
        xaxis=dict(
            title="Day of year",
            tickvals=_MONTH_START_DOY,
            ticktext=_MONTH_ABBR,
            gridcolor="#1a3a6a",
            zerolinecolor="#1a3a6a",
            range=[1, 366],
        ),
        yaxis=dict(
            title="Δ spread (re-based to Jan-1)",
            gridcolor="#1a3a6a",
            zerolinecolor="#2a5a9a",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.02,
            xanchor="right", x=1,
            font=dict(size=10),
        ),
        margin=dict(l=50, r=20, t=40, b=40),
        hovermode="x unified",
    )

    fig = go.Figure(data=traces, layout=layout)

    # Highlight the selected calendar month with a vertical band
    if highlight_month and 1 <= highlight_month <= 12:
        m = highlight_month - 1  # 0-based index
        x0 = _MONTH_START_DOY[m]
        x1 = _MONTH_START_DOY[m + 1] if m + 1 < 12 else 367

        # Colour the band by seasonal direction if stats are available
        band_color = "rgba(255,200,0,0.08)"
        if stats is not None and not stats.empty and highlight_month in stats.index:
            direction = stats.loc[highlight_month, "direction"]
            if direction == "up":
                band_color = "rgba(0,204,150,0.10)"
            elif direction == "down":
                band_color = "rgba(239,85,59,0.10)"

        fig.add_vrect(
            x0=x0, x1=x1,
            fillcolor=band_color,
            line_width=0,
            annotation_text=_MONTH_ABBR[m],
            annotation_position="top left",
            annotation=dict(font=dict(size=10, color=THEME["text_sub"])),
        )

    return fig
