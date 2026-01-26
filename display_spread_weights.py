import numpy as np
import pandas as pd

# Deterministic spread weights
spread_weights = {
    'CDB': {
        'Level': [0.2, 0.2, 0.2, 0.2, 0.2],
        'Slope': [-0.4, -0.2, 0.0, 0.2, 0.4],
    },
    'IRS': {
        'Level': [1/3, 1/3, 1/3],
        'Slope': [-0.5, 0.0, 0.5],
    },
    'ICP': {
        'Level': [1.0],
    },
}

print("\n" + "="*70)
print("DETERMINISTIC SPREAD FACTOR WEIGHTS")
print("="*70)

for spread_type, weights in spread_weights.items():
    if spread_type == 'CDB':
        tenors = ['1Y', '2Y', '5Y', '10Y', '30Y']
    elif spread_type == 'IRS':
        tenors = ['1Y', '2Y', '5Y']
    elif spread_type == 'ICP':
        tenors = ['1Y']
    else:
        continue
    
    df = pd.DataFrame(weights, index=tenors)
    print(f"\n{spread_type} ({len(tenors)} tenor{'s' if len(tenors) > 1 else ''}):")
    print("-" * 40)
    print(df.to_string())
    
    # Show sums
    print("\nWeight Sums:")
    for factor_name, w in weights.items():
        print(f"  {factor_name}: {sum(w):.2f}")

print("\n" + "="*70)
print("\nFactor Definitions:")
print("  * Level: Equal-weighted average (parallel shift)")
print("  * Slope: Short end negative, long end positive")
print("="*70 + "\n")
