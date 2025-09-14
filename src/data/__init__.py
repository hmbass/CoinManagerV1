"""Data processing and feature calculation modules.

This package provides data processing utilities and feature calculation engines
for technical analysis and trading signal generation.
"""

from .features import FeatureCalculator
from .candles import CandleProcessor

__all__ = [
    "FeatureCalculator",
    "CandleProcessor",
]
