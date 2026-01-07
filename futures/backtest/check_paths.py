import os
import sys

script_dir = r'D:\PyProjects\FIEngine\bin-v3.0\futures\backtest'
project_root = os.path.abspath(os.path.join(script_dir, '..', '..', '..'))

print(f"project_root: {project_root}")
print()

dirs_to_check = [
    os.path.join(project_root, 'bin-v3.0', 'web'),
    os.path.join(project_root, 'bin-v3.0', 'input'),
    os.path.join(project_root, 'bin-v3.0', 'data', 'futures'),
]

for d in dirs_to_check:
    exists = os.path.isdir(d)
    print(f"{d}")
    print(f"  Exists: {exists}")
    if exists:
        pkl_files = [f for f in os.listdir(d) if f.endswith('.pkl')]
        print(f"  .pkl files: {pkl_files}")
    print()
