# -*- coding: utf-8 -*-
"""
Created on Sun Apr 27 21:40:38 2025

@author: CMBC
"""
import os
import numpy as np
import pandas as pd
from scipy.optimize import minimize
import nlopt

from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA

# Import from correct modules
from settings.paths import DIR_INPUT
from settings.fixed_income import IRSConfig
from curves.utils.file import updatePKL
from curves.calibration.stat import OU_calibrate

mdurs = {'TS.CFE': 2, 'TF.CFE': 4.5, 'T.CFE': 8, 'TL.CFE': 20}

def get_pca_loadings(returns,N):
    pca = PCA(n_components=N)
    sec_pcs = pca.fit_transform(returns)
    sec_pca_inv = pca.inverse_transform(sec_pcs)
    sec_res = returns - sec_pca_inv
    loadings = pca.components_.T
    explained_variance = pca.explained_variance_
    print("\n" + "-" * 40)
    print("result".center(40))
    print("-" * 40)
    for i in range(loadings.shape[1]):
        print('主成分', str(i + 1), '权重:%.2f'%pca.explained_variance_ratio_[i])
        print("-" * 40)
        for j in range(returns.shape[1]):
            print('资产构成: ', '%.2f' % loadings[j, i], returns.columns[j])

    scaler = StandardScaler()
    residuals_zscore = scaler.fit_transform(sec_res)

    statinfo = OU_calibrate(sec_res)
    statinfo['spread'] = sec_res.iloc[-1]
    statinfo['Zscore'] = (statinfo['spread'] - statinfo['mean']) / statinfo['vol']
    pca_spd = {}
    pca_spd = updatePKL(pca_spd, os.path.join(DIR_INPUT, 'Portfolio-spds.pkl'))
    temp = pca_spd['Spot'][returns.columns]@loadings
    scaler = StandardScaler()
    temp = scaler.fit_transform(temp)
    temp = pd.DataFrame(temp, index=pca_spd['Spot'].index)
    temp.columns = ['PC' + str(i + 1) for i in range(N)]
    pca_spd['PC'] = temp
    pca_spd['Spread'] = sec_res
    pca_spd['StatInfo'] = statinfo
    pca_spd = updatePKL(pca_spd, os.path.join(DIR_INPUT, 'Portfolio-spds.pkl'),rewrite=True)
    import matplotlib.pyplot as plt
    pca_spd['PC'].plot(figsize=(12, 6), title='PC', grid=True)
    #plt.show()
    return loadings, explained_variance, residuals_zscore[-1]

def get_mat(clist):
    if "年" in clist[0]:
        mats = [str(int(f.split(":")[1].split("年")[0]))+'Y' for f in clist ]
    elif "FR007" in clist[0]:
        mats = [f.split("FR007S")[1].split(".")[0] for f in clist ]
    else:
        mats = 0
    return mats

def get_dur(clist):
    if "年" in clist[0]:
        ttm = [float(f.split(":")[1].split("年")[0]) for f in clist ]
        durs = np.array([ (1-(1+0.02)**(-t))/0.02/(1+0.02) for t in ttm ])
    elif "FR007" in clist[0]:
        durs_ = np.array([f.split("FR007S")[1].split(".")[0] for f in clist ])
        durs = np.array([ IRSConfig.TERM_MAP[r.lower()]/4*0.98 for r in durs_])
    else:
        durs = 0
    return durs

