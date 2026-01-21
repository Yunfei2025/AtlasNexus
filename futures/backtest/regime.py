import numpy as np
import pandas as pd
import pickle
import os
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler
from typing import Any, Dict, List, Optional, Tuple, Union, TYPE_CHECKING
from collections import deque

# Type ignore comments for dynamic sklearn/hmmlearn attributes
# pyright: reportAttributeAccessIssue=false

# =============================================================================
# Helper Functions for Enhanced Feature Calculation
# =============================================================================

def _estimate_hurst(series: np.ndarray) -> float:
    """
    Estimate Hurst exponent using R/S (Rescaled Range) method.
    
    Interpretation:
        H > 0.5: Persistent/Trending (positive autocorrelation)
        H = 0.5: Random walk (no memory)
        H < 0.5: Anti-persistent/Mean-reverting (negative autocorrelation)
    
    Args:
        series: 1D array of returns or price changes.
        
    Returns:
        Estimated Hurst exponent (float between 0 and 1).
    """
    if len(series) < 10:
        return 0.5
    
    series = np.asarray(series)
    series = series[~np.isnan(series)]
    
    if len(series) < 10:
        return 0.5
    
    n = len(series)
    mean = np.mean(series)
    cumdev = np.cumsum(series - mean)
    R = np.max(cumdev) - np.min(cumdev)
    S = np.std(series, ddof=1)
    
    if S == 0 or R == 0:
        return 0.5
    
    # H = log(R/S) / log(n)
    return np.log(R / S) / np.log(n)


def _calculate_adx(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """
    Calculate Average Directional Index (ADX) - measures trend strength.
    
    Interpretation:
        ADX > 25: Strong trend
        ADX < 20: Weak trend / ranging market
    
    Args:
        high: High prices.
        low: Low prices.
        close: Close prices.
        window: Lookback period.
        
    Returns:
        ADX values as pandas Series.
    """
    # True Range
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=window).mean()
    
    # Directional Movement
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
    
    plus_di = 100 * pd.Series(plus_dm, index=high.index).rolling(window=window).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=high.index).rolling(window=window).mean() / atr
    
    # ADX
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.rolling(window=window).mean()
    
    return adx


def _calculate_variance_ratio(returns: pd.Series, short_window: int = 5, long_window: int = 20) -> pd.Series:
    """
    Calculate Variance Ratio for trend/mean-reversion detection.
    
    Interpretation:
        VR > 1: Trending (variance grows faster than random walk)
        VR = 1: Random walk
        VR < 1: Mean-reverting (variance grows slower than random walk)
    
    Args:
        returns: Log returns series.
        short_window: Short-term variance window.
        long_window: Long-term variance window.
        
    Returns:
        Variance ratio series.
    """
    short_var = returns.rolling(window=short_window).var()
    long_var = returns.rolling(window=long_window).var()
    
    # Scale by window ratio for proper comparison
    scale_factor = long_window / short_window
    vr = (short_var * scale_factor) / long_var.replace(0, np.nan)
    
    return vr

