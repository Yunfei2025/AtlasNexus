# -*- coding: utf-8 -*-
"""Top-level data loaders: snapshot, timeseries, realtime, and macro series."""

from __future__ import annotations

from typing import Optional
import re

import pandas as pd

from .constants import _build_tenor_spread_timeseries, _exclude_swapspread_butterflies, SPREAD_CATEGORIES
from .io import _get_input_dir, _load_pickle_safe, _normalize_repo_frame


_NEWISSUE_STAGE_LABELS = {
    'nib_otr': 'NIBOTR',
    'otr_ofr1': 'OTROFR1',
}


def _ofr_ladder_stage_label(k: int) -> str:
    """Compact label prefix for the OFR{k}-vs-OFR1 stage, e.g. 'OFR2OFR1'."""
    return f'OFR{k}OFR1'

# Reverse of ``NewIssueConfig.ISSUER_CLASS_MAP``: which universe artifact a
# label's issuer class comes from. Kept local so the web layer does not need a
# settings import for a two-entry mapping.
_ISSUER_ASSET_CLASSES = {
    'CGB': 'TBond',
    'CDB': 'CBond',
}

_ASSET_ISSUER_CLASSES = {asset: issuer for issuer, asset in _ISSUER_ASSET_CLASSES.items()}


def _newissue_id_cols() -> tuple[str, ...]:
    """('nib_id', 'otr_id', 'ofr1_id'..'ofr{depth}_id') -- driven by
    NewIssueConfig.OFR_LADDER_DEPTH so the issuer index below doesn't
    silently miss bonds that only ever reach a higher OFR rank."""
    from settings.fixed_income import NewIssueConfig
    depth = NewIssueConfig.OFR_LADDER_DEPTH
    return ('nib_id', 'otr_id') + tuple(f'ofr{k}_id' for k in range(1, depth + 1))

# {bond_code: issuer_class}, rebuilt when either universe artifact changes.
# Keyed by the (mtime, mtime) pair of the two source pickles.
_BOND_ISSUER_INDEX: dict[str, str] = {}
_BOND_ISSUER_INDEX_KEY: Optional[tuple] = None


def _bond_issuer_index() -> dict[str, str]:
    """Build (once per artifact revision) a {bond_code: issuer_class} index.

    Codes appearing under more than one issuer are dropped rather than
    arbitrarily assigned, so an ambiguous code resolves to None downstream.
    """
    global _BOND_ISSUER_INDEX, _BOND_ISSUER_INDEX_KEY

    dir_input = _get_input_dir()
    paths = {issuer: dir_input / f'{asset}-newissue.pkl'
             for issuer, asset in _ISSUER_ASSET_CLASSES.items()}
    key = tuple(sorted(
        (issuer, p.stat().st_mtime if p.exists() else None) for issuer, p in paths.items()
    ))
    if key == _BOND_ISSUER_INDEX_KEY:
        return _BOND_ISSUER_INDEX

    by_code: dict[str, set[str]] = {}
    for issuer_class, path in paths.items():
        data = _load_pickle_safe(path)
        if not isinstance(data, dict):
            continue
        for df in data.values():
            if not isinstance(df, pd.DataFrame) or df.empty:
                continue
            for col in _newissue_id_cols():
                if col not in df.columns:
                    continue
                for code in df[col].dropna().astype(str).unique():
                    by_code.setdefault(code, set()).add(issuer_class)

    _BOND_ISSUER_INDEX = {code: next(iter(issuers))
                          for code, issuers in by_code.items() if len(issuers) == 1}
    _BOND_ISSUER_INDEX_KEY = key
    return _BOND_ISSUER_INDEX


def _issuer_class_for_bond_id(bond_id: str) -> Optional[str]:
    """Resolve the issuer class ('CGB'/'CDB') that a bond code belongs to.

    Looks the code up in the per-asset-class universe artifacts rather than
    parsing the code convention, so it stays correct if issuance numbering
    changes. Returns None when the code appears in neither (or both).
    """
    bond_id = str(bond_id).strip()
    if not bond_id:
        return None
    return _bond_issuer_index().get(bond_id)


def to_newissue_stage_label(ticker: str) -> str:
    """Convert NewIssue ticker to canonical compact label.

    The raw ticker is ``<tenor>:<stage>:<leg1_id>|<leg2_id>`` and carries no
    issuer information, so the issuer class is resolved from the leg bond codes
    against the universe artifacts. Labels are issuer-qualified — e.g.
    ``OTROFR1-CGB10Y`` / ``NIBOTR-CDB5Y`` — because a CGB and a CDB cohort of
    the same tenor and stage are distinct instruments and must never share a
    column or a chart.

    Falls back to the unqualified ``OTROFR1-10Y`` form only when the issuer
    cannot be resolved.
    """
    m = re.match(r'^([^:]+):([^:]+):([^|]+)\|(.+)$', str(ticker))
    if not m:
        return str(ticker)
    tenor, stage, leg1, leg2 = m.group(1), m.group(2), m.group(3), m.group(4)
    stage_m = re.match(r'^ofr(\d+)_ofr1$', stage)
    if stage_m:
        stage_label = _ofr_ladder_stage_label(int(stage_m.group(1)))
    else:
        stage_label = _NEWISSUE_STAGE_LABELS.get(stage, stage.upper())
    issuer = _issuer_class_for_bond_id(leg1) or _issuer_class_for_bond_id(leg2)
    if issuer:
        return f"{stage_label}-{issuer}{tenor}"
    return f"{stage_label}-{tenor}"


