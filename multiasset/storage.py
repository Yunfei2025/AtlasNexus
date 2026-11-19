# -*- coding: utf-8 -*-
"""
Storage module for Multi-Asset Dashboard.

Handles saving and loading of asset pools and configuration.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

# Define paths
# bin/multiasset/storage.py -> bin/multiasset -> bin -> MultiAsset
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]

INPUT_DIR = PROJECT_ROOT / 'input'
HISTORY_DIR = INPUT_DIR / 'asset_pool_history'
LAST_POOL_FILE = INPUT_DIR / 'asset_pool_last.json'

BACKTEST_DIR = INPUT_DIR / 'multiasset_backtest'
LAST_BACKTEST_FILE = BACKTEST_DIR / 'multiasset_backtest_last.json'


def ensure_directories():
    """Ensure input directories exist."""
    if not INPUT_DIR.exists():
        INPUT_DIR.mkdir(parents=True)
    if not HISTORY_DIR.exists():
        HISTORY_DIR.mkdir(parents=True)


def save_asset_pool(asset_pool: List[Dict[str, Any]], metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Save the current asset pool to a JSON file.
    Saves to both 'asset_pool_last.json' and a timestamped history file.
    
    Args:
        asset_pool: List of asset dictionaries (from asset-pool-store)
        metadata: Optional dictionary with additional info (e.g. weights, settings)
        
    Returns:
        Path to the history file created
    """
    ensure_directories()
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    data = {
        'timestamp': timestamp,
        'asset_pool': asset_pool,
        'metadata': metadata or {}
    }
    
    # Save to history
    history_filename = f"pool_{timestamp}.json"
    history_path = HISTORY_DIR / history_filename
    try:
        with open(history_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving history file: {e}")
        
    # Save as last run
    try:
        with open(LAST_POOL_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving last pool file: {e}")
        
    return str(history_path)


def load_last_asset_pool() -> Optional[Dict[str, Any]]:
    """
    Load the last saved asset pool.
    
    Returns:
        Dictionary containing 'asset_pool' and 'metadata', or None if no file exists.
    """
    if not LAST_POOL_FILE.exists():
        return None
        
    try:
        with open(LAST_POOL_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading last asset pool: {e}")
        return None


# Calendar days between two consecutive saved dates beyond which the merged curve is
# reported as having a GAP (a holiday break is at most ~10 days).
_MERGE_GAP_DAYS = 14


def _rows_to_series(rows) -> 'pd.Series':
    import pandas as pd
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series([float(r['value']) for r in rows],
                  index=pd.to_datetime([r['date'] for r in rows])).sort_index()
    return s[~s.index.duplicated(keep='last')]


def _series_to_rows(s) -> List[Dict[str, Any]]:
    return [{'date': d.strftime('%Y-%m-%d'), 'value': float(v)} for d, v in s.items()]


def _daily_pnl_from_cumulative(cum) -> 'pd.Series':
    """Per-day P&L from a cumulative curve whose first value is the first day's own P&L
    (how the backtest builds it: cumsum of daily P&L)."""
    pnl = cum.diff()
    if len(pnl):
        pnl.iloc[0] = cum.iloc[0]
    return pnl


def _incompatible_reason(existing: Dict[str, Any], new: Dict[str, Any]) -> Optional[str]:
    """Why ``new`` cannot be spliced onto ``existing`` (None = compatible)."""
    cap_old = float(existing.get('total_capital') or 0.0)
    cap_new = float(new.get('total_capital') or 0.0)
    if cap_old <= 0 or cap_new <= 0:
        return "total capital missing in a saved result"
    if abs(cap_old - cap_new) > 1e-6 * max(cap_old, cap_new):
        return (f"capital differs ({cap_old:g} vs {cap_new:g} million CNY): "
                "P&L in CNY is not comparable")
    mo, mn = existing.get('alloc_mode'), new.get('alloc_mode')
    if mo and mn and mo != mn:
        return f"allocation mode differs ({mo} vs {mn})"
    if not existing.get('equity_series'):
        return "the saved result has no equity series"
    return None


def _merged_stats(equity_rows, cash_rows, capital: float) -> Dict[str, float]:
    """Sharpe (over the cash benchmark when available), annualised return and max drawdown of
    the merged curve, with the beta+alpha combination panel's own convention
    (web/tabs/risk/books/combination.py ``_metrics``) so both report the same numbers."""
    import numpy as np
    import pandas as pd
    eq = _rows_to_series(equity_rows)
    r = (eq.diff().dropna() / capital)
    if r.empty or r.std() == 0:
        return {'sharpe': 0.0, 'annualized_return': 0.0, 'max_drawdown': 0.0}
    vol = float(r.std() * np.sqrt(252))
    nav = (1.0 + r).cumprod()
    n_years = len(r) / 252.0
    ann = float(nav.iloc[-1] ** (1.0 / n_years) - 1.0) if nav.iloc[-1] > 0 else -1.0
    if cash_rows:
        h = (_rows_to_series(cash_rows) / capital).reindex(r.index).fillna(0.0)
        sharpe = (ann - float(h.mean() * 252)) / vol
    else:
        sharpe = float(r.mean() / r.std() * np.sqrt(252))
    mdd = float(((nav - nav.cummax()) / nav.cummax()).min())
    return {'sharpe': float(sharpe), 'annualized_return': ann, 'max_drawdown': mdd}


def merge_backtest_results(existing: Optional[Dict[str, Any]], new: Dict[str, Any]) -> Dict[str, Any]:
    """Splice a new backtest run onto the saved result, day by day.

    The equity curve is cumulative P&L, so each run's curve restarts at its own start; the
    runs are joined on DAILY P&L, not on the cumulative values: per date the new run's P&L
    overwrites the saved one where they overlap, dates only in one run are kept, and the
    cumulative curve is rebuilt over the union. A date gap between runs contributes no P&L
    (reported in ``merge_info['gaps']``). The cash benchmark is merged per date the same way.

    Not merged (``new`` returned as is, with the reason in ``merge_info``): no saved result, a
    different total capital, or a different allocation mode. Headline stats of a merged result
    are recomputed over the merged curve; the new run's own stats are kept in
    ``merge_info['last_run']``.
    """
    import pandas as pd
    info: Dict[str, Any] = {'mode': 'fresh', 'reason': None, 'runs': 1}
    reason = None if existing is None else _incompatible_reason(existing, new)
    if existing is None:
        info['reason'] = 'first save'
    elif reason:
        info['reason'] = reason
    if existing is None or reason or not new.get('equity_series'):
        out = dict(new)
        out['merge_info'] = info
        return out

    pnl_old = _daily_pnl_from_cumulative(_rows_to_series(existing['equity_series']))
    pnl_new = _daily_pnl_from_cumulative(_rows_to_series(new['equity_series']))
    overlap = pnl_old.index.intersection(pnl_new.index)
    pnl = pd.concat([pnl_old.drop(overlap), pnl_new]).sort_index()
    equity = pnl.cumsum()

    cash_old, cash_new = existing.get('cash_benchmark'), new.get('cash_benchmark')
    cash_rows, cash_note = None, None
    if cash_old and cash_new:
        c_old, c_new = _rows_to_series(cash_old), _rows_to_series(cash_new)
        cash = pd.concat([c_old.drop(c_old.index.intersection(c_new.index)), c_new]).sort_index()
        cash_rows = _series_to_rows(cash)
    elif cash_old or cash_new:
        # A partial benchmark would score the uncovered dates at zero hurdle and overstate Sharpe.
        cash_note = "cash benchmark dropped: only one of the two results has it"

    dates = equity.index
    gaps = [[dates[k - 1].strftime('%Y-%m-%d'), dates[k].strftime('%Y-%m-%d')]
            for k in range(1, len(dates)) if (dates[k] - dates[k - 1]).days > _MERGE_GAP_DAYS]
    capital = float(new['total_capital'])
    out = dict(new)
    out['equity_series'] = _series_to_rows(equity)
    if cash_rows:
        out['cash_benchmark'] = cash_rows
    else:
        out.pop('cash_benchmark', None)
    out['start_date'] = dates[0].strftime('%Y-%m-%d')
    out['end_date'] = dates[-1].strftime('%Y-%m-%d')
    out['asset_pool'] = sorted(set(existing.get('asset_pool') or []) | set(new.get('asset_pool') or []))
    out['alloc_mode'] = new.get('alloc_mode') or existing.get('alloc_mode')
    out.update(_merged_stats(out['equity_series'], cash_rows, capital))
    prev_info = existing.get('merge_info') or {}
    info.update({
        'mode': 'merged',
        'runs': int(prev_info.get('runs', 1)) + 1,
        'overwrote_days': int(len(overlap)),
        'added_days': int(len(pnl_new) - len(overlap)),
        'gaps': gaps,
        'cash_note': cash_note,
        'last_run': {'start': new.get('start_date'), 'end': new.get('end_date'),
                     'sharpe': new.get('sharpe'), 'annualized_return': new.get('annualized_return'),
                     'max_drawdown': new.get('max_drawdown')},
    })
    out['merge_info'] = info
    return out


def save_backtest_result(
    equity_series: List[Dict[str, Any]],
    sharpe: float,
    annualized_return: float,
    max_drawdown: float,
    asset_pool: List[str],
    total_capital: float,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    cash_benchmark: Optional[List[Dict[str, Any]]] = None,
    alloc_mode: Optional[str] = None,
    merge_with_last: bool = True,
) -> str:
    """Persist the historical-allocation backtest's combined equity curve and
    summary stats, so a later beta+alpha combination reads a fixed result
    instead of re-running the factor risk-parity optimizer + per-asset
    return sweep on demand.

    ``equity_series``: list of {'date': iso-string, 'value': float} records
    (cumulative portfolio PnL, same units as multiasset/dashboard.py's
    df_pnl['Total'], i.e. million CNY) -- JSON-safe, no DataFrame/Series.

    ``sharpe`` is the Sharpe over the cash benchmark ("Sharpe (vs cash)"). ``cash_benchmark``:
    {'date', 'value'} records of the daily cash benchmark in million CNY on the initial capital
    (what ``total_capital`` earns in cash), so a reader can score the curve over cash the same
    way the backtest does; results saved before it existed lack it.

    Writes a timestamped history file holding THIS run only, and the fixed 'last' file the
    beta+alpha combination reads. With ``merge_with_last`` (default) the 'last' file is
    INCREMENTAL: the run is spliced onto the saved result by date, overwriting any overlapping
    days (see ``merge_backtest_results``); a different capital or allocation mode starts it
    afresh. ``alloc_mode`` records which mode produced the run so modes are never mixed.
    """
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    data = {
        'timestamp': timestamp,
        'sharpe': float(sharpe),
        'annualized_return': float(annualized_return),
        'max_drawdown': float(max_drawdown),
        'asset_pool': list(asset_pool),
        'total_capital': float(total_capital),
        'start_date': start_date,
        'end_date': end_date,
        'equity_series': equity_series,
    }
    if cash_benchmark:
        data['cash_benchmark'] = cash_benchmark
    if alloc_mode:
        data['alloc_mode'] = alloc_mode

    history_path = BACKTEST_DIR / f"backtest_{timestamp}.json"
    try:
        with open(history_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving backtest history file: {e}")

    last = data
    if merge_with_last:
        try:
            last = merge_backtest_results(load_last_backtest_result(), data)
        except Exception as e:
            print(f"Warning: could not merge with the saved backtest ({e}); saving this run alone")
            last = data
    try:
        with open(LAST_BACKTEST_FILE, 'w', encoding='utf-8') as f:
            json.dump(last, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving last backtest file: {e}")

    return str(history_path)


def describe_last_save() -> str:
    """One-line description of how the last save went (merged / replaced), for the UI."""
    r = load_last_backtest_result() or {}
    mi = r.get('merge_info') or {}
    span = f"{r.get('start_date')} → {r.get('end_date')}"
    if mi.get('mode') == 'merged':
        msg = (f"merged into the saved result ({mi.get('runs')} runs): now {span}, "
               f"{mi.get('overwrote_days', 0)} overlapping days overwritten, "
               f"{mi.get('added_days', 0)} new days added")
        if mi.get('gaps'):
            msg += f"; GAP with no P&L: {', '.join(a + '→' + b for a, b in mi['gaps'])}"
        if mi.get('cash_note'):
            msg += f"; {mi['cash_note']}"
        return msg
    if mi.get('reason') and mi.get('reason') != 'first save':
        return f"replaced the saved result ({mi['reason']}): {span}"
    return f"saved: {span}"


def load_last_backtest_result() -> Optional[Dict[str, Any]]:
    """Load the last-saved historical-allocation backtest result, or None."""
    if not LAST_BACKTEST_FILE.exists():
        return None
    try:
        with open(LAST_BACKTEST_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading last backtest result: {e}")
        return None


def list_history_files() -> List[str]:
    """List all available history files, sorted by newest first."""
    if not HISTORY_DIR.exists():
        return []
    
    files = [f.name for f in HISTORY_DIR.glob('*.json')]
    files.sort(reverse=True)
    return files
