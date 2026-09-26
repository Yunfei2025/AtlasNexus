# -*- coding: utf-8 -*-
"""Beta-book capital-usage and P&L accounting: separates risk exposure
(DV01-scaled capital gain) from capital usage (notional-scaled carry,
funding and cash return).

Scaffolded in Step 1 of docs/plans/beta_book_exposure_vs_capital.md — see
that plan for the full design. Modules are added with logic in later steps:

- sizing.py  — daily per-factor coefficient -> pooled per-tenor notional (Step 4)
- pnl.py     — capital-gain / carry split, BookPnL dataclass (Step 5)
- carry.py   — (reserved; carry math currently lives in pnl.py per the plan)
- funding.py — per-domicile funding hurdle for Sharpe; cash return on
               undeployed capital (Step 6)
- capital.py — long-only capital constraint with a utilisation buffer (Step 7)

This package gives the phantom `portfolio/` directory CLAUDE.md's
architecture section describes a real home — the risk-aggregation logic
that document attributes to `portfolio/` did not previously exist as code;
this is where it lands.
"""
