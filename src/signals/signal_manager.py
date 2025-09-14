"""Signal Manager for coordinating multiple trading strategies.

This module manages and coordinates signals from different trading strategies,
handles signal prioritization, filtering, and conflict resolution.
"""

from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from .orb import ORBStrategy, ORBSignal
from .svwap_pullback import SVWAPPullbackStrategy, SVWAPSignal
from .sweep import LiquiditySweepStrategy, SweepSignal
from ..utils.config import SignalsConfig
from ..utils.logging import get_trading_logger, log_performance
from ..utils.time_utils import get_kst_now


logger = get_trading_logger(__name__)

# Type alias for all signal types
TradingSignal = Union[ORBSignal, SVWAPSignal, SweepSignal]


class SignalPriority(Enum):
    """Signal priority levels."""
    HIGH = 1
    MEDIUM = 2
    LOW = 3


@dataclass
class SignalContext:
    """Context for signal evaluation."""
    
    signal: TradingSignal
    strategy_name: str
    priority: SignalPriority
    timestamp: datetime
    is_valid: bool
    conflict_score: float = 0.0


class SignalManager:
    """Manages multiple trading strategies and their signals.
    
    Responsibilities:
    - Coordinate multiple strategies
    - Handle signal conflicts
    - Apply signal filters
    - Prioritize signals
    - Track signal history
    """
    
    def __init__(self, config: Optional[SignalsConfig] = None):
        """Initialize signal manager.
        
        Args:
            config: Signals configuration
        """
        if config is None:
            from ..utils.config import get_config
            config = get_config().signals
        
        self.config = config
        self.logger = logger
        
        # Initialize strategies
        self.orb_strategy = ORBStrategy(config.orb) if config.orb.use else None
        self.svwap_strategy = SVWAPPullbackStrategy(config.svwap_pullback) if config.svwap_pullback.use else None
        self.sweep_strategy = LiquiditySweepStrategy(config.sweep_reversal) if config.sweep_reversal.use else None
        
        # Signal tracking
        self.recent_signals: Dict[str, List[SignalContext]] = {}  # market -> signals
        self.signal_history: Dict[str, List[SignalContext]] = {}  # market -> history
        
        # Strategy priorities (can be configured)
        self.strategy_priorities = {
            'orb': SignalPriority.HIGH,      # ORB has highest priority
            'svwap': SignalPriority.MEDIUM,  # sVWAP medium priority
            'sweep': SignalPriority.LOW      # Sweep lowest (most risky)
        }
    
    @log_performance
    def generate_signals(
        self,
        market: str,
        candle_data: List[Dict[str, Any]],
        current_price: float,
        current_volume: float,
        feature_result: Any
    ) -> List[SignalContext]:
        """Generate signals from all active strategies.
        
        Args:
            market: Market symbol
            candle_data: Historical candle data
            current_price: Current market price
            current_volume: Current volume
            feature_result: Calculated features
            
        Returns:
            List of signal contexts from all strategies
        """
        signals = []
        current_time = get_kst_now()
        
        # ORB Strategy
        if self.orb_strategy:
            try:
                orb_signal = self.orb_strategy.generate_signal(
                    market, candle_data, current_price, current_volume, feature_result
                )
                
                if orb_signal:
                    is_valid = self.orb_strategy.validate_signal(orb_signal)
                    signals.append(SignalContext(
                        signal=orb_signal,
                        strategy_name='orb',
                        priority=self.strategy_priorities['orb'],
                        timestamp=current_time,
                        is_valid=is_valid
                    ))
                    
                    self.logger.debug(f"ORB signal generated for {market}: valid={is_valid}")
                    
            except Exception as e:
                self.logger.error(f"Error generating ORB signal for {market}: {e}")
        
        # sVWAP Pullback Strategy
        if self.svwap_strategy:
            try:
                svwap_signal = self.svwap_strategy.generate_signal(
                    market, candle_data, current_price, current_volume, feature_result
                )
                
                if svwap_signal:
                    is_valid = self.svwap_strategy.validate_signal(svwap_signal)
                    signals.append(SignalContext(
                        signal=svwap_signal,
                        strategy_name='svwap',
                        priority=self.strategy_priorities['svwap'],
                        timestamp=current_time,
                        is_valid=is_valid
                    ))
                    
                    self.logger.debug(f"sVWAP signal generated for {market}: valid={is_valid}")
                    
            except Exception as e:
                self.logger.error(f"Error generating sVWAP signal for {market}: {e}")
        
        # Liquidity Sweep Strategy
        if self.sweep_strategy:
            try:
                sweep_signal = self.sweep_strategy.generate_signal(
                    market, candle_data, current_price, current_volume, feature_result
                )
                
                if sweep_signal:
                    is_valid = self.sweep_strategy.validate_signal(sweep_signal)
                    signals.append(SignalContext(
                        signal=sweep_signal,
                        strategy_name='sweep',
                        priority=self.strategy_priorities['sweep'],
                        timestamp=current_time,
                        is_valid=is_valid
                    ))
                    
                    self.logger.debug(f"Sweep signal generated for {market}: valid={is_valid}")
                    
            except Exception as e:
                self.logger.error(f"Error generating sweep signal for {market}: {e}")
        
        # Update recent signals
        if market not in self.recent_signals:
            self.recent_signals[market] = []
        
        self.recent_signals[market].extend(signals)
        self._cleanup_old_signals(market)
        
        self.logger.info(
            f"Generated {len(signals)} signals for {market}",
            data={
                "market": market,
                "total_signals": len(signals),
                "valid_signals": sum(1 for s in signals if s.is_valid),
                "strategies": [s.strategy_name for s in signals]
            }
        )
        
        return signals
    
    def _cleanup_old_signals(self, market: str, max_age_minutes: int = 60) -> None:
        """Remove old signals from recent signals list.
        
        Args:
            market: Market symbol
            max_age_minutes: Maximum age in minutes
        """
        if market not in self.recent_signals:
            return
        
        cutoff_time = get_kst_now() - timedelta(minutes=max_age_minutes)
        
        old_signals = [s for s in self.recent_signals[market] if s.timestamp < cutoff_time]
        
        # Move old signals to history
        if market not in self.signal_history:
            self.signal_history[market] = []
        
        self.signal_history[market].extend(old_signals)
        
        # Keep only recent signals
        self.recent_signals[market] = [
            s for s in self.recent_signals[market] 
            if s.timestamp >= cutoff_time
        ]
        
        # Limit history size
        if len(self.signal_history[market]) > 1000:
            self.signal_history[market] = self.signal_history[market][-1000:]
    
    def detect_signal_conflicts(self, signals: List[SignalContext]) -> Dict[str, List[SignalContext]]:
        """Detect conflicting signals.
        
        Args:
            signals: List of signal contexts
            
        Returns:
            Dict mapping conflict types to conflicting signals
        """
        conflicts = {
            'direction_conflict': [],
            'timing_conflict': [],
            'strategy_overlap': []
        }
        
        if len(signals) < 2:
            return conflicts
        
        for i, signal1 in enumerate(signals):
            for j, signal2 in enumerate(signals[i+1:], i+1):
                
                # Direction conflict: opposing directions
                dir1 = self._get_signal_direction(signal1.signal)
                dir2 = self._get_signal_direction(signal2.signal)
                
                if dir1 and dir2 and dir1 != dir2:
                    conflicts['direction_conflict'].extend([signal1, signal2])
                
                # Timing conflict: signals too close in time
                time_diff = abs((signal1.timestamp - signal2.timestamp).total_seconds())
                if time_diff < 300:  # 5 minutes
                    conflicts['timing_conflict'].extend([signal1, signal2])
                
                # Strategy overlap: similar entry conditions
                if self._signals_overlap(signal1.signal, signal2.signal):
                    conflicts['strategy_overlap'].extend([signal1, signal2])
        
        return conflicts
    
    def _get_signal_direction(self, signal: TradingSignal) -> Optional[str]:
        """Get signal direction (long/short).
        
        Args:
            signal: Trading signal
            
        Returns:
            Direction string or None
        """
        signal_type = signal.signal_type.lower()
        
        if 'long' in signal_type:
            return 'long'
        elif 'short' in signal_type:
            return 'short'
        else:
            return None
    
    def _signals_overlap(self, signal1: TradingSignal, signal2: TradingSignal) -> bool:
        """Check if two signals have overlapping entry conditions.
        
        Args:
            signal1: First signal
            signal2: Second signal
            
        Returns:
            True if signals overlap
        """
        # Check entry price proximity
        price_diff = abs(signal1.entry_price - signal2.entry_price)
        avg_price = (signal1.entry_price + signal2.entry_price) / 2
        price_diff_pct = (price_diff / avg_price) * 100
        
        return price_diff_pct < 1.0  # Less than 1% price difference
    
    @log_performance
    def resolve_conflicts(
        self, 
        signals: List[SignalContext],
        conflicts: Dict[str, List[SignalContext]]
    ) -> List[SignalContext]:
        """Resolve signal conflicts and return prioritized signals.
        
        Args:
            signals: Original signals
            conflicts: Detected conflicts
            
        Returns:
            Filtered and prioritized signals
        """
        if not conflicts['direction_conflict'] and not conflicts['strategy_overlap']:
            return self._prioritize_signals(signals)
        
        resolved_signals = []
        conflicted_signals = set()
        
        # Collect all conflicted signals
        for conflict_list in conflicts.values():
            conflicted_signals.update(conflict_list)
        
        # For conflicted signals, choose based on priority and confidence
        if conflicted_signals:
            # Group by priority
            priority_groups = {}
            for signal in conflicted_signals:
                if signal.priority not in priority_groups:
                    priority_groups[signal.priority] = []
                priority_groups[signal.priority].append(signal)
            
            # Select best from highest priority group
            highest_priority = min(priority_groups.keys(), key=lambda x: x.value)
            highest_priority_signals = priority_groups[highest_priority]
            
            # Among highest priority, choose by confidence
            best_signal = max(
                highest_priority_signals,
                key=lambda s: s.signal.confidence_score if hasattr(s.signal, 'confidence_score') else 0.0
            )
            
            if best_signal.is_valid:
                resolved_signals.append(best_signal)
            
            self.logger.info(
                f"Conflict resolved: selected {best_signal.strategy_name} signal",
                data={
                    "selected_strategy": best_signal.strategy_name,
                    "confidence": getattr(best_signal.signal, 'confidence_score', 0.0),
                    "conflicted_strategies": [s.strategy_name for s in conflicted_signals]
                }
            )
        
        # Add non-conflicted signals
        non_conflicted = [s for s in signals if s not in conflicted_signals]
        resolved_signals.extend(non_conflicted)
        
        return self._prioritize_signals(resolved_signals)
    
    def _prioritize_signals(self, signals: List[SignalContext]) -> List[SignalContext]:
        """Prioritize signals by priority and confidence.
        
        Args:
            signals: Signals to prioritize
            
        Returns:
            Prioritized signals
        """
        return sorted(
            signals,
            key=lambda s: (
                s.priority.value,  # Priority first (lower number = higher priority)
                -getattr(s.signal, 'confidence_score', 0.0),  # Then by confidence (higher is better)
                s.timestamp  # Finally by time (older first)
            )
        )
    
    def get_best_signal(
        self,
        market: str,
        candle_data: List[Dict[str, Any]],
        current_price: float,
        current_volume: float,
        feature_result: Any
    ) -> Optional[SignalContext]:
        """Get the best signal for a market.
        
        Args:
            market: Market symbol
            candle_data: Historical candle data
            current_price: Current market price
            current_volume: Current volume
            feature_result: Calculated features
            
        Returns:
            Best signal context or None
        """
        # Generate all signals
        signals = self.generate_signals(
            market, candle_data, current_price, current_volume, feature_result
        )
        
        if not signals:
            return None
        
        # Filter only valid signals
        valid_signals = [s for s in signals if s.is_valid]
        
        if not valid_signals:
            self.logger.debug(f"No valid signals found for {market}")
            return None
        
        # Detect conflicts
        conflicts = self.detect_signal_conflicts(valid_signals)
        
        # Resolve conflicts and prioritize
        resolved_signals = self.resolve_conflicts(valid_signals, conflicts)
        
        if not resolved_signals:
            return None
        
        best_signal = resolved_signals[0]
        
        self.logger.info(
            f"Best signal selected for {market}: {best_signal.strategy_name}",
            data={
                "market": market,
                "strategy": best_signal.strategy_name,
                "signal_type": best_signal.signal.signal_type,
                "confidence": getattr(best_signal.signal, 'confidence_score', 0.0),
                "entry_price": best_signal.signal.entry_price
            }
        )
        
        return best_signal
    
    def get_signal_statistics(self, market: Optional[str] = None) -> Dict[str, Any]:
        """Get signal generation statistics.
        
        Args:
            market: Specific market or None for all markets
            
        Returns:
            Statistics dictionary
        """
        stats = {
            'total_signals': 0,
            'valid_signals': 0,
            'by_strategy': {},
            'by_market': {},
            'recent_signals': 0
        }
        
        markets_to_check = [market] if market else self.signal_history.keys()
        
        for mkt in markets_to_check:
            if mkt in self.signal_history:
                market_signals = self.signal_history[mkt]
                stats['total_signals'] += len(market_signals)
                stats['valid_signals'] += sum(1 for s in market_signals if s.is_valid)
                
                # By strategy
                for signal in market_signals:
                    strategy = signal.strategy_name
                    if strategy not in stats['by_strategy']:
                        stats['by_strategy'][strategy] = {'total': 0, 'valid': 0}
                    
                    stats['by_strategy'][strategy]['total'] += 1
                    if signal.is_valid:
                        stats['by_strategy'][strategy]['valid'] += 1
                
                # By market
                stats['by_market'][mkt] = {
                    'total': len(market_signals),
                    'valid': sum(1 for s in market_signals if s.is_valid)
                }
            
            # Recent signals
            if mkt in self.recent_signals:
                stats['recent_signals'] += len(self.recent_signals[mkt])
        
        return stats
    
    def cleanup_sweep_data(self, market: str) -> None:
        """Cleanup sweep strategy data for a market.
        
        Args:
            market: Market symbol
        """
        if self.sweep_strategy:
            self.sweep_strategy.cleanup_old_sweeps(market)
