"""Tests for §5.2 of docs/plans/portfolio_construction_beta_alpha.md: seeding
the satellite candidate correlation-check with the Alpha core (default
TenorSpread) book's live holdings.

Two things are covered:
  - ``select_diverse_instruments(locked=...)``: locked instruments count
    toward every candidate's max-|corr| rejection check, but are never
    returned and never occupy one of the n output slots.
  - ``web.tabs.alpha.data.core_seed``: the quarterly-expiry cache around
    ``build_default_category_portfolio``.
"""
import pandas as pd
import pytest

from web.tabs.alpha import scoring as scoring_mod
from web.tabs.alpha.data import core_seed as core_seed_mod


def _corr_matrix(pairs: dict[tuple[str, str], float]) -> pd.DataFrame:
    """Build a symmetric correlation matrix from {(a, b): corr} pairs.

    Every key referenced gets 1.0 on the diagonal; unspecified off-diagonal
    entries default to 0.0.
    """
    keys = sorted({k for pair in pairs for k in pair})
    df = pd.DataFrame(0.0, index=keys, columns=keys)
    for k in keys:
        df.loc[k, k] = 1.0
    for (a, b), v in pairs.items():
        df.loc[a, b] = v
        df.loc[b, a] = v
    return df


# ---------------------------------------------------------------------------
# select_diverse_instruments(locked=...)
# ---------------------------------------------------------------------------

def test_locked_instruments_never_returned_or_counted_against_n():
    corr = _corr_matrix({('CORE-1', 'SAT-A'): 0.1, ('CORE-1', 'SAT-B'): 0.1})
    candidates = [
        {'ID': 'SAT-A', 'spread_type': 'CarrySpread', 'Zscore': 2.0},
        {'ID': 'SAT-B', 'spread_type': 'CarrySpread', 'Zscore': 1.5},
    ]
    locked = [{'ID': 'CORE-1', 'spread_type': 'TenorSpread'}]

    result = scoring_mod.select_diverse_instruments(
        corr, candidates, n=2, max_abs_corr=1.0, locked=locked,
    )

    assert 'CORE-1' not in result
    assert set(result) == {'SAT-A', 'SAT-B'}


def test_candidate_too_correlated_with_locked_core_is_rejected():
    # SAT-A is highly correlated with the core holding; SAT-B is not.
    corr = _corr_matrix({('CORE-1', 'SAT-A'): 0.9, ('CORE-1', 'SAT-B'): 0.1,
                          ('SAT-A', 'SAT-B'): 0.05})
    candidates = [
        {'ID': 'SAT-A', 'spread_type': 'CarrySpread', 'Zscore': 3.0},  # higher |z|, would win a candidates-only check
        {'ID': 'SAT-B', 'spread_type': 'CarrySpread', 'Zscore': 1.0},
    ]
    locked = [{'ID': 'CORE-1', 'spread_type': 'TenorSpread'}]

    result = scoring_mod.select_diverse_instruments(
        corr, candidates, n=2, max_abs_corr=0.5, locked=locked,
    )

    # SAT-A would have been picked first on z-score alone if the core seed's
    # correlation weren't being checked -- confirming the core-seeding
    # actually changes the outcome, not just plumbs a spare parameter through.
    assert 'SAT-A' not in result
    assert 'SAT-B' in result


def test_no_locked_instruments_is_unchanged_from_prior_behavior():
    corr = _corr_matrix({('SAT-A', 'SAT-B'): 0.2})
    candidates = [
        {'ID': 'SAT-A', 'spread_type': 'CarrySpread', 'Zscore': 2.0},
        {'ID': 'SAT-B', 'spread_type': 'CarrySpread', 'Zscore': 1.0},
    ]

    without_locked_arg = scoring_mod.select_diverse_instruments(corr, candidates, n=2, max_abs_corr=1.0)
    with_empty_locked = scoring_mod.select_diverse_instruments(corr, candidates, n=2, max_abs_corr=1.0, locked=[])

    assert without_locked_arg == with_empty_locked == ['SAT-A', 'SAT-B']


def test_tenorspread_candidate_eligible_when_not_itself_locked():
    # A TenorSpread candidate manually added to `candidates` (e.g. "Add" from
    # the main scan) that is NOT itself an open core position -- it must be
    # eligible for an output slot like any other candidate. Corrected
    # 2026-09-25 per user: an earlier version excluded every TenorSpread
    # candidate outright just for sharing the core's spread_type, which
    # silently dropped manually-picked core-category candidates from a
    # 14-candidate correlation check down to a handful.
    corr = _corr_matrix({('SAT-A', 'TS-PICK'): 0.1})
    candidates = [
        {'ID': 'SAT-A', 'spread_type': 'CarrySpread', 'Zscore': 1.0},
        {'ID': 'TS-PICK', 'spread_type': 'TenorSpread', 'Zscore': 5.0},
    ]

    result = scoring_mod.select_diverse_instruments(
        corr, candidates, n=2, max_abs_corr=1.0, locked=[],
    )

    assert set(result) == {'SAT-A', 'TS-PICK'}


