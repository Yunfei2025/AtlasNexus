"""Tests for engine.schema — the standardized artifact contracts.

Pure-python, no market data / Wind dependency, so these run in CI.
"""
from __future__ import annotations

import math

import pytest

from engine.schema import (
    SCHEMA_VERSION,
    BacktestResult,
    PerformanceMetrics,
    RunManifest,
    _max_drawdown,
)


# ── PerformanceMetrics.from_returns ───────────────────────────────────────

def test_from_returns_empty_is_zero():
    m = PerformanceMetrics.from_returns([])
    assert m == PerformanceMetrics()
    assert m.n_obs == 0


def test_from_returns_single_point_no_vol():
    m = PerformanceMetrics.from_returns([0.01])
    assert m.n_obs == 1
    assert m.ann_vol == 0.0
    assert m.sharpe == 0.0            # guarded against zero vol
    assert m.total_return == pytest.approx(0.01)


def test_from_returns_constant_positive_has_no_drawdown():
    m = PerformanceMetrics.from_returns([0.01] * 10)
    assert m.max_drawdown == 0.0
    assert m.calmar == 0.0            # no drawdown -> calmar guarded to 0
    assert m.total_return == pytest.approx(1.01 ** 10 - 1)
    assert m.sharpe > 0


def test_from_returns_total_return_is_geometric():
    m = PerformanceMetrics.from_returns([0.1, -0.1])
    # (1.1 * 0.9) - 1 = -0.01
    assert m.total_return == pytest.approx(-0.01)


def test_from_returns_drawdown_value():
    # up 20%, then down 50% -> equity 1.2 then 0.6; peak 1.2 -> dd = -0.5
    m = PerformanceMetrics.from_returns([0.2, -0.5])
    assert m.max_drawdown == pytest.approx(-0.5)


def test_from_returns_sharpe_sign_and_annualization():
    rs = [0.001, -0.0005, 0.002, 0.0, 0.0015]
    m = PerformanceMetrics.from_returns(rs, periods_per_year=252)
    mean_r = sum(rs) / len(rs)
    assert m.ann_return == pytest.approx(mean_r * 252)
    assert m.sharpe > 0


def test_from_returns_ignores_nan():
    a = PerformanceMetrics.from_returns([0.01, float("nan"), 0.02])
    b = PerformanceMetrics.from_returns([0.01, 0.02])
    assert a.n_obs == 2
    assert a.total_return == pytest.approx(b.total_return)


def test_metrics_roundtrip():
    m = PerformanceMetrics.from_returns([0.01, -0.02, 0.03])
    assert PerformanceMetrics.from_dict(m.to_dict()) == m


def test_max_drawdown_helper():
    assert _max_drawdown([1.0, 1.2, 0.6, 0.9]) == pytest.approx(-0.5)
    assert _max_drawdown([1.0, 2.0, 3.0]) == 0.0
    assert _max_drawdown([]) == 0.0


# ── BacktestResult ────────────────────────────────────────────────────────

def test_backtest_result_roundtrip(tmp_path):
    res = BacktestResult(
        name="T2412",
        asof="2026-06-05",
        metrics=PerformanceMetrics.from_returns([0.01, 0.02, -0.01]),
        equity_curve=[1.0, 1.01, 1.03],
        dates=["2026-06-03", "2026-06-04", "2026-06-05"],
        meta={"instrument": "futures", "notional": 1_000_000},
    )
    path = res.write(tmp_path / "bt.json")
    assert path.exists()

    loaded = BacktestResult.read(path)
    assert loaded.name == res.name
    assert loaded.asof == res.asof
    assert loaded.metrics == res.metrics
    assert loaded.equity_curve == res.equity_curve
    assert loaded.meta["notional"] == 1_000_000
    assert loaded.schema_version == SCHEMA_VERSION


def test_backtest_result_minimal():
    res = BacktestResult(name="x", asof="2026-06-05")
    d = res.to_dict()
    assert d["equity_curve"] is None
    assert BacktestResult.from_dict(d).name == "x"


# ── RunManifest (backward-compatible run_meta.json) ───────────────────────

def test_manifest_preserves_legacy_run_meta_shape():
    """web/services/artifacts.py depends on these exact keys."""
    man = RunManifest(
        run_id="20260605-eod-220035",
        mode="eod",
        asof="2026-06-05",
        generated_at="2026-06-05T14:01:08.232087",
        status="completed",
        steps={"curves": "ok", "futures": "failed"},
    )
    d = man.to_dict()
    for key in ("mode", "run_id", "asof", "generated_at", "status", "steps"):
        assert key in d, f"legacy run_meta.json key missing: {key}"
    assert d["mode"] == "eod"
    assert d["steps"]["futures"] == "failed"


def test_manifest_roundtrip(tmp_path):
    man = RunManifest(
        run_id="r1", mode="data", asof="2026-06-05",
        steps={"retrieve": "ok"}, artifacts=["bonds.json"],
    )
    path = man.write(tmp_path / "run_meta.json")
    loaded = RunManifest.read(path)
    assert loaded.run_id == "r1"
    assert loaded.steps == {"retrieve": "ok"}
    assert loaded.artifacts == ["bonds.json"]


def test_manifest_from_legacy_dict_without_new_fields():
    legacy = {
        "mode": "eod", "run_id": "x", "asof": "2026-06-05",
        "generated_at": "t", "status": "completed",
        "steps": {"curves": "ok"},
    }
    man = RunManifest.from_dict(legacy)
    assert man.artifacts == []
    assert man.schema_version == SCHEMA_VERSION


def test_manifest_step_results():
    man = RunManifest(run_id="r", mode="eod", asof="d",
                      steps={"a": "ok", "b": "failed"})
    results = {s.name: s.status for s in man.step_results()}
    assert results == {"a": "ok", "b": "failed"}
