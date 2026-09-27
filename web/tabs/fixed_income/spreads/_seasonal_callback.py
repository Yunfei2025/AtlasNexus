# -*- coding: utf-8 -*-
"""Orchestration for the Seasonal Pattern chart + stats panel
(graph-spread-seasonal / spread-seasonal-stats). Split out of the original
~400-line _update_seasonal closure in spreads.py: each spread-type branch
(BondNewIssue episode overlay, TBondCurve/CBondCurve OFR-ladder episode
overlay, TermBasis roll-cycle overlay, plain calendar-year overlay) is now a
top-level function here; register.py wires the @app.callback."""

from __future__ import annotations

import os

import pandas as pd
import plotly.graph_objs as go

from settings.paths import DIR_INPUT

from ._futures_figures import FUT_SPREADS, fut_stat_bucket
from ._pickle_cache import load_pickle_cached
from ._seasonal_stats_panels import (
    episode_bucket_stats_panel,
    term_basis_roll_cycle_stats_panel,
    monthly_seasonal_stats_panel,
)
from dash import html


def _empty_fig():
    return go.Figure(layout=dict(
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color="#ffffff"),
    ))


def _episode_overlay_title(base: str, pivot: pd.DataFrame, episode_duration_stats) -> str:
    """Append a "avg lifespan: N days (median M, n=K)" clause when at
    least 2 completed episodes exist, so the chart states up front
    how long this identity pairing typically holds before rolling."""
    dur = episode_duration_stats(pivot)
    if not dur:
        return base
    return (f"{base} · avg lifespan: {dur['mean_days']:.1f}d "
            f"(median {dur['median_days']:.0f}d, n={dur['n']})")


def _bondnewissue_seasonal(ticker, highlight_month, n_years):
    from web.tabs.alpha.seasonal import (
        episode_pivot, build_episode_overlay_figure, episode_bucket_stats,
        episode_duration_stats,
    )
    from web.tabs.alpha.data import load_newissue_episode_series, to_newissue_stage_label

    label = to_newissue_stage_label(ticker) if ':' in str(ticker) else ticker
    try:
        episodes = load_newissue_episode_series(label)
        pivot = episode_pivot(episodes)
    except Exception as e:
        print(f"[seasonal] BondNewIssue episode error for {label}: {e}")
        return _empty_fig(), html.Div()

    if pivot.empty:
        return _empty_fig(), html.Div(
            f"No episode history for {label}",
            style={"color": "#8fb3d9", "fontSize": "11px", "padding": "4px"},
        )

    bucket_stats = pd.DataFrame()
    try:
        bucket_stats = episode_bucket_stats(pivot)
    except Exception as e:
        print(f"[seasonal] BondNewIssue episode stats error: {e}")

    fig = build_episode_overlay_figure(
        pivot,
        title=_episode_overlay_title(f"{label} — episode overlay (day since roll)", pivot,
                                      episode_duration_stats),
        bucket_stats=bucket_stats,
    )

    try:
        stats_children = episode_bucket_stats_panel(bucket_stats)
    except Exception as e:
        print(f"[seasonal] BondNewIssue episode stats error: {e}")
        stats_children = html.Div()

    return fig, stats_children


def _ofr_ladder_seasonal(stype, ticker, highlight_month, n_years):
    # TBondCurve/CBondCurve OFR-ladder RV pair rows (ID = "ofrk_id|ofr1_id",
    # see curves/refreshers/otr_ofr_rv.py): episode-relative overlay (day
    # since a bond was promoted to OFR2/OFR3/...) across every historical
    # promotion in the same tenor bucket, instead of a calendar-year
    # overlay — each promotion only lasts weeks to a few months and isn't
    # anchored to a calendar date, so "day of year" is not meaningful.
    from web.tabs.alpha.seasonal import (
        episode_pivot, build_episode_overlay_figure, episode_bucket_stats,
        episode_duration_stats,
    )
    from web.tabs.alpha.data import load_otr_ofr_rv_episode_series

    asset_class = 'TBond' if stype == 'TBondCurve' else 'CBond'
    ofrk_id, _, ofr1_id = ticker.partition('|')
    try:
        episodes = load_otr_ofr_rv_episode_series(asset_class, ticker)
        pivot = episode_pivot(episodes)
    except Exception as e:
        print(f"[seasonal] {stype} OFR-ladder episode error for {ticker}: {e}")
        return _empty_fig(), html.Div()

    if pivot.empty:
        return _empty_fig(), html.Div(
            f"No OFR-ladder promotion history for {ofrk_id}",
            style={"color": "#8fb3d9", "fontSize": "11px", "padding": "4px"},
        )

    bucket_stats = pd.DataFrame()
    try:
        bucket_stats = episode_bucket_stats(pivot)
    except Exception as e:
        print(f"[seasonal] {stype} OFR-ladder episode stats error: {e}")

    fig = build_episode_overlay_figure(
        pivot,
        title=_episode_overlay_title(
            f"{ofrk_id} vs OFR1 — episode overlay (day since OFR2+ promotion)", pivot,
            episode_duration_stats,
        ),
        bucket_stats=bucket_stats,
    )

    try:
        stats_children = episode_bucket_stats_panel(bucket_stats)
    except Exception as e:
        print(f"[seasonal] {stype} OFR-ladder episode stats error: {e}")
        stats_children = html.Div()

    return fig, stats_children


