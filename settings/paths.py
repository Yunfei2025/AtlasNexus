#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Path and directory configuration used across the project.
"""
from pathlib import Path
import sys

# Base path is the project root (bin-new)
PATH = Path(__file__).parent.parent

# Ensure PATH is importable if needed by legacy code
if str(PATH) not in sys.path:
    sys.path.insert(0, str(PATH))

# Data/input/output directories (relative to project root)
DIR_INPUT = PATH.joinpath(r'../input').resolve()
DIR_OUTPUT = PATH.joinpath(r'../output').resolve()
DIR_DATA = PATH.joinpath(r'../database').resolve()
DIR_MODELS = DIR_INPUT / 'models'  # trained model artefacts (.joblib)
DIR_MODELS.mkdir(parents=True, exist_ok=True)