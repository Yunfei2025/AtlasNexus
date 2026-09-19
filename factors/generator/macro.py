"""
Macro factors calculator.

This module contains the macro factors calculator class.
"""

import pandas as pd
import os

from settings.paths import DIR_INPUT
class MacroFactors:
    """
    Macro factor generator: loads macro-px.pkl and creates level and pct_change features.
    """
    def __init__(self):
        self.macro_path = os.path.join(DIR_INPUT, 'macro-px.pkl')
        self.macro_df = self._load_macro()

    def _load_macro(self):
        with open(self.macro_path, 'rb') as f:
            macro_df = pd.read_pickle(f)
        macro_df = pd.concat(macro_df, axis=1).droplevel(0, axis=1)
        macro_df.columns = [i.split(".")[0] for i in macro_df.columns]
        # The source pickle stores its index as plain datetime.date objects,
        # while every other series in the factor pipeline (factor-rates.pkl,
        # curve data, etc.) uses pandas Timestamp / DatetimeIndex. Building a
        # DataFrame from a dict of Series with mismatched index *types* does
        # not align matching calendar dates at all — pandas treats every date
        # as distinct on both sides, unions them, and every macro column ends
        # up NaN wherever the non-macro series has data (and vice versa).
        # With ~48/52 macro/factor row split that silently pushed every macro
        # feature's NaN rate to ~52%, above build_features()'s 50% drop
        # threshold, so all 66 macro-derived features (level + pct_change)
        # were discarded before the model ever saw them. Normalising to a
        # DatetimeIndex here fixes it for every caller in one place.
        macro_df.index = pd.to_datetime(macro_df.index)
        print(f"✅ Loaded macro data with {macro_df.shape[1]} variables and {len(macro_df)} observations")
        return macro_df

    def calculate_all(self) -> pd.DataFrame:
        """
        Generate macro factor features: level and pct_change.
        Returns:
            pd.DataFrame: Macro factor features (level and pct_change)
        """
        macro_df = self.macro_df.copy()
        if macro_df.empty:
            return macro_df
        
        # Generate pct_change features
        pct_df = macro_df.pct_change().add_suffix('_pct')
        # Concatenate level and pct_change features
        all_macro = pd.concat([macro_df, pct_df], axis=1)
        print(f"✅ Generated {all_macro.shape[1]} macro factors ({macro_df.shape[1]} level + {pct_df.shape[1]} pct_change)")
        return all_macro

    def get_macro_factors(self) -> pd.DataFrame:
        """
        Alias for calculate_all().
        """
        return self.calculate_all()