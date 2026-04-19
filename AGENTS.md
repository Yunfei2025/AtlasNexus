# AGENTS.md

Guidance for AI coding agents working in this repository.

## Scope

- This is a Python-first mono-repo for financial research, dashboards, and orchestration.
- Keep changes minimal and localized; avoid broad refactors unless explicitly requested.

## Language Rules (Primary)

- Use English for all code identifiers: module names, functions, classes, variables, constants.
- Use English for docstrings, inline comments, and log messages by default.
- Keep user-facing text in its existing language.
- If a file already contains Chinese user-facing copy, preserve tone and wording style; add bilingual text only when requested.
- Do not translate existing domain terms unless asked.

## Style Expectations

- Follow the local style of each file (naming, imports, typing, logging pattern).
- Preserve function signatures and public module interfaces unless the task requires API changes.
- Prefer explicit, short comments only where logic is not obvious.

## Run Commands

From repository root:

```bash
python main.py daily-web
python main.py intraday-web
python main.py eod --asof YYYY-MM-DD --update-data
python main.py intraday --asof YYYY-MM-DD --update-data
python main.py refresh --asof YYYY-MM-DD --steps rates credit irs stat
python main.py scheduler --interval 300 --mode refresh
python main.py update-data --modules <module...> --force
python main.py curve-backtest --btype IRS --start YYYY-MM-DD --end YYYY-MM-DD
```

## Architecture Pointers

- Orchestration layer: [engine/README.md](engine/README.md)
- Startup and dashboard troubleshooting: [ATLASNEXUS_START_GUIDE.md](ATLASNEXUS_START_GUIDE.md)
- Backtesting package guide: [backtest/README.md](backtest/README.md)
- Alpha scoring notes: [web/README_ALPHA_SCORING.md](web/README_ALPHA_SCORING.md)
- Strategy/design notes: [docs/AlphaBook_BondSwap_TrendSignals.md](docs/AlphaBook_BondSwap_TrendSignals.md)

## Common Pitfalls

- Windows launcher scripts (`*.bat`) assume a Conda environment named `dev`; prefer Python entrypoints for cross-platform work.
- `xlwings` and Excel integrations may not work on non-Windows setups.
- Dash apps typically run on ports `8080`/`8081`; check for conflicts before launch.
- Keep `use_reloader=False` for Dash app entrypoints unless debugging a specific issue.

## Agent Workflow

- Before coding, quickly read related module README/docs and existing `interface.py` patterns.
- When updating docs, link to existing docs instead of duplicating content.
- When uncertain about language in user-visible copy, ask before rewriting text tone or language.
