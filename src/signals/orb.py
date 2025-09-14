"""ORB (Opening Range Breakout) Strategy Implementation.

This module implements the Opening Range Breakout strategy as specified
in requirement.md FR-5: Entry Signal Engine.

Strategy Details:
- Opening Range: 09:00-10:00 KST (requirement.md)
- Breakout Condition: high + 0.1×ATR
- Volume Confirmation: ≥1.5× recent average volume
- Risk Management: ATR-based stop/target levels
"""

import numpy as np
import pandas as pd
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

from ..utils.config import ORBConfig
from ..utils.logging import get_trading_logger, log_performance
from ..utils.time_utils import get_kst_now, to_kst, parse_time_window, get_orb_window_times
from ..data.features import FeatureCalculator


logger = get_trading_logger(__name__)


@dataclass
class ORBBox:
    """Opening Range Box definition."""
    
    high: float
    low: float
    open_price: float
    close_price: float
    volume: float
    start_time: datetime
    end_time: datetime
    range_size: float
    box_center: float


@dataclass
class ORBSignal:
    """ORB trading signal."""
    
    signal_type: str  # 'long_breakout', 'short_breakdown'
    market: str
    timestamp: datetime
    
    # Price levels
    entry_price: float
    stop_loss: float
    take_profit: float
    
    # ORB context
    orb_box: ORBBox
    breakout_price: float
    volume_ratio: float
    atr: float
    
    # Risk metrics
    risk_amount: float
    reward_amount: float
    risk_reward_ratio: float
    
    # Confidence scoring
    confidence_score: float
    volume_confirmation: bool
    trend_alignment: bool


