# -*- coding: utf-8 -*-
"""
Created on Thu Dec 11 19:08:28 2025

@author: CMBC
"""
import os
import sys
from pathlib import Path
import pandas as pd

# Add project path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from settings.paths import DIR_INPUT

file_path = os.path.join(DIR_INPUT, 'futures-dailyK_con.pkl')
data = pd.read_pickle(file_path)



