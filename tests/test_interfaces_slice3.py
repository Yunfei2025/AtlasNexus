"""Step 4 Slice 3 — remaining interface summaries.

Tests that each calibrate() produces a JSON-serializable summary dict with
the expected keys. No market data / Wind dependency — uses mocks throughout.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ── helpers ───────────────────────────────────────────────────────────────

def _is_json_serializable(obj) -> bool:
    try:
        json.dumps(obj)
        return True
    except (TypeError, ValueError):
        return False


def _make_run_config(asof_str: str = "2026-06-06"):
    from datetime import date
    from pathlib import Path
    from engine.context import RunConfig
    return RunConfig(
        asof=date.fromisoformat(asof_str),
        mode="eod",
        run_id="test-run",
        output_dir=Path("/tmp/test-run"),
        input_dir=Path("/tmp/input"),
    )


# ── curves/interface.py ───────────────────────────────────────────────────

class TestCurvesInterface:
    def test_returns_json_serializable_dict(self):
        cfg = _make_run_config()
        store = MagicMock()
        fake = MagicMock()
        fake.main.return_value = "Completed curve generation"
        with patch.dict("sys.modules", {"curves.initialise": fake}):
            import curves.interface as iface
            result = iface.calibrate(cfg, store)

        assert isinstance(result, dict)
        assert result["asof"] == "2026-06-06"
        assert "status" in result
        assert _is_json_serializable(result)

    def test_status_captured_from_main(self):
        cfg = _make_run_config()
        store = MagicMock()
        fake = MagicMock()
        fake.main.return_value = "Skipped: already updated today"
        with patch.dict("sys.modules", {"curves.initialise": fake}):
            import curves.interface as iface
            result = iface.calibrate(cfg, store)

        assert result["status"] == "Skipped: already updated today"


# ── factors/interface.py — _extract_factors_summary ───────────────────────

class TestFactorsExtractSummary:
    """Test the extraction helper in isolation — no factor engine needed."""

    def _make_results(self, status="success", sharpe=1.5, total_return=0.12,
                      selected_factors=None):
        bm = SimpleNamespace(
            total_return=total_return, annual_return=0.15,
            volatility=0.10, sharpe_ratio=sharpe,
            max_drawdown=-0.08, win_rate=0.55,
        )
        stats = SimpleNamespace(
            total_periods=12, successful_periods=11, success_rate=0.917,
        )
        pr = SimpleNamespace(
            selected_factors=selected_factors or ["momentum", "carry"],
        )
        return SimpleNamespace(
            status=status,
            stats=stats,
            backtest_metrics=bm,
            period_results=[pr],
        )

    def test_extracts_scalar_metrics(self):
        from factors.interface import _extract_factors_summary
        model_cfg = SimpleNamespace(ticker="TL.CFE")
        res = _extract_factors_summary("2026-06-06", self._make_results(), model_cfg)

        assert res["asof"] == "2026-06-06"
        assert res["status"] == "success"
        assert res["ticker"] == "TL.CFE"
        assert res["backtest_metrics"]["sharpe_ratio"] == pytest.approx(1.5)
        assert res["backtest_metrics"]["total_return"] == pytest.approx(0.12)
        assert res["stats"]["successful_periods"] == 11
        assert res["selected_factors"] == ["momentum", "carry"]
        assert _is_json_serializable(res)

    def test_handles_none_results(self):
        from factors.interface import _extract_factors_summary
        model_cfg = SimpleNamespace(ticker="X")
        res = _extract_factors_summary("2026-06-06", None, model_cfg)
        assert res["status"] == "failed"
        assert _is_json_serializable(res)

    def test_handles_missing_attributes_gracefully(self):
        from factors.interface import _extract_factors_summary
        model_cfg = SimpleNamespace(ticker="Y")
        bare = SimpleNamespace(status="success", stats=None,
                               backtest_metrics=None, period_results=[])
        res = _extract_factors_summary("2026-06-06", bare, model_cfg)
        assert res["status"] == "success"
        assert res["selected_factors"] == []
        assert _is_json_serializable(res)

    def test_no_non_serializable_objects_leak(self):
        """Ensure pandas Series / DataFrames don't leak into the summary."""
        import pandas as pd
        from factors.interface import _extract_factors_summary
        model_cfg = SimpleNamespace(ticker="Z")
        # Backtest data has Series — must NOT appear in output
        bd = SimpleNamespace(strategy_returns=pd.Series([0.01, 0.02]))
        res_obj = self._make_results()
        res_obj.backtest_data = bd
        res = _extract_factors_summary("2026-06-06", res_obj, model_cfg)
        assert _is_json_serializable(res)


