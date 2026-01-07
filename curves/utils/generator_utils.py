#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utility functions for curve generation.

This module contains helper functions for importing dependencies,
creating mock generators, and managing parallel execution.
"""

import datetime
import pathlib
import sys
import threading
import importlib.util
from typing import Dict, Any, Callable, Iterable


def get_project_root() -> pathlib.Path:
    """Get the project root directory."""
    return pathlib.Path(__file__).parent.parent.parent

def get_mtime_date(path_obj: pathlib.Path):
    """Get modification date of a file, return None if file doesn't exist."""
    try:
        p = pathlib.Path(path_obj)
        return datetime.datetime.fromtimestamp(p.stat().st_mtime).date()
    except FileNotFoundError:
        return None


def run_parallel_direct(job_functions: Iterable[Callable]):
    """Run multiple direct function calls in parallel using threads.
    
    Args:
        job_functions: iterable of callable functions
    """
    if not job_functions:
        return
    
    threads = []
    for func in job_functions:
        thread = threading.Thread(target=func)
        thread.start()
        threads.append(thread)
    
    for thread in threads:
        thread.join()


def create_mock_generator(class_name: str):
    """Create a mock generator class for testing purposes."""
    
    class MockGenerator:
        def __init__(self, *args, **kwargs):
            print(f"MockGenerator for {class_name} initialized")
            
        def run(self):
            print(f"MockGenerator {class_name}.run() called")
            
        @classmethod
        def main(cls, *args, **kwargs):
            print(f"MockGenerator {class_name}.main() called with args={args}, kwargs={kwargs}")
            instance = cls()
            instance.run()
    
    MockGenerator.__name__ = class_name
    return MockGenerator


def import_dependencies() -> Dict[str, Any]:
    """Import required dependencies with fallbacks for missing modules."""
    project_root = get_project_root()

    dependencies = {}

    # Import BondConfig (direct import; let ImportError propagate if package not set up)
    from ..settings.fixed_income import BondConfig
    dependencies['BondConfig'] = BondConfig

    # Try to import generator classes
    generator_modules = {
        'TrendGenerator': 'trend',
        'BondCurveGenerator': 'rates',
        'CreditSpreadGenerator': 'credit',
        'IRSGenerator': 'irs',
        'StatGenerator': 'stat'
    }
    generators_dir = project_root / "curves" / "generators"
    for class_name, module_name in generator_modules.items():
        try:
            module_path = generators_dir / f"{module_name}.py"
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[f"_temp_{module_name}"] = module
            spec.loader.exec_module(module)
            # Try to get the main generator class
            if hasattr(module, class_name):
                dependencies[class_name] = getattr(module, class_name)
            elif hasattr(module, 'main'):
                # If only main function exists, wrap it in a mock class
                dependencies[class_name] = create_mock_generator(class_name)
            else:
                dependencies[class_name] = create_mock_generator(class_name)
        except Exception as e:
            dependencies[class_name] = create_mock_generator(class_name)

    # Add DATA_PATH for summary (optional)
    from settings.paths import DIR_DATA
    dependencies['DATA_PATH'] = DIR_DATA

    # Add DataRetriever (optional)
    from .retrieve import retrieveCNBDTS
    dependencies['rd'] = retrieveCNBDTS

    return dependencies


def print_configuration_summary(deps: Dict[str, Any]) -> None:
    """Print a summary of the loaded configuration."""
    print("\n📋 Configuration Summary:")
    print(f"  • DATA_PATH: {deps['DATA_PATH']}")
    print(f"  • BondConfig: {'✅ Available' if deps['BondConfig'] else '❌ Not available'}")
    print(f"  • DataRetriever: {'✅ Available' if deps['rd'] else '❌ Not available'}")
    
    print("\n🔧 Generator Status:")
    for gen_name in ['TrendGenerator', 'BondCurveGenerator', 'CreditSpreadGenerator', 'IRSGenerator', 'StatGenerator']:
        if deps[gen_name]:
            is_mock = hasattr(deps[gen_name], '__name__') and 'Mock' in str(deps[gen_name])
            status = "🟡 Mock" if is_mock else "✅ Real"
            print(f"  • {gen_name}: {status}")
        else:
            print(f"  • {gen_name}: ❌ Not available")