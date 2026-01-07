# -*- coding: utf-8 -*-
"""
Storage module for Multi-Asset Dashboard.

Handles saving and loading of asset pools and configuration.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

# Define paths
# bin/multiasset/storage.py -> bin/multiasset -> bin -> MultiAsset
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]

INPUT_DIR = PROJECT_ROOT / 'input'
HISTORY_DIR = INPUT_DIR / 'asset_pool_history'
LAST_POOL_FILE = INPUT_DIR / 'asset_pool_last.json'


def ensure_directories():
    """Ensure input directories exist."""
    if not INPUT_DIR.exists():
        INPUT_DIR.mkdir(parents=True)
    if not HISTORY_DIR.exists():
        HISTORY_DIR.mkdir(parents=True)


def save_asset_pool(asset_pool: List[Dict[str, Any]], metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Save the current asset pool to a JSON file.
    Saves to both 'asset_pool_last.json' and a timestamped history file.
    
    Args:
        asset_pool: List of asset dictionaries (from asset-pool-store)
        metadata: Optional dictionary with additional info (e.g. weights, settings)
        
    Returns:
        Path to the history file created
    """
    ensure_directories()
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    data = {
        'timestamp': timestamp,
        'asset_pool': asset_pool,
        'metadata': metadata or {}
    }
    
    # Save to history
    history_filename = f"pool_{timestamp}.json"
    history_path = HISTORY_DIR / history_filename
    try:
        with open(history_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving history file: {e}")
        
    # Save as last run
    try:
        with open(LAST_POOL_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving last pool file: {e}")
        
    return str(history_path)


def load_last_asset_pool() -> Optional[Dict[str, Any]]:
    """
    Load the last saved asset pool.
    
    Returns:
        Dictionary containing 'asset_pool' and 'metadata', or None if no file exists.
    """
    if not LAST_POOL_FILE.exists():
        return None
        
    try:
        with open(LAST_POOL_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading last asset pool: {e}")
        return None


def list_history_files() -> List[str]:
    """List all available history files, sorted by newest first."""
    if not HISTORY_DIR.exists():
        return []
    
    files = [f.name for f in HISTORY_DIR.glob('*.json')]
    files.sort(reverse=True)
    return files
