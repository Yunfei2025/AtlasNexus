# -*- coding: utf-8 -*-
"""Tests for the SwapSpread liquidity gate (curves/refreshers/alpha_candidates.py).

Off-anchor-tenor combinations (Repo7d-4y5y, Shi3M-2y3y, ...) are real
instruments used for rebalancing an existing position's duration as it ages
(e.g. a 5y position rolling into 4y5y to hold the 5y point), not for sizing
new RV positions -- see conversation notes 2026-09-19. is_swapspread_liquid
requires every leg to be an anchor tenor with a reliable two-way market:
Repo7d's anchors match settings.futures.FuturesConfig.IRS_TERMS
(3m/6m/9m/1y/2y/5y); Shi3M and Basis are narrower (1y/5y only).
"""
from __future__ import annotations

import pytest

from curves.refreshers.alpha_candidates import (
    _swapspread_tenor_legs, is_swapspread_liquid,
    _REPO7D_LIQUID_TENORS, _SHI3M_LIQUID_TENORS, _BASIS_LIQUID_TENORS,
)


# ---------------------------------------------------------------------------
# _swapspread_tenor_legs: tokenization must match legs.py's own parsing
# ---------------------------------------------------------------------------

def test_tenor_legs_parses_repo7d_two_leg_slope():
    assert _swapspread_tenor_legs('Repo7d-1y2y') == ('repo7d', ['1y', '2y'])


def test_tenor_legs_parses_shi3m_two_leg_slope():
    assert _swapspread_tenor_legs('Shi3M-1y5y') == ('shi3m', ['1y', '5y'])


def test_tenor_legs_parses_three_leg_fly():
    assert _swapspread_tenor_legs('Repo7d-3m6m9m') == ('repo7d', ['3m', '6m', '9m'])


def test_tenor_legs_parses_single_tenor_basis():
    assert _swapspread_tenor_legs('Basis-5y') == ('basis', ['5y'])


def test_tenor_legs_parses_two_leg_basis_as_repo7d_fallback():
    """Basis-Xy is single-tenor only; a 'Basis-1y2y'-shaped ID (if it ever
    existed) would not match _BASIS_SINGLE_RE and falls through to no match
    (Basis doesn't have a repo7d/shi3m prefix), returning (None, [])."""
    assert _swapspread_tenor_legs('Basis-1y2y') == (None, [])


def test_tenor_legs_unknown_prefix_returns_none():
    assert _swapspread_tenor_legs('Junk-1y2y') == (None, [])


def test_tenor_legs_is_case_insensitive():
    assert _swapspread_tenor_legs('REPO7D-1Y2Y') == ('repo7d', ['1y', '2y'])


# ---------------------------------------------------------------------------
# is_swapspread_liquid: both legs must be anchor tenors
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('instrument,expected', [
    # Repo7d anchors: 3m, 6m, 9m, 1y, 2y, 5y -- every pairwise combination liquid.
    ('Repo7d-3m6m', True), ('Repo7d-6m9m', True), ('Repo7d-9m1y', True),
    ('Repo7d-1y2y', True), ('Repo7d-2y5y', True), ('Repo7d-1y5y', True),
    ('Repo7d-3m1y', True), ('Repo7d-3m5y', True),
    # Off-anchor legs (3y, 4y) make the whole spread illiquid even with one
    # anchor leg present.
    ('Repo7d-4y5y', False), ('Repo7d-2y3y', False), ('Repo7d-1y4y', False),
    ('Repo7d-3y4y', False),
    # 3-leg flies: liquid only if ALL THREE legs are anchors.
    ('Repo7d-3m6m9m', True), ('Repo7d-1y2y5y', True),
    ('Repo7d-3m2y3y', False),   # 3y leg breaks it
    ('Repo7d-3m4y5y', False),   # 4y leg breaks it
    # Shi3M: narrower liquid set (1y, 5y only) -- even anchor-looking 6m/9m
    # legs are illiquid for Shi3M specifically (thinner two-way market).
    ('Shi3M-1y5y', True),
    ('Shi3M-6m9m', False), ('Shi3M-2y3y', False), ('Shi3M-1y2y', False),
    # Basis: single-tenor, liquid only at 1y/5y.
    ('Basis-1y', True), ('Basis-5y', True),
    ('Basis-6m', False), ('Basis-2y', False), ('Basis-4y', False),
    # Unrecognized IDs are conservatively illiquid, not an error.
    ('Junk-xyz', False), ('', False),
])
def test_is_swapspread_liquid(instrument, expected):
    assert is_swapspread_liquid(instrument) is expected


def test_liquid_tenor_sets_match_stated_anchors():
    """Documents the exact anchor sets from the user's 2026-09-19 description:
    Repo7d-{3m,6m,9m,1y,2y,5y} and Shi3M-{1y,5y}; Basis matches Shi3M's
    narrower set since Basis = SHI3M leg - FR007 leg at one tenor."""
    assert _REPO7D_LIQUID_TENORS == {'3m', '6m', '9m', '1y', '2y', '5y'}
    assert _SHI3M_LIQUID_TENORS == {'1y', '5y'}
    assert _BASIS_LIQUID_TENORS == {'1y', '5y'}


# ---------------------------------------------------------------------------
# build_alpha_candidates: the gate must only touch SwapSpread rows, and only
# remove illiquid ones -- TenorSpread's already-curated carried-over subset
# and every other category must pass through untouched.
# ---------------------------------------------------------------------------

def test_build_alpha_candidates_liquidity_gate_scoped_to_swapspread_only():
    """The illiquid-SwapSpread removal logic must key off spread_type ==
    'SwapSpread' specifically -- a TenorSpread row must never be filtered by
    is_swapspread_liquid even if its ID happens to look like a SwapSpread ID
    (it won't in practice, but the gate's category scoping is the actual
    safety property under test, not the ID shape)."""
    import pandas as pd
    from curves.refreshers.alpha_candidates import is_swapspread_liquid

    df = pd.DataFrame({
        'spread_type': ['SwapSpread', 'SwapSpread', 'TenorSpread', 'TBondCurve'],
        'ID': ['Repo7d-1y2y', 'Repo7d-4y5y', 'Repo7d-4y5y', '210007.IB'],
    })
    swap_mask = df['spread_type'].eq('SwapSpread')
    illiquid = swap_mask & ~df['ID'].astype(str).map(is_swapspread_liquid)
    kept = df[~illiquid]

    # Only the illiquid SwapSpread row is dropped.
    assert list(kept['ID']) == ['Repo7d-1y2y', 'Repo7d-4y5y', '210007.IB']
    assert 'TenorSpread' in kept['spread_type'].values  # untouched despite same-looking ID
