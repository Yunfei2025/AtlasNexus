"""
TL2606期货双策略回测系统
策略1: MA均线交叉策略
策略2: MA±1倍标准差布林带策略
"""
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

import sys
from pathlib import Path
# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from settings.paths import DIR_DATA

def load_and_merge_data(pkl_file):
    """
    加载并合并多天的价格数据
    
    Parameters:
    -----------
    pkl_file : str
        数据文件路径
    num_days : int
        读取的天数
        
    Returns:
    --------
    pd.DataFrame : 合并后的数据
    """
    print(f"\n{'='*60}")
    print(f"[1/5] 加载数据...")
    
    # 读取pkl文件
    data_dict = pd.read_pickle(os.path.join(DIR_DATA,"futures",pkl_file))
    
    # 获取所有日期
    dates = list(data_dict.keys())
    print(f"读取 {len(dates)} 天的数据:")
    
    # 合并所有日期的数据
    all_data = []
    for date in dates:
        df = data_dict[date].copy()
        print(f"  - {date}: {len(df)} 条记录")
        all_data.append(df)
    
    # 合并数据
    merged_df = pd.concat(all_data, axis=0)
    merged_df = merged_df.sort_index()
    
    print(f"\n合并后数据:")
    print(f"  时间范围: {merged_df.index[0]} 至 {merged_df.index[-1]}")
    print(f"  总记录数: {len(merged_df)}")
    
    return merged_df


def resample_to_5min(df):
    """
    将tick数据重采样为5分钟K线
    
    Parameters:
    -----------
    df : pd.DataFrame
        原始tick数据
        
    Returns:
    --------
    pd.DataFrame : 5分钟K线数据
    """
    print(f"\n[2/5] 重采样为5分钟K线...")
    
    # 重采样为5分钟
    df_5min = df['last'].resample('5T').ohlc()
    df_5min['volume'] = df['volume'].resample('5T').sum()
    
    # 删除缺失值
    df_5min = df_5min.dropna()
    
    print(f"  5分钟K线数量: {len(df_5min)}")
    
    return df_5min


class MAStrategy:
    """策略1: MA均线交叉策略"""
    
    def __init__(self, data, short_window=5, long_window=20):
        """
        Parameters:
        -----------
        data : pd.DataFrame
            5分钟K线数据
        short_window : int
            短期MA周期
        long_window : int
            长期MA周期
        """
        self.data = data.copy()
        self.short_window = short_window
        self.long_window = long_window
        self.name = f"MA交叉策略({short_window},{long_window})"
        
    def calculate_indicators(self):
        """计算技术指标"""
        self.data['ma_short'] = self.data['close'].rolling(window=self.short_window).mean()
        self.data['ma_long'] = self.data['close'].rolling(window=self.long_window).mean()
        self.data = self.data.dropna()
        
    def generate_signals(self):
        """生成交易信号"""
        self.data['signal'] = 0
        
        # 上穿买入(1)，下穿卖出(-1)
        # 当短期均线 > 长期均线时，做多
        # 当短期均线 < 长期均线时，做空
        self.data['signal'] = np.where(self.data['ma_short'] > self.data['ma_long'], 1, -1)
        
        self.data['position'] = self.data['signal'].diff()
        
    def backtest(self):
        """执行回测"""
        self.calculate_indicators()
        self.generate_signals()
        
        # 计算收益
        self.data['returns'] = self.data['close'].pct_change()
        self.data['strategy_returns'] = self.data['signal'].shift(1) * self.data['returns']
        self.data['cumulative_returns'] = (1 + self.data['strategy_returns']).cumprod()
        
        return self.data


