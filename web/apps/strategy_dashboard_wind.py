import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
import re
from datetime import datetime, timedelta

import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from settings.paths import DIR_DATA
from WindPy import w


# 设置页面配置
st.set_page_config(page_title="量化策略回测仪表盘 (Wind数据源)", layout="wide")

# ==========================================
# 1. 数据加载与处理函数
# ==========================================

@st.cache_resource
def init_wind():
    """初始化 Wind 接口"""
    if 'w' in globals():
        if not w.isconnected():
            w.start()
        return True
    return False

@st.cache_data(ttl=3600) # 缓存1小时
def load_wind_data(symbol, start_date, end_date):
    """从 Wind 加载分钟数据"""
    if not init_wind():
        st.error("Wind 接口连接失败，请检查 Wind 终端是否开启")
        return None
        
    # Wind API 获取分钟数据 (WSD/WSI)
    # 这里使用 WSI 获取分钟序列数据
    # fields: open, high, low, close, volume
    try:
        # w.wsi 返回的是一个 WindData 对象，包含 .ErrorCode, .Data, .Times, .Fields 等
        wind_data = w.wsi(symbol, "open,high,low,close,volume", start_date, end_date, "")
        
        if wind_data.ErrorCode != 0:
            st.error(f"Wind 数据获取失败，错误码: {wind_data.ErrorCode}, 信息: {wind_data.Data}")
            return None
            
        if not wind_data.Data:
            st.warning(f"未获取到 {symbol} 的数据")
            return None
            
        # 将 WindData 转换为 DataFrame
        # wind_data.Data 是一个 list of lists，行是字段，列是时间
        #我们需要转置
        df = pd.DataFrame(wind_data.Data, index=wind_data.Fields, columns=wind_data.Times).T
        
        # 重命名列以匹配后续逻辑 (Wind 返回的字段名通常是大写)
        df.columns = [c.lower() for c in df.columns]
        df.index.name = 'datetime'
        
        # 确保包含所需的列
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required_cols):
             st.error(f"Wind 返回数据缺少必要字段。返回字段: {df.columns.tolist()}")
             return None

        # 为了兼容之前的逻辑，增加 last 列 (等于 close)
        df['last'] = df['close']
        
        return df
        
    except Exception as e:
        st.error(f"Wind 数据获取异常: {e}")
        return None

@st.cache_data
def get_file_list(directory='.'):
    """获取目录下所有的pkl文件"""
    files = [f for f in os.listdir(directory) if f.endswith('.pkl')]
    return sorted(files)

@st.cache_data
def load_local_data(file_path):
    """加载并合并本地pkl数据"""
    try:
        data_dict = pd.read_pickle(file_path)
        # 自动获取所有日期并合并
        all_data = []
        dates = sorted(list(data_dict.keys()))
        for date in dates:
            df = data_dict[date]
            # 简单的列名检查
            if 'last' not in df.columns:
                # st.warning(f"日期 {date} 的数据缺少 'last' 列，已跳过")
                continue
            all_data.append(df)
        
        if not all_data:
            return None
            
        merged_df = pd.concat(all_data, axis=0)
        
        # 尝试修复索引
        if not isinstance(merged_df.index, pd.DatetimeIndex):
            merged_df.index = pd.to_datetime(merged_df.index, errors='coerce')
            merged_df = merged_df[merged_df.index.notna()]
            
        merged_df = merged_df.sort_index()
        
        # 确保数值列是数字
        for col in ['last', 'volume']:
            if col in merged_df.columns:
                merged_df[col] = pd.to_numeric(merged_df[col], errors='coerce')
        
        merged_df = merged_df.dropna(subset=['last'])
        
        # 兼容性处理：构造 close, open, high, low 列
        merged_df['close'] = merged_df['last']
        # 对于本地tick/快照数据，如果没有OHLC，暂时用last填充
        if 'open' not in merged_df.columns: merged_df['open'] = merged_df['last']
        if 'high' not in merged_df.columns: merged_df['high'] = merged_df['last']
        if 'low' not in merged_df.columns: merged_df['low'] = merged_df['last']
        
        return merged_df
    except Exception as e:
        st.error(f"读取文件出错: {e}")
        return None

