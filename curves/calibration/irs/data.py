# -*- coding: utf-8 -*-
"""IRS curve data loading, caching, and persistence."""

import os
from datetime import date
from typing import Dict, List

import pandas as pd

from settings.fixed_income import IRSConfig
from settings.paths import DIR_INPUT
from curves.utils.file import updatePKL


class CurveDataManager:
    """Manages IRS curve data loading, caching, and persistence."""

    def __init__(self, data_path: str = None):
        self.data_path = data_path or os.path.join(DIR_INPUT, 'IRS-cvdata.pkl')
        self._curve_data = None
        self._last_load_time = None
        self._did_migrate_legacy_tenors = False

    def _migrate_legacy_tenors(self) -> bool:
        """Backfill legacy tenor columns (e.g., '3m') into current ones (e.g., '1s')."""
        if self._curve_data is None:
            return False

        legacy_to_current = {
            '3m': '1s',
            '6m': '2s',
            '9m': '3s',
            '1y': '4s'
        }

        changed = False
        for curve_type in IRSConfig.CURVE_TYPES:
            for kind in ['spot', 'forward']:
                df = self._curve_data.get(curve_type, {}).get(kind)
                if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                    continue

                for legacy, current in legacy_to_current.items():
                    if legacy not in df.columns:
                        continue

                    if current not in df.columns:
                        df[current] = df[legacy]
                        changed = True
                    else:
                        before_na = df[current].isna().sum()
                        df[current] = df[current].where(~df[current].isna(), df[legacy])
                        after_na = df[current].isna().sum()
                        if after_na != before_na:
                            changed = True

        return changed

    def load(self, force_reload: bool = False) -> Dict:
        """Load curve data from pickle file with caching."""
        if self._curve_data is None or force_reload:
            if os.path.exists(self.data_path):
                self._curve_data = pd.read_pickle(self.data_path)
                if not self._did_migrate_legacy_tenors:
                    if self._migrate_legacy_tenors():
                        print("Migrated legacy tenors in IRS-cvdata (e.g., 3m -> 1s).")
                        self.save()
                    self._did_migrate_legacy_tenors = True
            else:
                self._curve_data = {
                    ct: {'spot': pd.DataFrame(), 'forward': pd.DataFrame()}
                    for ct in IRSConfig.CURVE_TYPES
                }
        return self._curve_data

    def save(self) -> Dict:
        """Save curve data to pickle file."""
        if self._curve_data is not None:
            self._curve_data = updatePKL(self._curve_data, self.data_path)
        return self._curve_data

    def update_curve(self, curve_type: str, date: date, spot_values: pd.Series,
                     forward_values: pd.Series, tenor_labels: List[str]):
        """Update curve data for a specific date and curve type."""
        if self._curve_data is None:
            self.load()

        self._curve_data[curve_type]['spot'].loc[date, tenor_labels] = spot_values
        self._curve_data[curve_type]['forward'].loc[date, tenor_labels] = forward_values

    def has_date(self, curve_type: str, target_date: date) -> bool:
        """Check if curve data exists for a given date."""
        if self._curve_data is None:
            self.load()
        return target_date in self._curve_data[curve_type]['spot'].index

    def get_curve(self, curve_type: str, date: date, curve_kind: str = 'spot') -> pd.Series:
        """Get curve data for a specific date."""
        if self._curve_data is None:
            self.load()
        return self._curve_data[curve_type][curve_kind].loc[date]