class RegimeDetector:
    def __init__(self, n_states=2, covariance_type='full', random_state=42):
        """
        Initialize the Regime Detector using HMM.
        
        Args:
            n_states (int): Number of regimes to detect (default 2: Trend vs Mean-Reverting).
            covariance_type (str): 'full', 'diag', 'spherical', 'tied'.
            random_state (int): Seed for reproducibility.
        """
        self.n_states = n_states
        self.model = GaussianHMM(
            n_components=n_states, 
            covariance_type=covariance_type, 
            n_iter=100, 
            random_state=random_state,
            verbose=False
        )
        self.scaler = StandardScaler()
        self.is_fitted = False
        self.state_stats = {}

    def load_data(self, filepath):
        """
        Load data from pickle file.
        Assumes data is a Dictionary of DataFrames or a MultiIndex DataFrame.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")
            
        with open(filepath, 'rb') as f:
            data = pickle.load(f)
            
        return data

    def calculate_features(self, df, window=20, use_enhanced=True):
        """
        Calculate features for regime detection.
        
        Enhanced Features:
        1. Volatility (Rolling Std Dev of Returns)
        2. Efficiency Ratio (Kaufman) - Trend Strength
        3. Autocorrelation - Serial correlation of returns
        4. Hurst Exponent - Persistence measure (H>0.5 trending, H<0.5 mean-reverting)
        5. Variance Ratio - VR>1 trending, VR<1 mean-reverting
        6. ADX (if OHLC available) - Trend strength indicator
        
        Args:
            df (pd.DataFrame): Must contain 'close' column, optionally 'high' and 'low'.
            window (int): Lookback window.
            use_enhanced (bool): Whether to use enhanced features (Hurst, VR, ADX).
            
        Returns:
            pd.DataFrame: DataFrame with features, dropna applied.
        """
        df = df.copy()
        # Ensure column names are lower case
        df.columns = [c.lower() for c in df.columns]
        
        if 'close' not in df.columns:
            raise ValueError("DataFrame must contain 'close' column")

        # 1. Log Returns
        df['log_ret'] = np.log(df['close'] / df['close'].shift(1))
        
        # 2. Realized Volatility (Annualized)
        df['volatility'] = df['log_ret'].rolling(window=window).std() * np.sqrt(252)
        
        # 3. Efficiency Ratio (Kaufman) - Proxy for Trend Strength
        # ER = Change in Price / Sum of absolute changes
        change = df['close'].diff(window).abs()
        volatility_sum = df['close'].diff(1).abs().rolling(window).sum()
        df['efficiency_ratio'] = change / volatility_sum
        
        # 4. Serial Correlation (Autocorrelation of returns) - Proxy for Mean Reversion
        # Positive serial corr -> Trend, Negative -> Mean Reversion
        df['autocorr'] = df['log_ret'].rolling(window=window).apply(lambda x: x.autocorr(lag=1), raw=False)

        # 5. Correlation between Returns and Volatility (Leverage Effect)
        # Often negative in equity stress (price down, vol up)
        df['corr_ret_vol'] = df['log_ret'].rolling(window=window).corr(df['volatility'])
        
        feature_cols = ['volatility', 'efficiency_ratio', 'autocorr', 'corr_ret_vol']
        
        if use_enhanced:
            # 6. Hurst Exponent - Persistence measure
            # H > 0.5: Trending, H < 0.5: Mean-reverting, H = 0.5: Random walk
            df['hurst'] = df['log_ret'].rolling(window=window).apply(
                lambda x: _estimate_hurst(x.values), raw=False
            )
            
            # 7. Variance Ratio - VR > 1: Trending, VR < 1: Mean-reverting
            df['variance_ratio'] = _calculate_variance_ratio(
                df['log_ret'], 
                short_window=max(window // 4, 2), 
                long_window=window
            )
            
            # 8. ADX - Trend strength (if high/low available)
            if 'high' in df.columns and 'low' in df.columns:
                df['adx'] = _calculate_adx(df['high'], df['low'], df['close'], window)
                feature_cols.extend(['hurst', 'variance_ratio', 'adx'])
            else:
                feature_cols.extend(['hurst', 'variance_ratio'])
        
        # Store feature names for later use
        self.feature_names = feature_cols

        # Drop NaNs created by rolling windows
        features = df[feature_cols].dropna()
        
        return features

    def fit(self, features):
        """
        Fit the HMM model.
        """
        # Scale features
        X = self.scaler.fit_transform(features)
        
        # Initialize means manually to avoid KMeans/threadpoolctl issues in some envs
        # We pick random samples as initial means
        indices = np.random.choice(X.shape[0], self.n_states, replace=False)
        self.model.means_ = X[indices]
        
        # Disable 'm' (means) initialization in init_params to prevent KMeans usage
        # Default is 'stmc', we use 'stc'
        self.model.init_params = 'stc'
        
        # Fit HMM
        try:
            self.model.fit(X)
        except Exception as e:
            print(f"HMM fit failed: {e}. Falling back to GaussianMixture.")
            from sklearn.mixture import GaussianMixture
            self.model = GaussianMixture(n_components=self.n_states, covariance_type=self.model.covariance_type, random_state=self.model.random_state)
            self.model.fit(X)
            
        self.is_fitted = True
        
        # Analyze states to label them (e.g., which is "Trend", which is "Mean Reversion")
        means = self.model.means_
        # GMM has covariances_, HMM has covars_
        if hasattr(self.model, 'covars_'):
            covars = self.model.covars_
        else:
            covars = self.model.covariances_
        
        # We can try to interpret states based on feature means
        # Use stored feature names if available, otherwise use default
        feature_names = getattr(self, 'feature_names', 
                                ['volatility', 'efficiency_ratio', 'autocorr', 'corr_ret_vol'])
        
        for i in range(self.n_states):
            self.state_stats[i] = {name: means[i, j] for j, name in enumerate(feature_names) if j < means.shape[1]}
            
        return self

    def predict(self, features):
        """
        Predict regimes for new data.
        """
        if not self.is_fitted:
            raise ValueError("Model not fitted yet.")
            
        X = self.scaler.transform(features)
        states = self.model.predict(X)
        probs = self.model.predict_proba(X)
        
        return states, probs

    def interpret_states(self):
        """
        Print interpretation of states based on feature means.
        """
        if not self.is_fitted:
            return
            
        print("\nState Interpretation:")
        for state, stats in self.state_stats.items():
            print(f"State {state}:")
            print(f"  Avg Volatility (Scaled): {stats['volatility']:.2f}")
            print(f"  Avg Efficiency Ratio (Scaled): {stats['efficiency_ratio']:.2f}")
            print(f"  Avg Autocorr (Scaled): {stats['autocorr']:.2f}")
            print(f"  Avg Corr Ret-Vol (Scaled): {stats['corr_ret_vol']:.2f}")
            
            # Heuristic Labeling
            label = []
            if stats['volatility'] > 0: label.append("High Vol")
            else: label.append("Low Vol")
            
            if stats['efficiency_ratio'] > 0: label.append("Trending")
            else: label.append("Choppy/Mean-Rev")
            
            print(f"  -> Likely: {' + '.join(label)}")

    def get_state_regime_map(self) -> Dict[int, str]:
        """Return a deterministic mapping from numeric state -> regime label.

        Labels are based on fitted state means (in standardized feature space).
        Uses multiple indicators for robust classification:
        - Efficiency Ratio (higher = trending)
        - Autocorrelation (positive = trending)
        - Hurst Exponent (> 0.5 = trending) if available
        - Variance Ratio (> 1 = trending) if available
        - ADX (higher = stronger trend) if available
        
        The state with highest combined score is labeled "trending".
        """
        if not self.is_fitted or not self.state_stats:
            raise ValueError("Model not fitted yet.")

        scores: Dict[int, float] = {}
        for state, stats in self.state_stats.items():
            score = 0.0
            
            # Core indicators
            eff = float(stats.get('efficiency_ratio', 0.0) or 0.0)
            ac = float(stats.get('autocorr', 0.0) or 0.0)
            score += eff + ac
            
            # Enhanced indicators (if available)
            if 'hurst' in stats:
                # Hurst > 0.5 indicates trending, so (hurst - 0.5) contributes positively for trends
                hurst = float(stats.get('hurst', 0.5) or 0.5)
                score += (hurst - 0.5) * 2  # Scale to similar magnitude
            
            if 'variance_ratio' in stats:
                # VR > 1 indicates trending, so (vr - 1) contributes positively for trends
                vr = float(stats.get('variance_ratio', 1.0) or 1.0)
                score += (vr - 1) * 0.5  # Scale appropriately
            
            if 'adx' in stats:
                # Higher ADX = stronger trend
                adx = float(stats.get('adx', 0.0) or 0.0)
                score += adx * 0.02  # Normalize (ADX typically 0-100)
            
            scores[int(state)] = score

        trending_state = max(scores.keys(), key=lambda k: scores[k])
        mapping = {s: 'mean_reverting' for s in scores.keys()}
        mapping[trending_state] = 'trending'
        return mapping

    def map_states_to_regime(self, states: Any) -> pd.Series:
        """Map predicted numeric states to regime labels.

        Args:
            states: 1D array-like of predicted states.

        Returns:
            pd.Series of regime labels ("trending" or "mean_reverting").
        """
        mapping = self.get_state_regime_map()

        if isinstance(states, pd.Series):
            index: Any = states.index
            values = states.values
        else:
            index = None
            values = np.asarray(states)

        labels = [mapping.get(int(x), 'unknown') for x in values]
        return pd.Series(labels, index=index)

    def get_regime_persistence(self) -> Dict[str, float]:
        """
        Return regime persistence (self-transition) probabilities.
        
        Higher persistence means the regime tends to stay in the same state.
        
        Returns:
            Dictionary mapping regime label to its persistence probability.
        """
        if not self.is_fitted:
            raise ValueError("Model not fitted yet.")
        
        # Get transition matrix (HMM has transmat_, GMM doesn't)
        if hasattr(self.model, 'transmat_'):
            transmat = self.model.transmat_
        else:
            # For GMM fallback, return equal persistence
            return {'trending': 0.5, 'mean_reverting': 0.5}
        
        mapping = self.get_state_regime_map()
        persistence = {}
        
        for state, label in mapping.items():
            persistence[label] = float(transmat[state, state])
        
        return persistence

    def get_regime_confidence(self, features: pd.DataFrame) -> pd.DataFrame:
        """
        Return regime labels with confidence scores.
        
        Args:
            features: Feature DataFrame (output of calculate_features).
            
        Returns:
            DataFrame with columns: 'regime', 'confidence', 'trending_prob', 'mean_reverting_prob'
        """
        if not self.is_fitted:
            raise ValueError("Model not fitted yet.")
        
        states, probs = self.predict(features)
        mapping = self.get_state_regime_map()
        
        results = pd.DataFrame(index=features.index)
        results['regime'] = [mapping.get(int(s), 'unknown') for s in states]
        results['confidence'] = probs.max(axis=1)
        
        # Find which state corresponds to trending
        trending_state = [k for k, v in mapping.items() if v == 'trending'][0]
        meanrev_state = [k for k, v in mapping.items() if v == 'mean_reverting'][0]
        
        results['trending_prob'] = probs[:, trending_state]
        results['mean_reverting_prob'] = probs[:, meanrev_state]
        
        return results

    def ensemble_regime_detection(self, features: pd.DataFrame, 
                                   er_threshold: float = 0.6,
                                   ac_threshold: float = 0.1,
                                   hurst_threshold: float = 0.55,
                                   vr_threshold: float = 1.1) -> pd.DataFrame:
        """
        Combine HMM with rule-based indicators for robust regime detection.
        
        Uses voting ensemble:
        1. HMM prediction
        2. Efficiency Ratio threshold
        3. Autocorrelation threshold
        4. Hurst Exponent threshold (if available)
        5. Variance Ratio threshold (if available)
        
        Args:
            features: Feature DataFrame.
            er_threshold: Efficiency ratio threshold for trending.
            ac_threshold: Autocorrelation threshold for trending.
            hurst_threshold: Hurst exponent threshold for trending.
            vr_threshold: Variance ratio threshold for trending.
            
        Returns:
            DataFrame with 'regime', 'confidence', and individual indicator votes.
        """
        if not self.is_fitted:
            raise ValueError("Model not fitted yet.")
        
        # 1. HMM prediction
        hmm_confidence = self.get_regime_confidence(features)
        hmm_trending = (hmm_confidence['regime'] == 'trending').astype(int)
        
        votes = pd.DataFrame(index=features.index)
        votes['hmm'] = hmm_trending
        
        # 2. Rule-based: Efficiency Ratio threshold
        if 'efficiency_ratio' in features.columns:
            # Need to unscale or use raw features - here we assume features passed
            # might be raw or we check the sign in scaled space
            votes['er'] = (features['efficiency_ratio'] > er_threshold).astype(int)
        else:
            votes['er'] = 0
        
        # 3. Rule-based: Autocorrelation threshold
        if 'autocorr' in features.columns:
            votes['ac'] = (features['autocorr'] > ac_threshold).astype(int)
        else:
            votes['ac'] = 0
        
        # 4. Rule-based: Hurst Exponent threshold
        if 'hurst' in features.columns:
            votes['hurst'] = (features['hurst'] > hurst_threshold).astype(int)
        
        # 5. Rule-based: Variance Ratio threshold
        if 'variance_ratio' in features.columns:
            votes['vr'] = (features['variance_ratio'] > vr_threshold).astype(int)
        
        # Majority vote
        n_indicators = len(votes.columns)
        vote_sum = votes.sum(axis=1)
        threshold = n_indicators / 2
        
        results = pd.DataFrame(index=features.index)
        results['regime'] = 'mean_reverting'
        results.loc[vote_sum > threshold, 'regime'] = 'trending'
        
        # Confidence = proportion of agreeing indicators
        results['confidence'] = vote_sum / n_indicators
        results.loc[results['regime'] == 'mean_reverting', 'confidence'] = \
            (n_indicators - vote_sum.loc[results['regime'] == 'mean_reverting']) / n_indicators
        
        # Add individual votes for transparency
        for col in votes.columns:
            results[f'vote_{col}'] = votes[col]
        
        return results


class AdaptiveRegimeDetector(RegimeDetector):
    """
    Regime detector with online/adaptive updating capability.
    
    This class maintains a history of features and can refit the model
    periodically with exponential decay weighting on older observations.
    """
    
    def __init__(self, n_states=2, decay_factor=0.99, refit_interval=20, 
                 max_history=500, **kwargs):
        """
        Initialize the Adaptive Regime Detector.
        
        Args:
            n_states: Number of regimes.
            decay_factor: Exponential decay for old observations (0.99 = 1% decay per step).
            refit_interval: How often to refit the model (in number of updates).
            max_history: Maximum number of observations to keep in history.
            **kwargs: Additional arguments for parent RegimeDetector.
        """
        super().__init__(n_states=n_states, **kwargs)
        self.decay_factor = decay_factor
        self.refit_interval = refit_interval
        self.max_history = max_history
        self.feature_history: deque = deque(maxlen=max_history)
        self.update_count = 0
        self._last_features: Optional[pd.DataFrame] = None
    
    def fit(self, features: pd.DataFrame):
        """
        Initial fit and populate history.
        """
        super().fit(features)
        
        # Populate history
        self.feature_history.clear()
        for i in range(len(features)):
            self.feature_history.append(features.iloc[i].values)
        
        self._last_features = features
        return self
    
    def update(self, new_features: pd.DataFrame, force_refit: bool = False):
        """
        Update the model with new observations.
        
        Args:
            new_features: New feature observations (can be single row or multiple).
            force_refit: Force model refit regardless of interval.
        """
        # Add new observations to history
        for i in range(len(new_features)):
            self.feature_history.append(new_features.iloc[i].values)
            self.update_count += 1
        
        # Refit periodically
        if force_refit or (self.update_count % self.refit_interval == 0):
            self._weighted_refit()
    
    def _weighted_refit(self):
        """
        Refit model with exponentially decayed weights on older observations.
        """
        if len(self.feature_history) < 30:
            return
        
        # Convert history to array
        X_raw = np.array(list(self.feature_history))
        n_samples = len(X_raw)
        
        # Calculate weights (more recent = higher weight)
        weights = np.array([
            self.decay_factor ** (n_samples - i - 1)
            for i in range(n_samples)
        ])
        
        # Normalize weights
        weights = weights / weights.sum() * n_samples
        
        # Weighted standardization
        weighted_mean = np.average(X_raw, axis=0, weights=weights)
        weighted_var = np.average((X_raw - weighted_mean) ** 2, axis=0, weights=weights)
        weighted_std = np.sqrt(weighted_var)
        weighted_std[weighted_std == 0] = 1.0
        
        X_scaled = (X_raw - weighted_mean) / weighted_std
        
        # Update scaler parameters
        self.scaler.mean_ = weighted_mean
        self.scaler.scale_ = weighted_std
        self.scaler.var_ = weighted_var
        
        # Sample with replacement according to weights for fitting
        # (HMM doesn't support sample weights directly)
        sample_indices = np.random.choice(
            n_samples, 
            size=min(n_samples, self.max_history),
            replace=True,
            p=weights / weights.sum()
        )
        X_sampled = X_scaled[sample_indices]
        
        # Reinitialize and fit HMM
        try:
            indices = np.random.choice(len(X_sampled), self.n_states, replace=False)
            self.model.means_ = X_sampled[indices]
            self.model.init_params = 'stc'
            self.model.fit(X_sampled)
            
            # Update state stats
            feature_names = getattr(self, 'feature_names', 
                                    ['volatility', 'efficiency_ratio', 'autocorr', 'corr_ret_vol'])
            means = self.model.means_
            for i in range(self.n_states):
                self.state_stats[i] = {
                    name: means[i, j] 
                    for j, name in enumerate(feature_names) 
                    if j < means.shape[1]
                }
        except Exception as e:
            print(f"Adaptive refit failed: {e}")
    
    def get_regime_stability(self, lookback: int = 50) -> Dict[str, float]:
        """
        Calculate regime stability over recent history.
        
        Returns the proportion of time spent in each regime over the lookback period.
        
        Args:
            lookback: Number of recent observations to consider.
            
        Returns:
            Dictionary with regime proportions.
        """
        if len(self.feature_history) < lookback:
            lookback = len(self.feature_history)
        
        if lookback == 0:
            return {'trending': 0.5, 'mean_reverting': 0.5}
        
        # Get recent features
        recent_features = np.array(list(self.feature_history)[-lookback:])
        X_scaled = self.scaler.transform(recent_features)
        
        # Predict regimes
        states = self.model.predict(X_scaled)
        mapping = self.get_state_regime_map()
        
        labels = [mapping.get(int(s), 'unknown') for s in states]
        
        # Calculate proportions
        trending_count = sum(1 for l in labels if l == 'trending')
        
        return {
            'trending': trending_count / lookback,
            'mean_reverting': (lookback - trending_count) / lookback
        }


def create_dummy_data():
    """Generate dummy OHLC data for testing."""
    dates = pd.date_range(start='2020-01-01', end='2023-01-01', freq='B')
    n = len(dates)
    
    # Generate a random walk with switching volatility
    returns = np.random.normal(0, 0.01, n)
    # Inject a high vol period
    returns[300:500] *= 3
    # Inject a trending period (positive mean)
    returns[600:800] += 0.002
    
    price = 100 * np.exp(np.cumsum(returns))
    
    df = pd.DataFrame({
        'open': price,
        'high': price * 1.01,
        'low': price * 0.99,
        'close': price,
        'volume': np.random.randint(1000, 10000, n)
    }, index=dates)
    
    return df