def load_newissue_stage_timeseries() -> Optional[pd.DataFrame]:
    """Load canonical BondNewIssue stage series stitched across episode history.

    This reconstructs a continuous per-stage history from the backfilled
    ``TBond-newissue.pkl`` / ``CBond-newissue.pkl`` universe files so seasonal
    analytics can plot year-over-year overlays even though the dashboard-facing
    ``BondNewIssue-spds.pkl`` summary is only a compact snapshot.

    Output columns are issuer-qualified stage keys such as ``NIBOTR-CGB5Y``
    and ``OTROFR1-CDB10Y``. The issuer qualifier is required: without it the
    CGB and CDB cohorts of the same tenor collapse into one column under the
    pivot below, silently mixing two unrelated instruments.
    """
    dir_input = _get_input_dir()

    def _read_history(asset_class: str) -> list[pd.DataFrame]:
        data = _load_pickle_safe(dir_input / f'{asset_class}-newissue.pkl')
        if not isinstance(data, dict):
            return []
        out: list[pd.DataFrame] = []
        for tenor_bucket, df in data.items():
            if not isinstance(df, pd.DataFrame) or df.empty:
                continue
            frame = df.copy()
            frame.index = pd.to_datetime(frame.index)

            issuer = None
            if 'issuer_class' in frame.columns:
                issuers = frame['issuer_class'].dropna().astype(str)
                if not issuers.empty:
                    issuer = issuers.iloc[-1]
            if not issuer:
                issuer = _ASSET_ISSUER_CLASSES.get(asset_class, asset_class)
            bucket_key = f'{issuer}{tenor_bucket}'

            # OTR/OFR1 has the long-lived history we want for year-over-year overlays.
            if {'ytm_otr', 'ytm_ofr1'}.issubset(frame.columns):
                tmp = frame[['ytm_otr', 'ytm_ofr1']].copy()
                tmp['spread'] = pd.to_numeric(tmp['ytm_otr'], errors='coerce') - pd.to_numeric(tmp['ytm_ofr1'], errors='coerce')
                tmp = tmp.dropna(subset=['spread'])
                if not tmp.empty:
                    tmp['label'] = f'OTROFR1-{bucket_key}'
                    tmp['date'] = tmp.index
                    out.append(tmp[['label', 'spread', 'date']])

            # NIB/OTR is typically sparse because the NIB is new; keep any valid points.
            if {'ytm_nib', 'ytm_otr'}.issubset(frame.columns):
                tmp = frame[['ytm_nib', 'ytm_otr', 'instrument_id_nib_otr']].copy()
                tmp['spread'] = pd.to_numeric(tmp['ytm_nib'], errors='coerce') - pd.to_numeric(tmp['ytm_otr'], errors='coerce')
                tmp = tmp.dropna(subset=['spread'])
                if not tmp.empty:
                    tmp['label'] = f'NIBOTR-{bucket_key}'
                    tmp['date'] = tmp.index
                    out.append(tmp[['label', 'spread', 'date']])

            # OFR{k}-vs-OFR1 ladder history, moved here from TBondCurve's
            # mature-RV pairs per the 2026-09-06 decision. Scoped to
            # (TBond, 30Y) only -- 5Y/10Y TBond and every CBond bucket keep
            # using curves/refreshers/otr_ofr_rv.py's TBondCurve/CBondCurve
            # pairs unchanged, matching curves/refreshers/newissue_spreads.py
            # ``_STAGE_SCOPE``.
            if (asset_class, tenor_bucket) == ('TBond', '30Y'):
                from settings.fixed_income import NewIssueConfig
                for k in range(2, NewIssueConfig.OFR_LADDER_DEPTH + 1):
                    ytm_col = f'ytm_ofr{k}'
                    if not {ytm_col, 'ytm_ofr1'}.issubset(frame.columns):
                        continue
                    tmp = frame[[ytm_col, 'ytm_ofr1']].copy()
                    tmp['spread'] = pd.to_numeric(tmp[ytm_col], errors='coerce') - pd.to_numeric(tmp['ytm_ofr1'], errors='coerce')
                    tmp = tmp.dropna(subset=['spread'])
                    if not tmp.empty:
                        tmp['label'] = f'{_ofr_ladder_stage_label(k)}-{bucket_key}'
                        tmp['date'] = tmp.index
                        out.append(tmp[['label', 'spread', 'date']])
        return out

    frames = _read_history('TBond') + _read_history('CBond')
    if not frames:
        # Fallback to the compact summary artifact if universe history is missing.
        data = _load_pickle_safe(dir_input / 'BondNewIssue-spds.pkl')
        if not isinstance(data, dict):
            return None
        spread = data.get('BondNewIssue', {}).get('Spread') if isinstance(data.get('BondNewIssue'), dict) else None
        if not isinstance(spread, pd.DataFrame) or spread.empty:
            return None
        spread = spread.apply(pd.to_numeric, errors='coerce')
        return spread

    long_df = pd.concat(frames, axis=0, ignore_index=True)
    if long_df.empty:
        return None

    long_df['date'] = pd.to_datetime(long_df['date'])
    pivot = long_df.pivot_table(index='date', columns='label', values='spread', aggfunc='last').sort_index()
    pivot = pivot.apply(pd.to_numeric, errors='coerce')
    pivot = pivot.dropna(axis=1, how='all')
    return pivot if not pivot.empty else None


def _parse_newissue_stage_label(label: str) -> Optional[tuple[str, str, Optional[str]]]:
    """Reverse of ``to_newissue_stage_label``.

    ``'OTROFR1-CGB10Y'`` -> ``('otr_ofr1', '10Y', 'CGB')``.
    ``'OFR2OFR1-CGB30Y'`` -> ``('ofr2_ofr1', '30Y', 'CGB')``.
    The legacy unqualified form ``'OTROFR1-10Y'`` still parses, with issuer
    ``None`` meaning "issuer unknown — match every asset class".
    """
    m = re.match(r'^(NIBOTR|OTROFR1)-(CGB|CDB)?(.+)$', str(label))
    if m:
        stage = 'nib_otr' if m.group(1) == 'NIBOTR' else 'otr_ofr1'
        return stage, m.group(3), m.group(2)
    m = re.match(r'^OFR(\d+)OFR1-(CGB|CDB)?(.+)$', str(label))
    if m:
        return f'ofr{m.group(1)}_ofr1', m.group(3), m.group(2)
    return None


