import numpy as np
import pandas as pd
import pickle
import os
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler

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

    def calculate_features(self, df, window=20):
        """
        Calculate features for regime detection.
        
        Features:
        1. Volatility (Rolling Std Dev of Returns)
        2. Trend Strength (Efficiency Ratio or ADX proxy)
        3. Momentum (Returns) - Optional, maybe absolute returns
        
        Args:
            df (pd.DataFrame): Must contain 'close' column.
            window (int): Lookback window.
            
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

        # Drop NaNs created by rolling windows
        features = df[['log_ret', 'volatility', 'efficiency_ratio', 'autocorr', 'corr_ret_vol']].dropna()
        
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
        # Features: [log_ret, volatility, efficiency_ratio, autocorr, corr_ret_vol]
        feature_names = ['log_ret', 'volatility', 'efficiency_ratio', 'autocorr', 'corr_ret_vol']
        
        for i in range(self.n_states):
            self.state_stats[i] = {name: means[i, j] for j, name in enumerate(feature_names)}
            
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
