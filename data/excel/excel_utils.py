# -*- coding: utf-8 -*-
"""
Excel utilities for diagnosing and fixing xlwings issues
"""
import os
import xlwings as xw
import pandas as pd
from pathlib import Path

def check_excel_file(file_path: str) -> dict:
    """
    Check Excel file structure and return diagnostic information
    
    Args:
        file_path: Path to Excel file
        
    Returns:
        dict with diagnostic information
    """
    result = {
        'file_exists': False,
        'file_size': 0,
        'is_locked': False,
        'sheets': [],
        'can_open': False,
        'error': None
    }
    
    try:
        # Check if file exists
        if not os.path.exists(file_path):
            result['error'] = f"File not found: {file_path}"
            return result
            
        result['file_exists'] = True
        result['file_size'] = os.path.getsize(file_path)
        
        # Check if file is locked (open in Excel)
        lock_file = str(Path(file_path).parent / f"~${Path(file_path).name}")
        if os.path.exists(lock_file):
            result['is_locked'] = True
            result['error'] = "File is currently open in Excel"
            return result
        
        # Try to open with xlwings
        try:
            with xw.App(visible=False, add_book=False) as app:
                wb = app.books.open(file_path)
                result['can_open'] = True
                result['sheets'] = [sheet.name for sheet in wb.sheets]
                wb.close()
        except Exception as e:
            result['error'] = f"Could not open file with xlwings: {e}"
            
    except Exception as e:
        result['error'] = f"Unexpected error: {e}"
    
    return result

def create_bonddata_sheet(file_path: str) -> bool:
    """
    Create BondData sheet in Excel file if it doesn't exist
    
    Args:
        file_path: Path to Excel file
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        with xw.App(visible=False, add_book=False) as app:
            wb = app.books.open(file_path)
            
            # Check if BondData sheet exists
            sheet_names = [sheet.name for sheet in wb.sheets]
            if 'BondData' not in sheet_names:
                wb.sheets.add('BondData')
                wb.save()
                print("Created 'BondData' sheet successfully")
                return True
            else:
                print("'BondData' sheet already exists")
                return True
                
    except Exception as e:
        print(f"Error creating BondData sheet: {e}")
        return False

def backup_excel_file(file_path: str) -> str:
    """
    Create a backup of the Excel file
    
    Args:
        file_path: Path to Excel file
        
    Returns:
        str: Path to backup file
    """
    try:
        import shutil
        from datetime import datetime
        
        backup_path = file_path.replace('.xlsm', f'_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsm')
        shutil.copy2(file_path, backup_path)
        print(f"Backup created: {backup_path}")
        return backup_path
    except Exception as e:
        print(f"Error creating backup: {e}")
        return ""

def diagnose_dashboard_issues():
    """
    Run comprehensive diagnostics on Dashboard.xlsm
    """
    dashboard_path = Path(__file__).parent.parent.parent / 'Dashboard.xlsm'
    
    print("=== Dashboard.xlsm Diagnostics ===")
    print(f"File path: {dashboard_path}")
    
    # Check file status
    status = check_excel_file(str(dashboard_path))
    
    for key, value in status.items():
        print(f"{key}: {value}")
    
    if status['error']:
        print(f"\nIssue detected: {status['error']}")
        
        if status['is_locked']:
            print("\nSolution: Close the Dashboard.xlsm file in Excel and try again.")
        elif not status['file_exists']:
            print("\nSolution: Ensure Dashboard.xlsm exists in the project root directory.")
        elif not status['can_open']:
            print("\nSolution: The file may be corrupted. Try creating a backup and replacing the file.")
            backup_path = backup_excel_file(str(dashboard_path))
            if backup_path:
                print(f"Backup created at: {backup_path}")
    else:
        print("\nFile appears to be healthy!")
        
        if 'BondData' not in status['sheets']:
            print("\n'BondData' sheet not found. Attempting to create it...")
            if create_bonddata_sheet(str(dashboard_path)):
                print("Successfully created 'BondData' sheet!")
            else:
                print("Failed to create 'BondData' sheet.")

if __name__ == "__main__":
    diagnose_dashboard_issues() 