def resample_data(df, rule):
    """重采样数据"""
    # 确保索引是datetime类型
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, errors='coerce')
        df = df[df.index.notna()]
        
    # 如果已经是分钟数据，且 rule 也是分钟级别，可以直接 resample
    # 注意：Wind WSI 默认返回的是 1分钟数据 (如果未指定 bar size)
    # 这里假设输入已经是分钟级别的 DataFrame
    
    # Normalize minute alias: pandas deprecates 'T' in favor of 'min'
    if isinstance(rule, str) and 'T' in rule:
        rule = re.sub(r'(?<=\d)T\b', 'min', rule)

    df_resampled = df['close'].resample(rule).ohlc()
    df_resampled['volume'] = df['volume'].resample(rule).sum()
    df_resampled = df_resampled.dropna()
    
    # 修正列名，resample ohlc 会生成 open, high, low, close
    # 但我们后续逻辑用的是 last 代表 close，这里统一一下
    # 其实 ohlc 结果列名就是 open, high, low, close
    # 我们不需要额外的 last 列，因为后续策略用的是 close
    
    return df_resampled

# ==========================================
# 2. 策略逻辑函数
# ==========================================

def run_ma_strategy(data, short_window, long_window):
    """MA交叉策略：金叉做多，死叉做空"""
    df = data.copy()
    df['ma_short'] = df['close'].rolling(window=short_window).mean()
    df['ma_long'] = df['close'].rolling(window=long_window).mean()
    
    # 信号生成
    # ma_short > ma_long -> 1 (多)
    # ma_short < ma_long -> -1 (空)
    df['signal'] = np.where(df['ma_short'] > df['ma_long'], 1, -1)
    
    # 处理缺失值（前期均线未计算出来时信号为0）
    df.iloc[:long_window, df.columns.get_loc('signal')] = 0
    
    df['position'] = df['signal'].diff()
    
    # 计算收益
    df['returns'] = df['close'].pct_change()
    df['strategy_returns'] = df['signal'].shift(1) * df['returns']
    df['cumulative_returns'] = (1 + df['strategy_returns']).cumprod()
    
    return df

def run_bollinger_strategy(data, window, num_std, exit_at_ma=False):
    """
    布林带策略
    默认：跌破下轨做多，突破上轨做空（反手逻辑）
    exit_at_ma=True：触碰中轨平仓（回归均值逻辑）
    """
    df = data.copy()
    df['ma'] = df['close'].rolling(window=window).mean()
    df['std'] = df['close'].rolling(window=window).std()
    df['upper_band'] = df['ma'] + num_std * df['std']
    df['lower_band'] = df['ma'] - num_std * df['std']
    
    # 信号生成
    position = 0
    signals = []
    
    # 转换为numpy数组加速循环
    close_arr = df['close'].values
    upper_arr = df['upper_band'].values
    lower_arr = df['lower_band'].values
    ma_arr = df['ma'].values
    
    for i in range(len(df)):
        # 前期数据不足，保持空仓
        if np.isnan(upper_arr[i]):
            signals.append(0)
            continue
            
        c = close_arr[i]
        u = upper_arr[i]
        l = lower_arr[i]
        m = ma_arr[i]
        
        if c < l:
            position = 1  # 价格低于下轨，做多
        elif c > u:
            position = -1 # 价格高于上轨，做空
        elif exit_at_ma:
            # 如果开启了均线平仓
            if position == 1 and c > m: # 多头回归均线
                position = 0
            elif position == -1 and c < m: # 空头回归均线
                position = 0
        # else: 保持原有持仓
        
        signals.append(position)
        
    df['signal'] = signals
    df['position'] = df['signal'].diff()
    
    # 计算收益
    df['returns'] = df['close'].pct_change()
    df['strategy_returns'] = df['signal'].shift(1) * df['returns']
    df['cumulative_returns'] = (1 + df['strategy_returns']).cumprod()
    
    return df

