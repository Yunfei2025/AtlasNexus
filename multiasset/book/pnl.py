# -*- coding: utf-8 -*-
"""Capital-gain vs carry P&L split, computed on real per-tenor notional.

Reserved for Step 5 of docs/plans/beta_book_exposure_vs_capital.md:

    class BookPnL:
        capital_gain: pd.DataFrame   # notional * data.py 'capital'  (== DV01 x dy)
        carry:        pd.DataFrame   # notional * data.py 'carry'    (== y/365)
        other:        pd.DataFrame   # FX/commodity 'total' (unsplittable)
        cash:         pd.Series      # undeployed capital * FR007/365

    def returns_split_is_exact(asset_name) -> bool: ...
    def compute_book_pnl(notional_daily, market_data, start_date, end_date) -> BookPnL: ...
    def aggregate_for_display(pnl, asset_names) -> pd.DataFrame: ...

No logic yet — this module is a placeholder created in Step 1 (pure file
split) so later steps are additions, not new-file churn.
"""
