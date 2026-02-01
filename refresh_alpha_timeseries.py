"""Refresh Alpha-spreadsrt.pkl with time series data for correlation analysis."""

from curves.refreshers.alpha import save_alpha_spreads_snapshot

if __name__ == "__main__":
    print("Regenerating Alpha-spreadsrt.pkl with time series...")
    path = save_alpha_spreads_snapshot()
    print(f"✓ Saved to: {path}")