def _term_basis_seasonal(ticker):
    # TermBasis: roll-cycle overlay (days-to-maturity of the front
    # contract, one line per historical quarterly roll) instead of a
    # calendar-year overlay — term basis is structurally driven by
    # proximity to the front contract's roll, not the calendar month.
    from web.tabs.alpha.seasonal import (
        roll_cycle_pivot, roll_cycle_bucket_stats, build_roll_cycle_figure,
    )

    tb = (load_pickle_cached(os.path.join(DIR_INPUT, "futures-spds.pkl")) or {}).get("TermBasis", {})
    dtm_df = tb.get("DaysToMaturity") if isinstance(tb, dict) else None
    basis_df = tb.get("Spread") if isinstance(tb, dict) else None
    price_basis_df = tb.get("PriceBasis") if isinstance(tb, dict) else None
    roll_df = tb.get("RollProgress") if isinstance(tb, dict) else None
    # FYTM (yield) basis is the primary series: differencing the two
    # contracts' implied yields cancels the common day-to-day yield
    # move, isolating the curve-slope/carry component between the two
    # delivery dates. Price basis (front − next settlement price) does
    # NOT have this cancellation -- both legs move with the market
    # every day, so it's just as noisy and is shown only as secondary
    # context, not as the primary mechanism series.
    if not isinstance(dtm_df, pd.DataFrame) or not isinstance(basis_df, pd.DataFrame) \
            or ticker not in dtm_df.columns or ticker not in basis_df.columns:
        return _empty_fig(), html.Div(
            f"No roll-cycle history for {ticker}",
            style={"color": "#8fb3d9", "fontSize": "11px", "padding": "4px"},
        )

    pivot = roll_cycle_pivot(dtm_df[ticker], basis_df[ticker])
    if pivot.empty:
        return _empty_fig(), html.Div(
            f"No roll-cycle history for {ticker}",
            style={"color": "#8fb3d9", "fontSize": "11px", "padding": "4px"},
        )

    bucket_stats = pd.DataFrame()
    try:
        bucket_stats = roll_cycle_bucket_stats(pivot)
    except Exception as e:
        print(f"[seasonal] TermBasis roll-cycle stats error: {e}")

    roll_pivot = pd.DataFrame()
    if isinstance(roll_df, pd.DataFrame) and ticker in roll_df.columns:
        try:
            roll_pivot = roll_cycle_pivot(dtm_df[ticker], roll_df[ticker])
        except Exception as e:
            print(f"[seasonal] TermBasis roll-progress pivot error: {e}")

    price_pivot = pd.DataFrame()
    if isinstance(price_basis_df, pd.DataFrame) and ticker in price_basis_df.columns:
        try:
            price_pivot = roll_cycle_pivot(dtm_df[ticker], price_basis_df[ticker])
        except Exception as e:
            print(f"[seasonal] TermBasis price-basis pivot error: {e}")

    fig = build_roll_cycle_figure(
        pivot,
        title=f"{ticker} — roll-cycle overlay (days to maturity, FYTM basis bp)",
        bucket_stats=bucket_stats,
        roll_progress_pivot=roll_pivot if not roll_pivot.empty else None,
        price_basis_pivot=price_pivot if not price_pivot.empty else None,
        y_title="FYTM basis (bp)",
    )

    stats_children = term_basis_roll_cycle_stats_panel(bucket_stats)
    return fig, stats_children


