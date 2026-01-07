"""
High-order factor generator.

This module contains the generator for high-order factors from base factors.
"""

import pandas as pd
import numpy as np
from typing import Dict


class HighOrderFactorGenerator:
    """Generator for high-order factors from base factors."""
    
    def __init__(self, base_factors: pd.DataFrame, data: pd.DataFrame = None):
        """
        Initialize high-order factor generator.
        
        Parameters:
        -----------
        base_factors : pd.DataFrame
            DataFrame containing base factors
        data : pd.DataFrame, optional
            Original OHLCV data for advanced factor generation
        """
        self.base_factors = base_factors
        self.data = data
    
    def generate_multiplication_factors(self, max_factors: int = None) -> Dict[str, pd.Series]:
        """Generate multiplication factors."""
        factors = {}
        names = list(self.base_factors.columns)
        count = 0
        
        for i in range(len(names)):
            for j in range(i+1, len(names)):
                if max_factors and count >= max_factors:
                    break
                factors[f'{names[i]}_x_{names[j]}'] = (
                    self.base_factors[names[i]] * self.base_factors[names[j]]
                )
                count += 1
            if max_factors and count >= max_factors:
                break
        
        return factors
    
    def generate_subtraction_factors(self, max_factors: int = None) -> Dict[str, pd.Series]:
        """Generate subtraction factors."""
        factors = {}
        names = list(self.base_factors.columns)
        count = 0
        
        for i in range(len(names)):
            for j in range(i+1, len(names)):
                if max_factors and count >= max_factors:
                    break
                factors[f'{names[i]}_minus_{names[j]}'] = (
                    self.base_factors[names[i]] - self.base_factors[names[j]]
                )
                count += 1
            if max_factors and count >= max_factors:
                break
        
        return factors
    
    def generate_power_factors(self, max_factors: int = None) -> Dict[str, pd.Series]:
        """Generate power factors (x^2, x^3, sqrt(x))."""
        factors = {}
        names = list(self.base_factors.columns)
        count = 0
        
        for name in names:
            if max_factors and count >= max_factors:
                break
            # 平方因子
            factors[f'{name}_squared'] = self.base_factors[name] ** 2
            count += 1
            
            if max_factors and count >= max_factors:
                    break
            # 立方因子
            factors[f'{name}_cubed'] = self.base_factors[name] ** 3
            count += 1
            
            if max_factors and count >= max_factors:
                break
            # 平方根因子（处理负值）
            factors[f'{name}_sqrt'] = np.sqrt(np.abs(self.base_factors[name])) * np.sign(self.base_factors[name])
            count += 1
        
        return factors
    
    def generate_difference_factors(self, max_factors: int = None) -> Dict[str, pd.Series]:
        """Generate difference factors."""
        factors = {}
        names = list(self.base_factors.columns)
        count = 0
        
        for name in names:
            if max_factors and count >= max_factors:
                break
            factors[f'{name}_diff'] = self.base_factors[name].diff()
            count += 1
        
        return factors
    
    def generate_rolling_statistics_factors(self, max_factors: int = None) -> Dict[str, pd.Series]:
        """Generate rolling statistics factors."""
        factors = {}
        names = list(self.base_factors.columns)
        count = 0
        
        for name in names:
            if max_factors and count >= max_factors:
                break
            # 滚动均值
            factors[f'{name}_rolling_mean_5'] = self.base_factors[name].rolling(window=5).mean()
            count += 1
            
            if max_factors and count >= max_factors:
                break
            # 滚动标准差
            factors[f'{name}_rolling_std_5'] = self.base_factors[name].rolling(window=5).std()
            count += 1
            
            if max_factors and count >= max_factors:
                break
            # 滚动偏度
            factors[f'{name}_rolling_skew_10'] = self.base_factors[name].rolling(window=10).skew()
            count += 1
            
            if max_factors and count >= max_factors:
                break
            # 滚动峰度  
            factors[f'{name}_rolling_kurt_10'] = self.base_factors[name].rolling(window=10).kurt()
            count += 1
        
        return factors
    
    def generate_lag_factors(self, max_factors: int = None) -> Dict[str, pd.Series]:
        """Generate lag factors."""
        factors = {}
        names = list(self.base_factors.columns)
        count = 0
        
        for name in names:
            if max_factors and count >= max_factors:
                break
            # 1期滞后
            factors[f'{name}_lag_1'] = self.base_factors[name].shift(1)
            count += 1
            
            if max_factors and count >= max_factors:
                break
            # 2期滞后
            factors[f'{name}_lag_2'] = self.base_factors[name].shift(2)
            count += 1
            
            if max_factors and count >= max_factors:
                break
            # 3期滞后
            factors[f'{name}_lag_3'] = self.base_factors[name].shift(3)
            count += 1
        
        return factors
    
    def generate_rank_factors(self, max_factors: int = None) -> Dict[str, pd.Series]:
        """Generate rank factors."""
        factors = {}
        names = list(self.base_factors.columns)
        count = 0
        
        for name in names:
            if max_factors and count >= max_factors:
                break
            # 滚动排名
            factors[f'{name}_rolling_rank_10'] = self.base_factors[name].rolling(window=10).rank(pct=True)
            count += 1
            
            if max_factors and count >= max_factors:
                break
            # 滚动分位数
            factors[f'{name}_rolling_quantile_10'] = self.base_factors[name].rolling(window=10).quantile(0.5)
            count += 1
        
        return factors
    
    def generate_interaction_factors(self, max_factors: int = None) -> Dict[str, pd.Series]:
        """Generate interaction factors (product of two factors)."""
        factors = {}
        names = list(self.base_factors.columns)
        count = 0
        
        for i in range(len(names)):
            for j in range(i+1, len(names)):
                if max_factors and count >= max_factors:
                    break
                factors[f'{names[i]}_x_{names[j]}'] = (
                    self.base_factors[names[i]] * self.base_factors[names[j]]
                )
                count += 1
            if max_factors and count >= max_factors:
                break
        
        return factors
    
    def generate_momentum_factors(self, max_factors: int = None) -> Dict[str, pd.Series]:
        """Generate momentum and trend-based factors."""
        factors = {}
        count = 0
        
        # Extract price data from base factors if available, otherwise use Close
        if hasattr(self, 'data') and 'Close' in self.data.columns:
            close_price = self.data['Close']
        elif 'Close' in self.base_factors.columns:
            close_price = self.base_factors['Close']
        else:
            # Use first available price-like factor
            price_cols = [col for col in self.base_factors.columns if 'price' in col.lower() or 'close' in col.lower()]
            if price_cols:
                close_price = self.base_factors[price_cols[0]]
            else:
                return factors
        
        # Multi-timeframe momentum
        for period in [5, 10, 20, 60]:
            if max_factors and count >= max_factors:
                break
            factors[f'momentum_{period}'] = close_price.pct_change(period)
            count += 1
            
            if max_factors and count >= max_factors:
                break
            factors[f'trend_strength_{period}'] = (
                (close_price - close_price.rolling(period).mean()) / 
                (close_price.rolling(period).std() + 1e-8)
            )
            count += 1
        
        # Momentum acceleration
        if max_factors and count < max_factors:
            factors['momentum_acceleration'] = close_price.pct_change(5).diff()
            count += 1
        
        return factors
    
    def generate_volatility_factors(self, max_factors: int = None) -> Dict[str, pd.Series]:
        """Generate volatility regime and clustering factors."""
        factors = {}
        count = 0
        
        # Extract price data
        if hasattr(self, 'data') and 'Close' in self.data.columns:
            close_price = self.data['Close']
        elif 'Close' in self.base_factors.columns:
            close_price = self.base_factors['Close']
        else:
            price_cols = [col for col in self.base_factors.columns if 'price' in col.lower() or 'close' in col.lower()]
            if price_cols:
                close_price = self.base_factors[price_cols[0]]
            else:
                return factors
        
        returns = close_price.pct_change()
        
        # Rolling volatility estimates
        for window in [10, 20, 60]:
            if max_factors and count >= max_factors:
                break
            factors[f'volatility_{window}'] = returns.rolling(window).std()
            count += 1
            
            if max_factors and count >= max_factors:
                break
            vol_median = factors[f'volatility_{window}'].rolling(min(252, len(returns))).median()
            factors[f'volatility_regime_{window}'] = (
                factors[f'volatility_{window}'] > vol_median
            ).astype(int)
            count += 1
        
        # Volatility clustering
        if max_factors and count < max_factors:
            factors['vol_clustering'] = returns.abs().rolling(20).mean()
            count += 1
        
        return factors
    
    def generate_mean_reversion_factors(self, max_factors: int = None) -> Dict[str, pd.Series]:
        """Generate mean reversion factors."""
        factors = {}
        count = 0
        
        # Extract price data
        if hasattr(self, 'data') and 'Close' in self.data.columns:
            close_price = self.data['Close']
        elif 'Close' in self.base_factors.columns:
            close_price = self.base_factors['Close']
        else:
            price_cols = [col for col in self.base_factors.columns if 'price' in col.lower() or 'close' in col.lower()]
            if price_cols:
                close_price = self.base_factors[price_cols[0]]
            else:
                return factors
        
        # Distance from moving averages
        for ma_period in [10, 20, 50]:
            if max_factors and count >= max_factors:
                break
            ma = close_price.rolling(ma_period).mean()
            factors[f'distance_from_ma_{ma_period}'] = (close_price - ma) / (ma + 1e-8)
            count += 1
        
        # Z-score based factors
        for period in [20, 60]:
            if max_factors and count >= max_factors:
                break
            mean = close_price.rolling(period).mean()
            std = close_price.rolling(period).std()
            factors[f'zscore_{period}'] = (close_price - mean) / (std + 1e-8)
            count += 1
        
        return factors
    
    def generate_signal_quality_factors(self, max_factors: int = None) -> Dict[str, pd.Series]:
        """Generate factors measuring signal quality and confidence."""
        factors = {}
        count = 0
        
        # Extract price data
        if hasattr(self, 'data') and 'Close' in self.data.columns:
            close_price = self.data['Close']
        elif 'Close' in self.base_factors.columns:
            close_price = self.base_factors['Close']
        else:
            price_cols = [col for col in self.base_factors.columns if 'price' in col.lower() or 'close' in col.lower()]
            if price_cols:
                close_price = self.base_factors[price_cols[0]]
            else:
                return factors
        
        # Signal consistency across timeframes
        if max_factors and count < max_factors:
            short_signal = close_price > close_price.rolling(5).mean()
            long_signal = close_price > close_price.rolling(20).mean()
            factors['signal_consistency'] = (short_signal == long_signal).astype(int)
            count += 1
        
        # Trend confidence (alignment of multiple MAs)
        if max_factors and count < max_factors:
            ma5 = close_price.rolling(5).mean()
            ma10 = close_price.rolling(10).mean()
            ma20 = close_price.rolling(20).mean()
            factors['trend_confidence'] = (
                ((ma5 > ma10) & (ma10 > ma20)) | 
                ((ma5 < ma10) & (ma10 < ma20))
            ).astype(int)
            count += 1
        
        return factors
    
    def generate_regime_factors(self, max_factors: int = None) -> Dict[str, pd.Series]:
        """Generate market regime detection factors."""
        factors = {}
        count = 0
        
        # Extract price data
        if hasattr(self, 'data') and 'Close' in self.data.columns:
            close_price = self.data['Close']
        elif 'Close' in self.base_factors.columns:
            close_price = self.base_factors['Close']
        else:
            price_cols = [col for col in self.base_factors.columns if 'price' in col.lower() or 'close' in col.lower()]
            if price_cols:
                close_price = self.base_factors[price_cols[0]]
            else:
                return factors
        
        returns = close_price.pct_change()
        
        # Trend vs sideways regime
        for window in [20, 60]:
            if max_factors and count >= max_factors:
                break
            rolling_std = returns.rolling(window).std()
            rolling_mean = returns.rolling(window).mean().abs()
            factors[f'trend_regime_{window}'] = rolling_mean / (rolling_std + 1e-8)
            count += 1
        
        # Bull/bear regime indicators
        if max_factors and count < max_factors:
            bull_signal = close_price > close_price.rolling(50).mean()
            factors['bull_regime'] = bull_signal.rolling(10).mean()
            count += 1
        
        return factors
    
    def generate_enhanced_cross_sectional_factors(self, max_factors: int = None) -> Dict[str, pd.Series]:
        """Generate enhanced cross-sectional ranking factors."""
        factors = {}
        count = 0
        
        # Extract volume and price data
        volume_data = None
        price_data = None
        
        if hasattr(self, 'data'):
            if 'Volume' in self.data.columns:
                volume_data = self.data['Volume']
            if 'Close' in self.data.columns:
                price_data = self.data['Close']
        
        if volume_data is None and 'Volume' in self.base_factors.columns:
            volume_data = self.base_factors['Volume']
        if price_data is None and 'Close' in self.base_factors.columns:
            price_data = self.base_factors['Close']
        
        # Rank-based transformations for available data
        data_sources = {}
        if volume_data is not None:
            data_sources['Volume'] = volume_data
        if price_data is not None:
            data_sources['Close'] = price_data
        
        for name, data in data_sources.items():
            for window in [20, 60]:
                if max_factors and count >= max_factors:
                    break
                factors[f'{name}_rank_{window}'] = data.rolling(window).rank(pct=True)
                count += 1
        
        # Percentile-based factors
        if price_data is not None:
            for period in [10, 30]:
                if max_factors and count >= max_factors:
                    break
                factors[f'price_percentile_{period}'] = (
                    price_data.rolling(period*5).rank(pct=True)
                )
                count += 1
        
        return factors
    
    def generate_all_high_order_factors(self, max_high_order_factors: int = 100) -> pd.DataFrame:
        """Generate all high-order factors."""
        all_factors = {}
        remaining_factors = max_high_order_factors
        
        # Generate different types of high-order factors
        operations = [
            self.generate_multiplication_factors,
            self.generate_subtraction_factors,
            self.generate_power_factors,
            self.generate_difference_factors,
            self.generate_rolling_statistics_factors,
            self.generate_lag_factors,
            self.generate_rank_factors,
            self.generate_interaction_factors,
            self.generate_momentum_factors,
            self.generate_volatility_factors,
            self.generate_mean_reversion_factors,
            self.generate_signal_quality_factors,
            self.generate_regime_factors,
            self.generate_enhanced_cross_sectional_factors
        ]
        
        factors_per_operation = max_high_order_factors // len(operations)
        
        for operation in operations:
            if remaining_factors <= 0:
                break
            
            factors_to_generate = min(factors_per_operation, remaining_factors)
            new_factors = operation(max_factors=factors_to_generate)
            all_factors.update(new_factors)
            remaining_factors -= len(new_factors)
        
        return pd.DataFrame(all_factors, index=self.base_factors.index)