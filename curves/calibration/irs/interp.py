# -*- coding: utf-8 -*-
"""Interpolation and extrapolation utilities for IRS curves."""

import numpy as np
from scipy import interpolate


class Interpolator:
    """Handles interpolation and extrapolation with robust error handling."""

    @staticmethod
    def interpolate_with_extrapolation(x_known: np.ndarray, y_known: np.ndarray,
                                       x_target: np.ndarray) -> np.ndarray:
        """
        Interpolate with linear extrapolation beyond bounds.

        Parameters:
        -----------
        x_known : array-like
            Known x values (must be sorted)
        y_known : array-like
            Known y values corresponding to x_known
        x_target : array-like
            Target x values to interpolate/extrapolate

        Returns:
        --------
        ndarray : Interpolated/extrapolated y values
        """
        x_known = np.asarray(x_known)
        y_known = np.asarray(y_known)
        x_target = np.asarray(x_target)

        valid_mask = ~np.isnan(y_known)
        if not np.any(valid_mask):
            return np.full_like(x_target, np.nan, dtype=float)

        x_valid = x_known[valid_mask]
        y_valid = y_known[valid_mask]

        if len(x_valid) == 0:
            return np.full_like(x_target, np.nan, dtype=float)
        elif len(x_valid) == 1:
            return np.full_like(x_target, y_valid[0], dtype=float)

        interpolator = interpolate.interp1d(x_valid, y_valid, kind='linear',
                                            bounds_error=False, fill_value=np.nan)
        result = interpolator(x_target)

        min_x, max_x = x_valid.min(), x_valid.max()

        below_mask = x_target < min_x
        if np.any(below_mask):
            slope = (y_valid[1] - y_valid[0]) / (x_valid[1] - x_valid[0])
            result[below_mask] = y_valid[0] + slope * (x_target[below_mask] - x_valid[0])

        above_mask = x_target > max_x
        if np.any(above_mask):
            slope = (y_valid[-1] - y_valid[-2]) / (x_valid[-1] - x_valid[-2])
            result[above_mask] = y_valid[-1] + slope * (x_target[above_mask] - x_valid[-1])

        return result


def interpolate_with_extrapolation(x_known, y_known, x_target):
    """Interpolate with extrapolation (legacy wrapper)."""
    return Interpolator.interpolate_with_extrapolation(x_known, y_known, x_target)


def filter_terms_by_range(terms, workdays, index_range, allow_extrapolation=False):
    """Filter terms and corresponding workdays to only include values within index range."""
    if allow_extrapolation:
        return terms, workdays

    min_term, max_term = index_range.min(), index_range.max()
    valid_mask = [(min_term <= t <= max_term) for t in terms]
    valid_terms = [t for t, valid in zip(terms, valid_mask) if valid]
    valid_workdays = [wd for wd, valid in zip(workdays, valid_mask) if valid]
    return valid_terms, valid_workdays