def run_vwap_strategy(data, window):
    """VWAP策略：价格在VWAP之上做多，之下做空"""
    df = data.copy()
    
    # 计算 Rolling VWAP
    # VWAP = Sum(Price * Volume) / Sum(Volume)
    p = df['close']
    v = df['volume']
    df['pv'] = p * v
    
    df['vwap'] = df['pv'].rolling(window=window).sum() / v.rolling(window=window).sum()
    
    # 信号生成
    # Close > VWAP -> 1 (多)
    # Close < VWAP -> -1 (空)
    df['signal'] = np.where(df['close'] > df['vwap'], 1, -1)
    
    # 处理缺失值
    df.iloc[:window, df.columns.get_loc('signal')] = 0
    
    df['position'] = df['signal'].diff()
    
    # 计算收益
    df['returns'] = df['close'].pct_change()
    df['strategy_returns'] = df['signal'].shift(1) * df['returns']
    df['cumulative_returns'] = (1 + df['strategy_returns']).cumprod()
    
    return df

def calculate_metrics(df):
    """计算策略指标"""
    if df is None or len(df) == 0:
        return {}
        
    total_return = (df['cumulative_returns'].iloc[-1] - 1) * 100
    
    # 简单估算年化
    days = (df.index[-1] - df.index[0]).days
    if days <= 0: days = 1
    annual_return = (df['cumulative_returns'].iloc[-1] ** (365 / days) - 1) * 100
    
    # 最大回撤
    cum = df['cumulative_returns']
    drawdown = (cum - cum.expanding().max()) / cum.expanding().max()
    max_drawdown = drawdown.min() * 100
    
    # 交易次数
    trades = (df['signal'].diff().abs() > 0).sum()
    
    # 夏普比率 (基于日收益率计算)
    try:
        # 将策略收益重采样到日频
        daily_returns = df['strategy_returns'].resample('D').apply(lambda x: (1+x).prod() - 1)
        # 过滤掉非交易日(收益为0的日子，可能是周末或节假日，但也可能是策略空仓)
        # 这里简单过滤掉完全为0的，或者保留。保留0会降低波动率和收益率。
        # 通常夏普计算基于交易日。
        daily_returns = daily_returns[daily_returns != 0]
        
        if len(daily_returns) > 1:
            rf = 0.02 # 假设无风险利率 2%
            ann_ret = daily_returns.mean() * 252
            ann_vol = daily_returns.std() * np.sqrt(252)
            if ann_vol > 0:
                sharpe = (ann_ret - rf) / ann_vol
            else:
                sharpe = 0
        else:
            sharpe = 0
    except:
        sharpe = 0
    
    return {
        "总收益率": f"{total_return:.2f}%",
        "年化收益率": f"{annual_return:.2f}%",
        "最大回撤": f"{max_drawdown:.2f}%",
        "交易次数": trades,
        "夏普比率": f"{sharpe:.2f}"
    }

# ==========================================
# 3. 页面布局与交互
# ==========================================

st.title("📊 量化策略回测 Dashboard")

# --- 侧边栏：参数配置 ---
st.sidebar.header("1. 数据设置")

data_source = st.sidebar.radio("选择数据源", ("Wind 接口", "本地文件 (.pkl)"))

wind_code = None
start_str = None
end_str = None
selected_file = None

