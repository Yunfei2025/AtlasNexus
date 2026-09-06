# -*- coding: utf-8 -*-
"""Seasonal analysis helpers for the Alpha Book Spread subtab.

Pure, unit-testable functions:
  seasonal_pivot            -- reshape a spread series onto a day-of-year grid
  monthly_seasonal_stats    -- per-month edge table with binomial significance
  build_seasonal_overlay_figure  -- plotly year-overlay chart
  episode_pivot             -- reshape per-episode series onto a days-since-start grid
  build_episode_overlay_figure   -- plotly episode-overlay chart (BondNewIssue)
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
    and the chart shows intra-year moves rather than absolute levels. The
    discarded base level (and each year's latest absolute level) are kept on
    ``pivot.attrs["base_level"]`` / ``["last_level"]`` (dict of year -> float)
    so callers that need to report the actual level (e.g. chart legend/hover)
    don't have to re-derive it from the raw series.
    """
    s = _coerce_series(s).dropna()
    if s.empty:
        return pd.DataFrame()

    max_year = s.index[-1].year
    min_year = max_year - years + 1

    result: dict[int, pd.Series] = {}
    base_levels: dict[int, float] = {}
    last_levels: dict[int, float] = {}
    for yr in range(min_year, max_year + 1):
        yr_data = s[s.index.year == yr]
        if yr_data.empty:
            continue
        # Re-base: subtract the first available value so intra-year Δ is visible
        base = yr_data.iloc[0]
        base_levels[yr] = float(base)
        last_levels[yr] = float(yr_data.iloc[-1])
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
    pivot = pivot.sort_index()
    pivot.attrs["base_level"] = base_levels
    pivot.attrs["last_level"] = last_levels
    return pivot


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
    spread_type: Optional[str] = None,
    reference_series: Optional[pd.Series] = None,
    reference_label: str = "Reference (curve − swap)",
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
    spread_type :
        Spread type identifier (e.g. "TBondCurve", "FuturesSwap"). When the
        type is a China fixed-income product, known macro seasonal windows
        (CNY liquidity injection and quarter-end repo squeezes) are annotated.
    reference_series :
        Optional same-tenor proxy series (e.g. CGB/CDB par curve yield minus
        matched-tenor FR007 IRS) with a multi-year history, for instruments
        whose own history is too short for a real year-over-year comparison
        (e.g. a bond issued within the last 1-2 years). Plotted as a single
        dashed line -- the multi-year seasonal mean of the *reference*
        series, re-based the same way as the real per-year lines -- kept
        visually distinct (not blended into the per-year palette) since it
        does not represent this instrument's own actual history.
    reference_label :
        Legend label for the reference line.

    Returns
    -------
    plotly.graph_objects.Figure
    """
    import plotly.graph_objects as go

    empty_layout = dict(
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color=THEME["text_main"]),
    )

    if pivot is None or pivot.empty:
        return go.Figure(layout=empty_layout)

    years = sorted(pivot.columns.tolist())
    current_year = datetime.date.today().year
    n_years = len(years)
    base_levels: dict = pivot.attrs.get("base_level", {})

    traces = []

    for i, yr in enumerate(years):
        col = pivot[yr].dropna()
        if col.empty:
            continue

        is_current = (yr == current_year)
        base = base_levels.get(yr)
        legend_name = f"{yr} (base {base:+.1f})" if base is not None else str(yr)

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

        if base is not None:
            hovertemplate = (
                f"<b>{yr}</b> (base {base:+.1f})<br>Day-of-year: %{{x}}"
                "<br>Δ: %{y:.2f}<br>Level: %{customdata:.2f}<extra></extra>"
            )
            customdata = (col.values + base).tolist()
        else:
            hovertemplate = f"<b>{yr}</b><br>Day-of-year: %{{x}}<br>Δ: %{{y:.2f}}<extra></extra>"
            customdata = None

        traces.append(go.Scatter(
            x=col.index.tolist(),
            y=col.values.tolist(),
            mode="lines",
            name=legend_name,
            line=dict(color=color, width=width, dash=dash),
            opacity=opacity,
            customdata=customdata,
            hovertemplate=hovertemplate,
        ))

    # Historical mean (smoothed over completed years)
    past_years = [yr for yr in years if yr < current_year]
    if len(past_years) >= 2:
        if raw_series is not None and not raw_series.dropna().empty:
            mean_s = _yearly_seasonal_mean(raw_series)
        else:
            past_pivot = pivot[[yr for yr in pivot.columns if yr < current_year]]
            mean_raw = past_pivot.mean(axis=1)
            mean_s = mean_raw.rolling(window=7, center=True, min_periods=3).mean()
            mean_s.index = mean_s.index.astype(int)

        common_doys = mean_s.dropna().index
        traces.append(go.Scatter(
            x=common_doys.tolist(),
            y=mean_s.reindex(common_doys).values.tolist(),
            mode="lines",
            name="Hist. Mean",
            line=dict(color="rgba(52,152,219,0.80)", width=2.0, dash="dash"),
            hovertemplate="Hist. Mean<br>Day-of-year: %{x}<br>Δ: %{y:.2f}<extra></extra>",
        ))

    # Same-tenor proxy reference (e.g. curve yield − matched-tenor swap) for
    # instruments whose own history is too short for a real year-over-year
    # comparison. Shown as one dashed line -- the reference's OWN multi-year
    # seasonal mean -- kept visually and semantically separate from the
    # per-year palette above since it is not this instrument's actual data.
    if reference_series is not None and not reference_series.dropna().empty:
        ref_mean = _yearly_seasonal_mean(reference_series)
        ref_doys = ref_mean.dropna().index
        if len(ref_doys) > 0:
            traces.append(go.Scatter(
                x=ref_doys.tolist(),
                y=ref_mean.reindex(ref_doys).values.tolist(),
                mode="lines",
                name=reference_label,
                line=dict(color="rgba(170,176,192,0.85)", width=1.75, dash="dot"),
                hovertemplate=f"{reference_label}<br>Day-of-year: %{{x}}<br>Δ: %{{y:.2f}}<extra></extra>",
            ))

    layout = go.Layout(
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
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

    # China macro seasonal windows
    # Applied for all China bond / swap / futures spread types.
    # Two well-documented patterns:
    #   CNY window  (Jan–Feb): PBOC injects liquidity heavily before/after
    #       Chinese New Year → rates fall, spreads typically tighten → green.
    #   Quarter-end squeezes (Jun, Sep, Dec): banks hoard reserves for MPA
    #       reporting → short-rate spike, spreads typically widen → red.
    _CHINA_STYPES = {
        "TBondCurve", "TBondSwap",
        "CBondCurve", "CBondSwap",
        "SwapSpread",
        "FuturesSwap", "NetBasis", "TermBasis",
    }
    if spread_type in _CHINA_STYPES:
        _MACRO_BANDS = [
            # (month_start_1based, month_end_1based_inclusive, fill_color, label, label_color)
            (1, 2,  "rgba(0,204,150,0.07)",  "CNY liquidity",     "#00cc96"),
            (6, 6,  "rgba(239,85,59,0.07)",  "Q2-end squeeze",    "#ef553b"),
            (9, 9,  "rgba(239,85,59,0.07)",  "Q3-end squeeze",    "#ef553b"),
            (12, 12, "rgba(239,85,59,0.07)", "Y-end squeeze",     "#ef553b"),
        ]
        for m_start, m_end, fill, label, lcolor in _MACRO_BANDS:
            x0 = _MONTH_START_DOY[m_start - 1]
            x1 = _MONTH_START_DOY[m_end] if m_end < 12 else 367
            fig.add_vrect(
                x0=x0, x1=x1,
                fillcolor=fill,
                line_width=0,
                annotation_text=label,
                annotation_position="top left",
                annotation=dict(font=dict(size=9, color=lcolor)),
                layer="below",
            )

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


# ---------------------------------------------------------------------------
# Episode-relative overlay (BondNewIssue: day-since-roll, not calendar year)
# ---------------------------------------------------------------------------

def episode_pivot(episodes: list[tuple["pd.Timestamp", str, pd.Series]]) -> pd.DataFrame:
    """Reshape per-episode series onto a days-since-start × episode grid.

    Parameters
    ----------
    episodes :
        Output of ``load_newissue_episode_series`` — one (start_date,
        leg1_bond_code, series) tuple per contiguous issuance/roll episode,
        series indexed by integer days since that episode began (already
        re-based to 0 at day 0).

    Returns
    -------
    DataFrame with index = days since episode start, columns = leg1 bond code
    (the newly-issued leg of the pair), chronologically ordered. If the same
    bond code recurs across non-adjacent episodes, later occurrences are
    suffixed with the start date to keep columns unique.
    """
    if not episodes:
        return pd.DataFrame()

    result: dict[str, pd.Series] = {}
    for start_date, leg1_code, s in episodes:
        if s is None or s.empty:
            continue
        col = leg1_code
        if col in result:
            col = f"{leg1_code} ({start_date.strftime('%Y-%m-%d')})"
        result[col] = s

    if not result:
        return pd.DataFrame()

    pivot = pd.DataFrame(result)
    pivot.index.name = "days_since_start"
    return pivot.sort_index()


def _episode_median_band(pivot: pd.DataFrame, cols: list[str]) -> Optional[pd.DataFrame]:
    """Per-day cross-episode median and IQR (25th/75th pct) across *cols*.

    Only days with at least 3 contributing episodes are kept, matching the
    ``min_episodes`` floor used by :func:`episode_bucket_stats` so the band
    never implies confidence the underlying sample doesn't support.
    """
    if len(cols) < 3:
        return None
    sub = pivot[cols]
    counts = sub.count(axis=1)
    q25 = sub.quantile(0.25, axis=1)
    q50 = sub.quantile(0.50, axis=1)
    q75 = sub.quantile(0.75, axis=1)
    out = pd.DataFrame({"n": counts, "q25": q25, "q50": q50, "q75": q75})
    out = out[out["n"] >= 3]
    return out if not out.empty else None


def build_episode_overlay_figure(
    pivot: pd.DataFrame,
    title: str = "",
    bucket_stats: Optional[pd.DataFrame] = None,
) -> "go.Figure":
    """Build a Plotly episode-overlay chart: x=days since roll, one line per
    historical issuance/roll episode (see ``episode_pivot``), overlaid with a
    cross-episode median + IQR band.

    Individual episode lines are drawn thin and translucent — with 30-100+
    episodes typical for this event type, spaghetti-style overlays at full
    opacity make the dominant tendency (or lack of one) unreadable. The
    median/IQR band is the primary read; the "is there a pattern" question
    this chart answers is best judged from the band's slope and width, not
    from tracing individual lines.

    Parameters
    ----------
    bucket_stats :
        Output of :func:`episode_bucket_stats` for the same *pivot*. When
        given, day buckets with p < 0.10 get a marker on the median line so
        statistically-supported decay/widening points are visible at a
        glance instead of requiring a separate look at the stats table.
    """
    import plotly.graph_objects as go

    empty_layout = dict(
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color=THEME["text_main"]),
    )

    if pivot is None or pivot.empty:
        return go.Figure(layout=empty_layout)

    episode_cols = list(pivot.columns)  # already chronologically ordered
    n_episodes = len(episode_cols)

    traces = []
    for i, col in enumerate(episode_cols):
        s = pivot[col].dropna()
        if s.empty:
            continue

        is_latest = (i == n_episodes - 1)
        if is_latest:
            color = THEME["accent"]
            width = 2.0
            opacity = 0.95
        else:
            palette_idx = i % len(_YEAR_COLORS)
            color = _YEAR_COLORS[palette_idx]
            # Thin and faint: these are context, not the primary read — the
            # median/IQR band below carries the "is there a pattern" answer.
            width = 0.75
            opacity = 0.18

        traces.append(go.Scatter(
            x=s.index.tolist(),
            y=s.values.tolist(),
            mode="lines",
            name=col,
            line=dict(color=color, width=width),
            opacity=opacity,
            showlegend=is_latest,
            hovertemplate=f"<b>{col}</b><br>Day: %{{x}}<br>Δ: %{{y:.2f}}bp<extra></extra>",
        ))

    # Cross-episode median + IQR band, computed over all-but-latest episodes
    # so the ongoing episode isn't scored against its own history.
    past_cols = episode_cols[:-1] if n_episodes > 1 else []
    band = _episode_median_band(pivot, past_cols)
    if band is not None:
        traces.append(go.Scatter(
            x=band.index.tolist() + band.index.tolist()[::-1],
            y=band["q75"].tolist() + band["q25"].tolist()[::-1],
            fill="toself",
            fillcolor="rgba(52,152,219,0.15)",
            line=dict(color="rgba(0,0,0,0)"),
            hoverinfo="skip",
            name="IQR (25-75%)",
            showlegend=True,
        ))

        sig_days = set()
        if bucket_stats is not None and not bucket_stats.empty:
            sig_days = set(bucket_stats.index[bucket_stats["p_value"] < 0.10])

        marker_days = [d for d in band.index if d in sig_days]
        traces.append(go.Scatter(
            x=band.index.tolist(),
            y=band["q50"].tolist(),
            mode="lines+markers" if marker_days else "lines",
            name="Median",
            line=dict(color="#3498db", width=3.0),
            marker=dict(
                size=[9 if d in sig_days else 0 for d in band.index],
                color="#f1c40f",
                symbol="diamond",
                line=dict(color="#3498db", width=1),
            ),
            customdata=band["n"].tolist(),
            hovertemplate="Median<br>Day: %{x}<br>Δ: %{y:.2f}bp<br>n=%{customdata}<extra></extra>",
        ))

    layout = go.Layout(
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color=THEME["text_main"], size=11),
        title=dict(text=title, font=dict(size=12, color=THEME["text_sub"])) if title else None,
        xaxis=dict(
            title="Days since issuance/roll",
            gridcolor="#1a3a6a",
            zerolinecolor="#1a3a6a",
        ),
        yaxis=dict(
            title="Δ spread, bp (re-based to day 0)",
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
        annotations=[dict(
            text="◆ = day bucket with p<0.10 (see Issuance Statistics)",
            xref="paper", yref="paper", x=0, y=-0.14,
            showarrow=False, font=dict(size=9, color=THEME["text_sub"]),
        )] if band is not None else None,
    )
    return go.Figure(data=traces, layout=layout)


def episode_duration_stats(pivot: pd.DataFrame) -> dict:
    """Mean/median lifespan (in calendar days since day 0) of every episode
    in *pivot*, using each column's own last non-NaN index -- i.e. how long
    that specific (leg1, leg2) identity pairing actually held before the
    next roll/promotion replaced it. Excludes the still-open latest episode
    (its final length isn't known yet, so including it would understate the
    true average). Returns {} if fewer than 2 completed episodes exist.
    """
    if pivot is None or pivot.empty or pivot.shape[1] < 2:
        return {}
    # The latest (rightmost) column is the still-open current episode.
    past = pivot.iloc[:, :-1]
    lengths = past.apply(lambda col: col.dropna().index.max() if col.notna().any() else np.nan)
    lengths = lengths.dropna()
    if lengths.empty:
        return {}
    return {
        "n": int(len(lengths)),
        "mean_days": float(lengths.mean()),
        "median_days": float(lengths.median()),
    }


_ISSUANCE_DAY_BUCKETS = (10, 20, 30, 60, 90, 120, 150, 180, 270, 360)


def episode_bucket_stats(
    pivot: pd.DataFrame,
    buckets: tuple[int, ...] = _ISSUANCE_DAY_BUCKETS,
    min_episodes: int = 3,
) -> pd.DataFrame:
    """Cross-episode issuance-day statistics for BondNewIssue (analogue of
    ``monthly_seasonal_stats``, but bucketed by days since issuance/roll
    instead of calendar month).

    For each day bucket *d*, uses the last available Δ (re-based to day 0) at
    or before day *d* from every episode that has run at least that long, and
    reports the cross-episode consistency/direction of that Δ.

    Returns
    -------
    DataFrame indexed by day bucket, columns: n_episodes, avg_chg_bp,
    consistency, direction, p_value, max_chg_bp, min_chg_bp. Buckets with
    fewer than *min_episodes* qualifying episodes are omitted.
    """
    from scipy.stats import binomtest

    if pivot is None or pivot.empty:
        return pd.DataFrame()

    rows = []
    for d in buckets:
        vals = []
        for col in pivot.columns:
            s = pivot[col].dropna()
            if s.empty or s.index.max() < d:
                continue
            asof_idx = s.index[s.index <= d]
            if len(asof_idx) == 0:
                continue
            vals.append(float(s.loc[asof_idx.max()]))

        n = len(vals)
        if n < min_episodes:
            continue

        vals_s = pd.Series(vals)
        up_count = int((vals_s > 0).sum())
        dn_count = int((vals_s < 0).sum())
        if up_count > dn_count:
            direction, consistency, n_match = "up", up_count / n, up_count
        elif dn_count > up_count:
            direction, consistency, n_match = "down", dn_count / n, dn_count
        else:
            direction, consistency, n_match = "neutral", 0.5, n // 2

        p_value = binomtest(n_match, n, 0.5, alternative="greater").pvalue

        rows.append({
            "day":         d,
            "n_episodes":  n,
            "avg_chg_bp":  float(vals_s.mean()),
            "consistency": float(consistency),
            "direction":   direction,
            "p_value":     float(p_value),
            "max_chg_bp":  float(vals_s.max()),
            "min_chg_bp":  float(vals_s.min()),
        })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index("day")


# ---------------------------------------------------------------------------
# Roll-cycle overlay (Futures TermBasis: days-to-maturity of the front
# contract, not calendar year or days-since-start) — same "one line per
# historical cycle + median/IQR band" shape as the BondNewIssue episode
# overlay above, but keyed by proximity to the front contract's roll instead
# of proximity to issuance.
# ---------------------------------------------------------------------------

_ROLL_DTM_BUCKETS = (90, 60, 45, 30, 20, 10, 5, 2, 0)


def roll_cycle_pivot(dtm: "pd.Series", value: "pd.Series") -> "pd.DataFrame":
    """Reshape a (days-to-maturity, value) pair onto a DTM × roll-cycle grid.

    Parameters
    ----------
    dtm :
        Days-to-maturity of the front contract, one value per date (from
        ``futures-spds.pkl['TermBasis']['DaysToMaturity']``). Decreases toward
        0 within a cycle, then jumps back up when the front contract rolls —
        that jump is used to split the series into per-cycle segments.
    value :
        The series to bucket the same way (term basis, price basis, or roll
        progress), same DatetimeIndex as *dtm*.

    Returns
    -------
    DataFrame with index = days-to-maturity (descending toward 0), columns =
    cycle label (front contract's expiry year-month, chronologically
    ordered). Each cycle's *value* is NOT re-based -- levels are directly
    comparable across cycles (unlike the BondNewIssue Δ-from-day-0 overlay).
    """
    dtm = dtm.dropna()
    value = value.reindex(dtm.index).dropna()
    dtm = dtm.reindex(value.index)
    if dtm.empty:
        return pd.DataFrame()

    # A cycle boundary is a date where DTM increases vs. the prior date
    # (front contract just rolled to the next quarter).
    jump = dtm.diff() > 0
    cycle_id = jump.cumsum()

    result: dict[str, pd.Series] = {}
    for cid, idx in dtm.groupby(cycle_id).groups.items():
        d_seg = dtm.loc[idx]
        v_seg = value.loc[idx]
        if d_seg.empty:
            continue
        # Label each cycle by its target maturity month (last date + its own
        # DTM gives the maturity date directly) so consecutive cycles never
        # collide on a shared "last observed date" month.
        maturity = d_seg.index[-1] + pd.Timedelta(days=int(d_seg.iloc[-1]))
        label = maturity.strftime('%Y-%m')
        if label in result:
            label = f"{label} ({d_seg.index[0].strftime('%Y-%m-%d')})"
        seg = pd.Series(v_seg.values, index=d_seg.values.astype(int))
        seg = seg.groupby(seg.index).last()
        result[label] = seg

    if not result:
        return pd.DataFrame()

    pivot = pd.DataFrame(result)
    pivot.index.name = "days_to_maturity"
    return pivot.sort_index(ascending=False)


def roll_cycle_bucket_stats(
    pivot: "pd.DataFrame",
    buckets: tuple[int, ...] = _ROLL_DTM_BUCKETS,
    min_cycles: int = 3,
) -> "pd.DataFrame":
    """Cross-cycle statistics at fixed days-to-maturity checkpoints.

    Analogue of :func:`episode_bucket_stats` but for a descending
    days-to-maturity axis: for each checkpoint *d*, uses the first available
    observation at or before DTM=d (i.e. the closest approach to maturity
    without going past it) from every cycle that reached that far.

    Returns
    -------
    DataFrame indexed by DTM bucket (descending, i.e. farthest-from-maturity
    first), columns: n_cycles, avg_level, consistency, sign (of avg_level vs.
    0 -- "up"/"down" here means positive/negative *level*, NOT a trend),
    trend (change in avg_level from the prior, farther-from-maturity bucket
    -- "up"/"down" here means avg_level is rising/falling as DTM decreases,
    i.e. the actual convergence direction into the roll), p_value (for
    *sign*), max_level, min_level.
    """
    from scipy.stats import binomtest

    if pivot is None or pivot.empty:
        return pd.DataFrame()

    rows = []
    for d in buckets:
        vals = []
        for col in pivot.columns:
            s = pivot[col].dropna()
            if s.empty or s.index.min() > d:
                continue
            asof_idx = s.index[s.index <= d]
            if len(asof_idx) == 0:
                continue
            # Closest-to-maturity observation at or before DTM=d.
            vals.append(float(s.loc[asof_idx.max()]))

        n = len(vals)
        if n < min_cycles:
            continue

        vals_s = pd.Series(vals)
        up_count = int((vals_s > 0).sum())
        dn_count = int((vals_s < 0).sum())
        if up_count > dn_count:
            sign, consistency, n_match = "up", up_count / n, up_count
        elif dn_count > up_count:
            sign, consistency, n_match = "down", dn_count / n, dn_count
        else:
            sign, consistency, n_match = "neutral", 0.5, n // 2

        p_value = binomtest(n_match, n, 0.5, alternative="greater").pvalue

        rows.append({
            "dtm":         d,
            "n_cycles":    n,
            "avg_level":   float(vals_s.mean()),
            "consistency": float(consistency),
            "sign":        sign,
            "p_value":     float(p_value),
            "max_level":   float(vals_s.max()),
            "min_level":   float(vals_s.min()),
        })

    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).set_index("dtm")

    # Trend = change in avg_level from the prior (farther-from-maturity)
    # bucket -- buckets are already in descending-DTM order (farthest first,
    # per _ROLL_DTM_BUCKETS), so this reads left-to-right as "toward the
    # roll" and answers "is the spread converging" independent of sign.
    prev_level = out["avg_level"].shift(1)
    delta = out["avg_level"] - prev_level
    out["trend"] = np.where(
        prev_level.isna(), "n/a",
        np.where(delta > 0, "up", np.where(delta < 0, "down", "flat")),
    )
    return out


def build_roll_cycle_figure(
    pivot: "pd.DataFrame",
    title: str = "",
    bucket_stats: Optional["pd.DataFrame"] = None,
    roll_progress_pivot: Optional["pd.DataFrame"] = None,
    price_basis_pivot: Optional["pd.DataFrame"] = None,
    y_title: str = "Level",
) -> "go.Figure":
    """Build the days-to-maturity roll-cycle overlay for Futures TermBasis.

    Same visual language as :func:`build_episode_overlay_figure` (thin
    translucent per-cycle lines, latest cycle highlighted, median+IQR band)
    but the x-axis is days-to-maturity (descending, reversed so maturity is
    on the right) instead of days-since-start.

    Parameters
    ----------
    pivot :
        Output of :func:`roll_cycle_pivot` for the primary series -- the
        FYTM (yield) basis (front FYTM − next FYTM, bp) is preferred here
        because differencing the two contracts' implied yields cancels the
        common day-to-day yield move, isolating the curve-slope/carry
        component between the two delivery dates.
    roll_progress_pivot :
        Optional second pivot (same DTM axis) for OI roll-progress (0..1),
        overlaid on a secondary axis using only the cross-cycle median so the
        "does basis move with the roll" relationship reads at a glance.
    price_basis_pivot :
        Optional third pivot (same DTM axis) for the raw price basis
        (front − next settlement price, pts), overlaid on a tertiary axis
        using only the cross-cycle median. Unlike the FYTM basis, price
        basis does NOT cancel the common yield move (both legs are live
        tradeable prices), so it is noisier and shown only as secondary
        context alongside the FYTM-basis primary series.
    """
    import plotly.graph_objects as go

    empty_layout = dict(
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color=THEME["text_main"]),
    )

    if pivot is None or pivot.empty:
        return go.Figure(layout=empty_layout)

    cycle_cols = list(pivot.columns)
    n_cycles = len(cycle_cols)

    traces = []
    for i, col in enumerate(cycle_cols):
        s = pivot[col].dropna()
        if s.empty:
            continue
        is_latest = (i == n_cycles - 1)
        if is_latest:
            color, width, opacity = THEME["accent"], 2.0, 0.95
        else:
            palette_idx = i % len(_YEAR_COLORS)
            color = _YEAR_COLORS[palette_idx]
            width, opacity = 0.75, 0.18

        traces.append(go.Scatter(
            x=s.index.tolist(), y=s.values.tolist(),
            mode="lines", name=col,
            line=dict(color=color, width=width),
            opacity=opacity, showlegend=is_latest,
            hovertemplate=f"<b>{col}</b><br>DTM: %{{x}}<br>Level: %{{y:.2f}}<extra></extra>",
        ))

    past_cols = cycle_cols[:-1] if n_cycles > 1 else []
    band = _episode_median_band(pivot, past_cols)
    if band is not None:
        traces.append(go.Scatter(
            x=band.index.tolist() + band.index.tolist()[::-1],
            y=band["q75"].tolist() + band["q25"].tolist()[::-1],
            fill="toself", fillcolor="rgba(52,152,219,0.15)",
            line=dict(color="rgba(0,0,0,0)"), hoverinfo="skip",
            name="IQR (25-75%)", showlegend=True,
        ))
        sig_days = set()
        if bucket_stats is not None and not bucket_stats.empty:
            sig_days = set(bucket_stats.index[bucket_stats["p_value"] < 0.10])
        marker_days = [d for d in band.index if d in sig_days]
        traces.append(go.Scatter(
            x=band.index.tolist(), y=band["q50"].tolist(),
            mode="lines+markers" if marker_days else "lines",
            name="Median",
            line=dict(color="#3498db", width=3.0),
            marker=dict(size=[9 if d in sig_days else 0 for d in band.index],
                        color="#f1c40f", symbol="diamond",
                        line=dict(color="#3498db", width=1)),
            customdata=band["n"].tolist(),
            hovertemplate="Median<br>DTM: %{x}<br>Level: %{y:.2f}<br>n=%{customdata}<extra></extra>",
        ))

    _yaxis2 = None
    if roll_progress_pivot is not None and not roll_progress_pivot.empty:
        rp_median = roll_progress_pivot.median(axis=1, skipna=True).dropna()
        if not rp_median.empty:
            traces.append(go.Scatter(
                x=rp_median.index.tolist(), y=rp_median.values.tolist(),
                mode="lines", name="Median roll progress (OI share)",
                line=dict(color="#e05c5c", width=2.0, dash="dashdot"),
                yaxis="y2",
                hovertemplate="Median roll progress<br>DTM: %{x}<br>%{y:.2f}<extra></extra>",
            ))
            _yaxis2 = dict(title="OI share", overlaying="y", side="right",
                           range=[0, 1], showgrid=False, zeroline=False,
                           tickfont=dict(color="#e05c5c"), title_font=dict(color="#e05c5c"))

    _yaxis3 = None
    if price_basis_pivot is not None and not price_basis_pivot.empty:
        pb_median = price_basis_pivot.median(axis=1, skipna=True).dropna()
        if not pb_median.empty:
            traces.append(go.Scatter(
                x=pb_median.index.tolist(), y=pb_median.values.tolist(),
                mode="lines", name="Median price basis (pts)",
                line=dict(color="#b28cd6", width=1.5, dash="dot"),
                yaxis="y3",
                hovertemplate="Median price basis<br>DTM: %{x}<br>%{y:.3f}pts<extra></extra>",
            ))
            _yaxis3 = dict(title="Price basis (pts)", overlaying="y", side="right",
                           position=0.86, anchor="free",
                           showgrid=False, zeroline=False,
                           tickfont=dict(color="#b28cd6"), title_font=dict(color="#b28cd6"))

    layout = go.Layout(
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color=THEME["text_main"], size=11),
        title=dict(text=title, font=dict(size=12, color=THEME["text_sub"])) if title else None,
        xaxis=dict(
            title="Days to front-contract maturity",
            autorange="reversed",
            gridcolor="#1a3a6a", zerolinecolor="#2a5a9a",
        ),
        yaxis=dict(title=y_title, gridcolor="#1a3a6a", zerolinecolor="#2a5a9a"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=10)),
        margin=dict(l=50, r=70, t=40, b=40),
        hovermode="x unified",
        annotations=[dict(
            text="◆ = DTM checkpoint with p<0.10 (see Roll Statistics)",
            xref="paper", yref="paper", x=0, y=-0.14,
            showarrow=False, font=dict(size=9, color=THEME["text_sub"]),
        )] if band is not None else None,
    )
    if _yaxis2 is not None:
        layout.yaxis2 = _yaxis2
    if _yaxis3 is not None:
        layout.yaxis3 = _yaxis3
    return go.Figure(data=traces, layout=layout)

