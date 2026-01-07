# -*- coding: utf-8 -*-
"""
Excel Integration Module for Pair Analysis

This module handles Excel reading and writing operations.
"""
from typing import Dict, Any
import xlwings as xw
from .stats import RegressionResults


class ExcelHandler:
    """Class for handling Excel operations"""
    
    @staticmethod
    def read_pair_config(sht_cfg: xw.Sheet) -> Dict[str, Dict[str, Any]]:
        """Load pair configurations from Excel sheet"""
        # Batch read configuration values
        config_range = sht_cfg.range('B20:E22')  # Extended to include window column
        config_values = config_range.value
        # import pdb; pdb.set_trace()
        if not config_values:
            raise ValueError("No configuration data found")
        
        pairs = {}
        for i in range(len(config_values[0])):
            leg1 = config_values[0][i] if config_values[0][i] else None
            leg2 = config_values[1][i] if config_values[1][i] else None
            window = int(config_values[2][i]) if config_values[2][i] else 30

            if leg1 and leg2:
                pair_name = f"pair{i+1}"
                pairs[pair_name] = {
                    'leg1': leg1,
                    'leg2': leg2,
                    'window': window
                }
        return pairs
    
    @staticmethod
    def write_pair_results(sht_out: xw.Sheet, pair_name: str, leg1: str, leg2: str,
                          regression_result: RegressionResults, start_row) -> int:
        """Write pair results to Excel sheet"""
        # Ensure start_row is an integer row index
        start_row = int(start_row)

        stats = regression_result.stats 
        # import pdb; pdb.set_trace()
        # Determine column based on pair name (pair1->A, pair2->B, pair3->C)
        pair_num = int(pair_name.replace('pair', '')) if 'pair' in pair_name else 1
        column_letters = ['A', 'B', 'C', 'D', 'E', 'F']  # Support up to 6 pairs
        # Map pair1->B, pair2->C, etc.; keep headers in column A
        # Guard against out-of-range pair indices
        if pair_num < 1:
            pair_num = 1
        if pair_num > len(column_letters) - 1:
            # Cap to last data column to avoid IndexError
            pair_num = len(column_letters) - 1
        data_column = column_letters[pair_num]
        
        # Write headers only once (in column A) - check if they already exist
        header_range = sht_out.range(f"A{start_row}")
        if not header_range.value:  # Only write headers if they don't exist
            header_labels = [
                # "Pair Name",
                # "Leg1",
                # "Leg2",
                "Observations",
                "Intercept",
                "Slope(per step)",
                "R-squared",
                # "Adj. R-squared", 
                # "StdErr(Intercept)",
                # "StdErr(Slope)",
                "Residual Std (±1σ)",
                # "t(Intercept)",
                # "t(Slope)",
                # "p(Intercept)",
                # "p(Slope)",
                "Durbin-Watson"
            ]
            # Bulk-write headers into column A in a single operation for speed
            header_values = [[lbl] for lbl in header_labels]
            end_row = start_row + len(header_labels) - 1
            sht_out.range(f"A{start_row}:A{end_row}").value = header_values
            # Optional: bold the header cells
            try:
                sht_out.range(f"A{start_row}:A{end_row}").api.Font.Bold = True
            except Exception:
                # Some environments may not expose .api or Font; ignore formatting errors
                pass
        
        # Prepare data values for this pair
        # Prepare data values for this pair (defensively access stats)
        n_obs = int(stats.get("n_obs", 0))
        intercept = stats.get("intercept", None)
        slope_per_step = stats.get("slope_per_step", None)
        r2 = stats.get("r2", None)
        residual_std = stats.get("residual_std", None)
        dw = stats.get("dw", None)

        pair_data = [
            # pair_name,
            # leg1,
            # leg2,
            n_obs,
            intercept,
            slope_per_step, 
            r2,
            # stats["adj_r2"],
            # stats["stderr_intercept"],
            # stats["stderr_slope"],
            residual_std,
            # stats["t_intercept"],
            # stats["t_slope"],
            # stats["p_intercept"],
            # stats["p_slope"],
            dw
        ]
        
        # Bulk-write data values into the designated column to avoid per-cell COM calls
        data_values = [[v] for v in pair_data]
        data_end_row = start_row + len(pair_data) - 1
        sht_out.range(f"{data_column}{start_row}:{data_column}{data_end_row}").value = data_values

        # Format numeric values precisely for the written range
        try:
            # Observations as integer
            sht_out.range(f"{data_column}{start_row}").number_format = "0"
            # The rest as decimals
            if data_end_row > start_row:
                sht_out.range(f"{data_column}{start_row + 1}:{data_column}{data_end_row}").number_format = "0.0000"
        except Exception:
            # Ignore formatting errors (e.g., due to merged cells or protected sheets)
            pass

        # Return the next start row (one past the last written row)
        return data_end_row + 1
        
