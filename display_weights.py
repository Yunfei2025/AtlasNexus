import numpy as np
import pandas as pd

# Deterministic factor weights
weights = {
    'Level': [0.2, 0.2, 0.2, 0.2, 0.2],
    'Slope': [-0.4, -0.2, 0.0, 0.2, 0.4],
    'Curvature': [0.25, -0.25, 0.0, -0.25, 0.25]
}

tenors = ['1Y', '2Y', '5Y', '10Y', '30Y']
df = pd.DataFrame(weights, index=tenors)

print("\n" + "="*60)
print("DETERMINISTIC YIELD CURVE FACTOR WEIGHTS")
print("="*60)
print("\nTenors: 1Y, 2Y, 5Y, 10Y, 30Y")
print("\n" + df.to_string())
print("\n" + "="*60)
print("\nFactor Definitions:")
print("  • Level:     Equal-weighted average (parallel shift)")
print("  • Slope:     Short end negative, long end positive")
print("  • Curvature: Wings vs belly")
print("\nWeight Sums:")
print(f"  • Level sum:     {sum(weights['Level']):.2f} (should = 1.0)")
print(f"  • Slope sum:     {sum(weights['Slope']):.2f} (should = 0.0)")
print(f"  • Curvature sum: {sum(weights['Curvature']):.2f} (should = 0.0)")
print("="*60 + "\n")
