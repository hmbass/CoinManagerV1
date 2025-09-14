"""Liquidity Sweep Reversal Strategy Implementation.

This module implements the liquidity sweep reversal strategy as specified
in requirement.md FR-5: Entry Signal Engine.

Strategy Details:
- Swing Levels: Identify swing highs/lows (50-period basis)
- Penetration: Small breach (0.05×ATR) beyond swing levels
- Recovery: Return within 15 minutes
- Volume: 2× volume spike confirmation
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

from ..utils.config import SweepReversalConfig
from ..utils.logging import get_trading_logger, log_performance
from ..utils.time_utils import get_kst_now, to_kst
from ..data.features import FeatureCalculator


logger = get_trading_logger(__name__)


@dataclass
class SwingLevel:
    """Swing high/low level definition."""
    
    price: float
    timestamp: datetime
    level_type: str  # 'high' or 'low'
    strength: int    # Number of periods confirming the swing
    volume: float


@dataclass
class SweepEvent:
    """Liquidity sweep event."""
    
    swing_level: SwingLevel
    penetration_price: float
    penetration_distance: float
    penetration_time: datetime
    recovery_price: Optional[float] = None
    recovery_time: Optional[datetime] = None
    is_recovered: bool = False
    volume_ratio: float = 0.0


@dataclass
class SweepSignal:
    """Liquidity Sweep reversal trading signal."""
    
    signal_type: str  # 'long_sweep_reversal', 'short_sweep_reversal'
    market: str
    timestamp: datetime
    
    # Price levels
    entry_price: float
    stop_loss: float
    take_profit: float
    
    # Sweep context
    sweep_event: SweepEvent
    recovery_confirmation: bool
    volume_spike_confirmed: bool
    
    # Technical metrics
    penetration_ratio: float  # Distance relative to ATR
    time_to_recovery: float   # Minutes to recover
    
    # Risk metrics
    risk_amount: float
    reward_amount: float
    risk_reward_ratio: float
    
    # Confidence scoring
    confidence_score: float


class LiquiditySweepStrategy:
    """Liquidity Sweep reversal strategy implementation.
    
    Implements requirement.md FR-5 specification:
    - 스윙하이/로우 레벨 식별 (50봉 기준)
    - 소폭 관통(0.05×ATR) 후 15분 내 복귀 확인
    - 2배 거래량 급증 동반 시 진입
    """
    
    def __init__(self, config: Optional[SweepReversalConfig] = None):
        """Initialize Liquidity Sweep strategy.
        
        Args:
            config: Sweep reversal strategy configuration
        """
        if config is None:
            from ..utils.config import get_config
            config = get_config().signals.sweep_reversal
        
        self.config = config
        self.logger = logger
        self.feature_calculator = FeatureCalculator()
        
        # Track active sweep events
        self.active_sweeps: Dict[str, List[SweepEvent]] = {}
        
    def is_sweep_active_time(self, current_time: Optional[datetime] = None) -> bool:
        """Check if current time is within sweep strategy active period.
        
        Args:
            current_time: Current time (default: KST now)
            
        Returns:
            True if sweep strategy should be active
        """
        if not self.config.use:
            return False
        
        if current_time is None:
            current_time = get_kst_now()
        
        kst_time = to_kst(current_time).time()
        
        # Active during both trading sessions (more conservative than other strategies)
        morning_start, morning_end = (10, 30), (12, 30)  # Mid-session only
        evening_start, evening_end = (17, 30), (18, 30)  # Mid-session only
        
        morning_active = (
            kst_time >= datetime.min.time().replace(hour=morning_start[0], minute=morning_start[1]) and
            kst_time <= datetime.min.time().replace(hour=morning_end[0], minute=morning_end[1])
        )
        
        evening_active = (
            kst_time >= datetime.min.time().replace(hour=evening_start[0], minute=evening_start[1]) and
            kst_time <= datetime.min.time().replace(hour=evening_end[0], minute=evening_end[1])
        )
        
        return morning_active or evening_active
    
    @log_performance
    def identify_swing_levels(
        self,
        candle_data: List[Dict[str, Any]],
        lookback_periods: Optional[int] = None
    ) -> List[SwingLevel]:
        """Identify swing high and low levels.
        
        Args:
            candle_data: Candle data for analysis
            lookback_periods: Periods to analyze (default: config value)
            
        Returns:
            List of identified swing levels
        """
        if lookback_periods is None:
            lookback_periods = self.config.swing_lookback
        
        if len(candle_data) < lookback_periods:
            return []
        
        swing_levels = []
        
        # Analyze recent candles for swing points
        recent_candles = candle_data[-lookback_periods:]
        
        for i in range(5, len(recent_candles) - 5):  # Need buffer on both sides
            current_candle = recent_candles[i]
            high_price = float(current_candle['high_price'])
            low_price = float(current_candle['low_price'])
            volume = float(current_candle['candle_acc_trade_volume'])
            timestamp = pd.to_datetime(current_candle['candle_date_time_kst'])
            
            # Check for swing high
            is_swing_high = True
            for j in range(max(0, i-5), min(len(recent_candles), i+6)):
                if j != i and float(recent_candles[j]['high_price']) >= high_price:
                    is_swing_high = False
                    break
            
            if is_swing_high:
                strength = self._calculate_swing_strength(recent_candles, i, 'high')
                swing_levels.append(SwingLevel(
                    price=high_price,
                    timestamp=timestamp,
                    level_type='high',
                    strength=strength,
                    volume=volume
                ))
            
            # Check for swing low
            is_swing_low = True
            for j in range(max(0, i-5), min(len(recent_candles), i+6)):
                if j != i and float(recent_candles[j]['low_price']) <= low_price:
                    is_swing_low = False
                    break
            
            if is_swing_low:
                strength = self._calculate_swing_strength(recent_candles, i, 'low')
                swing_levels.append(SwingLevel(
                    price=low_price,
                    timestamp=timestamp,
                    level_type='low',
                    strength=strength,
                    volume=volume
                ))
        
        # Sort by timestamp and filter by strength
        swing_levels = sorted(swing_levels, key=lambda x: x.timestamp, reverse=True)
        
        # Keep only the strongest levels (top 50%)
        if swing_levels:
            strength_threshold = np.percentile([s.strength for s in swing_levels], 50)
            swing_levels = [s for s in swing_levels if s.strength >= strength_threshold]
        
        self.logger.debug(f"Identified {len(swing_levels)} swing levels")
        return swing_levels[:10]  # Keep most recent 10
    
    def _calculate_swing_strength(
        self,
        candles: List[Dict[str, Any]],
        center_idx: int,
        level_type: str
    ) -> int:
        """Calculate strength of swing level.
        
        Args:
            candles: Candle data
            center_idx: Index of potential swing point
            level_type: 'high' or 'low'
            
        Returns:
            Strength score (higher is stronger)
        """
        strength = 0
        center_price = float(candles[center_idx][f'{level_type}_price'])
        
        # Check how many periods on each side respect this level
        for distance in range(1, 6):  # Check up to 5 periods each side
            
            # Left side
            left_idx = center_idx - distance
            if left_idx >= 0:
                left_price = float(candles[left_idx][f'{level_type}_price'])
                if level_type == 'high' and left_price <= center_price:
                    strength += 1
                elif level_type == 'low' and left_price >= center_price:
                    strength += 1
            
            # Right side
            right_idx = center_idx + distance
            if right_idx < len(candles):
                right_price = float(candles[right_idx][f'{level_type}_price'])
                if level_type == 'high' and right_price <= center_price:
                    strength += 1
                elif level_type == 'low' and right_price >= center_price:
                    strength += 1
        
        return strength
    
    @log_performance
    def detect_sweep_events(
        self,
        market: str,
        swing_levels: List[SwingLevel],
        current_price: float,
        current_time: datetime,
        atr: float
    ) -> List[SweepEvent]:
        """Detect new liquidity sweep events.
        
        Args:
            market: Market symbol
            swing_levels: Identified swing levels
            current_price: Current market price
            current_time: Current timestamp
            atr: Average True Range
            
        Returns:
            List of new sweep events detected
        """
        new_sweeps = []
        penetration_threshold = self.config.penetration_atr_mult * atr
        
        for swing_level in swing_levels:
            # Check if this level was penetrated
            penetrated = False
            penetration_distance = 0.0
            
            if swing_level.level_type == 'high':
                # Check if price penetrated above swing high
                if current_price > swing_level.price + penetration_threshold:
                    penetrated = True
                    penetration_distance = current_price - swing_level.price
            
            elif swing_level.level_type == 'low':
                # Check if price penetrated below swing low
                if current_price < swing_level.price - penetration_threshold:
                    penetrated = True
                    penetration_distance = swing_level.price - current_price
            
            if penetrated:
                # Check if we already have an active sweep for this level
                existing_sweep = self._find_existing_sweep(market, swing_level, current_time)
                
                if not existing_sweep:
                    # Create new sweep event
                    sweep_event = SweepEvent(
                        swing_level=swing_level,
                        penetration_price=current_price,
                        penetration_distance=penetration_distance,
                        penetration_time=current_time
                    )
                    
                    new_sweeps.append(sweep_event)
                    
                    self.logger.info(
                        f"New sweep event detected: {swing_level.level_type} level at {swing_level.price}",
                        data={
                            "market": market,
                            "level_price": swing_level.price,
                            "penetration_price": current_price,
                            "distance": penetration_distance
                        }
                    )
        
        return new_sweeps
    
    def _find_existing_sweep(
        self,
        market: str,
        swing_level: SwingLevel,
        current_time: datetime
    ) -> Optional[SweepEvent]:
        """Find existing sweep event for the same level.
        
        Args:
            market: Market symbol
            swing_level: Swing level to check
            current_time: Current timestamp
            
        Returns:
            Existing sweep event or None
        """
        if market not in self.active_sweeps:
            return None
        
        # Look for sweep of same level within recent time
        time_threshold = timedelta(minutes=30)  # 30 minutes window
        
        for sweep in self.active_sweeps[market]:
            if (abs(sweep.swing_level.price - swing_level.price) < 0.01 and  # Same price level
                sweep.swing_level.level_type == swing_level.level_type and
                current_time - sweep.penetration_time <= time_threshold):
                return sweep
        
        return None
    
    @log_performance
    def update_sweep_events(
        self,
        market: str,
        current_price: float,
        current_time: datetime,
        current_volume: float,
        recent_volumes: List[float]
    ) -> List[SweepEvent]:
        """Update existing sweep events and check for recovery.
        
        Args:
            market: Market symbol
            current_price: Current market price
            current_time: Current timestamp
            current_volume: Current volume
            recent_volumes: Recent volume history
            
        Returns:
            List of sweep events ready for signal generation
        """
        if market not in self.active_sweeps:
            self.active_sweeps[market] = []
        
        ready_sweeps = []
        active_sweeps = self.active_sweeps[market]
        
        # Check each active sweep for recovery
        for sweep in active_sweeps[:]:  # Copy list to allow modification
            # Check if recovery time has expired
            time_since_penetration = (current_time - sweep.penetration_time).total_seconds() / 60
            
            if time_since_penetration > self.config.recovery_time_minutes:
                # Too much time passed, remove from active list
                active_sweeps.remove(sweep)
                continue
            
            # Check for recovery
            if not sweep.is_recovered:
                recovered = False
                
                if sweep.swing_level.level_type == 'high':
                    # Recovery: price back below the swing high
                    if current_price < sweep.swing_level.price:
                        recovered = True
                
                elif sweep.swing_level.level_type == 'low':
                    # Recovery: price back above the swing low
                    if current_price > sweep.swing_level.price:
                        recovered = True
                
                if recovered:
                    sweep.recovery_price = current_price
                    sweep.recovery_time = current_time
                    sweep.is_recovered = True
                    
                    # Calculate volume ratio
                    avg_volume = np.mean(recent_volumes) if recent_volumes else 1.0
                    sweep.volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
                    
                    self.logger.info(
                        f"Sweep recovery detected for {sweep.swing_level.level_type} level",
                        data={
                            "market": market,
                            "level_price": sweep.swing_level.price,
                            "recovery_price": current_price,
                            "time_to_recovery": time_since_penetration,
                            "volume_ratio": sweep.volume_ratio
                        }
                    )
                    
                    # Check if this sweep is ready for signal generation
                    if sweep.volume_ratio >= self.config.volume_spike_mult:
                        ready_sweeps.append(sweep)
                        active_sweeps.remove(sweep)  # Remove from active list
        
        return ready_sweeps
    
    def calculate_stop_and_target(
        self,
        entry_price: float,
        signal_type: str,
        sweep_event: SweepEvent,
        atr: float
    ) -> Tuple[float, float]:
        """Calculate stop loss and take profit levels.
        
        Args:
            entry_price: Entry price
            signal_type: Signal type
            sweep_event: Sweep event context
            atr: Average True Range
            
        Returns:
            Tuple of (stop_loss, take_profit)
        """
        if signal_type == "long_sweep_reversal":
            # Long after sweep of low: stop below sweep low
            stop_loss = sweep_event.swing_level.price - (0.5 * atr)
            target_distance = max(2.0 * atr, sweep_event.penetration_distance * 2)
            take_profit = entry_price + target_distance
            
        elif signal_type == "short_sweep_reversal":
            # Short after sweep of high: stop above sweep high
            stop_loss = sweep_event.swing_level.price + (0.5 * atr)
            target_distance = max(2.0 * atr, sweep_event.penetration_distance * 2)
            take_profit = entry_price - target_distance
            
        else:
            raise ValueError(f"Invalid signal type: {signal_type}")
        
        return stop_loss, take_profit
    
    def calculate_confidence_score(
        self,
        sweep_event: SweepEvent,
        time_to_recovery: float,
        volume_ratio: float,
        swing_strength: int
    ) -> float:
        """Calculate signal confidence score.
        
        Args:
            sweep_event: Sweep event
            time_to_recovery: Minutes to recovery
            volume_ratio: Volume spike ratio
            swing_strength: Strength of the swept level
            
        Returns:
            Confidence score (0.0 to 1.0)
        """
        score = 0.0
        
        # Recovery speed (0-0.3) - faster is better
        recovery_score = 0.3 * (1 - min(time_to_recovery / self.config.recovery_time_minutes, 1.0))
        score += recovery_score
        
        # Volume spike (0-0.3)
        volume_score = min(volume_ratio / 4.0, 0.3)  # Max at 4x volume
        score += volume_score
        
        # Swing level strength (0-0.2)
        strength_score = min(swing_strength / 10.0, 0.2)  # Max at strength 10
        score += strength_score
        
        # Penetration precision (0-0.2) - small penetration is better
        max_expected_penetration = 0.1  # 10% of price as max expected
        penetration_ratio = sweep_event.penetration_distance / sweep_event.swing_level.price
        penetration_score = 0.2 * (1 - min(penetration_ratio / max_expected_penetration, 1.0))
        score += penetration_score
        
        return min(score, 1.0)
    
    @log_performance
    def generate_signal(
        self,
        market: str,
        candle_data: List[Dict[str, Any]],
        current_price: float,
        current_volume: float,
        feature_result: Any  # FeatureResult from features module
    ) -> Optional[SweepSignal]:
        """Generate liquidity sweep reversal signal.
        
        Args:
            market: Market symbol
            candle_data: Historical candle data
            current_price: Current market price
            current_volume: Current volume
            feature_result: Calculated features (ATR, etc.)
            
        Returns:
            Sweep reversal signal or None if no signal
        """
        if not self.is_sweep_active_time():
            return None
        
        try:
            current_time = get_kst_now()
            
            # Identify swing levels
            swing_levels = self.identify_swing_levels(candle_data)
            
            if not swing_levels:
                return None
            
            # Detect new sweep events
            new_sweeps = self.detect_sweep_events(
                market, swing_levels, current_price, current_time, feature_result.atr_14
            )
            
            # Add new sweeps to active list
            if market not in self.active_sweeps:
                self.active_sweeps[market] = []
            
            self.active_sweeps[market].extend(new_sweeps)
            
            # Update existing sweeps and get ready ones
            recent_candles = candle_data[-10:]
            recent_volumes = [float(c['candle_acc_trade_volume']) for c in recent_candles]
            
            ready_sweeps = self.update_sweep_events(
                market, current_price, current_time, current_volume, recent_volumes
            )
            
            if not ready_sweeps:
                return None
            
            # Select best sweep event
            best_sweep = max(ready_sweeps, key=lambda s: s.volume_ratio)
            
            # Determine signal direction
            if best_sweep.swing_level.level_type == 'low':
                signal_type = "long_sweep_reversal"  # Buy after low was swept
            elif best_sweep.swing_level.level_type == 'high':
                signal_type = "short_sweep_reversal"  # Sell after high was swept
            else:
                return None
            
            # Calculate stop and target levels
            stop_loss, take_profit = self.calculate_stop_and_target(
                current_price, signal_type, best_sweep, feature_result.atr_14
            )
            
            # Calculate risk metrics
            if signal_type == "long_sweep_reversal":
                risk_amount = current_price - stop_loss
                reward_amount = take_profit - current_price
            else:  # short_sweep_reversal
                risk_amount = stop_loss - current_price
                reward_amount = current_price - take_profit
            
            risk_reward_ratio = reward_amount / risk_amount if risk_amount > 0 else 0
            
            # Calculate confidence score
            time_to_recovery = (best_sweep.recovery_time - best_sweep.penetration_time).total_seconds() / 60
            confidence_score = self.calculate_confidence_score(
                best_sweep, time_to_recovery, best_sweep.volume_ratio, best_sweep.swing_level.strength
            )
            
            # Create signal
            signal = SweepSignal(
                signal_type=signal_type,
                market=market,
                timestamp=current_time,
                entry_price=current_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                sweep_event=best_sweep,
                recovery_confirmation=best_sweep.is_recovered,
                volume_spike_confirmed=best_sweep.volume_ratio >= self.config.volume_spike_mult,
                penetration_ratio=best_sweep.penetration_distance / feature_result.atr_14,
                time_to_recovery=time_to_recovery,
                risk_amount=risk_amount,
                reward_amount=reward_amount,
                risk_reward_ratio=risk_reward_ratio,
                confidence_score=confidence_score
            )
            
            self.logger.info(
                f"Sweep reversal signal generated: {signal_type}",
                data={
                    "market": market,
                    "entry_price": current_price,
                    "swept_level": best_sweep.swing_level.price,
                    "recovery_time": time_to_recovery,
                    "volume_ratio": best_sweep.volume_ratio,
                    "confidence": confidence_score
                }
            )
            
            return signal
            
        except Exception as e:
            self.logger.error(f"Error generating sweep reversal signal for {market}: {e}")
            return None
    
    def validate_signal(self, signal: SweepSignal, min_confidence: float = 0.7) -> bool:
        """Validate signal quality before execution.
        
        Args:
            signal: Sweep reversal signal to validate
            min_confidence: Minimum confidence threshold (higher for this risky strategy)
            
        Returns:
            True if signal is valid for trading
        """
        if signal.confidence_score < min_confidence:
            self.logger.debug(f"Signal rejected: low confidence {signal.confidence_score}")
            return False
        
        if signal.risk_reward_ratio < 1.5:  # Higher R:R requirement for sweep strategy
            self.logger.debug(f"Signal rejected: poor R:R {signal.risk_reward_ratio}")
            return False
        
        if not signal.recovery_confirmation:
            self.logger.debug("Signal rejected: no recovery confirmation")
            return False
        
        if not signal.volume_spike_confirmed:
            self.logger.debug("Signal rejected: insufficient volume spike")
            return False
        
        # Time limit: only fresh recoveries
        if signal.time_to_recovery > self.config.recovery_time_minutes * 0.8:
            self.logger.debug("Signal rejected: recovery took too long")
            return False
        
        return True
    
    def cleanup_old_sweeps(self, market: str, max_age_hours: int = 2) -> None:
        """Clean up old sweep events.
        
        Args:
            market: Market symbol
            max_age_hours: Maximum age in hours
        """
        if market not in self.active_sweeps:
            return
        
        current_time = get_kst_now()
        cutoff_time = current_time - timedelta(hours=max_age_hours)
        
        self.active_sweeps[market] = [
            sweep for sweep in self.active_sweeps[market]
            if sweep.penetration_time > cutoff_time
        ]
