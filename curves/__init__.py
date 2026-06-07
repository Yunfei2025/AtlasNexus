# -*- coding: utf-8 -*-
"""
Created on Fri Feb  3 10:56:55 2023

@author: 马云飞
"""

from __future__ import annotations

import pathlib
import sys

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
_PROJECT_ROOT_STR = str(_PROJECT_ROOT)

if sys.path[:1] != [_PROJECT_ROOT_STR]:
	sys.path = [_PROJECT_ROOT_STR] + [entry for entry in sys.path if entry != _PROJECT_ROOT_STR]

_UTILS_MODULE = sys.modules.get("utils")
if _UTILS_MODULE is not None:
	_UTILS_PATH = str(getattr(_UTILS_MODULE, "__file__", "") or "").replace("\\", "/")
	if "/curves/utils/" in _UTILS_PATH:
		sys.modules.pop("utils", None)