def risk_parity_optimizer(returns, conditions, method='SLSQP', max_iter=10e4):
    annual_cov = returns.cov()
    cov_matrix = annual_cov.values
    n = cov_matrix.shape[0]
    init_weights = np.ones(n) / n

    def _risk_contribution(w):
        port_var = w.T @ cov_matrix @ w
        marginal_risk = cov_matrix @ w
        return (w * marginal_risk) / port_var

    def _objective(w):
        rc = _risk_contribution(w)
        a = np.sum((rc - 1 / n) ** 2)
        return a
    
    size_max = conditions['size']
    upper = np.array(conditions['risk_constraints']['upper'])/size_max
    lower = np.array(conditions['risk_constraints']['lower'])/size_max
    N = len(upper)
    loadings, explained_variance, zscore = get_pca_loadings(returns,N)
    durs = get_dur(returns.columns)
    dv = conditions['dv01'] / conditions['size']
    short = [list(returns.columns).index(c) for c in returns.columns if (str(10) in c) or (str(30) in c)]
    
    # 改进3：优化约束条件
    constraints = [
        {'type': 'eq', 'fun': lambda w: 1 - np.sum(w)},
        {'type': 'ineq', 'fun': lambda w: 1 - np.max(abs(w))},  # 集中度限制
        {'type': 'ineq', 'fun': lambda w: dv - np.max(np.multiply(durs, w))},  # 单边dv限制
        {'type': 'ineq', 'fun': lambda w: dv + np.min(np.multiply(durs, w))},  # 单边dv限制
        {'type': 'ineq', 'fun': lambda w: dv - np.dot(durs, w)}
    ]

    def rc_constraint(weights):
        weights_pc = -loadings.T @ weights
        rc_pc = weights_pc * explained_variance ** 0.5
        # rc_pc_normalized = rc_pc / np.sum(rc_pc)
        return rc_pc #rc_pc_normalized  # 归一化
    
    # constraints += [{'type': 'ineq', 'fun': lambda w: upper - rc_constraint(w)}]
    # constraints += [{'type': 'ineq', 'fun': lambda w: rc_constraint(w) - lower}]

    def get_pc_sensitivities(w):
        wdurs = durs * w
        pcdurs = loadings.T @ wdurs
        return pcdurs
    
    constraints += [{'type': 'ineq', 'fun': lambda w: upper - get_pc_sensitivities(w)}]
    # constraints += [{'type': 'ineq', 'fun': lambda w: get_pc_sensitivities(w) - lower}]
    
    bounds = conditions['bounds']
    # for i in short:
    #     bounds[i] = (-1, 1)
        
    # 改进4：优化求解参数
    result = minimize(_objective, init_weights,
                      method=method,
                      bounds=bounds,
                      constraints=constraints,
                      options={'maxiter': max_iter, 'ftol': 1e-9},
                      tol=1e-10)
    print("=" * 40)
    print("迭代次数：%d次" % result.nit)

    rcc = rc_constraint(result.x)
    sen = get_pc_sensitivities(result.x)
    print("-" * 40)
    for p in range(len(rcc)):
        print('主成分', str(p + 1), '风险贡献度: %.2f' % rcc[p])
        print('主成分', str(p + 1), '敏感度: %.2f' % (sen[p]*size_max))

    rc = _risk_contribution(result.x)
    print("-" * 40)
    for k in range(len(rc)):
        print(f"{returns.columns[k]:10s}", '风险贡献度: %.2f' % rc[k])
    if not result.success:
        raise RuntimeError(f"优化失败: {result.message}")

    alpha = 0  # 信号强度
    adjusted_weights = result.x + alpha * zscore  # 使用最新残差信号
    # adjusted_weights = adjusted_weights / np.sum(adjusted_weights)  # 归一化
    return dict(zip(annual_cov.columns, np.round(adjusted_weights, 3))),rc

def numerical_gradient(f, x, h=1e-5):
    grad = np.zeros_like(x)
    for i in range(len(x)):
        x_plus = x.copy()
        x_minus = x.copy()
        x_plus[i] += h
        x_minus[i] -= h
        grad[i] = (f(x_plus, None) - f(x_minus, None)) / (2 * h)
    return grad

