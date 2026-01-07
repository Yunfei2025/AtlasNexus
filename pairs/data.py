# -*- coding: utf-8 -*-
"""
Data Cache Module for Pair Analysis

This module handles data caching and loading functionality.
"""
import os
import pathlib
from functools import lru_cache
from typing import Optional
import pandas as pd


class DataCache:
    """Singleton class for managing data cache"""
    _instance = None
    _cache = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @lru_cache(maxsize=32)
    def get_cached_data(self, btype: str) -> Optional[pd.DataFrame]:
        """Cache data loading to avoid repeated file I/O operations"""
        # Get path relative to the generators folder
        current_path = pathlib.Path(__file__).parent.parent.parent
        file_path = os.path.join(current_path, 'input', f'{btype}-cvpx.pkl')
        
        if file_path in self._cache:
            print(f"Using cached data for {btype}")
            return self._cache[file_path]
        
        try:
            if not os.path.exists(file_path):
                print(f"File not found: {file_path}")
                return None
                
            data = pd.read_pickle(file_path)
             
            if 'ytm_act' in data:
                ytm_data = data['ytm_act']
                self._cache[file_path] = ytm_data
                return ytm_data
            else:
                self._cache[file_path] = data
                return data
                
        except Exception as e:
            print(f"❌ Error loading {btype} data: {e}")
            print(f"   File path: {file_path}")
            return None

    def clear_cache(self) -> None:
        """Clear the data cache"""
        self._cache.clear()
        self.get_cached_data.cache_clear()

    def cache_size(self) -> int:
        """Get current cache size"""
        return len(self._cache)