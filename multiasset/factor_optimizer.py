# -*- coding: utf-8 -*-
"""
Factor-level risk parity optimizer.

This optimizer allocates capital so that each risk factor contributes 
equally to total portfolio risk, rather than each asset.
"""
import pandas as pd
import numpy as np
from typing import Optional, Tuple, Dict
from scipy.optimize import minimize
from multiasset.factor_backtest import compute_ewma_factor_vols, compute_ewma_factor_covariance, get_factor_price_beta
from multiasset.portfolio import Portfolio
from multiasset.pca_analyzer import PCARiskFactorAnalyzer
from dateutil.relativedelta import relativedelta
# Prefer local config in multiasset; fallback to settings if not available
from .config import RiskModelConfig  # type: ignore


class FactorRiskParityOptimizer:
    """
    Optimizer using portfolio risk factors for factor risk parity.
    
    At each rebalance date:
    1. Load the configured portfolio risk factors
    2. Convert factor levels into price-return-space volatility estimates
    3. Calculate factor volatilities using EWMA
    4. Optimize portfolio weights for equal factor risk contribution
    """
    
    def __init__(self, portfolio: Portfolio, input_dir: str,
                 factor_model_lookback_years: float = 1.0,
                 vol_lookback_months: int = 3,
                 ewma_lambda: float = 0.94,
                 pca_lookback_years: Optional[float] = None):
        """
        Initialize the factor risk parity optimizer.
        
        Args:
            portfolio: Portfolio instance
            input_dir: Directory containing yield curve data
            factor_model_lookback_years: Years of data for factor-model fitting
            vol_lookback_months: Months of data for EWMA volatility
            ewma_lambda: EWMA decay parameter
            pca_lookback_years: Legacy alias for factor_model_lookback_years
        """
        if pca_lookback_years is not None:
            factor_model_lookback_years = pca_lookback_years

        self.portfolio = portfolio
        self.input_dir = input_dir
        self.factor_analyzer = PCARiskFactorAnalyzer(input_dir, factor_model_lookback_years)
        self.pca_analyzer = self.factor_analyzer
        self.vol_lookback_months = vol_lookback_months
        self.ewma_lambda = ewma_lambda
        self._weights: Optional[pd.Series] = None
        self._factor_vols: Optional[pd.Series] = None
        self._factor_cov: Optional[pd.DataFrame] = None
        self._pca_factor_vols = self._factor_vols
    
    def fit_and_calculate(self, rebalance_date: pd.Timestamp,
                          risk_budgets: Optional[Dict[str, float]] = None,
                          total_capital: float = 1.0,
                          hedge_asset_names: Optional[list] = None,
                          neutral_asset_names: Optional[list] = None,
                          use_vol_sqrt_budgets: bool = False,
                          use_dv01_shape: bool = True) -> Tuple[pd.Series, pd.Series]:
        """
        Calculate optimal weights for a given rebalance date.

        Args:
            rebalance_date: Date at which to rebalance
            risk_budgets: Optional dictionary mapping factor names to risk budgets.
                Ignored when ``use_vol_sqrt_budgets=True``.
            total_capital: Total capital for absolute risk budget calculation
            hedge_asset_names: Optional list of asset names that are allowed to
                take short positions (bounds [-0.3, 0.3] instead of [0, 1]).
            use_vol_sqrt_budgets: Kept for API compatibility. IR √vol ratio
                constraints are now always applied when risk_budgets is None,
                so this flag has no additional effect.
            use_dv01_shape: When True (default), intra-group bond weights are
                fixed to inverse-duration ratios via equality constraints so
                every bond contributes equal DV01.  Set False in backtest mode
                so that time-varying EWMA covariance drives bond allocation
                within each country group, producing visible monthly rebalancing.

        Returns:
            Tuple of (weights Series, factor volatilities Series)
        """
        risk_factors = self.portfolio.get_risk_factors(use_cache=True)
        if not isinstance(risk_factors.index, pd.DatetimeIndex):
            risk_factors.index = pd.to_datetime(risk_factors.index)
        risk_factors = risk_factors.sort_index()

        vol_start = rebalance_date - relativedelta(months=self.vol_lookback_months)
        factor_window = risk_factors.loc[
            (risk_factors.index >= vol_start) & (risk_factors.index <= rebalance_date)
        ]

        factor_vols = pd.Series(compute_ewma_factor_vols(
            factor_window,
            ewma_lambda=self.ewma_lambda,
        ))
        self._factor_vols = factor_vols
        self._pca_factor_vols = factor_vols

        factor_cov = compute_ewma_factor_covariance(factor_window, ewma_lambda=self.ewma_lambda)
        self._factor_cov = factor_cov

        # use_vol_sqrt_budgets: IR √vol ratio constraints are now injected inside
        # _optimize_weights whenever risk_budgets is None, so no pre-derivation needed.
        # The flag is kept for API compatibility but no longer overrides risk_budgets.

        if use_dv01_shape and risk_budgets is None:
            weights = self._two_stage_weights(
                factor_vols, factor_cov=factor_cov,
                total_capital=total_capital,
                hedge_asset_names=hedge_asset_names,
            )
        else:
            weights = self._optimize_weights(
                factor_vols, factor_cov=factor_cov,
                risk_budgets=risk_budgets, total_capital=total_capital,
                hedge_asset_names=hedge_asset_names,
                neutral_asset_names=neutral_asset_names,
                use_dv01_shape=use_dv01_shape,
            )
        self._weights = weights

        return weights, factor_vols

    def _two_stage_weights(self,
                           factor_vols: pd.Series,
                           factor_cov: Optional[pd.DataFrame] = None,
                           total_capital: float = 1.0,
                           hedge_asset_names: Optional[list] = None) -> pd.Series:
        """
        True two-stage allocation:

        Stage 1 — Factor-level risk parity (ERC) across all factors using
                   rolling EWMA factor covariance.  Produces a capital budget
                   per factor (e.g. IRDL.CN gets X%, CMDL.AU gets Y%).

        Stage 2 — Within each IR factor group (IRDL.XX, IRSL.XX, IRCV.XX),
                   distribute the factor's capital across the tenors it drives
                   proportional to 1/duration (= equal DV01 per tenor).
                   Non-IR assets (commodities, FX, single-tenor bonds) receive
                   their stage-1 budget directly.
        """
        exposure_matrix, asset_names, factor_names = self._build_exposure_matrix(factor_vols)
        if exposure_matrix.empty:
            n = len(self.portfolio.assets)
            return pd.Series(1.0 / n, index=list(self.portfolio.assets.keys()))

        B = exposure_matrix.values          # (n_assets, n_factors)
        n_assets = len(asset_names)
        n_factors = len(factor_names)

        # ── Stage 1: ERC at factor level ─────────────────────────────────────
        # Factor covariance C_f (n_factors × n_factors)
        use_full_cov = factor_cov is not None and not factor_cov.empty
        sigma_f = np.array([factor_vols.get(f, 0.0) for f in factor_names])
        if use_full_cov:
            C_f = np.array([
                [factor_cov.loc[fi, fj]
                 if fi in factor_cov.index and fj in factor_cov.columns
                 else (sigma_f[ki] ** 2 if ki == kj else 0.0)
                 for kj, fj in enumerate(factor_names)]
                for ki, fi in enumerate(factor_names)
            ], dtype=float)
        else:
            C_f = np.diag(sigma_f ** 2)

        C_f = (C_f + C_f.T) / 2 + 1e-10 * np.eye(n_factors)

        # ERC in factor space: minimize sum_k (e_k (C_f e)_k - 1/n)^2
        # where e = factor weight vector (fraction of total risk budget per factor)
        def _factor_port_var(e):
            return float(e @ C_f @ e)

        def _factor_rc(e):
            return e * (C_f @ e) / max(np.sqrt(_factor_port_var(e)), 1e-12)

        def _erc_objective(e):
            rc = _factor_rc(e)
            return float(np.sum((rc - rc.mean()) ** 2))

        e0 = np.ones(n_factors) / n_factors
        res = minimize(
            _erc_objective, e0,
            method='SLSQP',
            bounds=[(0.0, 1.0)] * n_factors,
            constraints=[{'type': 'eq', 'fun': lambda e: e.sum() - 1.0}],
            options={'maxiter': 500, 'ftol': 1e-10},
        )
        if not res.success:
            import warnings
            warnings.warn(
                f"_two_stage_weights: Stage-1 ERC did not converge "
                f"(status={res.status}, msg='{res.message}'). "
                "Falling back to equal factor budgets.",
                RuntimeWarning, stacklevel=3,
            )
        e_star = res.x if res.success else e0
        e_star = np.maximum(e_star, 0.0)
        e_star /= e_star.sum()

        # factor_budget[k] = fraction of total capital allocated to factor k
        factor_budget = {factor_names[k]: float(e_star[k]) for k in range(n_factors)}

        # ── Stage 2: distribute factor budgets to tenors via DV01 equalisation ──
        #
        # IR and Credit factors come in triplets (IRDL/IRSL/IRCV or CRDL/CRSL/CRCV)
        # that all drive the same set of tenors within a country/universe group.
        # The SLOPE and CURVATURE columns have sensitivities that reflect relative
        # directional exposure, NOT capital sizing — using 1/|slope_exposure| to size
        # tenors would be economically wrong (it would over-weight the belly for a
        # curvature factor, for example).
        #
        # Correct approach: pool the total budget for the whole IR/Credit group (all
        # three factors that share the same suffix), then apply DV01 equalisation
        # ONCE using only the LEVEL factor column (IRDL or CRDL), which holds pure
        # duration sensitivities.  Non-rate assets (commodities, FX, equity) are
        # distributed equally as before.
        asset_weight = np.zeros(n_assets)

        # Identify which factor names belong to IR/Credit triplet groups.
        # Key: group suffix (e.g. 'CN', 'LGB'); value: accumulated budget
        _LEVEL_PREFIXES = ('IRDL.', 'CRDL.')
        _SLOPE_PREFIXES = ('IRSL.', 'CRSL.')
        _CURVE_PREFIXES = ('IRCV.', 'CRCV.')
        _RATE_PREFIXES  = _LEVEL_PREFIXES + _SLOPE_PREFIXES + _CURVE_PREFIXES

        # Accumulate total budget per group suffix, record the level-factor column index
        _group_budget: dict = {}   # suffix -> total budget
        _group_level_col: dict = {}  # suffix -> col index of the LEVEL factor
        for k, fname in enumerate(factor_names):
            if fname.startswith(_LEVEL_PREFIXES):
                suffix = fname.split('.', 1)[1]   # e.g. 'CN', 'LGB', 'US'
                _group_budget[suffix] = _group_budget.get(suffix, 0.0) + factor_budget[fname]
                _group_level_col[suffix] = k
            elif fname.startswith(_SLOPE_PREFIXES) or fname.startswith(_CURVE_PREFIXES):
                suffix = fname.split('.', 1)[1]
                _group_budget[suffix] = _group_budget.get(suffix, 0.0) + factor_budget[fname]
                # Do NOT record a level column for slope/curve — level col already set

        # Distribute each group's pooled budget using 1/duration (level-factor column)
        _handled_suffixes: set = set()
        for k, fname in enumerate(factor_names):
            if fname.startswith(_RATE_PREFIXES):
                suffix = fname.split('.', 1)[1]
                if suffix in _handled_suffixes:
                    continue
                _handled_suffixes.add(suffix)
                if suffix not in _group_level_col:
                    continue   # no level factor present — skip
                lk = _group_level_col[suffix]
                col = B[:, lk]            # use LEVEL column for duration sizing
                active = np.abs(col) > 1e-6
                if not active.any():
                    continue
                idxs = np.where(active)[0]
                budget_group = _group_budget[suffix]
                # DV01 equalisation: each tenor gets capital ∝ 1/|duration|
                inv_dur = 1.0 / np.abs(col[idxs])
                shares = inv_dur / inv_dur.sum()
                for j, ix in enumerate(idxs):
                    asset_weight[ix] += budget_group * shares[j]
            else:
                # Commodities / FX / equity: equal split among active assets
                col = B[:, k]
                active = np.abs(col) > 1e-6
                if not active.any():
                    continue
                idxs = np.where(active)[0]
                budget_k = factor_budget[fname]
                shares = np.ones(len(idxs)) / len(idxs)
                for j, ix in enumerate(idxs):
                    asset_weight[ix] += budget_k * shares[j]

        # Normalise
        total = asset_weight.sum()
        if total > 1e-9:
            asset_weight /= total
        else:
            asset_weight = np.ones(n_assets) / n_assets

        # ── Apply per-asset-class floors and caps scaled to pool size ─────────
        # Floors/caps are proportional to equal share (1/n_assets) so they
        # remain sensible whether the pool has 3 or 15+ assets.
        from multiasset.assets import CommodityAsset, FXAsset, MultiFactorCreditAsset
        _comm_set   = {n for n in asset_names if isinstance(self.portfolio.assets.get(n), CommodityAsset)}
        _fx_set     = {n for n in asset_names if isinstance(self.portfolio.assets.get(n), FXAsset)}
        _credit_set = {n for n in asset_names if isinstance(self.portfolio.assets.get(n), MultiFactorCreditAsset)}
        _b = RiskModelConfig.scaled_bounds(n_assets)

        def _clip(i, name):
            if name in _comm_set:
                return np.clip(w[i], _b['floor_comm'], _b['cap_comm'])
            if name in _fx_set:
                return np.clip(w[i], _b['floor_fx'], _b['cap_fx'])
            if name in _credit_set:
                return np.clip(w[i], _b['floor_credit'], _b['cap_credit'])
            return np.clip(w[i], _b['floor_bond'], _b['cap_bond'])

        # ── Feasibility guard: check floors don't exceed 1 before clipping ──
        _floor_sum = sum(
            _b['floor_comm'] if name in _comm_set
            else _b['floor_fx'] if name in _fx_set
            else _b['floor_credit'] if name in _credit_set
            else _b['floor_bond']
            for name in asset_names
        )
        if _floor_sum > 1.0:
            import warnings
            warnings.warn(
                f"_two_stage_weights: sum of asset floors ({_floor_sum:.3f}) > 1.0 "
                f"for pool of {n_assets} assets — bounds are jointly infeasible. "
                "Weights may violate floors. Consider reducing FLOOR_RATIO constants "
                "in RiskModelConfig.",
                RuntimeWarning, stacklevel=3,
            )

        w = asset_weight.copy()
        # Iterate clip → renorm until convergence (floors/caps satisfied simultaneously)
        for _ in range(10):
            for i, name in enumerate(asset_names):
                w[i] = _clip(i, name)
            s = w.sum()
            if s > 1e-9:
                w /= s

        # ── Post-solve bounds assertion (soft — warn, don't raise) ────────────
        _TOL = 1e-4
        violations = []
        for i, name in enumerate(asset_names):
            lo = (_b['floor_comm']   if name in _comm_set
                  else _b['floor_fx']     if name in _fx_set
                  else _b['floor_credit'] if name in _credit_set
                  else _b['floor_bond'])
            hi = (_b['cap_comm']   if name in _comm_set
                  else _b['cap_fx']     if name in _fx_set
                  else _b['cap_credit'] if name in _credit_set
                  else _b['cap_bond'])
            if w[i] < lo - _TOL or w[i] > hi + _TOL:
                violations.append(f"{name}: w={w[i]:.4f} ∉ [{lo:.4f}, {hi:.4f}]")
        if violations:
            import warnings
            warnings.warn(
                "_two_stage_weights: bounds violated after clip→renorm:\n  "
                + "\n  ".join(violations),
                RuntimeWarning, stacklevel=3,
            )

        return pd.Series(w, index=asset_names)
    
    def _calculate_ewma_volatilities(self, factor_returns: pd.DataFrame) -> pd.Series:
        """
        Calculate EWMA volatilities for factor return series.
        
        Args:
            factor_returns: DataFrame of factor returns
            
        Returns:
            Series of annualized volatilities by factor
        """
        factor_vols = {}
        alpha = 1.0 - self.ewma_lambda
        
        for col in factor_returns.columns:
            returns = factor_returns[col].dropna()
            
            if len(returns) < 5:
                factor_vols[col] = float('nan')
                continue
            
            # EWMA variance
            ewma_var = returns.ewm(alpha=alpha, adjust=False).var()
            
            # Use latest EWMA variance, annualize (sqrt(252))
            latest_vol = np.sqrt(ewma_var.iloc[-1]) * np.sqrt(252)
            factor_vols[col] = latest_vol
        
        return pd.Series(factor_vols)
    
    def _optimize_weights(self, factor_vols: pd.Series,
                          factor_cov: Optional[pd.DataFrame] = None,
                          risk_budgets: Optional[Dict[str, float]] = None,
                          total_capital: float = 1.0,
                          hedge_asset_names: Optional[list] = None,
                          neutral_asset_names: Optional[list] = None,
                          use_dv01_shape: bool = True) -> pd.Series:
        """
        Optimize portfolio weights using factor risk parity or risk budgeting.

        Uses the full EWMA factor covariance matrix (Σ = B C_f Bᵀ) when
        available, so that inter-factor correlations are captured.  Falls back
        to the diagonal approximation when factor_cov is empty.

        Args:
            factor_vols: Series of factor volatilities (used for filtering and fallback)
            factor_cov: Annualised EWMA factor covariance DataFrame (n_factors × n_factors)
            risk_budgets: Optional dict of risk budgets per factor (in million CNY)
            total_capital: Total capital to allocate (absolute units)
            hedge_asset_names: Optional list of asset names allowed to take short
                positions; they receive bounds (-0.3, 0.3) while regular assets
                stay long-only (0.0, 1.0).
            use_dv01_shape: When True, add intra-group DV01 equality constraints.
                Set False in backtest to let rolling covariance drive bond allocation.

        Returns:
            Series of optimal weights
        """
        exposure_matrix, asset_names, factor_names = self._build_exposure_matrix(factor_vols)

        if exposure_matrix.empty:
            return pd.Series(1.0 / len(self.portfolio.assets),
                             index=list(self.portfolio.assets.keys()))

        B = exposure_matrix.values                                   # (n_assets, n_factors)
        sigma_f = np.array([factor_vols.get(f, 0) for f in factor_names])

        # Keep only factors with non-zero vol
        valid_mask = ~np.isnan(sigma_f) & (sigma_f > 0)
        B = B[:, valid_mask]
        sigma_f_valid = sigma_f[valid_mask]
        valid_factors = [f for i, f in enumerate(factor_names) if valid_mask[i]]

        if len(sigma_f_valid) == 0:
            return pd.Series(1.0 / len(asset_names), index=asset_names)

        n_assets = len(asset_names)

        # ── Build asset covariance Σ = B C_f Bᵀ ──────────────────────────────
        use_full_cov = (factor_cov is not None and not factor_cov.empty)
        if use_full_cov:
            C_f = np.array([
                [factor_cov.loc[fi, fj]
                 if (fi in factor_cov.index and fj in factor_cov.columns)
                 else (sigma_f_valid[ki] ** 2 if ki == kj else 0.0)
                 for kj, fj in enumerate(valid_factors)]
                for ki, fi in enumerate(valid_factors)
            ], dtype=float)
        else:
            C_f = np.diag(sigma_f_valid ** 2)

        Sigma = B @ C_f @ B.T
        Sigma = (Sigma + Sigma.T) / 2 + 1e-8 * np.eye(n_assets)   # symmetrise + regularise

        # Pre-compute transpose once so every scipy.minimize iteration avoids
        # recomputing it inside the closure.
        BT = B.T

        # ── Helper: asset-level risk contributions ────────────────────────────
        def _port_vol(w: np.ndarray) -> float:
            return float(np.sqrt(max(float(w @ Sigma @ w), 1e-12)))

        def _risk_contributions(w: np.ndarray) -> np.ndarray:
            pv = _port_vol(w)
            return w * (Sigma @ w) / pv                             # sums to pv

        # ── Helper: factor-level risk contributions ───────────────────────────
        def _factor_rc_fractions(w: np.ndarray) -> np.ndarray:
            """Return each factor's share of total portfolio variance (sums to 1)."""
            e = BT @ w                                              # (n_valid_factors,)
            Cfe = C_f @ e
            rc_var = e * Cfe                                        # contribution to variance
            total_var = float(rc_var.sum())
            if total_var < 1e-12:
                return np.ones(len(valid_factors)) / len(valid_factors)
            return rc_var / total_var

        # ── Constraints & objective ───────────────────────────────────────────
        constraints = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}]
        # Asset indices whose weight is pinned by an intra-group DV01 shape constraint
        # (populated only in the min-vol branch); their bounds are relaxed to [0, 1].
        _shape_locked_bonds: set = set()
        # Per-group anchor → shape mapping, used to build a feasible initial point.
        _shape_groups: list = []   # list of (idxs ndarray, shape ndarray)

        if risk_budgets:
            # User-defined / factor-scaling: steer factor RC fractions to explicit budgets.
            # Budget values are treated as proportional fractions of total risk regardless
            # of whether factor_cov is available — single unit system, no silent switching.
            # Negative budgets allow signed RC matching (e.g. short slope expression).
            has_negative = any(
                v is not None and float(v) < 0.0 for v in risk_budgets.values()
            )
            raw_budgets = np.array([
                float(risk_budgets.get(f, 0.0)) if risk_budgets.get(f) is not None else 0.0
                for f in valid_factors
            ])
            total_rb = np.abs(raw_budgets).sum()
            budget_fracs = (raw_budgets / total_rb
                            if total_rb > 1e-12
                            else np.ones(len(valid_factors)) / len(valid_factors))

            if has_negative:
                # Signed RC matching: direction of signed exposure matters
                def objective(w: np.ndarray) -> float:
                    e = BT @ w
                    Cfe = C_f @ e
                    signed_rc = e * Cfe / max(_port_vol(w), 1e-12)
                    total_sv = np.abs(signed_rc).sum()
                    target = budget_fracs * (total_sv if total_sv > 1e-12 else 1.0)
                    return float(np.sum((signed_rc - target) ** 2))
            else:
                # Unsigned RC fraction matching
                def objective(w: np.ndarray) -> float:
                    return float(np.sum((_factor_rc_fractions(w) - budget_fracs) ** 2))
        else:
            # Min-vol + analytic intra-group DV01 equalisation (two-stage).
            #
            # Problem: with N bonds all loading on the same 3 CN factors (IRDL/IRSL/IRCV),
            # the covariance Σ = B·C_f·Bᵀ has rank 3, leaving a (N-3)-dimensional null
            # space where pure min-vol picks an arbitrary corner.
            #
            # Fix (two-stage): within each country group (bonds sharing the same IRDL.XX
            # factor), FIX the relative bond shape analytically to inverse-duration
            # (w_i ∝ 1/|IRDL_i|, the modified durations from get_default_sensitivities),
            # so every bond in the group contributes equal DV01.  Then let the optimizer
            # choose only the SCALAR capital per group (plus commodity/FX), minimising
            # portfolio variance.  The fixed shape is imposed as equality constraints that
            # lock each bond's weight to the group's first bond via its duration ratio —
            # these are always mutually consistent, so SLSQP stays feasible.
            #
            # Result: bond degrees of freedom collapse from N to (#country groups),
            # eliminating the null space; bond weights are economically meaningful
            # (shorter tenors get more capital → equal DV01), and the cross-group +
            # cross-asset-class split still minimises portfolio vol.
            def objective(w: np.ndarray) -> float:
                return float(w @ Sigma @ w)

            # Build country groups keyed by IRDL.XX factor; compute inverse-duration shape.
            # _shape_locked_bonds collects asset indices whose weight is pinned by a shape
            # constraint (everything except the group anchor); their bounds are relaxed to
            # [0, 1] below since the equality constraints — not the floor — govern them.
            # When use_dv01_shape=False (backtest mode) this block is skipped entirely:
            # bonds are free within their bounds so rolling covariance drives rebalancing.
            irdl_factors = [f for f in valid_factors if f.startswith('IRDL.')] if use_dv01_shape else []
            for irdl_f in irdl_factors:
                fi = valid_factors.index(irdl_f)
                col = B[:, fi]                                   # IRDL exposure (∝ duration)
                bond_mask = np.abs(col) > 1e-6
                if bond_mask.sum() < 2:
                    continue                                     # single-bond group: no constraint needed
                idxs = np.where(bond_mask)[0]
                inv_dur = 1.0 / np.abs(col[idxs])                # 1/|IRDL| ∝ inverse duration
                shape = inv_dur / inv_dur.sum()                  # normalised within group
                _shape_groups.append((idxs, shape))
                # Anchor on the LONGEST-duration bond (smallest shape weight) so the
                # anchor never hits the per-asset cap and distorts the group ratios.
                _anchor_pos = int(np.argmax(np.abs(col[idxs])))   # max |IRDL| = longest duration
                i0 = idxs[_anchor_pos]
                s0 = shape[_anchor_pos]
                # Lock each other bond to the anchor via the shape ratio:
                #   w[idx_k] * shape[anchor] == w[anchor] * shape[k]
                for k in range(len(idxs)):
                    if k == _anchor_pos:
                        continue
                    ik = idxs[k]
                    sk = shape[k]
                    def _make_shape_con(_i0, _ik, _s0, _sk):
                        return lambda w: w[_ik] * _s0 - w[_i0] * _sk
                    constraints.append({'type': 'eq',
                                        'fun': _make_shape_con(i0, ik, s0, sk)})
                    _shape_locked_bonds.add(int(ik))
                # The anchor itself is also exempt from the per-asset bond cap: the
                # DV01 shape already controls concentration within the group.
                _shape_locked_bonds.add(int(i0))

        # ── Per-asset bounds ─────────────────────────────────────────────────
        # Hedge instruments are allowed to take short positions.  Regular assets
        # stay long-only.  A small minimum weight floor prevents the optimizer
        # from zeroing out assets when the B matrix is rank-deficient (e.g. 6
        # CN bonds all sharing the same 3 factors → degenerate ERC landscape).
        _MAX_HEDGE_WT = 0.30
        _hedge_set   = set(hedge_asset_names)   if hedge_asset_names   else set()
        _neutral_set = set(neutral_asset_names) if neutral_asset_names else set()

        # Auto-detect neutral assets from risk_budgets: an asset is neutral when
        # its total weighted budget exposure across all factors it loads on is ~0.
        # Scalar levels are {0, ±0.25, ±0.5, ±0.75, ±1.0}; scalar=0 means flat.
        if risk_budgets and not _neutral_set:
            _budget_arr = np.array([
                float(risk_budgets.get(f, 0.0)) if risk_budgets.get(f) is not None else 0.0
                for f in valid_factors
            ])
            _asset_budget_exposure = np.abs(B) @ np.abs(_budget_arr)
            _total_budget = np.abs(_budget_arr).sum()
            if _total_budget > 1e-9:
                for _ai, _aname in enumerate(asset_names):
                    if _asset_budget_exposure[_ai] < 1e-9 * _total_budget:
                        _neutral_set.add(_aname)

        from multiasset.assets import CommodityAsset, FXAsset
        _commodity_set = {name for name in asset_names if isinstance(self.portfolio.assets.get(name), CommodityAsset)}
        _fx_set = {name for name in asset_names if isinstance(self.portfolio.assets.get(name), FXAsset)}

        # Floors and caps scale with pool size: floor = eq_share × ratio, cap = eq_share × ratio
        _sb = RiskModelConfig.scaled_bounds(n_assets)
        _commodity_min_wt = _sb['floor_comm']
        _fx_min_wt        = _sb['floor_fx']
        _min_wt           = _sb['floor_bond']
        _CAP_COMM         = _sb['cap_comm']
        _CAP_FX           = _sb['cap_fx']
        _CAP_BOND         = _sb['cap_bond']
        _CAP_NEUTRAL      = max(0.25 / n_assets, _min_wt)

        # When no explicit budgets are given (min-vol / two-stage path): fix commodity
        # and FX at their class floor so the bond sub-problem stays well-conditioned.
        _pin_non_ir = (risk_budgets is None)
        # Bonds inside a multi-bond group have their relative weight fixed by the DV01
        # shape equality constraints, so their per-asset floor/cap must be relaxed to
        # [0, 1] — otherwise a long-duration bond's tiny shape weight (e.g. 1/17 for
        # CN30Y) would conflict with the floor and make the problem infeasible.
        bounds = [
            (-_MAX_HEDGE_WT, _MAX_HEDGE_WT) if name in _hedge_set
            else (0.0, _CAP_NEUTRAL)            if name in _neutral_set
            else (_commodity_min_wt, _commodity_min_wt if _pin_non_ir else _CAP_COMM) if name in _commodity_set
            else (_fx_min_wt,        _fx_min_wt        if _pin_non_ir else _CAP_FX)   if name in _fx_set
            else (0.0, 1.0)                     if i in _shape_locked_bonds
            else (_min_wt, _CAP_BOND)
            for i, name in enumerate(asset_names)
        ]

        # Initial point: commodity/FX at floor; bond groups laid out on their fixed
        # inverse-duration shape so SLSQP starts feasible w.r.t. the shape equalities.
        w0 = np.array([
            _commodity_min_wt if name in _commodity_set
            else _fx_min_wt   if name in _fx_set
            else _min_wt
            for name in asset_names
        ])
        if _shape_groups:
            # Distribute the remaining (non-commodity/FX) capital across groups equally,
            # then within each group along its inverse-duration shape.
            _fixed = sum(w0[i] for i, name in enumerate(asset_names)
                         if name in _commodity_set or name in _fx_set)
            _grouped_idx = set()
            for idxs, _ in _shape_groups:
                _grouped_idx.update(int(x) for x in idxs)
            _ungrouped_bonds = [i for i, name in enumerate(asset_names)
                                if name not in _commodity_set and name not in _fx_set
                                and i not in _grouped_idx]
            _n_units = len(_shape_groups) + len(_ungrouped_bonds)
            _avail = max(1.0 - _fixed, 0.0)
            _per_unit = _avail / _n_units if _n_units > 0 else 0.0
            for idxs, shape in _shape_groups:
                for j, ix in enumerate(idxs):
                    w0[ix] = _per_unit * shape[j]
            for ix in _ungrouped_bonds:
                w0[ix] = _per_unit
        else:
            remaining = 1.0 - w0.sum()
            if remaining > 0:
                bond_indices = [i for i, name in enumerate(asset_names)
                                if name not in _commodity_set and name not in _fx_set]
                if bond_indices:
                    w0[bond_indices] += remaining / len(bond_indices)

        result = minimize(
            objective, w0,
            method='SLSQP',
            bounds=bounds,
            constraints=constraints,
            options={'maxiter': 1000, 'ftol': 1e-9},
        )

        # ── If the primary solve did not converge, retry without hedge shorts ─
        if not result.success and _hedge_set:
            fallback_bounds = [
                (_commodity_min_wt, _CAP_COMM) if name in _commodity_set
                else (_fx_min_wt, _CAP_FX)     if name in _fx_set
                else (0.0, 1.0)                if i in _shape_locked_bonds
                else (_min_wt, _CAP_BOND)
                for i, name in enumerate(asset_names)
            ]
            result_fb = minimize(
                objective, w0,
                method='SLSQP',
                bounds=fallback_bounds,
                constraints=constraints,
                options={'maxiter': 1000, 'ftol': 1e-9},
            )
            if result_fb.success or result_fb.fun < result.fun:
                result = result_fb

        if not result.success:
            import warnings
            warnings.warn(
                f"FactorRiskParityOptimizer: SLSQP did not converge "
                f"(status={result.status}, message='{result.message}'). "
                "Returning best-effort weights — risk contributions may not match targets.",
                RuntimeWarning,
                stacklevel=3,
            )

        return pd.Series(result.x, index=asset_names)

    def _compute_factor_risk_contributions(
        self,
        weights: pd.Series,
        exposure_matrix: pd.DataFrame,
        factor_names: list,
        factor_cov: Optional[pd.DataFrame],
        factor_vols: pd.Series,
    ) -> pd.DataFrame:
        """
        Compute factor-level risk contributions using the full covariance matrix.

        For each factor k:
          RC_k = e_k * (C_f @ e)_k  (contribution to portfolio variance)
          where e = Bᵀ w  (portfolio factor exposures)

        Returns a DataFrame with columns:
          Risk Factor, Volatility (% ann.), Risk Contribution (%)
        """
        if exposure_matrix.empty:
            return pd.DataFrame()

        _exp_idx = exposure_matrix.index
        if not _exp_idx.is_unique:
            _exp_idx = _exp_idx[~_exp_idx.duplicated(keep='first')]
        w = weights.reindex(_exp_idx).fillna(0.0).values
        B = exposure_matrix.values                                   # (n_assets, n_factors)
        sigma_f = np.array([factor_vols.get(f, 0.0) for f in factor_names])

        valid_mask = ~np.isnan(sigma_f) & (sigma_f > 0)
        B_v = B[:, valid_mask]
        sigma_v = sigma_f[valid_mask]
        valid_factors = [f for i, f in enumerate(factor_names) if valid_mask[i]]

        use_full_cov = (factor_cov is not None and not factor_cov.empty)
        if use_full_cov:
            C_f = np.array([
                [factor_cov.loc[fi, fj]
                 if (fi in factor_cov.index and fj in factor_cov.columns)
                 else (sigma_v[ki] ** 2 if ki == kj else 0.0)
                 for kj, fj in enumerate(valid_factors)]
                for ki, fi in enumerate(valid_factors)
            ], dtype=float)
        else:
            C_f = np.diag(sigma_v ** 2)

        e = B_v.T @ w                                               # (n_valid_factors,)
        Cfe = C_f @ e
        port_var = float(e @ Cfe)
        port_vol_val = float(np.sqrt(max(port_var, 1e-12)))

        rows = []
        for k, f in enumerate(valid_factors):
            rc_var = float(e[k] * Cfe[k])
            rc_pct = rc_var / port_var * 100.0 if port_var > 1e-12 else 0.0
            # Signed net factor exposure e_k tells you directional bet:
            #   positive → portfolio gains when factor PRICE rises (e.g. long level = yield falls)
            #   negative → portfolio gains when factor PRICE falls (e.g. short slope)
            rows.append({
                'Risk Factor': f,
                'Volatility (% ann.)': float(sigma_v[k]),
                'Net Exposure': float(e[k]),          # signed: + long factor, - short factor
                'Risk Contribution (%)': rc_pct,      # always >= 0 (variance contribution)
            })

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        return df.sort_values('Risk Contribution (%)', ascending=False).reset_index(drop=True)

    
    def _build_exposure_matrix(self, factor_vols: pd.Series) -> Tuple[pd.DataFrame, list, list]:
        """
        Build asset-factor exposure matrix using factor names.
        
        Maps asset sensitivities to model factors (IRDL.XX, IRSL.XX, IRCV.XX).
        """
        asset_names = list(self.portfolio.assets.keys())
        factor_names = [f for f in factor_vols.index if pd.notna(factor_vols[f])]
        
        # Build exposure matrix
        exposure_matrix = np.zeros((len(asset_names), len(factor_names)))
        
        for i, asset_name in enumerate(asset_names):
            asset = self.portfolio.assets[asset_name]
            for j, factor_name in enumerate(factor_names):
                if factor_name in asset.factors:
                    exposure_matrix[i, j] = get_factor_price_beta(
                        factor_name,
                        asset.factors[factor_name],
                    )
        
        return pd.DataFrame(exposure_matrix, index=asset_names, columns=factor_names), asset_names, factor_names
    
    def allocate_capital(self, total_capital: float, 
                        rebalance_date: pd.Timestamp) -> pd.Series:
        """
        Allocate capital using factor risk parity.
        
        Args:
            total_capital: Total capital to allocate
            rebalance_date: Date at which to rebalance
            
        Returns:
            Series of capital allocations
        """
        weights, _ = self.fit_and_calculate(rebalance_date)
        return weights * total_capital
    
    def get_factor_model_diagnostics(self) -> Dict:
        """Get factor-model diagnostics including explained variance ratios."""
        diagnostics = {}
        
        for country in ['US', 'JP', 'DE', 'UK', 'CN']:
            var_ratios = self.factor_analyzer.get_explained_variance(country)
            if var_ratios is not None:
                diagnostics[country] = {
                    'PC1_var': var_ratios[0] if len(var_ratios) > 0 else None,
                    'PC2_var': var_ratios[1] if len(var_ratios) > 1 else None,
                    'PC3_var': var_ratios[2] if len(var_ratios) > 2 else None,
                    'total_explained': sum(var_ratios)
                }
        
        return diagnostics

    def get_pca_diagnostics(self) -> Dict:
        """Backward-compatible alias for factor-model diagnostics."""
        return self.get_factor_model_diagnostics()
    
    def get_factor_loadings(self, country: str) -> Optional[pd.DataFrame]:
        """Get PCA factor loadings for a country."""
        return self.factor_analyzer.get_factor_loadings(country)
    
    def clear_cache(self):
        """Clear cached data."""
        self._weights = None
        self._factor_vols = None
        self._pca_factor_vols = None
        self.factor_analyzer.clear_cache()

    @staticmethod
    def assert_weights_match(
        w1: 'pd.Series',
        w2: 'pd.Series',
        tol: float = 1e-6,
        label: str = '',
    ) -> None:
        """Assert that two weight series are identical within tolerance.

        Use this in regression tests to verify that the live path (via
        ``optimize()``) and the backtest path (direct ``fit_and_calculate()``)
        return the same weights for the same inputs — preventing §7.6 drift.

        Raises:
            AssertionError: if any weight differs by more than *tol*, with a
                summary of the largest divergences.
        """
        common = w1.index.union(w2.index)
        a = w1.reindex(common, fill_value=0.0)
        b = w2.reindex(common, fill_value=0.0)
        diff = (a - b).abs()
        max_diff = float(diff.max())
        if max_diff > tol:
            worst = diff.nlargest(5)
            tag = f" [{label}]" if label else ""
            raise AssertionError(
                f"Weight mismatch{tag}: max |Δw| = {max_diff:.2e} > tol={tol:.2e}\n"
                + worst.to_string()
            )

    def optimize(self, total_capital: float, use_cache: bool = True,
                 risk_budgets: Dict[str, float] = None,
                 hedge_asset_names: list = None,
                 neutral_asset_names: list = None):
        """
        Run the optimization and return detailed results.
        
        Args:
            total_capital: Total capital to allocate
            use_cache: Whether to use cached data
            risk_budgets: Optional risk budgets per factor
            hedge_asset_names: Optional list of asset names with short-allowed bounds
            
        Returns:
            Tuple of (summary, asset_returns, volatilities, factor_exposures, factor_risk_contributions)
        """
        # Snap to the last day of the previous month — the same cut-off the
        # factor model uses for training — so the portfolio tab never fits on
        # current-month/today's data (avoids look-ahead bias / overfitting).
        _today = pd.Timestamp.today().normalize()
        _prev_month_end = _today.replace(day=1) - relativedelta(days=1)
        _data_max = self.portfolio.risk_factor_loader.last_date()
        if _data_max is None:
            raise RuntimeError("RiskFactorLoader: no data loaded — call load_risk_factors() first.")
        rebalance_date = min(_prev_month_end, _data_max)
        
        # Fit and Calculate
        weights, factor_vols = self.fit_and_calculate(
            rebalance_date,
            risk_budgets=risk_budgets,
            total_capital=total_capital,
            hedge_asset_names=hedge_asset_names,
            neutral_asset_names=neutral_asset_names,
        )
        
        # Construct summary
        allocation = weights * total_capital
        summary = pd.DataFrame({
            'Asset': weights.index,
            'Allocation (CNY)': allocation.values,
            'Weight (%)': weights.values * 100,
            'Asset Type': [self.portfolio.assets[a].__class__.__name__ for a in weights.index] # Approx type
        })
        
        # Compute Factor Exposures (Long Format) and Risk Contributions
        exposure_matrix, asset_names, factor_names = self._build_exposure_matrix(factor_vols)

        # Use full-covariance attribution when available
        factor_risk_contributions = self._compute_factor_risk_contributions(
            weights, exposure_matrix, factor_names, self._factor_cov, factor_vols
        )

        factor_exposures_df = pd.DataFrame(exposure_matrix, index=weights.index, columns=factor_names)
        factor_exp_long = factor_exposures_df.reset_index().melt(id_vars='index', var_name='Risk Factor', value_name='Exposure')
        factor_exp_long.rename(columns={'index': 'Asset'}, inplace=True)
        
        # Dummy asset returns (not calculated here usually, but required by signature)
        asset_returns = pd.DataFrame() 
        
        return summary, asset_returns, factor_vols, factor_exp_long, factor_risk_contributions

    def print_summary(self, summary, total_capital, factor_exposures, factor_risk_contributions):
        """Print summary of optimization results."""
        print(f"Total Capital: {total_capital:,.2f}")
        print(summary)


PCAFactorRiskParityOptimizer = FactorRiskParityOptimizer
