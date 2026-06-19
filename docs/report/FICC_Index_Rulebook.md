# FICC综合指数规则手册（Rulebook v1.1）

> **文件性质**：本文档描述当前系统的实际建模逻辑与参数配置，与代码实现保持一致。标注`[待实现]`的字段为规划中功能，尚未落地；标注`[可调]`的为已实现但可配置的参数。  
> **版本**：v1.1（对应代码库 bin-v4.0）  
> **最后更新**：2026-06  
> **变更说明**：v1.0 → v1.1，将理想方法论与实际实现对齐；更新资产宇宙、收益序列构造方式、权重约束逻辑及因子信号模块。

---

## 目录

1. [指数概述](#1-指数概述)
2. [资产宇宙与分层结构](#2-资产宇宙与分层结构)
3. [收益序列构造规则](#3-收益序列构造规则)
4. [风险平价层（基准指数 FICC-RP）](#4-风险平价层基准指数-ficc-rp)
5. [因子增厚层（增强指数 FICC-EF）](#5-因子增厚层增强指数-ficc-ef)
6. [再平衡规则](#6-再平衡规则)
7. [指数计算与发布](#7-指数计算与发布)
8. [异常情形处理](#8-异常情形处理)
9. [回溯历史区间说明](#9-回溯历史区间说明)
10. [术语表](#10-术语表)

---

## 1. 指数概述

### 1.1 目标定位

本指数旨在构建一个覆盖中国视角下全FICC资产类别的综合表现基准，供以下用途：

- **内部**：多资产组合业绩考核基准、风险监控仪表盘参考（Beta Book面板）
- **外部**：银行理财/保险资管FICC组合考核基准、市场状态（risk-on/off）观测指标

### 1.2 指数体系

本体系发布两条指数线，**严格分层，独立计算**：

| 指数名称 | 简称 | 定位 | 实现状态 |
|---|---|---|---|
| FICC综合基准指数 | **FICC-RP** | 纯风险平价beta，透明可复制 | **已实现** |
| FICC综合增强指数 | **FICC-EF** | 基准 + 因子模型信号倾斜 | **已实现**（因子信号层） |

> **设计原则**：两条线分轨发布，使用者可独立引用基准指数，因子超额部分单独归因。不将alpha与beta混合进单一指数。

### 1.3 基准货币

- 主基准：**人民币（CNY）**，适配国内机构视角

### 1.4 基准日与初始值

- 数据最早起始日：**2015-01-04**（受限于 `database-px.pkl` / `macro-px.pkl` 数据起始）
- NAV基准点位：**1000**（回测图表中统一使用）

---

## 2. 资产宇宙与分层结构

### 2.1 当前实际资产宇宙

```
FICC综合指数（当前实现）
├── 固定收益（FI）  — 因子建模，单期限资产权重上限 40%
│   ├── CGB_1Y    中国国债 1年期关键期限
│   ├── CGB_2Y    中国国债 2年期关键期限
│   ├── CGB_5Y    中国国债 5年期关键期限
│   ├── CGB_10Y   中国国债 10年期关键期限
│   ├── CGB_20Y   中国国债 20年期关键期限
│   └── CGB_30Y   中国国债 30年期关键期限
│
├── 外汇（FX）      — 单货币对权重上限 20%
│   ├── EURCNY
│   ├── USDCNY
│   ├── GBPCNY
│   └── JPYCNY
│
└── 商品（COMM）    — 单品种权重上限 15%
    ├── Gold      黄金（SHFE AU）
    ├── Copper    铜  （SHFE CU）
    ├── Aluminium 铝  （SHFE AL）
    └── Crude_Oil 原油（INE SC）
```

**数据来源：**

| 资产类 | 数据文件 | 关键字段 |
|---|---|---|
| 国债收益率曲线 | `database-px.pkl['CGB']` | `中债国债到期收益率:1年` … `30年` |
| 外汇即期价格 | `macro-px.pkl['fx']` | `USDCNY.IB`, `EURCNY.IB`, `JPYCNY.IB`, `GBPCNY.IB` |
| 商品期货近月价 | `macro-px.pkl['commodity']` | `AU.SHF`, `CU.SHF`, `AL.SHF`, `SC.INE` |
| 短期利率 | `macro-px.pkl['currency']` | `FR007.IR`, `SHIBOR3M.IR` |
| 风险因子时序 | `fxcurve_ts.pkl` | IRDL/IRSL/IRCV per country |

> **待扩展**：CGB 3Y/7Y期限缺失（数据无该点位，当前用2Y/20Y代替）；FX缺少 CAD/AUD/CHF；商品缺少白银（XAG）。扩展时须同步更新数据管道和因子映射表。

### 2.2 资产纳入标准

- 存在连续可交易的市场价格，日度数据可获取
- 历史数据覆盖至回测起始日
- 单资产年化波动率可计算（需至少 `[可调: 126]` 个交易日历史）

---

## 3. 收益序列构造规则

### 3.1 固定收益（国债）— 因子驱动收益

**实际方法：基于IRDL/IRSL/IRCV确定性风险因子的价格收益序列**

国债资产收益通过风险因子暴露矩阵 $B$ 和因子协方差 $C_f$ 合成：

$$\Sigma_{asset} = B \cdot C_f \cdot B^\top$$

其中因子收益由中债收益率曲线的确定性正交分解得到：

| 因子 | 代码 | 构造方式 | 各期限权重 |
|---|---|---|---|
| 水平因子 | IRDL.CN | 等权做空各期限收益率 | 各期限 +0.20 |
| 斜率因子 | IRSL.CN | 做空短端/做多长端 | 1Y:-0.40, 2Y:-0.20, 5Y:0, 10Y:+0.20, 30Y:+0.40 |
| 曲率因子 | IRCV.CN | 蝶式 | 1Y:+0.25, 2Y:-0.25, 5Y:0, 10Y:-0.25, 30Y:+0.25 |

**各期限修正久期（用于因子暴露计算）：**

| 期限 | IRDL（修正久期） |
|---|---|
| 1Y | 0.95 |
| 2Y | 1.90 |
| 5Y | 4.50 |
| 10Y | 8.50 |
| 20Y | 13.0 |
| 30Y | 17.0 |

> **说明**：当前实现未独立构建 §3（v1.0）中的恒定久期合成收益序列（constant maturity total return），而是复用 `multiasset/factor_backtest.py` 中的 `compute_ewma_factor_covariance()` 直接在因子空间建模。两种方法在数学上等价，但因子方法更易在现有代码结构中维护。

---

### 3.2 外汇（G4货币对）— 即期收益

**实际方法：纯即期价格涨跌幅**

$$r_{FX_i,t} = \frac{S_{i,t} - S_{i,t-1}}{S_{i,t-1}}$$

> **注**：当前未叠加利率差carry（$r_{foreign} - r_{CNY}$），原因是境外隔夜利率（SOFR/€STR等）尚未接入数据管道。已有 `FR007.IR` 作为CNY端利率，`[待实现]` 补充境外隔夜利率后升级为全收益序列。

---

### 3.3 商品 — 近月价格涨跌幅

**实际方法：近月合约价格简单涨跌幅（不含展期成本调整）**

$$r_{COMM_j,t} = \frac{F_{j,t}^{front} - F_{j,t-1}^{front}}{F_{j,t-1}^{front}}$$

> **注**：当前数据仅有近月合约价格（`AU.SHF` 等），无次近月价格，故无法计算 $\text{RollCost}$。`[待实现]` 当次近月数据接入后，按§3.3（v1.0）展期日历补充展期成本调整。

---

## 4. 风险平价层（基准指数 FICC-RP）

### 4.1 方法论：基于因子协方差的资产级ERC

**资产协方差矩阵由因子空间合成：**

$$\Sigma = B \cdot C_f \cdot B^\top + \epsilon \cdot I$$

其中 $\epsilon = 10^{-8}$（数值正定修正），$C_f$ 为EWMA因子协方差矩阵。

**ERC目标函数（资产级）：**

$$\min_{\mathbf{w}} \sum_{i=1}^{N} \left( w_i \cdot (\mathbf{\Sigma w})_i - \frac{\sigma_p^2}{N} \right)^2$$

$$\text{s.t.} \quad \sum_i w_i = 1, \quad w_i \geq w_i^{min}$$

求解器：`scipy.optimize.minimize`（SLSQP方法），实现位于 `multiasset/factor_optimizer.py`。

---

### 4.2 权重约束

**当前实现：分资产类差异化上限**（替代v1.0中的大类硬约束）

| 资产类 | 单资产下限 | 单资产上限 | 设计依据 |
|---|---|---|---|
| 商品（4个品种） | 1% | **15%** | 高波动（年化~15-20%），防止单品种主导 |
| 外汇（4个货币对） | 动态最小值 | **20%** | 中波动（年化~5-8%） |
| 国债/利率互换（多个期限） | 动态最小值 | **40%** | 低波动（年化~2-5%），各期限高相关，ERC自然分散 |
| 对冲工具 | -30% | +30% | 允许做空，用于利率对冲 |

所有上限取 $\max(\text{类别上限},\ 1/N_{assets})$ 以保证优化可行性。

> **注**：v1.0中的大类总权重硬约束（FI≤70%，FX≤20%，COMM≤25%）**未以约束形式直接加入优化器**，而是通过各单资产上限间接控制。当资产池配置合理（当前4商品×15%=60%上限，4FX×20%=80%上限），实际结果中大类权重已落在合理区间。若需进一步约束，`[待实现]` 在优化约束中增加大类求和不等式。

**非商品资产的动态最小权重：**

$$w_i^{min} = \frac{1}{N_{non-comm} \times 10}$$

例：10个非商品资产时，最小权重约1%，防止因子暴露矩阵降秩时资产权重被清零。

---

### 4.3 协方差矩阵估计

**方法：EWMA（指数加权移动平均）**

$$\sigma_{ij,t}^{EWMA} = \lambda \cdot \sigma_{ij,t-1}^{EWMA} + (1-\lambda) \cdot r_{i,t} \cdot r_{j,t}$$

| 参数 | 当前值 | 配置位置 |
|---|---|---|
| 衰减因子 $\lambda$ | **0.94** | `multiasset/config.py` → `RiskModelConfig.FACTOR_VOL_EWMA_LAMBDA` |
| 波动率回看窗口 | `[可调: 3个月]` | `RiskModelConfig.FACTOR_VOL_LOOKBACK_MONTHS` |
| 正定修正 | $+10^{-8} \cdot I$ | `factor_optimizer.py` `_optimize_weights()` |

> **与v1.0的差异**：Ledoit-Wolf收缩`[待实现]`，当前仅使用对角正则项。

---

### 4.4 目标波动率

**当前状态：无目标波动率缩放（unlevered模式）**

优化输出权重满足 $\sum w_i = 1$，不进行杠杆缩放。

> **与v1.0的差异**：v1.0规划的目标波动率缩放（$k = \sigma^*/\hat{\sigma}_p$）**已从实现计划中移除**。原因是 `factors/factor_model.py` 中的因子信号模块已包含独立的波动率归一化（`vol_scale = target_vol / realized_vol`，见§5），在信号层面完成风险控制，无需在RP层再叠加缩放。

---

## 5. 因子增厚层（增强指数 FICC-EF）

### 5.1 框架概述

增强指数 = 基准指数权重（FICC-RP）×（1 + 因子信号倾斜系数）后归一化

**实际实现路径：**

```
因子模型信号（FactorModel）
    ↓  walk-forward训练，每月第一个交易日信号刷新
因子信号标量（scalar ∈ {-2, -1, 0, +1, +2}）
    ↓  乘以 RP 基础权重后信号层再平衡
    ↓  截面归一化（仅保留正信号资产进入多头书）
    ↓  信号下限 = 0.2（防止单一资产100%集中）
    ↓  按大类上限二次截断（商品15%，FX 20%，债券40%）
    ↓  再归一化
FICC-EF 权重
```

---

### 5.2 因子信号模块（FactorModel）

**信号来源**：`factors/engine/factor_engine.py` → `FactorCalculatorFactory` → 走势、动量、统计特征等多因子

**信号持久化**：`factor-backtest.pkl`（per factor code，key = 'FactorModel'），由 Beta Book → Backtest → Individual Factors 子标签页训练并保存

**信号使用方式（每个因子 code 对应一条 position 序列）：**

| 参数 | 值 | 说明 |
|---|---|---|
| 信号模式 | `discrete` | 离散5档：{-2, -1, 0, +1, +2} |
| ICIR置信窗口 | `[可调: 60日]` | 平滑IC-ratio用于置信度加权 |
| 波动率归一化窗口 | `[可调: 60日]` | `vol_scale = target_vol / realized_vol` |
| 目标波动率 | `[可调: 10% annualized]` | `FactorModelConfig.target_vol`（连续模式生效） |
| 最大杠杆 | `[可调: 2.0x]` | `FactorModelConfig.max_leverage` |

**当前已有信号的因子：**（以实际 `factor-backtest.pkl` 中的 key 为准）

| 因子代码 | 资产映射 | 信号最新日期（示例） |
|---|---|---|
| IRDL.CN | CN债券各期限（正向暴露） | 2026-06-04 |
| IRSL.CN | CN债券（斜率暴露，不同期限方向相反） | 2026-06-04 |
| FXDL.USDCNY | USDCNY | 2026-05-26 |
| CMDL.AU | Gold | 2026-06-03 |
| CMDL.CU | Copper | 2026-05-26 |

---

### 5.3 信号到权重的转换

**步骤1：信号倾斜**

$$w_i^{scaled} = w_i^{RP} \times \max(\bar{s}_i,\ 0.2)$$

其中 $\bar{s}_i$ 为资产 $i$ 对应因子信号的均值（当资产暴露于多个因子时取平均），信号下限 0.2 保留最低权重，避免零信号资产被完全排除。

**步骤2：归一化**

$$w_i^{norm} = \frac{w_i^{scaled}}{\sum_j w_j^{scaled}}$$

**步骤3：按大类上限截断（迭代3次收敛）**

$$w_i^{capped} = \min(w_i^{norm},\ \text{ClassCap}_i)$$

$$\text{ClassCap} = \begin{cases} 15\% & \text{商品} \\ 20\% & \text{外汇} \\ 40\% & \text{债券/利率互换} \end{cases}$$

截断后再归一化，重复3次使超限权重均匀分配至未触限资产。

> **与v1.0的差异**：v1.0规划的 Carry / Momentum / Value 三因子叠加结构**尚未实现**。  
> - **Carry**：需FX隔夜利率数据（`[待实现]`）  
> - **Momentum（TSMOM）**：逻辑上可用现有因子序列近似，`[待实现]` 独立实现  
> - **Value（实际利率）**：需CPI/PPI数据（当前数据管道无此字段，`[待实现]`）

---

## 6. 再平衡规则

### 6.1 定期再平衡

| 层级 | 频率 | 执行时点 | 实现状态 |
|---|---|---|---|
| 协方差矩阵更新 | 每月 | 每月1日，用该日前所有可用数据 | **已实现** |
| 权重优化（FICC-RP） | 每月 | 每月1日（`optimize()` 中 `rebalance_date = first_of_month`） | **已实现** |
| 因子信号刷新 | 每月 | 与权重优化同步，从 `factor-backtest.pkl` 读取最新信号 | **已实现** |
| 价值因子 | 季度 | — | **未实现**（数据缺失） |
| 商品合约展期 | 按展期日历 | — | **未实现**（次近月数据缺失） |

> **关键设计**：再平衡日固定为**当月1日**（`pd.Timestamp.today().replace(day=1)`），而非最新可用数据日。这确保 Portfolio 面板的当前优化结果与 Backtest 历史回测的月度再平衡节点严格一致，避免前视偏差（look-ahead bias）。

### 6.2 触发式再平衡

`[待实现]` — 漂移触发（±5%绝对值偏离）和波动率触发（1.5倍目标波动率）规则已在v1.0中定义，尚未在 `portfolio_run.py` 中落地。

### 6.3 交易成本

当前回测和NAV计算均为**总收益指数（不扣交易成本）**。实际可复制成本参考：

| 资产类 | 估计单边成本 |
|---|---|
| 国债（合成序列） | ~1bp |
| 外汇 | ~2-5bp |
| 商品期货 | ~3-5bp |

---

## 7. 指数计算与发布

### 7.1 NAV计算方式

$$\text{NAV}_t = \text{NAV}_{t-1} \times \left(1 + \sum_{i=1}^{N} w_{i,t-1} \cdot r_{i,t}\right)$$

- $\text{NAV}_0 = 1000$（回测起始日）
- $w_{i,t-1}$：最近一次再平衡日确定的权重，在两次再平衡间随价格**自然漂移**（不强制每日归一化）

**实现位置**：`web/tabs/beta/callbacks/backtest_hist.py`

```python
portfolio_values = initial_capital + df_pnl['Total']
nav_series = (portfolio_values / portfolio_values.iloc[0]) * 1000
```

### 7.2 回测展示内容（Portfolio 子标签页）

| 图表 | 内容 |
|---|---|
| Historical Allocation Chart | 各月再平衡后各资产的绝对配置规模（Million CNY，堆叠面积图） |
| Cumulative PnL Chart | 各资产累计盈亏（堆叠面积图）+ **NAV指数线**（金色，右轴，基准1000） |
| 绩效摘要表 | 年化收益率、Sharpe比率（rf=2%）、最大回撤、再平衡次数 |
| Monthly Holdings | 每月持仓资产列表 |

### 7.3 版本管理

- 方法论变更须发布新版本（v1.x → v2.0），旧版本历史数据保留
- 参数调整（`[可调]`字段）记录为minor update（v1.x → v1.x+1），附参数变更日志
- **历史数据不得追溯修改**

---

## 8. 异常情形处理

### 8.1 价格数据缺失

| 缺失时长 | 当前处理 |
|---|---|
| 任意缺失 | `pct_change()` 自动产生NaN，资产当日收益视为0（不进入PnL计算） |
| 因子波动率缺失 | 使用默认估计值（商品：15%年化）并打印警告 |
| `[待实现]` | 连续缺失 >10 日触发监控，>20 日启动剔除流程 |

### 8.2 协方差矩阵数值问题

- 对角正则化：$\Sigma \leftarrow \Sigma + 10^{-8} \cdot I$（已实现）
- Ledoit-Wolf收缩：`[待实现]`
- 条件数 > 1000 时降级为逆波动率加权：`[待实现]`

### 8.3 信号异常

- 所有信号为0或负时：自动回退为纯RP权重（`backtest_hist.py` 中已实现）
- 因子信号文件 `factor-backtest.pkl` 不存在或无数据：显示错误提示，要求先运行 Individual Factors 回测

---

## 9. 回溯历史区间说明

| 区间 | 数据状态 | 说明 |
|---|---|---|
| 2015-01-04 至今 | **实时** | 国债、G4外汇、4个商品数据完整 |
| 2015年前 | 不可用 | 数据管道起始日限制 |

- 国债数据：`中债国债到期收益率` 各期限，来源Wind/中债登
- FX数据：CFETS银行间即期价格（`.IB`后缀）
- 商品数据：SHFE/INE近月合约收盘价

**披露要求：**  
回测结果须注明"历史数据为模拟回测，不代表实际可实现收益。指数计算未扣除交易成本。"

---

## 10. 术语表

| 术语 | 定义 |
|---|---|
| **ERC** | Equal Risk Contribution，等风险贡献 |
| **EWMA** | Exponentially Weighted Moving Average，指数加权移动平均 |
| **IRDL/IRSL/IRCV** | 中国国债收益率曲线的确定性正交因子：水平（Level）/斜率（Slope）/曲率（Curvature） |
| **FactorModel** | `factors/engine/factor_engine.py` 中的走势预测模型，输出离散信号 {-2,-1,0,+1,+2} |
| **ICIR** | Information Coefficient / Information Ratio，衡量因子预测有效性 |
| **NAV** | Net Asset Value，净值（基准1000） |
| **Roll Yield** | 期货展期收益，因近远月价差导致的系统性损益（当前未计入） |
| **Carry** | 持有资产在利率/期限结构不变假设下的收益（FX carry当前未计入） |
| **Roll-down** | 随时间流逝，债券沿收益率曲线下移带来的价格收益（当前未单独计入） |
| **Signal Floor** | 因子信号倾斜时的最低乘数（当前=0.2），防止零信号资产完全退出组合 |
| **Backfill** | 用替代数据补填历史空白区间 |

---

## 附录 A：关键模块与文件映射

| 功能 | 文件 | 核心函数/类 |
|---|---|---|
| 数据加载（FX/商品） | `multiasset/risk_loader.py` | `RiskFactorLoader._load_fx_factors()` / `_load_commodity_factors()` |
| 数据加载（国债因子） | `multiasset/pca_analyzer.py` | `DeterministicRiskFactorAnalyzer` |
| ERC优化 | `multiasset/factor_optimizer.py` | `FactorRiskParityOptimizer._optimize_weights()` |
| 因子信号训练 | `factors/engine/factor_engine.py` | `FactorEngine` / `load_and_prepare_factors()` |
| 因子信号读取 | `multiasset/factor_backtest.py` | `load_factor_backtest()` |
| 主运行入口 | `multiasset/main.py` | `run_risk_parity_allocation()` |
| Portfolio 回调 | `web/tabs/beta/callbacks/portfolio_run.py` | `run_analysis()` |
| Backtest 回调 | `web/tabs/beta/callbacks/backtest_hist.py` | `update_historical_allocation()` |
| Backtest 布局 | `web/tabs/beta/layouts/backtest.py` | `build_multiasset_backtest_layout()` |

---

## 附录 B：关键参数汇总（快速参考）

| 参数 | 当前值 | 配置位置 |
|---|---|---|
| 数据起始日 | 2015-01-04 | 受限于数据文件 |
| NAV基准点位 | 1000 | `backtest_hist.py` |
| EWMA衰减因子 λ | **0.94** | `multiasset/config.py` |
| 波动率回看窗口 | 3个月 | `RiskModelConfig.FACTOR_VOL_LOOKBACK_MONTHS` |
| 商品单品种上限 | **15%** | `factor_optimizer.py` `_CAP_COMM` |
| FX单货币对上限 | **20%** | `factor_optimizer.py` `_CAP_FX` |
| 债券单期限上限 | **40%** | `factor_optimizer.py` `_CAP_BOND` |
| 商品最低权重 | 1% | `factor_optimizer.py` `_commodity_min_wt` |
| 再平衡日期 | 当月1日 | `factor_optimizer.py` `optimize()` |
| 因子信号下限 | 0.2 | `backtest_hist.py` `_SIGNAL_FLOOR` |
| 回测资产池信号截断上限（商品） | 15% | `backtest_hist.py` `_CLASS_CAPS` |
| 回测资产池信号截断上限（FX） | 20% | `backtest_hist.py` `_CLASS_CAPS` |
| 回测资产池信号截断上限（债券） | 40% | `backtest_hist.py` `_CLASS_CAPS` |
| 因子信号模式 | discrete（5档） | `multiasset/factor_model.py` `FactorModelConfig.sizing_mode` |
| 因子ICIR窗口 | 60日 | `FactorModelConfig.icir_window` |

---

## 附录 C：待实现功能列表（`[待实现]`）

| 功能 | 优先级 | 依赖条件 |
|---|---|---|
| FX carry（外汇隔夜利率）接入 | 中 | 需接入SOFR/€STR等境外短利率数据 |
| 商品展期成本调整 | 中 | 需接入次近月合约价格 |
| Carry因子信号 | 中 | 依赖FX carry和商品期限结构数据 |
| Value因子信号（实际利率） | 低 | 需接入月度CPI/PPI数据（注意发布滞后） |
| TSMOM独立动量信号 | 低 | 可基于现有因子序列实现 |
| 大类总权重硬约束 | 低 | 在优化约束中加大类求和不等式 |
| Ledoit-Wolf收缩 | 低 | 当前正则项已足够 |
| 触发式再平衡（漂移/波动率） | 低 | 在 `portfolio_run.py` 中增加触发检测 |
| CGB 3Y/7Y期限扩展 | 低 | 需确认数据可用性 |
| XAG/CAD/AUD/CHF资产扩展 | 低 | 需接入对应数据 |

---

*本文档版本 v1.1 与代码库 bin-v4.0 对应。参数调整须同步更新附录B并记录版本日志。*
