"""Configuration constants for yield surface visualization."""

from __future__ import annotations

import datetime as dt

# labels
cn_id_list = "M1004136,M1004677,M1004829,S0059741,S0059742,S0059743,S0059744,\
            S0059745,S0059746,M0057946,S0059747,M0057947,S0059748,M1000165,\
            M1004678,S0059749,S0059750,S0059751,S0059752"
cn_id_name = [
    '中债国债到期收益率:0年', '中债国债到期收益率:1个月', '中债国债到期收益率:2个月',
    '中债国债到期收益率:3个月', '中债国债到期收益率:6个月', '中债国债到期收益率:9个月',
    '中债国债到期收益率:1年', '中债国债到期收益率:2年', '中债国债到期收益率:3年',
    '中债国债到期收益率:4年', '中债国债到期收益率:5年', '中债国债到期收益率:6年',
    '中债国债到期收益率:7年', '中债国债到期收益率:8年', '中债国债到期收益率:9年',
    '中债国债到期收益率:10年', '中债国债到期收益率:15年', '中债国债到期收益率:20年',
    '中债国债到期收益率:30年',
]

us_id_list = "G0000883,W0862667,G0011651,G0000884,\
           N8801325,G0000885,\
           G0000886,G0000887,G0000888,\
           G0000889,G0000890,G0000891,\
           G0000892,G0000893"
us_id_name = [
    '美国国债收益率:1个月', '美国国债收益率:1.5个月', '美国国债收益率:2个月', '美国国债收益率:3个月',
    '美国国债收益率:4个月', '美国国债收益率:6个月',
    '美国国债收益率:1年', '美国国债收益率:2年', '美国国债收益率:3年',
    '美国国债收益率:5年', '美国国债收益率:7年', '美国国债收益率:10年',
    '美国国债收益率:20年', '美国国债收益率:30年',
]

# Available term options for dropdown selectors
TERM_LIST = [
    '0-month', '1-month', '2-month', '3-month', '6-month',
    '1-year', '2-year', '3-year', '4-year', '5-year', '10-year'
]

# Camera up vectors for different view modes
UPS = {
    0: dict(x=0, y=0, z=1),
    1: dict(x=0, y=0, z=1),
    2: dict(x=0, y=0, z=1),
    3: dict(x=0, y=0, z=1),
    4: dict(x=0, y=0, z=1),
    5: dict(x=0, y=0, z=1),
}

# Camera center positions for different view modes
CENTERS = {
    0: dict(x=0.3, y=0.8, z=0.1),
    1: dict(x=0, y=0, z=0.5),
    2: dict(x=0, y=1.1, z=0.0),
    3: dict(x=0, y=-0.7, z=0),
    4: dict(x=0, y=-0.2, z=0),
    5: dict(x=-0.11, y=-0.5, z=0),
}

# Camera eye positions for different view modes
EYES = {
    0: dict(x=2.7, y=2.7, z=0.3),
    1: dict(x=0.01, y=3.8, z=-0.37),
    2: dict(x=1.3, y=3, z=0),
    3: dict(x=2.6, y=-1.6, z=0),
    4: dict(x=3, y=-0.2, z=0),
    5: dict(x=-0.1, y=-0.5, z=2.66),
}

# Descriptive texts for each view mode
TEXTS = {
    0: """
##### Yield Curve Visualization
The yield curve shows the relationship between interest rates and time to maturity,
revealing market expectations for future economic conditions including inflation
and growth prospects.
""".replace("  ", ""),
    1: """
##### Current Yield Curve
Today's yield curve snapshot shows the current term structure of interest rates
across different maturities.
""".replace("  ", ""),
    2: """
##### Current Market Position
The current position in the yield curve highlights today's rates across 
the maturity spectrum.
""".replace("  ", ""),
    3: """
##### Short-Term Trends
Short-term rate movements are typically influenced by central bank policy
and near-term economic expectations.
""".replace("  ", ""),
    4: """
##### Long-Term Trends
Long-term rates reflect market expectations for economic growth, inflation,
and risk premiums over extended periods.
""".replace("  ", ""),
    5: """
##### Top-Down View
An overhead perspective of the yield surface across time and maturity.
""".replace("  ", ""),
}

# Annotations for specific view modes
ANNOTATIONS = {
    0: [],
    1: [
        dict(
            showarrow=False,
            x="1-month",
            y=dt.datetime.today().strftime("%Y-%m-%d"),
            z=0.046,
            text="Short-term rates basically <br>follow the interest rates set <br>by the Federal Reserve.",
            xref="x",
            yref="y",
            zref="z",
            xanchor="left",
            yanchor="auto",
        )
    ],
    2: [],
    3: [],
    4: [],
    5: [],
}

# Color scale for surface plot - Optimized for dark background
# Vibrant teal-cyan gradient for better visibility and contrast
COLORSCALE = [
    [0, "rgb(13,8,135)"],      # Deep indigo (low yield)
    [0.2, "rgb(84,2,163)"],    # Purple
    [0.4, "rgb(139,10,165)"],  # Magenta-purple
    [0.6, "rgb(185,50,137)"],  # Pink-purple
    [0.8, "rgb(219,92,104)"],  # Coral
    [1, "rgb(244,136,73)"],    # Bright orange (high yield)
]

# Alternative palettes (uncomment to use):
# Option 2: Viridis-like (professional, colorblind-friendly)
# COLORSCALE = [
#     [0, "rgb(68,1,84)"],     # Purple
#     [0.25, "rgb(59,82,139)"], # Blue-purple
#     [0.5, "rgb(33,145,140)"], # Teal
#     [0.75, "rgb(94,201,98)"], # Green
#     [1, "rgb(253,231,37)"],   # Yellow
# ]

# Option 3: Warm (Red-Orange-Yellow)
# COLORSCALE = [
#     [0, "rgb(103,0,31)"],    # Dark red
#     [0.25, "rgb(178,24,43)"], # Red
#     [0.5, "rgb(214,96,77)"],  # Orange-red
#     [0.75, "rgb(244,165,130)"], # Light orange
#     [1, "rgb(253,219,199)"],  # Pale orange
# ]

# Option 4: Ocean (Deep blue to cyan)
# COLORSCALE = [
#     [0, "rgb(8,48,107)"],    # Deep ocean blue
#     [0.25, "rgb(33,113,181)"], # Ocean blue
#     [0.5, "rgb(66,146,198)"],  # Sky blue
#     [0.75, "rgb(107,174,214)"], # Light sky blue
#     [1, "rgb(189,215,231)"],   # Pale blue
# ]