def _load_calendar_series(stype, ticker):
    """Acquire the spread series for the plain calendar-year overlay path."""
    series = None
    try:
        if stype in FUT_SPREADS:
            bucket = fut_stat_bucket(stype)
            if ticker in bucket:
                series = bucket[ticker][0]  # (series, mean, vol, max, min, ewm_vol, extra)
            elif bucket:
                series = next(iter(bucket.values()))[0]
        else:
            from web.tabs.alpha.data import load_spread_timeseries
            spd_df = load_spread_timeseries(stype)
            if isinstance(spd_df, pd.DataFrame) and not spd_df.empty:
                if ticker in spd_df.columns:
                    series = spd_df[ticker]
                elif spd_df.columns.size:
                    series = spd_df.iloc[:, 0]
                # load_spread_timeseries returns raw CNBD/IRS percent
                # values (e.g. 0.015 = 1.5bp) for correlation/backtest
                # callers that don't care about units -- but this chart
                # and its Monthly Statistics table display in bp (see
                # web/core/graphs.py::_primary_series, which applies the
                # same ×100 to the exact same pickles for the chart
                # above), so scale here too or AvgΔ rounds to "+0.0".
                if series is not None:
                    series = 100.0 * pd.to_numeric(series, errors='coerce')
    except Exception as e:
        print(f"[seasonal] series load error for {stype}/{ticker}: {e}")
    return series


def _calendar_year_seasonal(stype, ticker, highlight_month, n_years):
    from web.tabs.alpha.seasonal import seasonal_pivot, monthly_seasonal_stats, build_seasonal_overlay_figure

    series = _load_calendar_series(stype, ticker)
    if series is None or series.dropna().empty:
        return _empty_fig(), html.Div(
            f"No data for {ticker or stype}",
            style={"color": "#8fb3d9", "fontSize": "11px", "padding": "4px"},
        )

    # --- Compute seasonal statistics ---
    try:
        pivot = seasonal_pivot(series, years=n_years)
        stats = monthly_seasonal_stats(series, min_years=3)
    except Exception as e:
        print(f"[seasonal] compute error: {e}")
        return _empty_fig(), html.Div()

    # --- Build overlay figure ---
    try:
        title_ticker = ticker
        if stype == 'BondNewIssue' and ':' in str(ticker):
            from web.tabs.alpha.data import to_newissue_stage_label
            title_ticker = to_newissue_stage_label(ticker)

        # Bonds are non-fungible and often <2yr old, giving BondSwap too
        # little own history for a real calendar-year comparison. Overlay
        # a same-tenor curve-vs-swap reference (full history since 2015)
        # as a separate dashed line so the chart still shows a seasonal
        # tendency to compare against, without pretending it's this
        # bond's own past.
        reference_series = None
        if stype in ('TBondSwap', 'CBondSwap'):
            try:
                from web.tabs.alpha.data import get_bondswap_reference_series
                reference_series = get_bondswap_reference_series(stype, ticker)
            except Exception as e:
                print(f"[seasonal] BondSwap reference series error: {e}")

        fig = build_seasonal_overlay_figure(
            pivot,
            highlight_month=int(highlight_month) if highlight_month else None,
            stats=stats,
            title=f"{title_ticker} — seasonal year overlay",
            raw_series=series,
            spread_type=stype,
            reference_series=reference_series,
            reference_label="Reference (same-tenor curve − swap)",
        )
    except Exception as e:
        print(f"[seasonal] figure error: {e}")
        fig = _empty_fig()

    stats_children = monthly_seasonal_stats_panel(stats, highlight_month)
    return fig, stats_children


def update_seasonal(stype, ticker, highlight_month, n_years):
    """Dispatch to the right seasonal-overlay branch for *stype*."""
    if not ticker or not stype:
        return _empty_fig(), html.Div()

    n_years = int(n_years or 5)

    # BondNewIssue: episode-relative overlay (day-since-issuance/roll, one
    # line per historical episode) instead of a calendar-year overlay —
    # each pair identity only lives from one roll to the next (quarter,
    # at most a year), so "day of year" is not meaningful here.
    if stype == 'BondNewIssue':
        return _bondnewissue_seasonal(ticker, highlight_month, n_years)

    if stype in ('TBondCurve', 'CBondCurve') and isinstance(ticker, str) and '|' in ticker:
        return _ofr_ladder_seasonal(stype, ticker, highlight_month, n_years)

    if stype == 'TermBasis':
        return _term_basis_seasonal(ticker)

    return _calendar_year_seasonal(stype, ticker, highlight_month, n_years)