def risk_parity_optimizer_nl(returns, N, conditions, method='LD_SLSQP'):
    annual_cov = returns.cov()
    cov_matrix = annual_cov.values
    n = cov_matrix.shape[0]

    bondfut = [f for f in returns.columns if f in mdurs.keys()]
    bondfutidx = [list(returns.columns).index(f) for f in bondfut]
    bondfutdur = np.array([mdurs[f] for f in bondfut])
    dv = conditions['dv01'] / conditions['size']
    
    upper = conditions['risk_constraints']['upper']
    lower = conditions['risk_constraints']['lower']
    N = len(upper)
    loadings, explained_variance, zscore = get_pca_loadings(returns,N)

    def _risk_contribution(w):
        port_var = w.T @ cov_matrix @ w
        marginal_risk = cov_matrix @ w
        return (w * marginal_risk) / port_var

    def _rc_sumsq(w):
        rc = _risk_contribution(w)
        a = np.sum((rc - 1 / n) ** 2)
        return a

    def _rc_constraint(weights):
        weights_pc = -loadings.T @ weights
        rc_pc = weights_pc * explained_variance ** 0.5
        rc_pc_normalized = rc_pc / np.sum(rc_pc)
        return rc_pc_normalized  # 归一化
    
    def _objective(w, grad=None):
        value = _rc_sumsq(w)
        if grad is not None and grad.size > 0:
            grad[:] = numerical_gradient(lambda x, _: _rc_sumsq(x), w)
        return value

    def _constraint_sum(w, grad=None):
        if grad is not None and grad.size > 0:
            #grad[:] = -1.0  # 权重和的梯度为1
            grad[:] = numerical_gradient(lambda x, _: np.sum(x)-1, w)
        return np.sum(w) - 1

    def _constraint_dv_single(w, grad=None):
        def _dv_single(w):
            return np.max(abs(np.multiply(bondfutdur, np.take(w, bondfutidx)))) - dv
        if grad is not None and grad.size > 0:
            grad[:] = numerical_gradient(lambda x, _: _dv_single(x), w)
        return _dv_single(w)

    def _constraint_dv_total(w, grad=None):
        def _dv_total(w):
            return np.dot(bondfutdur, np.take(w, bondfutidx)) - dv
        if grad is not None and grad.size > 0:
            grad[:] = numerical_gradient(lambda x, _: _dv_total(x), w)
        return _dv_total(w)
    
    def _rcc_upper(w, grad=None):
        rcc = _rc_constraint(w)
        # Find the index of the worst constraint violation
        idx = np.argmin(upper - rcc)
        min_value = rcc[idx] - upper[idx]
        
        if grad is not None and grad.size > 0:  # Check both conditions
            # Calculate gradient only for the most violated constraint
            def grad_func(x, _):
                rc = _rc_constraint(x)
                return rc[idx] - upper[idx]  # Only return the scalar value for worst violation
            
            grad[:] = numerical_gradient(grad_func, w)
        return min_value  # Return scalar instead of array

    def _rcc_lower(w, grad=None):
        rcc = _rc_constraint(w)
        # Find the index of the worst constraint violation
        idx = np.argmin(rcc - lower)
        min_value = lower[idx] - rcc[idx]
        
        if grad is not None and grad.size > 0:  # Check both conditions
            # Calculate gradient only for the most violated constraint
            def grad_func(x, _):
                rc = _rc_constraint(x)
                return lower[idx] - rc[idx] # Only return the scalar value for worst violation
            
            grad[:] = numerical_gradient(grad_func, w)
        return min_value  # Return scalar instead of array
    
    # 定义优化器
    if method == 'LD_SLSQP':
        opt = nlopt.opt(nlopt.LD_SLSQP, len(returns.columns))
    elif method == 'LD_MAA':
        opt = nlopt.opt(nlopt.LD_MMA, len(returns.columns))
    elif method == 'LN_COBYLA':
        opt = nlopt.opt(nlopt.LN_COBYLA, len(returns.columns))
    elif method == 'GN_MLSL':
        # MLSL is a global optimizer that requires a local optimizer to handle constraints
        # First create the local optimizer
        local_opt = nlopt.opt(nlopt.LD_SLSQP, len(returns.columns))
        local_opt.set_xtol_rel(1e-4)
        
        # Set bounds for the local optimizer
        local_opt.set_lower_bounds([-1.0] * len(returns.columns))
        local_opt.set_upper_bounds([1.0] * len(returns.columns))
        
        # Set constraints for the local optimizer
        local_opt.set_min_objective(_objective)
        local_opt.add_equality_constraint(lambda w, grad: _constraint_sum(w, grad), 1e-8)
        local_opt.add_inequality_constraint(lambda w, grad: _constraint_dv_total(w, grad), 1e-8)
        if upper is not None:
            local_opt.add_inequality_constraint(lambda w, grad: _rcc_upper(w, grad), 1e-8)
            local_opt.add_inequality_constraint(lambda w, grad: _rcc_lower(w, grad), 1e-8)
        
        # Create the MLSL global optimizer
        opt = nlopt.opt(nlopt.GN_MLSL, len(returns.columns))
        opt.set_local_optimizer(local_opt)
    else:
        print('Not a existing method.')
        
    # 设置目标函数（自动选择梯度模式）
    if method != 'GN_MLSL':  # For MLSL, we already set the objective on the local optimizer
        opt.set_min_objective(_objective)

    # Set constraints based on algorithm type
    if method in ['LD_SLSQP','LD_MAA']:
        # 添加约束（自动选择梯度模式）
        opt.add_inequality_constraint(lambda w, grad: _constraint_sum(w, grad), 1e-8)
        opt.add_inequality_constraint(lambda w, grad: _constraint_dv_single(w, grad), 1e-8)
        opt.add_inequality_constraint(lambda w, grad: _constraint_dv_total(w, grad), 1e-8)
        if upper is not None:
            opt.add_inequality_constraint(lambda w, grad: _rcc_upper(w, grad), 1e-8)
            opt.add_inequality_constraint(lambda w, grad: _rcc_lower(w, grad), 1e-8)
    elif method == 'LN_COBYLA':
        # 添加约束（自动选择梯度模式）
        opt.add_inequality_constraint(lambda w, grad: _constraint_sum(w), 1e-8)
        opt.add_inequality_constraint(lambda w, grad: _constraint_dv_single(w, grad), 1e-8)
        opt.add_inequality_constraint(lambda w, grad: _constraint_dv_total(w), 1e-8)
        if upper is not None:
            opt.add_inequality_constraint(lambda w, grad: _rcc_upper(w), 1e-8)
            opt.add_inequality_constraint(lambda w, grad: _rcc_lower(w), 1e-8)
    elif method == 'GN_MLSL':
        # For MLSL, set bounds on the global optimizer
        opt.set_lower_bounds([-1.0] * len(returns.columns))
        opt.set_upper_bounds([1.0] * len(returns.columns))
        # The constraints are handled by the local optimizer already set above

    # 配置数值梯度参数（仅在需要时启用）
    opt.set_xtol_rel(1e-8)
    opt.set_maxeval(10000)
    
    # 执行优化
    init_weights = np.ones(len(returns.columns)) / len(returns.columns)
    x_opt = opt.optimize(init_weights)
    
    print("=" * 40)
    #print("迭代次数：%d次" % iter_count)

    if conditions['risk_constraints']:
        rcc = _rc_constraint(x_opt)
        print("-" * 40)
        for p in range(len(rcc)):
            print('主成分', str(p + 1), '风险贡献度: %.2f' % rcc[p])

    rc = _risk_contribution(x_opt)
    print("-" * 40)
    for k in bondfutidx:
        print(f"{returns.columns[k]:10s}", '风险贡献度: %.2f' % rc[k])
    return dict(zip(annual_cov.columns, np.round(x_opt, 3))),rc