def _newissue_stage_columns(stage: str) -> tuple[str, str, str, str]:
    """(leg1_ytm_col, leg2_ytm_col, leg1_id_col, leg2_id_col) for a stage.

    ``otr_ofr1``/``nib_otr`` are the two original BondNewIssue stages;
    ``ofr{k}_ofr1`` (k=2..OFR_LADDER_DEPTH) is the OFR-ladder family moved
    here from TBondCurve's mature-RV pairs (curves/refreshers/otr_ofr_rv.py)
    per the 2026-09-06 decision -- OFR1 is always the reference leg (leg2),
    matching curves/calibration/otr_ofr_universe.py's
    spread_ofr{k}_ofr1 = ytm_ofr{k} - ytm_ofr1 convention.
    """
    if stage == 'otr_ofr1':
        return 'ytm_otr', 'ytm_ofr1', 'otr_id', 'ofr1_id'
    m = re.match(r'^ofr(\d+)_ofr1$', stage)
    if m:
        k = m.group(1)
        return f'ytm_ofr{k}', 'ytm_ofr1', f'ofr{k}_id', 'ofr1_id'
    return 'ytm_nib', 'ytm_otr', 'nib_id', 'otr_id'


def load_newissue_episode_series(label: str) -> list[tuple[pd.Timestamp, str, pd.Series]]:
    """Per-episode BondNewIssue spread paths, indexed by days since the
    episode's identity (leg1/leg2 bond pair) was established.

    Unlike ``load_newissue_stage_timeseries`` (a single calendar-indexed
    column), this splits the history into one series per contiguous run of a
    stable (leg1_id, leg2_id) pair — i.e. one series per issuance/roll episode
    — so callers can overlay "day 0 = new pair" through to the next roll
    (typically a quarter, at most a year) instead of a full calendar year.

    Returns a list of (start_date, leg1_bond_code, series) tuples, sorted
    chronologically. ``leg1_bond_code`` is the newly-issued leg of the pair
    (NIB for nib_otr, OTR for otr_ofr1) — used as the episode legend/label
    since it identifies the bond, unlike the start date.

    Only the issuer named by *label* is read: an ``OTROFR1-CGB10Y`` request
    returns CGB episodes alone, never the CDB 10Y cohort's. A legacy label
    without an issuer qualifier still spans both, preserving old behaviour.
    """
    parsed = _parse_newissue_stage_label(label)
    if parsed is None:
        return []
    stage, tenor_bucket, issuer_class = parsed
    leg1_col, leg2_col, id1_col, id2_col = _newissue_stage_columns(stage)

    if issuer_class:
        asset_classes = (_ISSUER_ASSET_CLASSES.get(issuer_class),)
        if asset_classes[0] is None:
            return []
    else:
        asset_classes = ('TBond', 'CBond')

    dir_input = _get_input_dir()
    episodes: list[tuple[pd.Timestamp, str, pd.Series]] = []
    for asset_class in asset_classes:
        data = _load_pickle_safe(dir_input / f'{asset_class}-newissue.pkl')
        if not isinstance(data, dict):
            continue
        df = data.get(tenor_bucket)
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        needed = {leg1_col, leg2_col, id1_col, id2_col}
        if not needed.issubset(df.columns):
            continue

        frame = df.copy()
        frame.index = pd.to_datetime(frame.index)
        sub = frame[[leg1_col, leg2_col, id1_col, id2_col]].copy()
        # CNBD yields are in percent (e.g. 0.015 = 1.5bp); ×100 so the
        # episode-overlay chart's y-axis reads in bp, matching every other
        # spread chart in this dashboard rather than an unlabeled raw %.
        sub['spread'] = 100.0 * (pd.to_numeric(sub[leg1_col], errors='coerce') - pd.to_numeric(sub[leg2_col], errors='coerce'))
        sub = sub.dropna(subset=['spread', id1_col, id2_col])
        if sub.empty:
            continue

        pair_key = sub[id1_col].astype(str) + '|' + sub[id2_col].astype(str)
        episode_id = (pair_key != pair_key.shift()).cumsum()
        for _, grp in sub.groupby(episode_id):
            if len(grp) < 2:
                continue
            start_date = grp.index[0]
            leg1_code = str(grp[id1_col].iloc[0])
            days_since_start = (grp.index - start_date).days
            rebased = grp['spread'].to_numpy() - grp['spread'].iloc[0]
            s = pd.Series(rebased, index=days_since_start)
            s = s[~s.index.duplicated(keep='last')].sort_index()
            episodes.append((start_date, leg1_code, s))

    episodes.sort(key=lambda item: item[0])
    return episodes


