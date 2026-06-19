#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置文件 - 基于OOP的集中配置管理系统
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Tuple, Union
from datetime import datetime
import json


# Constants for validation
VALID_FREQUENCIES = ["1min", "5min", "15min", "30min", "1H", "1D"]
VALID_FILL_METHODS = ["Fill=Previous", "Fill=Next", "Fill=Zero", "Drop"]
VALID_LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR']
VALID_FILTERING_METHODS = ['ic_only', 'ir_only', 'combined', 'significance']
VALID_RETURN_METHODS = ['pct_change', 'diff', 'log_returns']
VALID_WEIGHTING_METHODS = ['equal', 'ic_weighted', 'ir_weighted', 'regression', 'ridge_regression', 'risk_parity', 'max_sharpe']
VALID_INTENSITY_METHODS = ['rolling', 'expanding', 'ewm']
VALID_POSITION_METHODS = ['linear', 'tanh', 'step', 'exponential']
VALID_PORTFOLIO_METHODS = ['simple', 'intensity', 'smooth_qp', 'smooth']
VALID_SMOOTHING_METHODS = ['hysteresis', 'quadratic_tracking', 'adaptive_quadratic', 'regime_aware_tracking']


class BaseConfig(ABC):
    """配置基类，提供通用的配置功能"""
    
    def __init__(self):
        self._validate_config()
    
    @abstractmethod
    def _validate_config(self) -> None:
        """验证配置的有效性"""
        pass
    
    def _validate_positive(self, field_name: str, value: Union[int, float]) -> None:
        """Helper method to validate positive values"""
        if value <= 0:
            raise ValueError(f"{field_name} must be positive")
    
    def _validate_non_negative(self, field_name: str, value: Union[int, float]) -> None:
        """Helper method to validate non-negative values"""
        if value < 0:
            raise ValueError(f"{field_name} must be non-negative")
    
    def _validate_range(self, field_name: str, value: Union[int, float], min_val: float, max_val: float) -> None:
        """Helper method to validate value within range"""
        if not min_val <= value <= max_val:
            raise ValueError(f"{field_name} must be between {min_val} and {max_val}")
    
    def _validate_choice(self, field_name: str, value: str, valid_choices: List[str]) -> None:
        """Helper method to validate choice from list"""
        if value not in valid_choices:
            raise ValueError(f"{field_name} must be one of {valid_choices}")
    
    def to_dict(self) -> Dict[str, Any]:
        """将配置转换为字典格式"""
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}
    
    def to_json(self) -> str:
        """将配置转换为JSON格式"""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
    
    def update(self, **kwargs) -> None:
        """更新配置参数"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self._validate_config()


class DateConfig(BaseConfig):
    """日期配置类"""
    
    def __init__(self):
        # 日线数据日期范围
        self.day_data_start_date = "2020-01-01" # factor data starts from 2019-12-09, prediction should start after 2020-06-01
        self.day_data_end_date = "2025-08-31"
        
        # 分钟数据日期范围
        self.bar_data_start_date = "2025-07-13 09:00:00"
        self.bar_data_end_date = "2025-08-13 15:30:00"
        
        # 利率数据日期范围
        self.interest_rate_start_date = "2025-02-02"
        self.interest_rate_end_date = "2025-08-01"
        self.interest_rate_frequency = "15min"
        
        # 利率品种代码
        self.interest_rate_symbols = "TB10Y.WI,TB2Y.WI,TB5Y.WI"
        
        super().__init__()
    
    def _validate_date_format(self, date_str: str, format_str: str, field_name: str) -> None:
        """Helper method to validate date format"""
        try:
            datetime.strptime(date_str, format_str)
        except ValueError as e:
            raise ValueError(f"{field_name} format error: {e}")
    
    def _validate_config(self) -> None:
        """验证日期配置的有效性"""
        # 验证日期格式
        date_fields = [
            (self.day_data_start_date, "%Y-%m-%d", "day_data_start_date"),
            (self.day_data_end_date, "%Y-%m-%d", "day_data_end_date"),
            (self.interest_rate_start_date, "%Y-%m-%d", "interest_rate_start_date"),
            (self.interest_rate_end_date, "%Y-%m-%d", "interest_rate_end_date"),
            (self.bar_data_start_date, "%Y-%m-%d %H:%M:%S", "bar_data_start_date"),
            (self.bar_data_end_date, "%Y-%m-%d %H:%M:%S", "bar_data_end_date"),
        ]
        
        for date_str, format_str, field_name in date_fields:
            self._validate_date_format(date_str, format_str, field_name)
        
        # 验证频率格式
        self._validate_choice("interest_rate_frequency", self.interest_rate_frequency, VALID_FREQUENCIES)

class ModelConfig(BaseConfig):
    """Factor model configuration"""
    
    def __init__(self):
        # --- Data & Factor Selection ---
        self.ticker = 'T.CFE' # 'T.CFE','Pair:T.CFE-TS.CFE','Fly:TS.CFE-TF.CFE-T.CFE'
        self.ic_threshold = 0.08  # Increased from 0.05 for stronger signals
        self.top_n = 5  # Reduced for more selective factor picking
        self.filtering_method = 'combined'
        self.ir_threshold = 0.7  # Increased from 0.5 for better information ratio
        self.correlation_threshold = 0.7 # Slightly reduced for more diversification
        self.use_vif_filtering = True
        self.vif_threshold = 5.0
        self.vif_fallback_threshold = 10.0
        self.use_significance_test = True
        self.confidence_level = 0.05
        self.min_observations = 120
        self.use_factor_returns = True
        self.factor_return_method = 'pct_change'

        # --- Model Training & Weighting ---
        self.weighting_method = 'max_sharpe'
        self.scale_ic_predictions = True

        # --- Portfolio Construction ---
        self.portfolio_method = 'simple'  # Options: 'simple', 'intensity', 'smooth_qp', 'smooth'
        self.max_position = 1.0
        self.threshold = 0.45  # Increased threshold for stronger signal requirement
        self.min_periods = 25  # Increased for more stable factors
        
        # --- Intensity Portfolio Parameters ---
        self.position_buckets = [-1.0, -0.8, -0.6, -0.4, -0.2, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0]  # Position increments of 0.2
        self.bucket_smoothing = True  # Whether to smooth transitions between buckets

        # --- Signal Intensity & Smoothing ---
        self.intensity_method = 'rolling'
        self.position_method = 'tanh'
        self.lookback_window = 6  # Increased for more stable signals
        self.tanh_scale = 1.5  # Reduced for less aggressive position sizing
        self.max_daily_change = 0.3  # Reduced for smoother trading
        self.min_tick = 0.02
        self.friction_cost = 0.0005  # Increased to discourage excessive trading
        self.optimization_method = 'random_search'
        self.signal_smoothing = False
        self.signal_smoothing_method = 'quadratic_tracking'  # 'hysteresis', 'quadratic_tracking', 'adaptive_quadratic', 'regime_aware_tracking'
        self.signal_smoothing_window = 6*20  # Increased for better smoothing
        self.min_signal_strength = 0.01  # Doubled to filter weak signals
        self.signal_persistence_threshold = 2  # Increased for more persistent signals
        self.momentum_decay = 0.9
        
        # --- Quadratic Tracking Parameters ---
        self.turnover_penalty_lambda = 0.5  # Penalty for signal changes in quadratic tracking
        self.tracking_weight = 1.0  # Weight for tracking original signal
        
        # --- Adaptive Quadratic Parameters ---
        self.base_turnover_penalty = 0.3  # Base penalty for adaptive quadratic
        self.adaptive_window = 10  # Window for adaptive volatility calculation
        
        # --- Regime-Aware Parameters ---
        self.regime_detection_window = 20  # Window for regime detection
        self.low_vol_penalty = 0.2  # Penalty in low volatility regime
        self.high_vol_penalty = 0.8  # Penalty in high volatility regime

        # --- Advanced Position Generation ---
        self.adaptive_threshold = True
        self.min_prediction_strength = 0.001
        self.win_rate_optimization = True
        
        # --- Enhanced Monthly QP + Drift Position Parameters ---
        self.position_scaling = 500.0  # Much more aggressive scaling for higher returns
        self.smoothing_factor = 0.8    # How much to smooth position changes (0-1, higher = smoother)
        self.turnover_lambda = 0.025   # Reduced turnover penalty for more aggressive positioning
        self.ema_alpha = 0.6          # Higher alpha for faster response to profitable signals

        # --- Risk Management Parameters ---
        self.use_risk_management = True  # Enable risk management module
        self.stop_loss_pct = 0.05  # Stop loss threshold (5% drawdown)
        self.trailing_stop_pct = 0.03  # Trailing stop threshold
        self.max_drawdown_limit = 0.15  # Maximum allowed drawdown (15%)
        self.volatility_target = 0.15  # Target annualized volatility
        self.min_position_threshold = 0.05  # Minimum position size to hold
        self.use_volatility_scaling = True  # Scale positions by volatility
        self.use_drawdown_protection = True  # Reduce positions during drawdowns
        self.use_confidence_filtering = True  # Filter low-confidence signals
        
        # --- Kelly Criterion Position Sizing ---
        self.use_kelly_sizing = False  # Use Kelly Criterion for position sizing
        self.kelly_fraction = 0.25  # Fraction of Kelly to use (conservative)
        
        # --- Factor Selection Enhancements ---
        self.use_factor_stability = True  # Check factor stability across periods
        self.stability_window = 3  # Number of periods to check stability
        self.min_stable_ic = 0.03  # Minimum IC to consider stable
        self.use_factor_diversification = True  # Ensure factor diversification
        self.max_factor_correlation = 0.6  # Max correlation between selected factors
        
        # --- Exposure Bucket Mapping (Signal → Risk Budget) ---
        self.bucket_quantile_boundaries = [0.0, 0.05, 0.20, 0.40, 0.60, 0.80, 0.95, 1.0]
        self.bucket_scalars = [-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5]
        self.bucket_labels = [
            'Strong Short', 'Short', 'Mild Short', 'Neutral',
            'Mild Long', 'Long', 'Strong Long'
        ]
        self.bucket_quantile_lookback = 252  # Rolling window for quantile estimation
        self.bucket_persistence_days = 3     # Hysteresis: days before bucket change triggers
        self.bucket_base_risk_budget = 1.0   # Base risk budget per factor (millions CNY)
        
        # --- Regime-Aware IC Weighting ---
        self.use_regime_aware_ic = False     # Use regime-conditional IC weights
        self.regime_ic_window = 60           # Lookback for regime features

        # --- Normalization ---
        self.normalization_method = 'zscore'

        super().__init__()
    
    def _validate_config(self) -> None:
        """Validate model configuration"""
        # Range validations
        self._validate_range("ic_threshold", self.ic_threshold, 0, 1)
        # confidence_level must be between 0 and 1 (exclusive)
        if not 0 < self.confidence_level < 1:
            raise ValueError("confidence_level must be between 0 and 1 (exclusive)")
        
        # Positive value validations
        positive_fields = ["top_n", "lookback_window", "max_position"]
        for field in positive_fields:
            self._validate_positive(field, getattr(self, field))
        
        # Non-negative validations  
        non_negative_fields = ["ir_threshold", "threshold"]
        for field in non_negative_fields:
            self._validate_non_negative(field, getattr(self, field))
        
        # Minimum value validations
        if self.min_observations < 10:
            raise ValueError("min_observations must be at least 10")
        
        # Choice validations
        choice_validations = [
            ("filtering_method", self.filtering_method, VALID_FILTERING_METHODS),
            ("factor_return_method", self.factor_return_method, VALID_RETURN_METHODS),
            ("weighting_method", self.weighting_method, VALID_WEIGHTING_METHODS),
            ("portfolio_method", self.portfolio_method, VALID_PORTFOLIO_METHODS),
            ("intensity_method", self.intensity_method, VALID_INTENSITY_METHODS),
            ("position_method", self.position_method, VALID_POSITION_METHODS),
            ("signal_smoothing_method", self.signal_smoothing_method, VALID_SMOOTHING_METHODS),
        ]
        
        for field_name, value, valid_choices in choice_validations:
            self._validate_choice(field_name, value, valid_choices)
    
    def get_model_parameters(self):
        """Get model_type and ic_weighting_method based on weighting_method setting."""
        weighting_map = {
            'equal': ('linear', 'ic_signed'),
            'ic_weighted': ('ic_weighted', 'ic_signed'),
            'ir_weighted': ('ic_weighted', 'ir_signed'),
            'regression': ('linear', 'ic_signed'),
            'ridge_regression': ('ridge', 'ic_signed'),
            'risk_parity': ('ic_weighted', 'ic_abs'),
            'max_sharpe': ('ic_weighted', 'ic_abs')
        }
        
        if self.weighting_method in weighting_map:
            return weighting_map[self.weighting_method]
        else:
            # Default for unknown weighting methods
            return 'ic_weighted', 'ic_signed'
        
class BacktestConfig(BaseConfig):
    """回测配置类"""

    def __init__(self):
        # 默认回测月数
        self.default_months = 6
        
        # 交易日数（每月）
        self.trading_days_per_month = 22
        
        # 年化交易日数
        self.annual_trading_days = 252
        
        super().__init__()
    
    def _validate_config(self) -> None:
        """验证回测配置的有效性"""
        self._validate_positive("default_months", self.default_months)
        self._validate_positive("trading_days_per_month", self.trading_days_per_month)
        self._validate_positive("annual_trading_days", self.annual_trading_days)


# Note: TechnicalIndicatorConfig and FactorParameterConfig classes removed as they were not used in the codebase
# Only keeping essential configuration classes that are actually used

class VisualizationConfig(BaseConfig):
    """可视化配置类"""
    
    def __init__(self):
        # 图表尺寸
        self.figure_size = (15, 10)
        self.heatmap_size = (12, 10)
        
        # 字体设置
        self.font_family = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
        
        # 颜色映射
        self.colormap = 'RdYlBu_r'
        
        super().__init__()
    
    def _validate_size_tuple(self, field_name: str, value: Any) -> None:
        """Helper method to validate size tuples"""
        if not isinstance(value, tuple) or len(value) != 2:
            raise ValueError(f"{field_name} must be a tuple with two elements")
    
    def _validate_config(self) -> None:
        """验证可视化配置的有效性"""
        self._validate_size_tuple("figure_size", self.figure_size)
        self._validate_size_tuple("heatmap_size", self.heatmap_size)
        if not isinstance(self.font_family, list):
            raise ValueError("font_family must be a list")


class DataQualityConfig(BaseConfig):
    """数据质量配置类"""
    
    def __init__(self):
        # 最小数据长度
        self.min_data_length = 10
        
        # 缺失值处理
        self.fill_method = "Fill=Previous"
        
        # 数据字段
        self.data_fields = "open,high,low,close,volume"
        
        # 输出文件前缀
        self.output_file_prefix = "factor_analysis"
        
        # CSV文件后缀
        self.csv_suffix = ".csv"
        
        super().__init__()
    
    def _validate_config(self) -> None:
        """验证数据质量配置的有效性"""
        self._validate_positive("min_data_length", self.min_data_length)
        self._validate_choice("fill_method", self.fill_method, VALID_FILL_METHODS)


class AutoExecutionConfig(BaseConfig):
    """简化的自动执行配置类 - 只保留核心必需参数"""
    
    def __init__(self):
        # 核心功能 - 无提示执行
        self.silent_mode = True              # 无权限提示模式
        self.auto_save_results = True        # 自动保存结果
        
        # 错误处理
        self.max_retry_attempts = 3          # 最大重试次数
        
        # 性能设置
        self.max_parallel_workers = 4        # 最大并行工作数
        
        # 日志设置 
        self.log_level = "INFO"             # 日志级别: DEBUG, INFO, WARNING, ERROR
        
        super().__init__()
    
    def _validate_config(self) -> None:
        """验证自动执行配置的有效性"""
        self._validate_non_negative("max_retry_attempts", self.max_retry_attempts)
        self._validate_positive("max_parallel_workers", self.max_parallel_workers)
        self._validate_choice("log_level", self.log_level, VALID_LOG_LEVELS)

class ConfigManager:
    """配置管理器 - 集中管理所有配置"""
    
    def __init__(self):
        self._date_config = DateConfig()
        self._backtest_config = BacktestConfig()
        self._visualization_config = VisualizationConfig()
        self._data_quality_config = DataQualityConfig()
        self._auto_execution_config = AutoExecutionConfig()
        self._model_config = ModelConfig()
    
    @property
    def date_config(self) -> DateConfig:
        """获取日期配置"""
        return self._date_config
    
    @property
    def backtest_config(self) -> BacktestConfig:
        """获取回测配置"""
        return self._backtest_config
    
    @property
    def model_config(self) -> ModelConfig:
        """获取模型配置"""
        return self._model_config
    
    @property
    def visualization_config(self) -> VisualizationConfig:
        """获取可视化配置"""
        return self._visualization_config
    
    @property
    def data_quality_config(self) -> DataQualityConfig:
        """获取数据质量配置"""
        return self._data_quality_config
    
    @property
    def auto_execution_config(self) -> AutoExecutionConfig:
        """获取自动执行配置"""
        return self._auto_execution_config
    
    def get_all_configs(self) -> Dict[str, Dict[str, Any]]:
        """获取所有配置信息"""
        return {
            'date_config': self._date_config.to_dict(),
            'backtest_config': self._backtest_config.to_dict(),
            'visualization_config': self._visualization_config.to_dict(),
            'data_quality_config': self._data_quality_config.to_dict(),
            'auto_execution_config': self._auto_execution_config.to_dict(),
            'model_config': self._model_config.to_dict()
        }
    
    def print_config_summary(self):
        """打印配置摘要"""
        print("=== 配置摘要 ===")
        print(f"日线数据期间: {self._date_config.day_data_start_date} 到 {self._date_config.day_data_end_date}")
        print(f"分钟数据期间: {self._date_config.bar_data_start_date} 到 {self._date_config.bar_data_end_date}")
        print(f"利率数据期间: {self._date_config.interest_rate_start_date} 到 {self._date_config.interest_rate_end_date}")
        print(f"IC值阈值: {self._model_config.ic_threshold}")
        print(f"相关性阈值: {self._model_config.correlation_threshold}")
        print(f"默认回测月数: {self._backtest_config.default_months}")
        print(f"利率品种: {self._date_config.interest_rate_symbols}")
    
    def validate_all_configs(self) -> bool:
        """验证所有配置的有效性"""
        try:
            configs = [
                self._date_config, self._backtest_config,
                self._visualization_config, self._data_quality_config, 
                self._auto_execution_config, self._model_config
            ]
            
            for config in configs:
                config._validate_config()
            
            print("所有配置验证通过")
            return True
        except ValueError as e:
            print(f"配置验证失败: {e}")
            return False
    
    def save_config_to_file(self, filepath: str) -> None:
        """将配置保存到文件"""
        all_configs = self.get_all_configs()
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(all_configs, f, indent=2, ensure_ascii=False)
        print(f"配置已保存到: {filepath}")
    
    def load_config_from_file(self, filepath: str) -> None:
        """从文件加载配置"""
        with open(filepath, 'r', encoding='utf-8') as f:
            configs = json.load(f)
        
        for config_name, config_data in configs.items():
            if hasattr(self, f"_{config_name}"):
                config_obj = getattr(self, f"_{config_name}")
                config_obj.update(**config_data)
        
        print(f"配置已从文件加载: {filepath}")
 
# MACRO symbols list (only keys)
MACRO_SYMBOLS = {
    'commodity': [
        'IF.CFE','IC.CFE','IH.CFE','IM.CFE',
        'AU.SHF','AG.SHF','CU.SHF','AL.SHF',
        'ZN.SHF','RB.SHF','LC.GFE', # 碳酸锂 广期所
        'SA.CZC',  # 纯碱 郑商所
        'SC.INE',  # 原油 上期能源
        'JM.DCE','EC.INE',  # 集运指数 上期能源
    ],
    'fx': [
        'USDCNY.IB',  # 美元兑人民币汇率
        'EURCNY.IB',  # 欧元兑人民币汇率
        'JPYCNY.IB',  # 日元兑人民币汇率
        'GBPCNY.IB',
        'CADCNY.IB',
        'AUDCNY.IB',
        'CHFCNY.IB',
        'KRWCNY.IB',
        'SGDCNY.IB',
        'INRCNY.IB',
        # 'USDCNH.FX',
        # 'EURCNH.FX',
        # 'JPYCNH.FX',
        # 'GBPCNH.FX',
    ],
    'currency': [
        'SHIBOR3M.IR',  # SHIBOR利率
        'FR007.IR',  # 回购利率
        'SOFR.IR','ESTR.IR','SONIA.IR','TONAR.IR','DR001.IB'
    ],
}

# ===================== 全局配置实例 =====================
config_manager = ConfigManager()


if __name__ == "__main__":
    # 验证所有配置
    config_manager.validate_all_configs()
    
    # 打印配置摘要
    config_manager.print_config_summary()
    
    # 演示配置使用
    print("\n=== 配置使用示例 ===")
    print("日期配置:", config_manager.date_config.to_json())
    print("自动执行配置:", config_manager.auto_execution_config.to_dict())
