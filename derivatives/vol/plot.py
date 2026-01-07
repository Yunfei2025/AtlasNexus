import numpy as np
import math
from scipy.stats import norm
import plotly.graph_objects as go

def delta_to_strike(delta: float, F: float, sigma: float, T: float, option_type: str = 'call'):
    """
    Black-76 forward-delta -> strike inversion (analytic).
    delta: absolute forward delta (e.g. 0.25)
    F: forward price (use futures price or S if rates ~0)
    sigma: annual vol (e.g. 0.25)
    T: time to expiry in years
    """
    if sigma <= 0 or T <= 0:
        raise ValueError("sigma and T must be positive")
    d_abs = float(delta)
    if option_type.lower().startswith('c'):
        target = d_abs
    else:
        target = 1.0 - d_abs
    target = min(max(target, 1e-12), 1.0 - 1e-12)
    d1 = norm.ppf(target)
    K = F * math.exp(-d1 * sigma * math.sqrt(T) + 0.5 * sigma * sigma * T)
    return K

# Parameters (example)
S = 2000.0            # spot/futures price (you can set to current underlying)
F = S                 # forward ~ spot for short-dated examples or if rates ~0
sigma = 0.25          # annual implied vol (25%)
T = 30.0/252.0        # time to expiry in years (30 trading days)

# Grid of call deltas (0.01..0.99)
deltas = np.linspace(0.01, 0.99, 300)
strikes = np.array([delta_to_strike(d, F, sigma, T, option_type='call') for d in deltas])
payoffs = np.maximum(S - strikes, 0.0)  # call payoff at expiry for each strike (intrinsic)

import plotly.io as pio
pio.renderers.default = "browser"
# Build Plotly figure
fig = go.Figure()
fig.add_trace(go.Scatter(x=deltas, y=payoffs,
                         mode='lines',
                         name='Call payoff at expiry',
                         line=dict(color='royalblue', width=2)))
fig.update_layout(
    title=f"Call Option Payoff at Expiry vs Call Delta (S={S}, σ={sigma:.2%}, T={T:.3f}y)",
    xaxis_title="Call forward delta",
    yaxis_title="Payoff at expiry (max(S - K, 0))",
    template="plotly_white"
)
fig.show()