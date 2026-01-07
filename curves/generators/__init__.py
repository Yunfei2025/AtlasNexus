"""Curve generation task wrappers."""

from .rates import BondCurveGenerator
from .credit import CreditSpreadGenerator
from .irs import IRSGenerator
from .stat import StatGenerator
from .trend import TrendGenerator

__all__ = [
    'BondCurveGenerator',
    'CreditSpreadGenerator', 
    'IRSGenerator',
    'StatGenerator',
    'TrendGenerator'
]
