# -*- coding: utf-8 -*-
"""
Quick Excel file checker
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from api.excel_utils import diagnose_dashboard_issues

if __name__ == "__main__":
    diagnose_dashboard_issues() 