class BollingerStrategy:
    """策略2: MA±1倍标准差布林带策略"""
    
    def __init__(self, data, window=20, num_std=1):
        """
        Parameters:
        -----------
        data : pd.DataFrame
            5分钟K线数据
        window : int
            移动窗口周期
        num_std : float
            标准差倍数
        """
        self.data = data.copy()
        self.window = window
        self.num_std = num_std
        self.name = f"布林带策略({window},{num_std}σ)"
        
    def calculate_indicators(self):
        """计算技术指标"""
        self.data['ma'] = self.data['close'].rolling(window=self.window).mean()
        self.data['std'] = self.data['close'].rolling(window=self.window).std()
        self.data['upper_band'] = self.data['ma'] + 1 * self.num_std * self.data['std']
        self.data['lower_band'] = self.data['ma'] - 1 * self.num_std * self.data['std']
        self.data = self.data.dropna()
        
    def generate_signals(self):
        """生成交易信号"""
        self.data['signal'] = 0
        position = 0
        signals = []
        
        for i in range(len(self.data)):
            close = self.data['close'].iloc[i]
            upper = self.data['upper_band'].iloc[i]
            lower = self.data['lower_band'].iloc[i]
            
            # 布林带策略：上轨和下轨
            # 价格突破下轨买入（做多），突破上轨卖出（做空）
            # 只有触碰上下轨才改变持仓，不回归均线平仓
            if close < lower:
                position = 1  # 价格低于下轨，做多
            elif close > upper:
                position = -1  # 价格高于上轨，做空
            # else: 保持原有持仓
                    
            signals.append(position)
        
        self.data['signal'] = signals
        self.data['position'] = self.data['signal'].diff()
        
    def backtest(self):
        """执行回测"""
        self.calculate_indicators()
        self.generate_signals()
        
        # 计算收益
        self.data['returns'] = self.data['close'].pct_change()
        self.data['strategy_returns'] = self.data['signal'].shift(1) * self.data['returns']
        self.data['cumulative_returns'] = (1 + self.data['strategy_returns']).cumprod()
        
        return self.data


def calculate_performance_metrics(data, strategy_name):
    """
    计算策略绩效指标
    
    Parameters:
    -----------
    data : pd.DataFrame
        回测结果数据
    strategy_name : str
        策略名称
        
    Returns:
    --------
    dict : 绩效指标
    """
    returns = data['strategy_returns'].dropna()
    
    # 总收益率
    total_return = (data['cumulative_returns'].iloc[-1] - 1) * 100
    
    # 年化收益率（假设252个交易日）
    days = (data.index[-1] - data.index[0]).days
    periods_per_year = 252 * 12 * 5  # 每年交易日 * 每日12小时 * 每小时12个5分钟
    annual_return = (data['cumulative_returns'].iloc[-1] ** (periods_per_year / len(data)) - 1) * 100
    
    # 夏普比率（假设无风险利率为2%）
    risk_free_rate = 0.02 / periods_per_year
    excess_returns = returns - risk_free_rate
    sharpe_ratio = np.sqrt(periods_per_year) * excess_returns.mean() / excess_returns.std() if excess_returns.std() > 0 else 0
    
    # 最大回撤
    cumulative = data['cumulative_returns']
    running_max = cumulative.expanding().max()
    drawdown = (cumulative - running_max) / running_max
    max_drawdown = drawdown.min() * 100
    
    # 胜率
    win_rate = (returns > 0).sum() / len(returns) * 100 if len(returns) > 0 else 0
    
    # 交易次数
    trades = (data['signal'].diff().abs() > 0).sum()
    
    metrics = {
        '策略名称': strategy_name,
        '总收益率': f'{total_return:.2f}%',
        '年化收益率': f'{annual_return:.2f}%',
        '夏普比率': f'{sharpe_ratio:.4f}',
        '最大回撤': f'{max_drawdown:.2f}%',
        '胜率': f'{win_rate:.2f}%',
        '交易次数': int(trades),
        '总周期数': len(data)
    }
    
    return metrics


