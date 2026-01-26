"""
Display deterministic factor weights for yield curve analysis.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from multiasset.pca_analyzer import DeterministicRiskFactorAnalyzer

# Create analyzer instance (input_dir not needed for just viewing weights)
analyzer = DeterministicRiskFactorAnalyzer(input_dir=".")

# Get weights as DataFrame
weights_df = analyzer.get_weights_dataframe()

print("\n" + "="*60)
print("DETERMINISTIC YIELD CURVE FACTOR WEIGHTS")
print("="*60)
print("\nTenors: 1Y, 2Y, 5Y, 10Y, 30Y")
print("\n" + weights_df.to_string())
print("\n" + "="*60)
print("\nFactor Definitions:")
print("  • Level:     Equal-weighted average of all tenors (parallel shift)")
print("  • Slope:     Short end (1Y-2Y) vs Long end (10Y-30Y)")
print("  • Curvature: Wings (1Y, 30Y) vs Belly (2Y, 5Y, 10Y)")
print("="*60 + "\n")