def test_tenorspread_candidate_excluded_only_when_itself_locked():
    # CORE-1 is both a locked (open) core position AND happens to also be
    # present in `candidates` (e.g. the scan included it) -- it must not be
    # double-counted as a "new" pick. A DIFFERENT TenorSpread candidate
    # (TS-OTHER) that is not itself locked remains eligible.
    corr = _corr_matrix({('CORE-1', 'TS-OTHER'): 0.1, ('CORE-1', 'SAT-A'): 0.1,
                          ('TS-OTHER', 'SAT-A'): 0.1})
    candidates = [
        {'ID': 'CORE-1', 'spread_type': 'TenorSpread', 'Zscore': 9.0},
        {'ID': 'TS-OTHER', 'spread_type': 'TenorSpread', 'Zscore': 5.0},
        {'ID': 'SAT-A', 'spread_type': 'CarrySpread', 'Zscore': 1.0},
    ]
    locked = [{'ID': 'CORE-1', 'spread_type': 'TenorSpread'}]

    result = scoring_mod.select_diverse_instruments(
        corr, candidates, n=3, max_abs_corr=1.0, locked=locked,
    )

    assert 'CORE-1' not in result
    assert set(result) == {'TS-OTHER', 'SAT-A'}


def test_locked_instruments_own_column_excluded_from_fallback():
    # cand_meta ends up empty (no candidate matches a corr_matrix column), so
    # the function falls back to all matrix columns -- that fallback must
    # still exclude the locked core instrument's own column.
    corr = _corr_matrix({('SAT-A', 'CORE-1'): 0.1})
    candidates = [{'ID': 'NOT-IN-MATRIX', 'spread_type': 'CarrySpread', 'Zscore': 1.0}]
    locked = [{'ID': 'CORE-1', 'spread_type': 'TenorSpread'}]

    result = scoring_mod.select_diverse_instruments(
        corr, candidates, n=2, max_abs_corr=1.0, locked=locked,
    )

    assert 'CORE-1' not in result
    assert result == ['SAT-A']


def test_locked_instrument_missing_from_corr_matrix_is_silently_dropped():
    corr = _corr_matrix({('SAT-A', 'SAT-B'): 0.2})
    candidates = [
        {'ID': 'SAT-A', 'spread_type': 'CarrySpread', 'Zscore': 2.0},
        {'ID': 'SAT-B', 'spread_type': 'CarrySpread', 'Zscore': 1.0},
    ]
    # NO-HISTORY isn't a column in corr_matrix (e.g. insufficient price
    # history for this lookback) -- should not raise, should just be ignored.
    locked = [{'ID': 'NO-HISTORY', 'spread_type': 'TenorSpread'}]

    result = scoring_mod.select_diverse_instruments(
        corr, candidates, n=2, max_abs_corr=1.0, locked=locked,
    )
    assert set(result) == {'SAT-A', 'SAT-B'}


# ---------------------------------------------------------------------------
# core_seed cache
# ---------------------------------------------------------------------------

def test_load_core_seed_builds_and_caches(monkeypatch, tmp_path):
    monkeypatch.setattr(core_seed_mod, '_get_input_dir', lambda: tmp_path)

    calls = {'n': 0}

    def _fake_build(spread_type):
        calls['n'] += 1
        return [
            {'ID': 'A', 'spread_type': 'TenorSpread', 'weight': 0.5},
            {'ID': 'B', 'spread_type': 'TenorSpread', 'weight': 0.5},
        ]

    import web.tabs.alpha.scoring as scoring_pkg
    monkeypatch.setattr(scoring_pkg, 'build_default_category_portfolio', _fake_build)

    seed1 = core_seed_mod.load_core_seed()
    assert calls['n'] == 1
    assert {s['ID'] for s in seed1} == {'A', 'B'}
    assert all(s['spread_type'] == 'TenorSpread' for s in seed1)

    # Second call within the expiry window reads the cache, no rebuild.
    seed2 = core_seed_mod.load_core_seed()
    assert calls['n'] == 1
    assert seed2 == seed1


def test_load_core_seed_rebuilds_after_expiry(monkeypatch, tmp_path):
    monkeypatch.setattr(core_seed_mod, '_get_input_dir', lambda: tmp_path)

    calls = {'n': 0}

    def _fake_build(spread_type):
        calls['n'] += 1
        return [{'ID': f'A{calls["n"]}', 'spread_type': 'TenorSpread', 'weight': 1.0}]

    import web.tabs.alpha.scoring as scoring_pkg
    monkeypatch.setattr(scoring_pkg, 'build_default_category_portfolio', _fake_build)

    core_seed_mod.load_core_seed()
    assert calls['n'] == 1

    # max_age_days=0 forces every call to treat the cache as expired.
    core_seed_mod.load_core_seed(max_age_days=0)
    assert calls['n'] == 2


def test_core_seed_age_days_none_before_first_build(monkeypatch, tmp_path):
    monkeypatch.setattr(core_seed_mod, '_get_input_dir', lambda: tmp_path)
    assert core_seed_mod.core_seed_age_days() is None


def test_core_seed_build_failure_returns_empty_list_not_raise(monkeypatch, tmp_path):
    monkeypatch.setattr(core_seed_mod, '_get_input_dir', lambda: tmp_path)

    import web.tabs.alpha.scoring as scoring_pkg

    def _raise(spread_type):
        raise RuntimeError("no data available")

    monkeypatch.setattr(scoring_pkg, 'build_default_category_portfolio', _raise)

    seed = core_seed_mod.load_core_seed()
    assert seed == []
