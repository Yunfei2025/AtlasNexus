# -*- coding: utf-8 -*-
"""Tenor string/numeric conversions for IRS curves."""

from typing import List, Union

from settings.general import GeneralConfig


class TenorConverter:
    """Handles tenor string/numeric conversions with caching."""

    def __init__(self):
        self._yn = GeneralConfig.YN
        self._cache_str2num = {}
        self._cache_num2str = {}

    def to_string(self, tenor_list: List[float]) -> List[str]:
        """Convert numeric tenors to string format (e.g., 7d, 3m, 1s)."""
        result = []
        for d in tenor_list:
            if d in self._cache_num2str:
                result.append(self._cache_num2str[d])
                continue

            if d * self._yn < 15:
                s = f"{int(round(d * self._yn))}d"
            elif d * self._yn < 90:
                s = f"{int(round(d * 12))}m"
            else:
                s = f"{int(round(d * 4))}s"

            self._cache_num2str[d] = s
            result.append(s)
        return result

    def to_numeric(self, tenor_str_list: List[Union[str, float, int]]) -> List[float]:
        """Convert string format to numeric tenors (inverse of to_string)."""
        result = []
        for s in tenor_str_list:
            if isinstance(s, (int, float)):
                result.append(s)
                continue

            if s in self._cache_str2num:
                result.append(self._cache_str2num[s])
                continue

            s = str(s).strip().lower()
            if s.endswith('d'):
                val = int(s[:-1]) / self._yn
            elif s.endswith('m'):
                val = int(s[:-1]) / 12.0
            elif s.endswith('s'):
                val = int(s[:-1]) / 4.0
            else:
                raise ValueError(f"Invalid tenor format: {s}")

            self._cache_str2num[s] = val
            result.append(val)
        return result


# Module-level singleton and legacy wrappers
_tenor_converter = TenorConverter()


def tenor2str(tenor_list):
    """Convert tenors to string format (legacy wrapper)."""
    return _tenor_converter.to_string(tenor_list)


def str2tenor(tenor_str_list):
    """Convert string format to tenors (legacy wrapper)."""
    return _tenor_converter.to_numeric(tenor_str_list)