def load_otr_ofr_rv_episode_series(
    asset_class: str, ticker: str
) -> list[tuple[pd.Timestamp, str, pd.Series]]:
    """Per-episode OFR-ladder RV spread paths, indexed by trading days since
    a bond was promoted to that OFR rank.

    ``ticker`` is a TBondCurve/CBondCurve pair ID (``ofrk_id|ofr1_id``, see
    curves/refreshers/otr_ofr_rv.py) identifying which tenor bucket to read —
    the OFRk leg is looked up across ``ofr2_id..ofr{depth}_id`` in each
    bucket's newissue history to find the bucket it belongs to. Every bond's
    stint at rank OFR2..OFR{depth} in THAT bucket is a separate episode (not
    just the current pair's own bond), overlaying how the ladder has behaved
    across different promotions — never mixed across tenor buckets or across
    OFR1 (a different economic role: the reference leg every other rung
    prices against, not an RV leg itself).

    Mirrors ``load_newissue_episode_series``'s contiguous-run detection
    (group by identity-column runs, drop 1-row noise) applied to each rank
    column in turn, then collapsed to one row per calendar date so a bond
    promoted straight from OFR3 to OFR2 (skipping no days) still contributes
    one continuous episode rather than two overlapping ones.

    Returns a list of (start_date, bond_code, series) tuples, sorted
    chronologically. ``series`` is the OFRk-vs-OFR1 spread in bp, re-based to
    0 at day 0.
    """
    from settings.fixed_income import NewIssueConfig

    if not isinstance(ticker, str) or '|' not in ticker:
        return []
    ofrk_id, _, _ = ticker.partition('|')

    dir_input = _get_input_dir()
    data = _load_pickle_safe(dir_input / f'{asset_class}-newissue.pkl')
    if not isinstance(data, dict):
        return []

    depth = NewIssueConfig.OFR_LADDER_DEPTH
    tenor_bucket = None
    for bucket, df in data.items():
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        for k in range(2, depth + 1):
            id_col = f'ofr{k}_id'
            if id_col in df.columns and (df[id_col].astype(str) == ofrk_id).any():
                tenor_bucket = bucket
                break
        if tenor_bucket:
            break
    if tenor_bucket is None:
        return []

    df = data[tenor_bucket]
    frame = df.copy()
    frame.index = pd.to_datetime(frame.index)

    episodes: list[tuple[pd.Timestamp, str, pd.Series]] = []
    for k in range(2, depth + 1):
        id_col, ytm_col = f'ofr{k}_id', f'ytm_ofr{k}'
        if id_col not in frame.columns or ytm_col not in frame.columns or 'ytm_ofr1' not in frame.columns:
            continue
        sub = frame[[id_col, ytm_col, 'ytm_ofr1']].copy()
        # CNBD yields are in percent (e.g. 0.015 = 1.5bp); ×100 so the
        # episode-overlay chart's y-axis reads in bp.
        sub['spread'] = 100.0 * (pd.to_numeric(sub[ytm_col], errors='coerce') - pd.to_numeric(sub['ytm_ofr1'], errors='coerce'))
        sub = sub.dropna(subset=['spread', id_col])
        if sub.empty:
            continue

        run_id = (sub[id_col] != sub[id_col].shift()).cumsum()
        for _, grp in sub.groupby(run_id):
            if len(grp) < 2:
                continue
            start_date = grp.index[0]
            bond_code = str(grp[id_col].iloc[0])
            if not bond_code or bond_code in ('nan', 'None'):
                continue
            days_since_start = (grp.index - start_date).days
            rebased = grp['spread'].to_numpy() - grp['spread'].iloc[0]
            s = pd.Series(rebased, index=days_since_start)
            s = s[~s.index.duplicated(keep='last')].sort_index()
            episodes.append((start_date, bond_code, s))

    episodes.sort(key=lambda item: item[0])
    return episodes


def load_newissue_current_episode(
    label: str,
) -> Optional[pd.Series] | tuple[pd.Series, Optional[str]]:
    """Calendar-indexed spread series for *only* the current (leg1, leg2) pair.

    Unlike ``load_newissue_stage_timeseries`` (one column stitched across every
    historical bond pair for a stage/bucket) or ``load_newissue_episode_series``
    (every past episode, rebased and indexed by days-since-start), this returns
    just the still-open episode identified by the pair on the most recent row,
    on real calendar dates with un-rebased spread levels — what a "since this
    bond/stage was established" time series chart should plot. A brand-new NIB
    (e.g. issued days ago) will correctly return a short series starting at its
    own issue date, not several years of an unrelated predecessor bond's history.

    Returns ``None`` if nothing is found. Otherwise returns
    ``(spread_series, "leg1_id|leg2_id")`` — the pair label lets callers show
    the actual bond codes (e.g. the Spread Time Series chart title) even when
    ``load_newissue_pair_history``'s richer bond-level lookup comes up empty,
    which it always does for legs outside the standard pricing universe (e.g.
    30Y OFR-ladder bonds are not in TBond-cvpx.pkl, capped at
    BondConfig.PRICING_MAX_TTM=10.0).
    """
    parsed = _parse_newissue_stage_label(label)
    if parsed is None:
        return None
    stage, tenor_bucket, issuer_class = parsed
    leg1_col, leg2_col, id1_col, id2_col = _newissue_stage_columns(stage)

    if issuer_class:
        asset_classes = (_ISSUER_ASSET_CLASSES.get(issuer_class),)
        if asset_classes[0] is None:
            return None
    else:
        asset_classes = ('TBond', 'CBond')

    dir_input = _get_input_dir()
    best: Optional[tuple[pd.Series, str]] = None
    for asset_class in asset_classes:
        data = _load_pickle_safe(dir_input / f'{asset_class}-newissue.pkl')
        if not isinstance(data, dict):
            continue
        df = data.get(tenor_bucket)
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        needed = {leg1_col, leg2_col, id1_col, id2_col}
        if not needed.issubset(df.columns):
            continue

        frame = df.copy()
        frame.index = pd.to_datetime(frame.index)
        sub = frame[[leg1_col, leg2_col, id1_col, id2_col]].copy()
        # CNBD yields are in percent (e.g. 0.015 = 1.5bp); ×100 so the chart's
        # "bp" title/axis actually matches the plotted units.
        sub['spread'] = 100.0 * (pd.to_numeric(sub[leg1_col], errors='coerce') - pd.to_numeric(sub[leg2_col], errors='coerce'))
        sub = sub.dropna(subset=['spread', id1_col, id2_col])
        if sub.empty:
            continue
        # A row where both rank columns momentarily resolve to the same bond
        # code is a data quirk (e.g. an OFR rung briefly colliding with OFR1
        # during a roll), not a real pair -- same guard as
        # curves/refreshers/otr_ofr_rv.py's episode builder. Drop it so
        # "current episode" resolves to the last genuinely distinct pairing
        # instead of a meaningless self-spread with an unusable leg1==leg2
        # label.
        sub = sub[sub[id1_col].astype(str) != sub[id2_col].astype(str)]
        if sub.empty:
            continue

        pair_key = sub[id1_col].astype(str) + '|' + sub[id2_col].astype(str)
        current_pair = pair_key.iloc[-1]
        episode_id = (pair_key != pair_key.shift()).cumsum()
        current_episode = episode_id.iloc[-1]
        grp = sub[(episode_id == current_episode) & (pair_key == current_pair)]
        if grp.empty:
            continue
        s = grp['spread'].sort_index()
        s = s[~s.index.duplicated(keep='last')]
        if best is None or s.index[0] > best[0].index[0]:
            # Prefer whichever asset class's episode actually started most
            # recently -- the other's stale bucket (if issuer-unqualified) would
            # otherwise dominate the plotted window.
            best = (s, str(current_pair))
    return best


