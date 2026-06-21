"""One-off script: extract real OHLC bars from gitignored database/futures/*.pkl
into a small static JSON used purely for decorative candlesticks on cover.html.
Run manually; output is committed, this script is not imported anywhere."""
import json
import pickle
from pathlib import Path

DB = Path(__file__).resolve().parents[2].parent / "database" / "futures"
OUT = Path(__file__).resolve().parent / "cover-data.json"

# (contract, label, bars-per-day) — bond futures + a commodity for visual variety
SOURCES = [
    ("TL2603.pkl", "TL2603", 5),
    ("RB2605.pkl", "RB2605", 5),
]


def bars_for_day(df, n):
    last = df["last"].dropna()
    if len(last) < n:
        return []
    chunks = [last.iloc[i] for i in
              [slice(*b) for b in
               zip([len(last) * i // n for i in range(n)],
                   [len(last) * i // n for i in range(1, n + 1)])]]
    out = []
    for c in chunks:
        if len(c) == 0:
            continue
        out.append([round(float(c.iloc[0]), 4), round(float(c.max()), 4),
                    round(float(c.min()), 4), round(float(c.iloc[-1]), 4)])
    return out


def extract(fname, n):
    with open(DB / fname, "rb") as f:
        d = pickle.load(f)
    bars = []
    for date in sorted(d.keys()):
        bars.extend(bars_for_day(d[date], n))
    return bars


def normalize(bars):
    lows = [b[2] for b in bars]
    highs = [b[1] for b in bars]
    mn, mx = min(lows), max(highs)
    rg = (mx - mn) or 1.0
    return [[round((v - mn) / rg, 5) for v in b] for b in bars]


data = {}
for fname, label, n in SOURCES:
    raw = extract(fname, n)
    data[label] = normalize(raw)
    print(label, len(raw), "bars")

OUT.write_text(json.dumps(data, separators=(",", ":")))
print("wrote", OUT)
