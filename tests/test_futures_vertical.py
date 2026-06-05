"""Step 4 Slice 2 — futures vertical: compute → artifact → service reader.

Tests the full chain without market data:
  futures/daily/main.run_with_summary  (compute layer)
  engine/schema.BacktestResult         (contract layer)
  web/services/artifacts.load_step_result (reader layer)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.schema import BacktestResult, PerformanceMetrics, RunManifest


# ── compute layer: run_with_summary() structure ───────────────────────────

def test_run_with_summary_returns_none_when_no_data(monkeypatch):
    """run_with_summary() must return None gracefully when the data file is absent."""
    monkeypatch.setattr("os.path.exists", lambda _: False)
    from futures.daily.main import run_with_summary
    assert run_with_summary() is None


# ── contract layer: BacktestResult round-trip from a futures-shaped dict ─

def _make_futures_result(asof: str = "2026-06-06") -> BacktestResult:
    """Build a BacktestResult that mirrors what futures/interface.py returns."""
    metrics = PerformanceMetrics.from_returns(
        [0.003, -0.001, 0.005, 0.002, -0.002, 0.004],
        periods_per_year=252,
    )
    return BacktestResult(
        name="Blended (Max Sharpe)",
        asof=asof,
        metrics=metrics,
        equity_curve=[1.003, 1.002, 1.007, 1.009, 1.007, 1.011],
        dates=[
            "2026-06-01", "2026-06-02", "2026-06-03",
            "2026-06-04", "2026-06-05", "2026-06-06",
        ],
        meta={"symbol": "TL.CFE", "period_start": "2021-06-06", "period_end": "2026-06-06"},
    )


def test_backtest_result_from_futures_shape(tmp_path):
    res = _make_futures_result()
    path = res.write(tmp_path / "futures_result.json")
    loaded = BacktestResult.read(path)

    assert loaded.name == "Blended (Max Sharpe)"
    assert loaded.meta["symbol"] == "TL.CFE"
    assert loaded.metrics.n_obs == 6
    assert loaded.metrics.sharpe > 0
    assert loaded.equity_curve is not None
    assert len(loaded.equity_curve) == 6


def test_futures_result_metrics_values():
    """Verify the stored metrics are computed correctly, not just passed through."""
    returns = [0.01, -0.005, 0.008, -0.002, 0.006]
    m = PerformanceMetrics.from_returns(returns, periods_per_year=252)
    assert m.n_obs == 5
    assert m.total_return == pytest.approx((1.01 * 0.995 * 1.008 * 0.998 * 1.006) - 1)
    assert m.max_drawdown < 0     # there's a drawdown after first positive
    assert m.sharpe != 0.0


# ── service layer: load_step_result() reads from a run dir ────────────────

def _write_run_dir(base: Path, run_id: str, step_name: str, payload: dict) -> Path:
    """Helper: create a minimal run dir with run_meta.json + step artifact."""
    run_dir = base / run_id
    run_dir.mkdir()
    RunManifest(
        run_id=run_id,
        mode="eod",
        asof="2026-06-06",
        steps={step_name: "ok"},
        artifacts=[f"{step_name}_result.json"],
    ).write(run_dir / "run_meta.json")
    artifact = run_dir / f"{step_name}_result.json"
    artifact.write_text(json.dumps(payload))
    return run_dir


def test_load_step_result_returns_payload(tmp_path, monkeypatch):
    """load_step_result() finds the latest EOD run and returns the artifact."""
    from web.services import artifacts as svc

    monkeypatch.setattr(svc, "runs_dir", lambda: tmp_path)

    payload = {
        "asof": "2026-06-06",
        "symbol": "TL.CFE",
        "strategies": {
            "Blended (Max Sharpe)": {"sharpe": 1.23, "ann_return": 0.15},
        },
    }
    _write_run_dir(tmp_path, "20260606-eod-120000", "futures", payload)

    result = svc.load_step_result("futures", mode="eod")
    assert result is not None
    assert result["symbol"] == "TL.CFE"
    assert result["strategies"]["Blended (Max Sharpe)"]["sharpe"] == pytest.approx(1.23)


def test_load_step_result_returns_none_when_no_runs(tmp_path, monkeypatch):
    from web.services import artifacts as svc
    monkeypatch.setattr(svc, "runs_dir", lambda: tmp_path)
    assert svc.load_step_result("futures") is None


def test_load_step_result_returns_none_when_artifact_missing(tmp_path, monkeypatch):
    """Run dir exists with a manifest but no artifact file."""
    from web.services import artifacts as svc
    monkeypatch.setattr(svc, "runs_dir", lambda: tmp_path)

    run_dir = tmp_path / "20260606-eod-120000"
    run_dir.mkdir()
    RunManifest(run_id="20260606-eod-120000", mode="eod", asof="2026-06-06",
                steps={"futures": "failed"}).write(run_dir / "run_meta.json")
    # No futures_result.json written

    assert svc.load_step_result("futures") is None


def test_latest_run_picked_over_older_one(tmp_path, monkeypatch):
    """load_step_result() should pick the most recently modified run dir."""
    from web.services import artifacts as svc
    monkeypatch.setattr(svc, "runs_dir", lambda: tmp_path)

    _write_run_dir(tmp_path, "20260605-eod-100000", "futures",
                   {"asof": "2026-06-05", "symbol": "OLD"})
    import time; time.sleep(0.01)   # ensure mtime differs
    _write_run_dir(tmp_path, "20260606-eod-120000", "futures",
                   {"asof": "2026-06-06", "symbol": "NEW"})

    result = svc.load_step_result("futures")
    assert result is not None
    assert result["symbol"] == "NEW"
