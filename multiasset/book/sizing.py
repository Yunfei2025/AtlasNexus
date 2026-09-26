# -*- coding: utf-8 -*-
"""Daily per-factor coefficient -> pooled per-tenor notional sizing.

Reserved for Step 4 of docs/plans/beta_book_exposure_vs_capital.md:

    scaled_factor_budgets_daily(reference_budget, signal_asof, daily_index,
                                screened_factors) -> pd.DataFrame
    notional_daily_from_context(ctx_by_month, budgets_daily, total_capital,
                                max_utilisation=0.95) -> pd.DataFrame

No logic yet — this module is a placeholder created in Step 1 (pure file
split) so later steps are additions, not new-file churn.
"""