# ── pairs/interface.py ────────────────────────────────────────────────────

class TestPairsInterface:
    def test_returns_pair_names_and_count(self):
        cfg = _make_run_config()
        store = MagicMock()
        fake_results = {"TBond_10y_5y": MagicMock(), "CBond_AAA_AA": MagicMock()}
        fake_main_mod = MagicMock()
        fake_main_mod.main.return_value = fake_results
        with patch.dict("sys.modules", {"pairs.main": fake_main_mod}):
            import pairs.interface as iface
            result = iface.calibrate(cfg, store)

        assert result["asof"] == "2026-06-06"
        assert result["pair_count"] == 2
        assert set(result["pairs"]) == {"TBond_10y_5y", "CBond_AAA_AA"}
        assert _is_json_serializable(result)

    def test_handles_empty_results(self):
        cfg = _make_run_config()
        store = MagicMock()
        fake_main_mod = MagicMock()
        fake_main_mod.main.return_value = {}
        with patch.dict("sys.modules", {"pairs.main": fake_main_mod}):
            import pairs.interface as iface
            result = iface.calibrate(cfg, store)

        assert result["pair_count"] == 0
        assert result["pairs"] == []

    def test_handles_none_results(self):
        cfg = _make_run_config()
        store = MagicMock()
        fake_main_mod = MagicMock()
        fake_main_mod.main.return_value = None
        with patch.dict("sys.modules", {"pairs.main": fake_main_mod}):
            import pairs.interface as iface
            result = iface.calibrate(cfg, store)

        assert result["pair_count"] == 0


# ── multiasset/interface.py ───────────────────────────────────────────────

class TestMultiassetInterface:
    def _make_asset(self, name):
        return SimpleNamespace(name=name)

    def test_returns_counts_and_names(self):
        cfg = _make_run_config()
        store = MagicMock()
        bonds = [self._make_asset("TBond_10y"), self._make_asset("CBond_AAA")]
        spreads = [self._make_asset("IRS_5y")]
        fake_main_mod = MagicMock()
        fake_main_mod.create_bond_universe.return_value = bonds
        fake_main_mod.create_spread_universe.return_value = spreads
        with patch.dict("sys.modules", {"multiasset.main": fake_main_mod}):
            import multiasset.interface as iface
            result = iface.calibrate(cfg, store)

        assert result["asof"] == "2026-06-06"
        assert result["bond_count"] == 2
        assert result["spread_count"] == 1
        assert "TBond_10y" in result["bond_names"]
        assert "IRS_5y" in result["spread_names"]
        assert _is_json_serializable(result)

    def test_handles_empty_universes(self):
        cfg = _make_run_config()
        store = MagicMock()
        fake_main_mod = MagicMock()
        fake_main_mod.create_bond_universe.return_value = []
        fake_main_mod.create_spread_universe.return_value = []
        with patch.dict("sys.modules", {"multiasset.main": fake_main_mod}):
            import multiasset.interface as iface
            result = iface.calibrate(cfg, store)

        assert result["bond_count"] == 0
        assert result["spread_count"] == 0
        assert _is_json_serializable(result)


# ── derivatives/interface.py ──────────────────────────────────────────────

class TestDerivativesInterface:
    def test_returns_greeks_with_asof(self):
        cfg = _make_run_config()
        store = MagicMock()
        greeks = {"price": 0.0523, "delta": 0.42, "gamma": 0.08,
                  "vega": 0.15, "theta": -0.003, "rho": 0.01}
        fake_pricer_main = MagicMock()
        fake_pricer_main.main.return_value = greeks
        with patch.dict("sys.modules", {"derivatives.pricer.main": fake_pricer_main}):
            import derivatives.interface as iface
            result = iface.calibrate(cfg, store)

        assert result["asof"] == "2026-06-06"
        assert result["price"] == pytest.approx(0.0523)
        assert result["delta"] == pytest.approx(0.42)
        assert _is_json_serializable(result)

    def test_handles_import_error_gracefully(self):
        cfg = _make_run_config()
        store = MagicMock()
        with patch.dict("sys.modules", {"derivatives.pricer.main": None}):
            import derivatives.interface as iface
            result = iface.calibrate(cfg, store)

        assert result is None

    def test_handles_non_dict_return(self):
        cfg = _make_run_config()
        store = MagicMock()
        fake_pricer_main = MagicMock()
        fake_pricer_main.main.return_value = None
        with patch.dict("sys.modules", {"derivatives.pricer.main": fake_pricer_main}):
            import derivatives.interface as iface
            result = iface.calibrate(cfg, store)

        assert result == {"asof": "2026-06-06"}
        assert _is_json_serializable(result)
