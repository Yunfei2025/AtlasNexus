# AtlasNexus Daily — UI Kit

High-fidelity recreation of the **AtlasNexus · Daily** terminal: a multi-asset, multi-strategy
fixed-income systematic investment platform. Built entirely from the AtlasNexus component primitives
(`Panel`, `Tabs`, `DataTable`, `Button`, `KPICard`, `Badge`, `Checkbox`, `Slider`, …).

## Files
- `cover.html` — branded entry / cover screen (self-contained, no bundle). Links into the app.
- `index.html` — the interactive terminal. Switch books (Market / Beta Book / Alpha Book / Summary / Run Center) and sub-tabs.
- `AppShell.jsx` — header (wordmark, EOD metadata, status pill) + main book tabs + sub-tab row. Drives per-book accent color.
- `MarketData.jsx` — Market › Data: money-market rates, on-the-run & reference bonds, IRS forward rates with in-cell bars.
- `BetaCandidates.jsx` — Beta Book › Candidates: factor selection pool (IR/FX/EQ/CM) + train/predict.
- `AlphaCandidates.jsx` — Alpha Book › Candidates: RV scanner, z-score slider, signal clusters.
- `SummaryBooks.jsx` — Summary › Books: portfolio combination KPIs + beta/alpha allocation tables.
- `RunCenter.jsx` — daily pipeline, data backfill, status & logs.

## Per-book accent
Market = cyan · Beta Book = blue · Alpha Book = amber · Summary = cyan · Run Center = teal.
The shell sets the active accent automatically; pass the matching `accent` to `Panel`/`Tabs`/`Button` inside a book.

## Coverage note
Only the *Candidates / Data / Books* views and Run Center were in the supplied source. Other sub-tabs
(Trend, Pricer, Surface, Curves, Portfolio, Backtest, Factor, Spread, Pairs, Volatility, Risk, Tickets)
render an honest placeholder rather than invented designs — fill them in from real product source when available.

## Source
Recreated from product screenshots of AtlasNexus · Daily (no codebase/Figma supplied). Screenshots in `/uploads`.
