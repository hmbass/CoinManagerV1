"""sVWAP Pullback Strategy Implementation.

This module implements the session VWAP pullback strategy as specified
in requirement.md FR-5: Entry Signal Engine.

Strategy Details:
- Entry Condition: Price enters sVWAP ± 0.25×ATR zone
- Additional Condition: EMA20 > EMA50 alignment confirmed
- Pullback Range: 0.5~2% limitation
- Volume: Confirm with increased volume on bounce
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

from ..utils.config import SVWAPPullbackConfig
from ..utils.logging import get_trading_logger, log_performance
from ..utils.time_utils import get_kst_now, to_kst
from ..data.features import FeatureCalculator


logger = get_trading_logger(__name__)


@dataclass
class SVWAPZone:
    """sVWAP entry zone definition."""
    
    svwap_price: float
    upper_zone: float    # sVWAP + 0.25×ATR
    lower_zone: float    # sVWAP - 0.25×ATR
    atr: float
    zone_width: float


@dataclass
class PullbackContext:
    """Pullback analysis context."""
    
    recent_high: float
    recent_low: float
    pullback_percentage: float
    pullback_from_level: str  # 'high' or 'low'
    is_valid_pullback: bool
    trend_direction: str  # 'up' or 'down'


@dataclass
class SVWAPSignal:
    """sVWAP Pullback trading signal."""
    
    signal_type: str  # 'long_pullback', 'short_pullback'
    market: str
    timestamp: datetime
    
    # Price levels
    entry_price: float
    stop_loss: float
    take_profit: float
    
    # sVWAP context
    svwap_zone: SVWAPZone
    pullback_context: PullbackContext
    
    # Technical conditions
    ema_alignment: bool
    volume_confirmation: bool
    trend_strength: float
    
    # Risk metrics
    risk_amount: float
    reward_amount: float
    risk_reward_ratio: float
    
    # Confidence scoring
    confidence_score: float


class SVWAPPullbackStrategy:
    """sVWAP Pullback strategy implementation.
    
    Implements requirement.md FR-5 specification:
    - 진입조건: sVWAP ± 0.25×ATR 구간 진입 시
    - 추가조건: EMA20>EMA50 정렬 확인  
    - 되돌림 범위: 0.5~2% 이내 제한
    """
    
    def __init__(self, config: Optional[SVWAPPullbackConfig] = None):
        """Initialize sVWAP Pullback strategy.
        
        Args:
            config: sVWAP pullback strategy configuration
        """
        if config is None:
            from ..utils.config import get_config
            config = get_config().signals.svwap_pullback
        
        self.config = config
        self.logger = logger
        self.feature_calculator = FeatureCalculator()
        
    def is_svwap_active_time(self, current_time: Optional[datetime] = None) -> bool:
        """Check if current time is within sVWAP active period.
        
        Args:
            current_time: Current time (default: KST now)
            
        Returns:
            True if sVWAP strategy should be active
        """
        if not self.config.use:
            return False
        
        if current_time is None:
            current_time = get_kst_now()
        
        kst_time = to_kst(current_time).time()
        
        # Active during both trading sessions
        morning_start, morning_end = (9, 10), (13, 0)
        evening_start, evening_end = (17, 10), (19, 0)
        
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
    def calculate_svwap_zone(
        self,
        svwap_price: float,
        atr: float
    ) -> SVWAPZone:
        """Calculate sVWAP entry zone.
        
        Args:
            svwap_price: Session VWAP price
            atr: Average True Range
            
        Returns:
            sVWAP zone definition
        """
        zone_half_width = self.config.zone_atr_mult * atr
        
        upper_zone = svwap_price + zone_half_width
        lower_zone = svwap_price - zone_half_width
        zone_width = upper_zone - lower_zone
        
        return SVWAPZone(
            svwap_price=svwap_price,
            upper_zone=upper_zone,
            lower_zone=lower_zone,
            atr=atr,
            zone_width=zone_width
        )
    
    @log_performance
    def analyze_pullback(
        self,
        candle_data: List[Dict[str, Any]],
        current_price: float,
        lookback_periods: int = 20
    ) -> PullbackContext:
        """Analyze recent price pullback characteristics.
        
        Args:
            candle_data: Recent candle data
            current_price: Current market price
            lookback_periods: Periods to analyze for pullback
            
        Returns:
            Pullback analysis context
        """
        if len(candle_data) < lookback_periods:
            lookback_periods = len(candle_data)
        
        recent_candles = candle_data[-lookback_periods:]
        
        # Find recent high and low
        highs = [float(c['high_price']) for c in recent_candles]
        lows = [float(c['low_price']) for c in recent_candles]
        
        recent_high = max(highs)
        recent_low = min(lows)
        
        # Determine pullback direction and percentage
        high_pullback_pct = ((recent_high - current_price) / recent_high) * 100
        low_pullback_pct = ((current_price - recent_low) / recent_low) * 100
        
        # Determine primary pullback direction
        if high_pullback_pct > low_pullback_pct:
            pullback_from_level = "high"
            pullback_percentage = high_pullback_pct
            trend_direction = "down"  # Pullback from high suggests downtrend
        else:
            pullback_from_level = "low"
            pullback_percentage = low_pullback_pct
            trend_direction = "up"  # Pullback from low suggests uptrend
        
        # Validate pullback range (requirement.md: 0.5~2% 이내)
        is_valid_pullback = (
            self.config.min_pullback_pct <= pullback_percentage <= self.config.max_pullback_pct
        )
        
        return PullbackContext(
            recent_high=recent_high,
            recent_low=recent_low,
            pullback_percentage=pullback_percentage,
            pullback_from_level=pullback_from_level,
            is_valid_pullback=is_valid_pullback,
            trend_direction=trend_direction
        )
    
    def check_ema_alignment(
        self,
        ema_20: float,
        ema_50: float,
        trend_direction: str
    ) -> bool:
        """Check EMA alignment for trend confirmation.
        
        Args:
            ema_20: 20-period EMA
            ema_50: 50-period EMA  
            trend_direction: Expected trend direction
            
        Returns:
            True if EMA alignment confirms trend
        """
        if not self.config.require_ema_alignment:
            return True
        
        if trend_direction == "up":
            return ema_20 > ema_50
        elif trend_direction == "down":
            return ema_20 < ema_50
        else:
            return False
    
    def check_volume_confirmation(
        self,
        current_volume: float,
        recent_volumes: List[float],
        volume_multiplier: float = 1.2
    ) -> bool:
        """Check volume confirmation for pullback bounce.
        
        Args:
            current_volume: Current period volume
            recent_volumes: Recent volume history
            volume_multiplier: Minimum volume increase required
            
        Returns:
            True if volume confirms the pullback bounce
        """
        if not recent_volumes:
            return True  # No data to compare
        
        avg_volume = np.mean(recent_volumes)
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        return volume_ratio >= volume_multiplier
    
    def check_zone_entry(
        self,
        current_price: float,
        svwap_zone: SVWAPZone
    ) -> Tuple[bool, str]:
        """Check if price is entering sVWAP zone.
        
        Args:
            current_price: Current market price
            svwap_zone: sVWAP zone definition
            
        Returns:
            Tuple of (in_zone, position_relative_to_vwap)
        """
        in_zone = svwap_zone.lower_zone <= current_price <= svwap_zone.upper_zone
        
        if current_price > svwap_zone.svwap_price:
            position = "above_vwap"
        elif current_price < svwap_zone.svwap_price:
            position = "below_vwap"
        else:
            position = "at_vwap"
        
        return in_zone, position
    
    def calculate_stop_and_target(
        self,
        entry_price: float,
        signal_type: str,
        svwap_zone: SVWAPZone,
        pullback_context: PullbackContext
    ) -> Tuple[float, float]:
        """Calculate stop loss and take profit levels.
        
        Args:
            entry_price: Entry price
            signal_type: Signal type ('long_pullback' or 'short_pullback')
            svwap_zone: sVWAP zone
            pullback_context: Pullback context
            
        Returns:
            Tuple of (stop_loss, take_profit)
        """
        if signal_type == "long_pullback":
            # Long: stop below recent low, target above recent high
            stop_loss = pullback_context.recent_low - (0.5 * svwap_zone.atr)
            target_distance = pullback_context.recent_high - entry_price
            take_profit = entry_price + max(target_distance * 1.2, 2.0 * svwap_zone.atr)
            
        elif signal_type == "short_pullback":
            # Short: stop above recent high, target below recent low
            stop_loss = pullback_context.recent_high + (0.5 * svwap_zone.atr)
            target_distance = entry_price - pullback_context.recent_low
            take_profit = entry_price - max(target_distance * 1.2, 2.0 * svwap_zone.atr)
            
        else:
            raise ValueError(f"Invalid signal type: {signal_type}")
        
        return stop_loss, take_profit
    
    def calculate_confidence_score(
        self,
        pullback_context: PullbackContext,
        ema_alignment: bool,
        volume_confirmation: bool,
        zone_distance: float
    ) -> float:
        """Calculate signal confidence score.
        
        Args:
            pullback_context: Pullback analysis
            ema_alignment: EMA alignment status
            volume_confirmation: Volume confirmation status
            zone_distance: Distance from sVWAP center
            
        Returns:
            Confidence score (0.0 to 1.0)
        """
        score = 0.0
        
        # Pullback validity (0-0.3)
        if pullback_context.is_valid_pullback:
            pullback_score = 0.3 * (1 - abs(pullback_context.pullback_percentage - 1.0) / 1.5)
            score += max(pullback_score, 0.1)
        
        # EMA alignment (0-0.3)
        ema_score = 0.3 if ema_alignment else 0.1
        score += ema_score
        
        # Volume confirmation (0-0.2)
        volume_score = 0.2 if volume_confirmation else 0.05
        score += volume_score
        
        # Zone proximity (0-0.2) - closer to sVWAP is better
        zone_score = 0.2 * (1 - min(zone_distance, 1.0))
        score += zone_score
        
        return min(score, 1.0)
    
    @log_performance
    def generate_signal(
        self,
        market: str,
        candle_data: List[Dict[str, Any]],
        current_price: float,
        current_volume: float,
        feature_result: Any  # FeatureResult from features module
    ) -> Optional[SVWAPSignal]:
        """Generate sVWAP pullback trading signal.
        
        Args:
            market: Market symbol
            candle_data: Historical candle data
            current_price: Current market price
            current_volume: Current volume
            feature_result: Calculated features (sVWAP, EMA, ATR, etc.)
            
        Returns:
            sVWAP pullback signal or None if no signal
        """
        if not self.is_svwap_active_time():
            return None
        
        try:
            # Calculate sVWAP zone
            svwap_zone = self.calculate_svwap_zone(
                feature_result.svwap,
                feature_result.atr_14
            )
            
            # Check if price is in zone
            in_zone, vwap_position = self.check_zone_entry(current_price, svwap_zone)
            
            if not in_zone:
                return None
            
            # Analyze pullback characteristics
            pullback_context = self.analyze_pullback(candle_data, current_price)
            
            if not pullback_context.is_valid_pullback:
                self.logger.debug(
                    f"Invalid pullback: {pullback_context.pullback_percentage:.2f}% "
                    f"(range: {self.config.min_pullback_pct}-{self.config.max_pullback_pct}%)"
                )
                return None
            
            # Check EMA alignment
            ema_alignment = self.check_ema_alignment(
                feature_result.ema_20,
                feature_result.ema_50,
                pullback_context.trend_direction
            )
            
            if not ema_alignment and self.config.require_ema_alignment:
                self.logger.debug("EMA alignment check failed")
                return None
            
            # Check volume confirmation
            recent_candles = candle_data[-10:]
            recent_volumes = [float(c['candle_acc_trade_volume']) for c in recent_candles]
            volume_confirmation = self.check_volume_confirmation(
                current_volume, recent_volumes
            )
            
            # Determine signal direction
            if (pullback_context.trend_direction == "up" and 
                pullback_context.pullback_from_level == "low" and
                vwap_position in ["below_vwap", "at_vwap"]):
                signal_type = "long_pullback"
                
            elif (pullback_context.trend_direction == "down" and 
                  pullback_context.pullback_from_level == "high" and
                  vwap_position in ["above_vwap", "at_vwap"]):
                signal_type = "short_pullback"
                
            else:
                self.logger.debug(
                    f"No valid signal direction: trend={pullback_context.trend_direction}, "
                    f"pullback_from={pullback_context.pullback_from_level}, vwap_pos={vwap_position}"
                )
                return None
            
            # Calculate stop and target levels
            stop_loss, take_profit = self.calculate_stop_and_target(
                current_price, signal_type, svwap_zone, pullback_context
            )
            
            # Calculate risk metrics
            if signal_type == "long_pullback":
                risk_amount = current_price - stop_loss
                reward_amount = take_profit - current_price
            else:  # short_pullback
                risk_amount = stop_loss - current_price
                reward_amount = current_price - take_profit
            
            risk_reward_ratio = reward_amount / risk_amount if risk_amount > 0 else 0
            
            # Calculate confidence score
            zone_distance = abs(current_price - svwap_zone.svwap_price) / svwap_zone.zone_width
            confidence_score = self.calculate_confidence_score(
                pullback_context, ema_alignment, volume_confirmation, zone_distance
            )
            
            # Create signal
            signal = SVWAPSignal(
                signal_type=signal_type,
                market=market,
                timestamp=get_kst_now(),
                entry_price=current_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                svwap_zone=svwap_zone,
                pullback_context=pullback_context,
                ema_alignment=ema_alignment,
                volume_confirmation=volume_confirmation,
                trend_strength=abs(pullback_context.pullback_percentage) / 100,
                risk_amount=risk_amount,
                reward_amount=reward_amount,
                risk_reward_ratio=risk_reward_ratio,
                confidence_score=confidence_score
            )
            
            self.logger.info(
                f"sVWAP pullback signal generated: {signal_type}",
                data={
                    "market": market,
                    "entry_price": current_price,
                    "svwap": svwap_zone.svwap_price,
                    "pullback_pct": pullback_context.pullback_percentage,
                    "confidence": confidence_score
                }
            )
            
            return signal
            
        except Exception as e:
            self.logger.error(f"Error generating sVWAP pullback signal for {market}: {e}")
            return None
    
    def validate_signal(self, signal: SVWAPSignal, min_confidence: float = 0.5) -> bool:
        """Validate signal quality before execution.
        
        Args:
            signal: sVWAP pullback signal to validate
            min_confidence: Minimum confidence threshold
            
        Returns:
            True if signal is valid for trading
        """
        if signal.confidence_score < min_confidence:
            self.logger.debug(f"Signal rejected: low confidence {signal.confidence_score}")
            return False
        
        if signal.risk_reward_ratio < 1.0:
            self.logger.debug(f"Signal rejected: poor R:R {signal.risk_reward_ratio}")
            return False
        
        if not signal.pullback_context.is_valid_pullback:
            self.logger.debug("Signal rejected: invalid pullback range")
            return False
        
        if self.config.require_ema_alignment and not signal.ema_alignment:
            self.logger.debug("Signal rejected: EMA alignment required but not present")
            return False
        
        return True