class ORBStrategy:
    """Opening Range Breakout strategy implementation.
    
    Implements requirement.md FR-5 specification:
    - 시초 60분(09:00–10:00) 박스 정의
    - 돌파 조건: high + 0.1×ATR 이상
    - 거래량 급증: 1.5× 이상 확인 후 진입
    """
    
    def __init__(self, config: Optional[ORBConfig] = None):
        """Initialize ORB strategy.
        
        Args:
            config: ORB strategy configuration
        """
        if config is None:
            from ..utils.config import get_config
            config = get_config().signals.orb
        
        self.config = config
        self.logger = logger
        self.feature_calculator = FeatureCalculator()
        
        # Parse box window
        self.box_start_time, self.box_end_time = parse_time_window(config.box_window)
        
    def is_orb_active_time(self, current_time: Optional[datetime] = None) -> bool:
        """Check if current time is within ORB active period.
        
        Args:
            current_time: Current time (default: KST now)
            
        Returns:
            True if ORB strategy should be active
        """
        if not self.config.use:
            return False
        
        if current_time is None:
            current_time = get_kst_now()
        
        kst_time = to_kst(current_time).time()
        
        # ORB is active after box formation (10:00) until end of session
        orb_start_time = time(10, 0)  # After box formation
        session_end_time = time(13, 0)  # End of morning session
        
        return orb_start_time <= kst_time <= session_end_time
    
    @log_performance
    def calculate_orb_box(
        self,
        candle_data: List[Dict[str, Any]],
        target_date: Optional[datetime] = None
    ) -> Optional[ORBBox]:
        """Calculate ORB box from candle data.
        
        Args:
            candle_data: Candle data (5-minute intervals)
            target_date: Target date for ORB calculation (default: today)
            
        Returns:
            ORB box or None if insufficient data
        """
        if target_date is None:
            target_date = get_kst_now().date()
        
        # Get ORB window times for target date
        box_start, box_end = get_orb_window_times(self.config.box_window)
        box_start = box_start.replace(
            year=target_date.year, 
            month=target_date.month, 
            day=target_date.day
        )
        box_end = box_end.replace(
            year=target_date.year,
            month=target_date.month, 
            day=target_date.day
        )
        
        # Filter candles within ORB window
        orb_candles = []
        for candle in candle_data:
            candle_time = pd.to_datetime(candle['candle_date_time_kst'])
            if candle_time.tz is None:
                candle_time = to_kst(candle_time)
            
            if box_start <= candle_time <= box_end:
                orb_candles.append(candle)
        
        if not orb_candles:
            self.logger.debug(f"No candles found in ORB window: {box_start} to {box_end}")
            return None
        
        # Calculate box metrics
        highs = [float(candle['high_price']) for candle in orb_candles]
        lows = [float(candle['low_price']) for candle in orb_candles]
        volumes = [float(candle['candle_acc_trade_volume']) for candle in orb_candles]
        
        orb_high = max(highs)
        orb_low = min(lows)
        orb_open = float(orb_candles[0]['opening_price'])
        orb_close = float(orb_candles[-1]['trade_price'])
        orb_volume = sum(volumes)
        
        range_size = orb_high - orb_low
        box_center = (orb_high + orb_low) / 2
        
        orb_box = ORBBox(
            high=orb_high,
            low=orb_low,
            open_price=orb_open,
            close_price=orb_close,
            volume=orb_volume,
            start_time=box_start,
            end_time=box_end,
            range_size=range_size,
            box_center=box_center
        )
        
        self.logger.debug(
            f"ORB box calculated",
            data={
                "high": orb_high,
                "low": orb_low,
                "range_size": range_size,
                "volume": orb_volume
            }
        )
        
        return orb_box
    
    @log_performance
    def check_breakout_conditions(
        self,
        current_price: float,
        current_volume: float,
        orb_box: ORBBox,
        atr: float,
        recent_volumes: List[float]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Check if breakout conditions are met.
        
        Args:
            current_price: Current market price
            current_volume: Current volume
            orb_box: ORB box definition
            atr: Average True Range
            recent_volumes: Recent volume history for comparison
            
        Returns:
            Tuple of (is_breakout, direction, context_data)
        """
        context = {
            "current_price": current_price,
            "orb_high": orb_box.high,
            "orb_low": orb_box.low,
            "atr": atr,
            "volume_ratio": 0.0
        }
        
        # Calculate breakout levels (requirement.md: high + 0.1×ATR)
        long_breakout_level = orb_box.high + (self.config.breakout_atr_mult * atr)
        short_breakdown_level = orb_box.low - (self.config.breakout_atr_mult * atr)
        
        context["long_breakout_level"] = long_breakout_level
        context["short_breakdown_level"] = short_breakdown_level
        
        # Check price breakout
        long_breakout = current_price >= long_breakout_level
        short_breakdown = current_price <= short_breakdown_level
        
        if not long_breakout and not short_breakdown:
            return False, "none", context
        
        # Volume confirmation (requirement.md: ≥1.5× recent average)
        if recent_volumes:
            avg_volume = np.mean(recent_volumes)
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
            context["volume_ratio"] = volume_ratio
            
            volume_confirmed = volume_ratio >= self.config.volume_spike_mult
        else:
            volume_confirmed = True  # No historical data, assume confirmed
            context["volume_ratio"] = 1.0
        
        if not volume_confirmed:
            self.logger.debug(
                f"Volume confirmation failed: {volume_ratio:.2f} < {self.config.volume_spike_mult}"
            )
            return False, "volume_insufficient", context
        
        # Determine direction
        if long_breakout:
            direction = "long"
        elif short_breakdown:
            direction = "short"
        else:
            direction = "none"
        
        self.logger.info(
            f"Breakout detected: {direction}",
            data={
                "price": current_price,
                "breakout_level": long_breakout_level if direction == "long" else short_breakdown_level,
                "volume_ratio": volume_ratio
            }
        )
        
        return True, direction, context
    
    def calculate_stop_and_target(
        self,
        entry_price: float,
        direction: str,
        orb_box: ORBBox,
        atr: float
    ) -> Tuple[float, float]:
        """Calculate stop loss and take profit levels.
        
        Args:
            entry_price: Entry price
            direction: Trade direction ('long' or 'short')
            orb_box: ORB box
            atr: Average True Range
            
        Returns:
            Tuple of (stop_loss, take_profit)
        """
        if direction == "long":
            # Long trade: stop below ORB low, target based on range
            stop_loss = orb_box.low - (0.5 * atr)  # Buffer below ORB low
            target_distance = max(orb_box.range_size, 1.5 * atr)  # At least 1.5R
            take_profit = entry_price + target_distance
            
        elif direction == "short":
            # Short trade: stop above ORB high, target based on range
            stop_loss = orb_box.high + (0.5 * atr)  # Buffer above ORB high
            target_distance = max(orb_box.range_size, 1.5 * atr)  # At least 1.5R
            take_profit = entry_price - target_distance
            
        else:
            raise ValueError(f"Invalid direction: {direction}")
        
        return stop_loss, take_profit
    
    def calculate_confidence_score(
        self,
        volume_ratio: float,
        range_size: float,
        atr: float,
        trend_aligned: bool
    ) -> float:
        """Calculate signal confidence score.
        
        Args:
            volume_ratio: Current volume vs average ratio
            range_size: ORB range size
            atr: Average True Range
            trend_aligned: Whether breakout aligns with trend
            
        Returns:
            Confidence score (0.0 to 1.0)
        """
        score = 0.0
        
        # Volume factor (0-0.4)
        volume_score = min(volume_ratio / 3.0, 0.4)  # Max at 3x volume
        score += volume_score
        
        # Range factor (0-0.3)
        range_score = min(range_size / (2 * atr), 0.3)  # Max at 2x ATR range
        score += range_score
        
        # Trend alignment (0-0.3)
        trend_score = 0.3 if trend_aligned else 0.1
        score += trend_score
        
        return min(score, 1.0)
    
    @log_performance
    def generate_signal(
        self,
        market: str,
        candle_data: List[Dict[str, Any]],
        current_price: float,
        current_volume: float,
        feature_result: Any  # FeatureResult from features module
    ) -> Optional[ORBSignal]:
        """Generate ORB trading signal.
        
        Args:
            market: Market symbol
            candle_data: Historical candle data
            current_price: Current market price
            current_volume: Current volume
            feature_result: Calculated features (trend, ATR, etc.)
            
        Returns:
            ORB signal or None if no signal
        """
        if not self.is_orb_active_time():
            return None
        
        try:
            # Calculate ORB box
            orb_box = self.calculate_orb_box(candle_data)
            if not orb_box:
                return None
            
            # Get recent volumes for comparison
            recent_candles = candle_data[-self.config.volume_lookback:]
            recent_volumes = [float(c['candle_acc_trade_volume']) for c in recent_candles]
            
            # Check breakout conditions
            is_breakout, direction, context = self.check_breakout_conditions(
                current_price, current_volume, orb_box, 
                feature_result.atr_14, recent_volumes
            )
            
            if not is_breakout or direction == "none":
                return None
            
            # Calculate stop and target levels
            stop_loss, take_profit = self.calculate_stop_and_target(
                current_price, direction, orb_box, feature_result.atr_14
            )
            
            # Calculate risk metrics
            if direction == "long":
                risk_amount = current_price - stop_loss
                reward_amount = take_profit - current_price
            else:  # short
                risk_amount = stop_loss - current_price
                reward_amount = current_price - take_profit
            
            risk_reward_ratio = reward_amount / risk_amount if risk_amount > 0 else 0
            
            # Calculate confidence score
            trend_aligned = (
                direction == "long" and feature_result.trend == 1
            ) or (
                direction == "short" and feature_result.trend == 0
            )
            
            confidence_score = self.calculate_confidence_score(
                context["volume_ratio"],
                orb_box.range_size,
                feature_result.atr_14,
                trend_aligned
            )
            
            # Create signal
            signal = ORBSignal(
                signal_type=f"{direction}_breakout",
                market=market,
                timestamp=get_kst_now(),
                entry_price=current_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                orb_box=orb_box,
                breakout_price=context.get("long_breakout_level" if direction == "long" else "short_breakdown_level", current_price),
                volume_ratio=context["volume_ratio"],
                atr=feature_result.atr_14,
                risk_amount=risk_amount,
                reward_amount=reward_amount,
                risk_reward_ratio=risk_reward_ratio,
                confidence_score=confidence_score,
                volume_confirmation=context["volume_ratio"] >= self.config.volume_spike_mult,
                trend_alignment=trend_aligned
            )
            
            self.logger.info(
                f"ORB signal generated: {signal.signal_type}",
                data={
                    "market": market,
                    "entry_price": current_price,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "risk_reward": risk_reward_ratio,
                    "confidence": confidence_score
                }
            )
            
            return signal
            
        except Exception as e:
            self.logger.error(f"Error generating ORB signal for {market}: {e}")
            return None
    
    def validate_signal(self, signal: ORBSignal, min_confidence: float = 0.6) -> bool:
        """Validate signal quality before execution.
        
        Args:
            signal: ORB signal to validate
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
        
        if not signal.volume_confirmation:
            self.logger.debug("Signal rejected: no volume confirmation")
            return False
        
        return True