def plot_results(strategy1_data, strategy2_data, metrics1, metrics2):
    """
    绘制回测结果
    
    Parameters:
    -----------
    strategy1_data : pd.DataFrame
        策略1的回测数据
    strategy2_data : pd.DataFrame
        策略2的回测数据
    metrics1 : dict
        策略1的绩效指标
    metrics2 : dict
        策略2的绩效指标
    """
    print(f"\n[5/5] 生成可视化图表...")
    
    fig = plt.figure(figsize=(16, 20))
    
    # 创建网格布局
    gs = fig.add_gridspec(5, 2, hspace=0.4, wspace=0.3)
    
    # 准备X轴数据（使用索引位置以消除时间空隙）
    x = np.arange(len(strategy1_data))
    
    # 生成X轴标签（按小时）
    times = strategy1_data.index
    tick_indices = []
    tick_labels = []
    
    # 记录上一个时间的小时
    last_time = None
    
    for i, t in enumerate(times):
        if last_time is None or t.hour != last_time.hour or t.day != last_time.day:
            # 如果是新的一天，显示日期和时间
            if last_time is None or t.day != last_time.day:
                tick_labels.append(t.strftime('%m-%d %H:%M'))
            else:
                # 同一天只显示时间
                tick_labels.append(t.strftime('%H:%M'))
            tick_indices.append(i)
            last_time = t
            
    # 辅助函数：设置X轴
    def format_xaxis(ax):
        ax.set_xticks(tick_indices)
        ax.set_xticklabels(tick_labels, rotation=45, fontsize=8)
        ax.set_xlim(x[0], x[-1])
    
    # ========== Row 0: 价格走势 ==========
    ax0 = fig.add_subplot(gs[0, :])
    ax0.plot(x, strategy1_data['close'], label='价格 (Close)', color='black', linewidth=1)
    # 图1: 策略1 - 仓位变化
    ax1 = fig.add_subplot(gs[1, 0])
    ax1.plot(x, strategy1_data['signal'], 
             label='持仓', linewidth=1.5, color='blue', drawstyle='steps-post')
    ax1.fill_between(x, 0, strategy1_data['signal'], 
                     alpha=0.3, color='blue', step='post')
    ax1.set_title('策略1: MA交叉策略 - 仓位变化', fontsize=12, fontweight='bold')
    ax1.set_ylabel('持仓 (1=多, -1=空)')
    ax1.set_ylim(-1.2, 1.2)
    ax1.set_yticks([-1, 0, 1])
    ax1.grid(True, alpha=0.3)
    ax1.legend()
    format_xaxis(ax1)
    
    # 图2: 策略1 - 收益率曲线
    ax2 = fig.add_subplot(gs[2, 0])
    ax2.plot(x, strategy1_data['cumulative_returns'], 
             label='累计收益', linewidth=2, color='green')
    ax2.axhline(y=1, color='black', linestyle='--', linewidth=1, alpha=0.5)
    ax2.set_title('策略1: MA交叉策略 - 累计收益曲线', fontsize=12, fontweight='bold')
    ax2.set_ylabel('累计收益倍数')
    ax2.grid(True, alpha=0.3)
    ax2.legend()
    format_xaxis(ax2)
    
    # 添加绩效指标文本
    metrics_text1 = f"总收益: {metrics1['总收益率']}\n"
    metrics_text1 += f"夏普比率: {metrics1['夏普比率']}\n"
    metrics_text1 += f"最大回撤: {metrics1['最大回撤']}\n"
    metrics_text1 += f"交易次数: {metrics1['交易次数']}"
    ax2.text(0.02, 0.98, metrics_text1, transform=ax2.transAxes, 
             fontsize=9, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    # ========== 策略2：布林带策略 ==========
    # 图3: 策略2 - 仓位变化
    ax3 = fig.add_subplot(gs[1, 1])
    ax3.plot(x, strategy2_data['signal'], 
             label='持仓', linewidth=1.5, color='orange', drawstyle='steps-post')
    ax3.fill_between(x, 0, strategy2_data['signal'], 
                     alpha=0.3, color='orange', step='post')
    ax3.set_title('策略2: 布林带策略 - 仓位变化', fontsize=12, fontweight='bold')
    ax3.set_ylabel('持仓 (1=多, -1=空)')
    ax3.set_ylim(-1.2, 1.2)
    ax3.set_yticks([-1, 0, 1])
    ax3.grid(True, alpha=0.3)
    ax3.legend()
    format_xaxis(ax3)
    format_xaxis(ax3)
    
    # 图4: 策略2 - 收益率曲线
    ax4 = fig.add_subplot(gs[2, 1])
    ax4.plot(x, strategy2_data['cumulative_returns'], 
             label='累计收益', linewidth=2, color='purple')
    ax4.axhline(y=1, color='black', linestyle='--', linewidth=1, alpha=0.5)
    ax4.set_title('策略2: 布林带策略 - 累计收益曲线', fontsize=12, fontweight='bold')
    ax4.set_ylabel('累计收益倍数')
    ax4.grid(True, alpha=0.3)
    ax4.legend()
    format_xaxis(ax4)
    
    # 添加绩效指标文本
    metrics_text2 = f"总收益: {metrics2['总收益率']}\n"
    metrics_text2 += f"夏普比率: {metrics2['夏普比率']}\n"
    metrics_text2 += f"最大回撤: {metrics2['最大回撤']}\n"
    metrics_text2 += f"交易次数: {metrics2['交易次数']}"
    ax4.text(0.02, 0.98, metrics_text2, transform=ax4.transAxes, 
             fontsize=9, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    # ========== 底部：策略对比 ==========
    
    # 图5: 两个策略的收益率对比
    ax5 = fig.add_subplot(gs[3, :])
    ax5.plot(x, strategy1_data['cumulative_returns'], 
             label='策略1: MA交叉', linewidth=2, color='green')
    ax5.plot(x, strategy2_data['cumulative_returns'], 
             label='策略2: 布林带', linewidth=2, color='purple')
    ax5.axhline(y=1, color='black', linestyle='--', linewidth=1, alpha=0.5)
    ax5.set_title('两策略累计收益对比', fontsize=13, fontweight='bold')
    ax5.set_ylabel('累计收益倍数')
    ax5.grid(True, alpha=0.3)
    ax5.legend(loc='best', fontsize=10)
    format_xaxis(ax5)
    
    # ========== 底部：组合策略 ==========
    
    # 计算组合策略收益 (50/50权重)
    combined_returns = (strategy1_data['strategy_returns'] + strategy2_data['strategy_returns']) / 2
    combined_cumulative = (1 + combined_returns).cumprod()
    
    # 图6: 组合策略收益
    ax6 = fig.add_subplot(gs[4, :])
    ax6.plot(x, combined_cumulative, label='组合策略 (50% MA + 50% Bollinger)', linewidth=2, color='red')
    ax6.axhline(y=1, color='black', linestyle='--', linewidth=1, alpha=0.5)
    ax6.set_title('组合策略累计收益 (等权重)', fontsize=13, fontweight='bold')
    ax6.set_xlabel('时间')
    ax6.set_ylabel('累计收益倍数')
    ax6.grid(True, alpha=0.3)
    ax6.legend(loc='best', fontsize=10)
    format_xaxis(ax6)
    
    plt.suptitle('TL2606期货双策略回测结果', fontsize=16, fontweight='bold', y=0.995)
    
    # 保存图表
    plt.savefig('tl2606_strategy_results.png',
                dpi=300, bbox_inches='tight')
    print(f"  图表已保存至: tl2606_strategy_results.png")
    plt.show()


def main():
    """主函数"""
    print("="*60)
    print("TL2606期货双策略回测系统")
    print(f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    # 1. 加载并合并数据
    raw_data = load_and_merge_data('TL2606.pkl')
    
    # 2. 重采样为5分钟K线
    df_5min = resample_to_5min(raw_data)
    
    # 3. 策略1: MA交叉策略
    print(f"\n[3/5] 执行策略1: MA交叉策略...")
    strategy1 = MAStrategy(df_5min, short_window=5, long_window=20)
    result1 = strategy1.backtest()
    metrics1 = calculate_performance_metrics(result1, strategy1.name)
    
    print(f"\n策略1绩效:")
    for key, value in metrics1.items():
        print(f"  {key}: {value}")
    
    # 4. 策略2: 布林带策略
    print(f"\n[4/5] 执行策略2: 布林带策略...")
    strategy2 = BollingerStrategy(df_5min, window=20, num_std=1)
    result2 = strategy2.backtest()
    metrics2 = calculate_performance_metrics(result2, strategy2.name)
    
    print(f"\n策略2绩效:")
    for key, value in metrics2.items():
        print(f"  {key}: {value}")
    
    # 5. 绘制结果
    plot_results(result1, result2, metrics1, metrics2)
    
    print("\n" + "="*60)
    print("回测完成！")
    print("="*60)
    
    return result1, result2, metrics1, metrics2


if __name__ == "__main__":
    result1, result2, metrics1, metrics2 = main()