def load_newissue_pair_history(label: str) -> Optional[tuple[pd.Series, Optional[str], Optional[pd.Timestamp]]]:
    """Full yield-spread history for the current episode's two specific bonds.

    ``load_newissue_current_episode`` only returns the days this exact
    (leg1_id, leg2_id) pair held the OTR/OFR1 (or NIB/OTR) rank together --
    a bond freshly promoted into that rank (e.g. an OFR2 bond becoming OFR1)
    can show only a day or two even though both bonds have long, overlapping
    quote histories under their *previous* ranks. This instead resolves the
    two bond codes from the current episode, then reads their own
    ``ytm_quo`` history from ``{asset_class}-cvpx.pkl`` directly -- computing
    ``spread = ytm(leg1) - ytm(leg2)`` for every day both bonds quote,
    regardless of which rank either held that day.

    Returns ``(spread_series, switch_label, switch_date)`` where
    ``switch_date`` is the first date the current episode's rank pairing was
    confirmed (for a chart marker showing "the OTR/OFR1 label switched here"),
    and ``switch_label`` is the leg codes for that annotation. Returns None
    if the label doesn't parse or no bond-level history is found.
    """
    parsed = _parse_newissue_stage_label(label)
    if parsed is None:
        return None
    stage, tenor_bucket, issuer_class = parsed
    _, _, leg1_id_col, leg2_id_col = _newissue_stage_columns(stage)

    if issuer_class:
        asset_classes = (_ISSUER_ASSET_CLASSES.get(issuer_class),)
        if asset_classes[0] is None:
            return None
    else:
        asset_classes = ('TBond', 'CBond')

    dir_input = _get_input_dir()
    for asset_class in asset_classes:
        data = _load_pickle_safe(dir_input / f'{asset_class}-newissue.pkl')
        if not isinstance(data, dict):
            continue
        df = data.get(tenor_bucket)
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        if not {leg1_id_col, leg2_id_col}.issubset(df.columns):
            continue

        frame = df.copy()
        frame.index = pd.to_datetime(frame.index)
        ids = frame[[leg1_id_col, leg2_id_col]].dropna().astype(str)
        # A row where both rank columns momentarily resolve to the same bond
        # code is a data quirk, not a real pair -- guard the same way
        # curves/refreshers/otr_ofr_rv.py's episode builder does, since a
        # self-spread is meaningless and also breaks the column selection
        # below (two same-named columns select as a DataFrame, not a Series).
        ids = ids[ids[leg1_id_col] != ids[leg2_id_col]]
        if ids.empty:
            continue
        leg1_id, leg2_id = ids.iloc[-1][leg1_id_col], ids.iloc[-1][leg2_id_col]

        # First date this exact pair identity was confirmed, for the marker.
        pair_key = ids[leg1_id_col] + '|' + ids[leg2_id_col]
        current_pair = pair_key.iloc[-1]
        episode_id = (pair_key != pair_key.shift()).cumsum()
        current_episode = episode_id.iloc[-1]
        switch_date = ids.index[(episode_id == current_episode) & (pair_key == current_pair)][0]

        bond_px = _load_pickle_safe(dir_input / f'{asset_class}-cvpx.pkl')
        ytm_quo = bond_px.get('ytm_quo') if isinstance(bond_px, dict) else None
        if not isinstance(ytm_quo, pd.DataFrame) or leg1_id not in ytm_quo.columns or leg2_id not in ytm_quo.columns:
            continue

        panel = ytm_quo[[leg1_id, leg2_id]].copy()
        panel.index = pd.to_datetime(panel.index)
        leg1 = pd.to_numeric(panel[leg1_id], errors='coerce')
        leg2 = pd.to_numeric(panel[leg2_id], errors='coerce')
        # ytm_quo is in percent (e.g. 2.1678 = 2.1678%); ×100 so the chart's
        # "bp" title/axis actually matches the plotted units.
        s = (100.0 * (leg1 - leg2)).dropna().sort_index()
        s = s[~s.index.duplicated(keep='last')]
        if s.empty:
            continue
        return s, f'{leg1_id}|{leg2_id}', pd.Timestamp(switch_date)
    return None


