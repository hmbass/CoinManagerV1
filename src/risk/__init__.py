"""Risk management modules.

This package provides comprehensive risk management functionality
including position sizing, daily drawdown limits, and consecutive
loss prevention.
"""

from .guard import RiskGuard

__all__ = ["RiskGuard"]