if data_source == "Wind 接口":
    # Wind 数据输入
    wind_code = st.sidebar.text_input("输入Wind代码 (如 000001.SZ, TL.CFE)", value="TL.CFE")

    # 日期选择
    today = datetime.now().date()
    start_date = st.sidebar.date_input("开始日期", value=today - timedelta(days=30))
    end_date = st.sidebar.date_input("结束日期", value=today)

    # 确保日期格式正确
    start_str = start_date.strftime("%Y-%m-%d %H:%M:%S")
    end_str = (end_date + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S") # 包含结束日期当天
else:
    pkl_files = get_file_list(directory=os.path.join(DIR_DATA, 'futures'))
    selected_file = st.sidebar.selectbox("选择数据文件", pkl_files, index=0 if pkl_files else None)

timeframe_map = {
    "1分钟": "1T",
    "3分钟": "3T",
    "5分钟": "5T",
    "15分钟": "15T",
    "30分钟": "30T",
    "1小时": "1H",
    "1天": "1D"
}
selected_tf_label = st.sidebar.selectbox("K线周期 (Resample)", list(timeframe_map.keys()), index=2)
selected_tf = timeframe_map[selected_tf_label]

st.sidebar.header("2. MA策略参数")
ma_short = st.sidebar.number_input("短期均线 (Short Window)", min_value=2, value=5)
ma_long = st.sidebar.number_input("长期均线 (Long Window)", min_value=5, value=20)

st.sidebar.header("3. 布林带策略参数")
boll_window = st.sidebar.number_input("布林带周期 (Window)", min_value=5, value=20)
boll_std = st.sidebar.number_input("标准差倍数 (Std Dev)", min_value=0.1, value=1.0, step=0.1)
boll_exit_at_ma = st.sidebar.checkbox("布林带回归均线平仓 (Exit at MA)", value=False)

st.sidebar.header("4. VWAP策略参数")
vwap_window = st.sidebar.number_input("VWAP周期 (Window)", min_value=5, value=20)

# --- 主逻辑 ---

if st.sidebar.button("开始回测"):
    raw_df = None
    
    # 根据选择的数据源加载数据
    if data_source == "Wind 接口":
        if not wind_code:
            st.warning("请输入有效的 Wind 代码")
        else:
            with st.spinner(f'正在从 Wind 获取 {wind_code} 的数据...'):
                raw_df = load_wind_data(wind_code, start_str, end_str)
    else:
        if not selected_file:
            st.warning("请选择数据文件")
        else:
            with st.spinner('正在加载本地数据...'):
                raw_df = load_local_data(selected_file)

    if raw_df is not None:
        # 2. 重采样
        df_resampled = resample_data(raw_df, selected_tf)
        
        if df_resampled.empty:
            st.warning("重采样后数据为空，请检查原始数据或时间范围")
        else:
            # 3. 运行策略
            df_ma = run_ma_strategy(df_resampled, ma_short, ma_long)
            df_boll = run_bollinger_strategy(df_resampled, boll_window, boll_std, exit_at_ma=boll_exit_at_ma)
            df_vwap = run_vwap_strategy(df_resampled, vwap_window)
            
            # --- 展示指标 ---
            metrics_ma = calculate_metrics(df_ma)
            metrics_boll = calculate_metrics(df_boll)
            metrics_vwap = calculate_metrics(df_vwap)
            
            # 指标卡片
            col1, col2, col3 = st.columns(3)
            with col1:
                st.subheader("MA 交叉策略")
                st.metric("总收益率", metrics_ma['总收益率'])
                st.metric("最大回撤", metrics_ma['最大回撤'])
                st.metric("夏普比率", metrics_ma['夏普比率'])
                st.metric("交易次数", metrics_ma['交易次数'])
            
            with col2:
                st.subheader("布林带策略")
                st.metric("总收益率", metrics_boll['总收益率'])
                st.metric("最大回撤", metrics_boll['最大回撤'])
                st.metric("夏普比率", metrics_boll['夏普比率'])
                st.metric("交易次数", metrics_boll['交易次数'])
                
            with col3:
                st.subheader("VWAP 策略")
                st.metric("总收益率", metrics_vwap['总收益率'])
                st.metric("最大回撤", metrics_vwap['最大回撤'])
                st.metric("夏普比率", metrics_vwap['夏普比率'])
                st.metric("交易次数", metrics_vwap['交易次数'])

            # --- 绘图 (Plotly) ---
            st.subheader("📈 策略图表分析")
            
            # 创建多子图
            # shared_xaxes=False: 允许我们自定义哪些轴共享
            # 我们将手动设置 Row 2 和 Row 3 共享 X 轴，而 Row 1 独立
            fig = make_subplots(
                rows=3, cols=1, 
                shared_xaxes=False, 
                vertical_spacing=0.08,
                row_heights=[0.5, 0.25, 0.25],
                subplot_titles=("价格与技术指标", "累计收益率对比", "持仓情况")
            )
            
            # 使用字符串索引作为 X 轴 (Category模式)，消除非交易时间空隙
            # 使用 <br> 换行显示日期和时间
            x_index = df_resampled.index.strftime('%Y-%m-%d<br>%H:%M')
            
            # Row 1: K线图 + 指标
            fig.add_trace(go.Scatter(x=x_index, y=df_resampled['close'], name='收盘价', line=dict(color='black', width=2)), row=1, col=1)
            fig.add_trace(go.Scatter(x=x_index, y=df_ma['ma_short'], name=f'MA{ma_short}', line=dict(color='orange', width=1)), row=1, col=1)
            fig.add_trace(go.Scatter(x=x_index, y=df_ma['ma_long'], name=f'MA{ma_long}', line=dict(color='blue', width=1)), row=1, col=1)
            fig.add_trace(go.Scatter(x=x_index, y=df_boll['upper_band'], name='布林上轨', line=dict(color='green', width=1, dash='dot')), row=1, col=1)
            fig.add_trace(go.Scatter(x=x_index, y=df_boll['lower_band'], name='布林下轨', line=dict(color='red', width=1, dash='dot')), row=1, col=1)
            fig.add_trace(go.Scatter(x=x_index, y=df_vwap['vwap'], name='VWAP', line=dict(color='purple', width=1, dash='dash')), row=1, col=1)
            
            # Row 2: 收益率对比
            fig.add_trace(go.Scatter(x=x_index, y=df_ma['cumulative_returns'], name='MA收益', line=dict(color='blue')), row=2, col=1)
            fig.add_trace(go.Scatter(x=x_index, y=df_boll['cumulative_returns'], name='布林收益', line=dict(color='orange')), row=2, col=1)
            fig.add_trace(go.Scatter(x=x_index, y=df_vwap['cumulative_returns'], name='VWAP收益', line=dict(color='purple')), row=2, col=1)
            
            # Row 3: 综合持仓强度 (所有策略信号之和)
            # 信号叠加：+1代表多头，-1代表空头。3个策略叠加范围为 [-3, 3]
            aggregate_signal = df_ma['signal'] + df_boll['signal'] + df_vwap['signal']
            
            # 为了让图表更直观，使用颜色区分多空
            # 这里简单绘制一条线，并填充
            fig.add_trace(go.Scatter(
                x=x_index, 
                y=aggregate_signal, 
                name='综合持仓强度', 
                line=dict(color='rgba(50, 50, 50, 0.8)', width=1.5, shape='hv'),
                fill='tozeroy',
                fillcolor='rgba(100, 100, 100, 0.2)'
            ), row=3, col=1)
            
            # 布局调整
            fig.update_layout(
                height=1200, 
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            
            # 配置 X 轴 (Category 模式)
            common_xaxis_config = dict(
                type='category',
                tickmode='auto',
                nticks=10,
                showgrid=True
            )
            
            # xaxis1: 价格图 (独立)
            fig.update_xaxes(
                title_text="时间", 
                row=1, col=1,
                **common_xaxis_config
            )
            
            # xaxis2: 收益率图 (与 xaxis3 共享)
            fig.update_xaxes(
                row=2, col=1,
                showticklabels=False, # 隐藏中间图的标签
                **common_xaxis_config
            )
            
            # xaxis3: 持仓图 (主控轴)
            fig.update_xaxes(
                title_text="时间",
                row=3, col=1,
                matches='x2',
                **common_xaxis_config
            )
            
            fig.update_layout(
                xaxis2=dict(matches='x3'),
                xaxis3=dict(matches='x2')
            )
            
            fig.update_yaxes(title_text="价格", row=1, col=1)
            fig.update_yaxes(title_text="净值", row=2, col=1)
            fig.update_yaxes(title_text="持仓强度", row=3, col=1, tickvals=[-3, -2, -1, 0, 1, 2, 3])
            
            st.plotly_chart(fig, use_container_width=True)
            
            # --- 数据展示 ---
            with st.expander("查看详细数据"):
                st.dataframe(df_resampled.head(100))