def load_spread_data(spread_type: str) -> Optional[pd.DataFrame]:
    """Load spread data for a given type and return DataFrame with required columns."""
    dir_input = _get_input_dir()
    loaded_snap_df = None

    try:
        from curves.refreshers.alpha import get_alpha_spread_table

        snap_df = get_alpha_spread_table(spread_type, dir_input=dir_input)
        if snap_df is not None and isinstance(snap_df, pd.DataFrame) and not snap_df.empty:
            snap_df = _normalize_repo_frame(snap_df)
            if spread_type == 'SwapSpread':
                snap_df = snap_df[~snap_df.index.astype(str).str.endswith('.IR')].copy()
                snap_df = snap_df[_exclude_swapspread_butterflies(snap_df.index)].copy()
            if spread_type != 'TenorSpread':
                return snap_df
            loaded_snap_df = snap_df
    except Exception:
        pass

    if spread_type in ['TBondCurve', 'TBondSwap']:
        data = _load_pickle_safe(dir_input / 'TBond-spds.pkl')
        if data is None:
            return None
        key = 'BondCurve' if spread_type == 'TBondCurve' else 'BondSwap'
        return data.get(key, {}).get('StatInfo')

    elif spread_type in ['CBondCurve', 'CBondSwap']:
        data = _load_pickle_safe(dir_input / 'CBond-spds.pkl')
        if data is None:
            return None
        key = 'BondCurve' if spread_type == 'CBondCurve' else 'BondSwap'
        return data.get(key, {}).get('StatInfo')

    elif spread_type == 'SwapSpread':
        data = _load_pickle_safe(dir_input / 'IRS-pxspds.pkl')
        if data is None:
            return None
        df = data.get('StatInfo')
        if isinstance(df, pd.DataFrame) and not df.empty:
            df = df[~df.index.astype(str).str.endswith('.IR')].copy()
            df = df[_exclude_swapspread_butterflies(df.index)].copy()
            return df
        return None

    elif spread_type == 'TenorSpread':
        loaded_df = loaded_snap_df
        try:
            from curves.utils.loader import loadCNBDTS
            tenor_ts = _build_tenor_spread_timeseries(loadCNBDTS())
            if tenor_ts:
                fallback_df = pd.DataFrame({
                    'spread': {name: pd.to_numeric(series, errors='coerce').dropna().iloc[-1]
                               for name, series in tenor_ts.items()
                               if isinstance(series, pd.Series) and not pd.to_numeric(series, errors='coerce').dropna().empty}
                })
                if loaded_df is not None and not loaded_df.empty:
                    return loaded_df.reindex(columns=loaded_df.columns.union(fallback_df.columns)).combine_first(fallback_df)
                loaded_df = fallback_df
        except Exception:
            pass
        if loaded_df is not None and not loaded_df.empty:
            return loaded_df
        return None

    elif spread_type == 'NetBasis':
        data = _load_pickle_safe(dir_input / 'futures-spds.pkl')
        if data is None:
            return None
        nb_data = data.get('NetBasis', {})
        frames = []
        for contract, cdata in nb_data.items():
            if isinstance(cdata, dict) and 'StatInfo' in cdata:
                df = cdata['StatInfo'].copy()
                df['contract'] = contract
                frames.append(df)
        return pd.concat(frames, axis=0) if frames else None

    elif spread_type == 'TermBasis':
        data = _load_pickle_safe(dir_input / 'futures-spds.pkl')
        if data is None:
            return None
        return data.get('TermBasis', {}).get('StatInfo')

    elif spread_type == 'FuturesSwap':
        data = _load_pickle_safe(dir_input / 'futures-spds.pkl')
        if data is None:
            return None
        fs = data.get('FuturesSwap', {})
        if not isinstance(fs, dict) or not fs:
            return None
        frames = []
        for ctype, cdata in fs.items():
            if isinstance(cdata, dict) and 'StatInfo' in cdata:
                df = cdata['StatInfo'].copy()
                df['ctype'] = ctype
                frames.append(df)
        return pd.concat(frames, axis=0) if frames else None

    elif spread_type == 'PCASpread':
        data = _load_pickle_safe(dir_input / 'Misc-spds.pkl')
        if data is None:
            return None
        return data.get('PCASpread', {}).get('StatInfo')

    elif spread_type == 'BinarySpread':
        data = _load_pickle_safe(dir_input / 'Misc-spds.pkl')
        if data is None:
            return None
        return data.get('BinarySpread', {}).get('StatInfo')

    elif spread_type == 'BondNewIssue':
        data = _load_pickle_safe(dir_input / 'BondNewIssue-spds.pkl')
        if data is None:
            return None
        return data.get('BondNewIssue', {}).get('StatInfo')

    return None


def load_carry_roll_timeseries(spread_type: str) -> Optional[pd.DataFrame]:
    """Load daily 3m carry+roll time series for each instrument (in bp)."""
    dir_input = _get_input_dir()

    if spread_type in ('TBondSwap', 'CBondSwap'):
        prefix = 'TBond' if spread_type == 'TBondSwap' else 'CBond'
        data = _load_pickle_safe(dir_input / f'{prefix}-spds.pkl')
        if isinstance(data, dict):
            carry = data.get('BondSwap', {}).get('BondCarry')
            if isinstance(carry, pd.DataFrame) and not carry.empty:
                # BondCarry = (bond_yield - FR007S3M) * 100 = annual spread in bp.
                # Convert to 3m carry in % to match spread_ts units (also in %):
                #   bp → % : / 100
                #   annual → 3m : * (90/360)
                #   combined: / 400
                return carry.apply(pd.to_numeric, errors='coerce') / 400.0
        return None

    if spread_type in ('TBondCurve', 'CBondCurve'):
        prefix = 'TBond' if spread_type == 'TBondCurve' else 'CBond'
        data = _load_pickle_safe(dir_input / f'{prefix}-spds.pkl')
        if isinstance(data, dict):
            spd = data.get('BondCurve', {}).get('Spread')
            if isinstance(spd, pd.DataFrame) and not spd.empty:
                # Spread is annual yield difference in % (e.g. 0.01 = 1bp).
                # Convert to 3m carry in % to match price_pnl units:
                #   annual % → 3m % : * (90/360)
                return spd.apply(pd.to_numeric, errors='coerce') * (90.0 / 360.0)
        return None

    if spread_type == 'SwapSpread':
        data = _load_pickle_safe(dir_input / 'IRS-pxspds.pkl')
        if isinstance(data, dict):
            cr = data.get('CarryRoll3m')
            if isinstance(cr, pd.DataFrame) and not cr.empty:
                # CarryRoll3m is already stored as 3m carry in % (carry3m + roll3m
                # from generators/irs.py are in % after / 100 conversion).
                # No further scaling needed.
                return cr.apply(pd.to_numeric, errors='coerce')
        return None

    if spread_type == 'TenorSpread':
        # Primary: read from pre-computed Tenor-spds.pkl written by StatGenerator.
        tenor_spds = _load_pickle_safe(dir_input / 'Tenor-spds.pkl')
        if isinstance(tenor_spds, dict):
            cr = tenor_spds.get('TenorSpread', {}).get('CarryRoll3m')
            if isinstance(cr, pd.DataFrame) and not cr.empty:
                return cr.apply(pd.to_numeric, errors='coerce')

        # Fallback: compute on-the-fly from database-px.pkl.
        # Carry component in 3m %, to match spread_ts units (raw CNBD yield diff in %).
        # Convention for _carry_accrual: ts[t] = 3m carry in %, so that
        #   carry_income = position * sum(ts[t0:t1]) / 90  is in %
        # and the final *100 in run_spread_backtest converts to bp.
        #
        # Annual carry for each structure:
        #   XsYs (CGB-5s10s, CDB-5s10s)  BUY=steepener: carry = Y_short - Y_long = -spread_%
        #   CDBCGB cross-sector      BUY=long CDB : carry = Y_CDB - Y_CGB   = +spread_%
        #   Fly (NsMsLs, 3 tenors)   BUY=long belly: carry = 2*Y_belly - Y_short - Y_long = +spread_%
        # Convert annual % → 3m %: multiply by 90/360.
        # Negate XsYs (\d+s\d+) columns; CDBCGB and flies stay positive.
        try:
            import re
            db = _load_pickle_safe(dir_input / 'database-px.pkl')
            if isinstance(db, dict) and 'CGB' in db and 'CDB' in db:
                tenor_ts = _build_tenor_spread_timeseries(db)
                if tenor_ts:
                    df = pd.DataFrame(tenor_ts).apply(pd.to_numeric, errors='coerce') * (90.0 / 360.0)
                    for col in df.columns:
                        if len(re.findall(r'\d+s', col, re.IGNORECASE)) >= 3:
                            continue  # fly: carry = +spread, no negation
                        if re.search(r'\d+s\d+', col, re.IGNORECASE):
                            df[col] = -df[col]
                    return df
        except Exception:
            pass
        return None

    return None


