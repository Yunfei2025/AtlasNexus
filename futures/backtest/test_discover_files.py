"""Test script to verify discover_pkl_files() works correctly"""
import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from data_loader import discover_pkl_files

print("Testing discover_pkl_files()...")
print("-" * 60)

try:
    result = discover_pkl_files()
    
    if result:
        print(f"Found {len(result)} pickle file(s):")
        for item in result:
            print(f"  Label: {item['label']}")
            print(f"  Path:  {item['value']}")
            print(f"  Exists: {os.path.exists(item['value'])}")
            print()
    else:
        print("No pickle files found!")
        print("\nChecking directories...")
        
        script_dir = os.path.dirname(__file__)
        project_root = os.path.abspath(os.path.join(script_dir, '..', '..', '..'))
        
        print(f"Script dir: {script_dir}")
        print(f"Project root: {project_root}")
        print()
        
        dirs_to_check = [
            os.path.join(project_root, 'bin-v3.0', 'input'),
            os.path.join(project_root, 'bin-v3.0', 'data', 'futures'),
            os.path.join(project_root, 'bin-v3.0', 'web'),
        ]
        
        for d in dirs_to_check:
            exists = os.path.isdir(d)
            print(f"  {d}")
            print(f"    Exists: {exists}")
            if exists:
                files = [f for f in os.listdir(d) if f.endswith('.pkl')]
                print(f"    .pkl files: {files if files else 'None'}")
            print()

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

print("-" * 60)
