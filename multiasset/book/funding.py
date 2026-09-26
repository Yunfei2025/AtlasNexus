# -*- coding: utf-8 -*-
"""Per-domicile funding hurdle (for Sharpe only, never subtracted from P&L)
and cash return on undeployed capital.

Reserved for Step 6 of docs/plans/beta_book_exposure_vs_capital.md:

    _DOMICILE_ALIASES = {'EU': 'DE'}   # data.py:231/607 map 'DE Gov Bond' -> 'EU',
                                        # but _IRDL_FUNDING_RATE_MACRO_COL keys 'DE'

    def normalise_domicile(code: str) -> str: ...
    def book_funding_cost_daily(notional_daily, domicile_of) -> pd.Series: ...
    def cash_return_daily(notional_daily, total_capital, max_utilisation=0.95) -> pd.Series: ...

No logic yet — this module is a placeholder created in Step 1 (pure file
split) so later steps are additions, not new-file churn.
"""