def display_key(spread_type: str, inst: str) -> str:
    """Return a short, human-readable column key for correlation matrices.

    Bond IDs share the same code across Curve/Swap types, so the suffix
    disambiguates.  Futures types (NetBasis / TermBasis / FuturesSwap) all use
    T/TF/TS/TL, so a suffix is mandatory there too.
    """
    if spread_type in ('TBondCurve', 'CBondCurve'):
        return f'{inst}-OTR'
    if spread_type in ('TBondSwap', 'CBondSwap'):
        return f'{inst}-Swp'
    if spread_type == 'NetBasis':
        return f'{inst}-Basis'
    if spread_type == 'TermBasis':
        return f'{inst}-Cal'
    if spread_type == 'FuturesSwap':
        return f'{inst}-FtSwp'
    # All other types (SwapSpread, TenorSpread, PCASpread …) have unique IDs —
    # return as-is so existing behaviour is unchanged.
    return inst


def load_spread_timeseries(spread_type: str) -> Optional[pd.DataFrame]:
    """Load historical spread time series for correlation analysis."""
    dir_input = _get_input_dir()

    alpha_snapshot = _load_pickle_safe(dir_input / 'Alpha-spreadsrt.pkl')
    if alpha_snapshot and isinstance(alpha_snapshot, dict):
        timeseries_data = alpha_snapshot.get('_timeseries', {})
        if isinstance(timeseries_data, dict) and spread_type in timeseries_data:
            ts = timeseries_data[spread_type]
            if isinstance(ts, pd.DataFrame) and not ts.empty:
                if spread_type == 'SwapSpread':
                    cols = pd.Index(ts.columns.astype(str))
                    ts = ts.loc[:, ~cols.str.endswith('.IR')].copy()
                    ts = ts.loc[:, _exclude_swapspread_butterflies(pd.Index(ts.columns))].copy()
                return ts

    if spread_type in ['TBondCurve', 'TBondSwap']:
        filepath = dir_input / 'TBond-spds.pkl'
        data = _load_pickle_safe(filepath)
        if data is None:
            return None
        key = 'BondCurve' if spread_type == 'TBondCurve' else 'BondSwap'
        if isinstance(data, dict) and key in data:
            nested = data[key]
            if isinstance(nested, dict) and 'Spread' in nested:
                result = _normalize_repo_frame(nested['Spread'])
                return result
        return None

    elif spread_type in ['CBondCurve', 'CBondSwap']:
        filepath = dir_input / 'CBond-spds.pkl'
        data = _load_pickle_safe(filepath)
        if data is None:
            return None
        key = 'BondCurve' if spread_type == 'CBondCurve' else 'BondSwap'
        if isinstance(data, dict) and key in data:
            nested = data[key]
            if isinstance(nested, dict) and 'Spread' in nested:
                result = _normalize_repo_frame(nested['Spread'])
                return result
        return None

    elif spread_type == 'PCASpread':
        filepath = dir_input / 'Misc-spds.pkl'
        data = _load_pickle_safe(filepath)
        if data is None:
            return None
        if isinstance(data, dict) and 'PCASpread' in data:
            nested = data['PCASpread']
            if isinstance(nested, dict) and 'Spread' in nested:
                result = _normalize_repo_frame(nested['Spread'])
                return result
        return None

    elif spread_type == 'SwapSpread':
        filepath = dir_input / 'IRS-pxspds.pkl'
        data = _load_pickle_safe(filepath)
        if data is None:
            return None
        if isinstance(data, dict) and 'Spread' in data:
            df_spread = data.get('Spread')
            if isinstance(df_spread, pd.DataFrame) and not df_spread.empty:
                df_spread = _normalize_repo_frame(df_spread)
                cols = pd.Index(df_spread.columns.astype(str))
                df_spread = df_spread.loc[:, ~cols.str.endswith('.IR')].copy()
                df_spread = df_spread.loc[:, _exclude_swapspread_butterflies(pd.Index(df_spread.columns))].copy()
                return df_spread
        return None

    elif spread_type == 'TenorSpread':
        # Primary: pre-computed Tenor-spds.pkl is the canonical source of truth
        # (same source as the Spread sub-tab / dropdown via load_spread_data).
        loaded_df = None
        tenor_spds = _load_pickle_safe(dir_input / 'Tenor-spds.pkl')
        if isinstance(tenor_spds, dict):
            spd = tenor_spds.get('TenorSpread', {}).get('Spread')
            if isinstance(spd, pd.DataFrame) and not spd.empty:
                loaded_df = spd.apply(pd.to_numeric, errors='coerce')

        # Fallback: rebuild from database-px.pkl via loadCNBDTS if the pkl is unavailable.
        try:
            from curves.utils.loader import loadCNBDTS
            env = loadCNBDTS()
            tenor_ts = _build_tenor_spread_timeseries(env)
            if tenor_ts:
                df = pd.DataFrame(tenor_ts)
                df = df.apply(pd.to_numeric, errors='coerce')
                if loaded_df is not None and not loaded_df.empty:
                    return loaded_df.reindex(columns=loaded_df.columns.union(df.columns)).combine_first(df)
                return df
        except Exception:
            pass

        if loaded_df is not None and not loaded_df.empty:
            return loaded_df

        return None

    elif spread_type == 'NetBasis':
        data = _load_pickle_safe(dir_input / 'futures-spds.pkl')
        if data is None:
            return None
        nb_data = data.get('NetBasis', {})
        if not isinstance(nb_data, dict):
            return None
        frames = []
        for ctype, cdata in nb_data.items():
            if isinstance(cdata, dict) and 'Spread' in cdata:
                sp = cdata['Spread']
                if isinstance(sp, pd.DataFrame) and not sp.empty:
                    frames.append(sp)
        return pd.concat(frames, axis=1) if frames else None

    elif spread_type == 'TermBasis':
        data = _load_pickle_safe(dir_input / 'futures-spds.pkl')
        if data is None:
            return None
        tb = data.get('TermBasis', {})
        if isinstance(tb, dict) and 'Spread' in tb:
            sp = tb['Spread']
            return sp if isinstance(sp, pd.DataFrame) and not sp.empty else None
        return None

    elif spread_type == 'FuturesSwap':
        data = _load_pickle_safe(dir_input / 'futures-spds.pkl')
        if data is None:
            return None
        fs = data.get('FuturesSwap', {})
        if not isinstance(fs, dict):
            return None
        frames = []
        for ctype, cdata in fs.items():
            if isinstance(cdata, dict) and 'Spread' in cdata:
                sp = cdata['Spread']
                if isinstance(sp, pd.DataFrame) and not sp.empty:
                    frames.append(sp)
        return pd.concat(frames, axis=1) if frames else None

    elif spread_type == 'BondNewIssue':
        return load_newissue_stage_timeseries()

    return None


def load_macro_series(series_name: str) -> Optional[pd.Series]:
    """Load macro time series used for bond-swap style trades."""
    try:
        from curves.utils.loader import loadCNBDTS
    except Exception:
        return None

    try:
        env = loadCNBDTS()
        cgb = env.get('CGB')
        swap = env.get('SwapTS')
        if cgb is None or swap is None:
            return None

        if series_name == 'TBond-FR007:1Y':
            s = cgb['中债国债到期收益率:1年'] - swap['FR007S1Y.IR']
        elif series_name == 'TBond-FR007:5Y':
            s = cgb['中债国债到期收益率:5年'] - swap['FR007S5Y.IR']
        else:
            return None

        s = pd.to_numeric(s, errors='coerce').dropna()
        s.name = series_name
        return s
    except Exception:
        return None


def load_realtime_spreads(spread_type: str) -> Optional[pd.DataFrame]:
    """Load realtime spread data (refreshed by StatRefresher)."""
    dir_input = _get_input_dir()

    if spread_type in ['TBondCurve', 'TBondSwap']:
        data = _load_pickle_safe(dir_input / 'TBond-spdsrt.pkl')
        if data is None:
            return None
        key = 'BondCurve' if spread_type == 'TBondCurve' else 'BondSwap'
        return _normalize_repo_frame(data.get(key))

    elif spread_type in ['CBondCurve', 'CBondSwap']:
        data = _load_pickle_safe(dir_input / 'CBond-spdsrt.pkl')
        if data is None:
            return None
        key = 'BondCurve' if spread_type == 'CBondCurve' else 'BondSwap'
        return _normalize_repo_frame(data.get(key))

    elif spread_type == 'SwapSpread':
        data = _load_pickle_safe(dir_input / 'IRS-spdsrt.pkl')
        if not isinstance(data, dict):
            return None
        return _normalize_repo_frame(data.get('spreads'))

    elif spread_type in ['NetBasis', 'TermBasis']:
        return _load_pickle_safe(dir_input / 'futures-spdsrt.pkl')

    elif spread_type == 'FuturesSwap':
        data = _load_pickle_safe(dir_input / 'futures-spds.pkl')
        if data is None:
            return None
        fs = data.get('FuturesSwap', {})
        if not isinstance(fs, dict):
            return None
        frames = []
        for ctype, cdata in fs.items():
            if isinstance(cdata, dict) and 'Spread' in cdata:
                sp = cdata['Spread']
                if isinstance(sp, pd.DataFrame) and not sp.empty:
                    frames.append(sp)
        return pd.concat(frames, axis=1) if frames else None

    elif spread_type in ['PCASpread', 'BinarySpread']:
        data = _load_pickle_safe(dir_input / 'Misc-spdsrt.pkl')
        if data:
            return data.get(spread_type)

    return None


def get_realtime_spread_bp(spread_type: str, instrument: str) -> Optional[float]:
    """Return the latest quote spread in basis points.

    Prefer bid/ofr-derived mid quotes. For close-yield spread products such as
    TenorSpread, use the latest close-yield spread when no realtime mid-quote
    artifact exists. Keep this separate from ``load_spread_data`` so UI labels
    do not accidentally use a statistical/model spread.
    """
    try:
        realtime = load_realtime_spreads(spread_type)
        if isinstance(realtime, pd.DataFrame) and instrument in realtime.index:
            row = realtime.loc[instrument]
            # IRS-spdsrt keeps both the statistical spread and the current quote
            # spread. Always use the latter for live labels.
            value_column = 'QtPx' if spread_type == 'SwapSpread' else 'spread'
            value = pd.to_numeric(row.get(value_column), errors='coerce')
            if pd.notna(value):
                return float(value) * 100.0

        if spread_type == 'TenorSpread':
            from curves.utils.loader import loadCNBDTS

            tenor_ts = _build_tenor_spread_timeseries(loadCNBDTS())
            series = tenor_ts.get(instrument)
            if isinstance(series, pd.Series):
                close_value = pd.to_numeric(series, errors='coerce').dropna()
                if not close_value.empty:
                    return float(close_value.iloc[-1]) * 100.0
        return None
    except Exception:
        return None


def get_spread_style(spread_type: str) -> str:
    """Get the trading style for a spread type."""
    for cat, info in SPREAD_CATEGORIES.items():
        if spread_type in info['types']:
            return info['style']
    return 'Unknown'
