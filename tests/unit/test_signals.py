"""Unit tests for trading signals module."""

import pytest
from datetime import datetime, time
from unittest.mock import Mock, patch

from src.signals.orb import ORBStrategy, ORBBox
from src.signals.svwap_pullback import SVWAPPullbackStrategy
from src.signals.signal_manager import SignalManager
from src.utils.config import ORBConfig, SVWAPPullbackConfig
from src.data.features import FeatureResult


@pytest.mark.unit
class TestORBStrategy:
    """Test ORB (Opening Range Breakout) strategy."""
    
    def setup_method(self):
        """Set up test fixtures."""
        config = ORBConfig(
            use=True,
            box_window="09:00-10:00",
            breakout_atr_mult=0.1,
            volume_spike_mult=1.5,
            volume_lookback=20
        )
        self.strategy = ORBStrategy(config)
    
    @patch('src.signals.orb.get_kst_now')
    def test_is_orb_active_time(self, mock_now):
        """Test ORB active time detection."""
        # Test during active hours (10:30 AM)
        mock_now.return_value = datetime(2024, 1, 1, 10, 30)
        assert self.strategy.is_orb_active_time()
        
        # Test outside active hours (8:00 AM)
        mock_now.return_value = datetime(2024, 1, 1, 8, 0)
        assert not self.strategy.is_orb_active_time()
        
        # Test outside active hours (14:00 PM)
        mock_now.return_value = datetime(2024, 1, 1, 14, 0)
        assert not self.strategy.is_orb_active_time()
    
    def test_calculate_orb_box(self, sample_candles):
        """Test ORB box calculation."""
        # Filter candles to ORB window
        orb_candles = sample_candles[20:32]  # Simulate 1-hour window
        
        orb_box = self.strategy.calculate_orb_box(orb_candles)
        
        assert orb_box is not None
        assert orb_box.high > orb_box.low
        assert orb_box.range_size == orb_box.high - orb_box.low
        assert orb_box.box_center == (orb_box.high + orb_box.low) / 2
    
    def test_check_breakout_conditions(self):
        """Test breakout condition checking."""
        orb_box = ORBBox(
            high=50000, low=49000, open_price=49500, close_price=49800,
            volume=1000, start_time=datetime.now(), end_time=datetime.now(),
            range_size=1000, box_center=49500
        )
        
        # Test long breakout
        is_breakout, direction, context = self.strategy.check_breakout_conditions(
            current_price=50100,  # Above high + ATR
            current_volume=150,
            orb_box=orb_box,
            atr=1000,
            recent_volumes=[100] * 20  # Average volume = 100
        )
        
        assert is_breakout
        assert direction == "long"
        assert context["volume_ratio"] == 1.5  # 150/100 = 1.5
    
    def test_calculate_stop_and_target(self):
        """Test stop loss and take profit calculation."""
        orb_box = ORBBox(
            high=50000, low=49000, open_price=49500, close_price=49800,
            volume=1000, start_time=datetime.now(), end_time=datetime.now(),
            range_size=1000, box_center=49500
        )
        
        stop_loss, take_profit = self.strategy.calculate_stop_and_target(
            entry_price=50100,
            direction="long",
            orb_box=orb_box,
            atr=1000
        )
        
        assert stop_loss < 50100  # Stop should be below entry
        assert take_profit > 50100  # Target should be above entry
        assert take_profit - 50100 > 50100 - stop_loss  # Positive R:R
    
    def test_validate_signal(self):
        """Test signal validation."""
        from src.signals.orb import ORBSignal
        from datetime import datetime
        
        valid_signal = ORBSignal(
            signal_type="long_breakout",
            market="KRW-BTC",
            timestamp=datetime.now(),
            entry_price=50100,
            stop_loss=49500,
            take_profit=51600,
            orb_box=Mock(),
            breakout_price=50000,
            volume_ratio=2.0,
            atr=1000,
            risk_amount=600,
            reward_amount=1500,
            risk_reward_ratio=2.5,
            confidence_score=0.8,
            volume_confirmation=True,
            trend_alignment=True
        )
        
        assert self.strategy.validate_signal(valid_signal)
        
        # Invalid signal (low confidence)
        invalid_signal = valid_signal
        invalid_signal.confidence_score = 0.3
        
        assert not self.strategy.validate_signal(invalid_signal)


@pytest.mark.unit
class TestSVWAPPullbackStrategy:
    """Test sVWAP Pullback strategy."""
    
    def setup_method(self):
        """Set up test fixtures."""
        config = SVWAPPullbackConfig(
            use=True,
            zone_atr_mult=0.25,
            require_ema_alignment=True,
            min_pullback_pct=0.5,
            max_pullback_pct=2.0
        )
        self.strategy = SVWAPPullbackStrategy(config)
    
    def test_calculate_svwap_zone(self):
        """Test sVWAP zone calculation."""
        svwap_zone = self.strategy.calculate_svwap_zone(
            svwap_price=50000,
            atr=1000
        )
        
        assert svwap_zone.svwap_price == 50000
        assert svwap_zone.upper_zone == 50250  # 50000 + 0.25*1000
        assert svwap_zone.lower_zone == 49750  # 50000 - 0.25*1000
        assert svwap_zone.zone_width == 500
    
    def test_analyze_pullback(self, sample_candles):
        """Test pullback analysis."""
        pullback_context = self.strategy.analyze_pullback(
            sample_candles, current_price=49800, lookback_periods=20
        )
        
        assert pullback_context.recent_high > 0
        assert pullback_context.recent_low > 0
        assert pullback_context.pullback_percentage >= 0
        assert pullback_context.pullback_from_level in ["high", "low"]
        assert pullback_context.trend_direction in ["up", "down"]
    
    def test_check_ema_alignment(self):
        """Test EMA alignment checking."""
        # Test uptrend alignment
        assert self.strategy.check_ema_alignment(
            ema_20=50000, ema_50=49500, trend_direction="up"
        )
        
        # Test downtrend alignment
        assert self.strategy.check_ema_alignment(
            ema_20=49500, ema_50=50000, trend_direction="down"
        )
        
        # Test misalignment
        assert not self.strategy.check_ema_alignment(
            ema_20=49500, ema_50=50000, trend_direction="up"
        )
    
    def test_check_zone_entry(self):
        """Test zone entry checking."""
        from src.signals.svwap_pullback import SVWAPZone
        
        zone = SVWAPZone(
            svwap_price=50000,
            upper_zone=50250,
            lower_zone=49750,
            atr=1000,
            zone_width=500
        )
        
        # Test price in zone above VWAP
        in_zone, position = self.strategy.check_zone_entry(50100, zone)
        assert in_zone
        assert position == "above_vwap"
        
        # Test price outside zone
        in_zone, position = self.strategy.check_zone_entry(51000, zone)
        assert not in_zone


@pytest.mark.unit
class TestSignalManager:
    """Test signal manager functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Create mock config
        from src.utils.config import SignalsConfig, ORBConfig, SVWAPPullbackConfig, SweepReversalConfig
        
        signals_config = SignalsConfig(
            orb=ORBConfig(use=True),
            svwap_pullback=SVWAPPullbackConfig(use=True),
            sweep_reversal=SweepReversalConfig(use=False)
        )
        
        self.signal_manager = SignalManager(signals_config)
    
    def test_signal_priorities(self):
        """Test signal priority system."""
        from src.signals.signal_manager import SignalPriority
        
        assert self.signal_manager.strategy_priorities['orb'] == SignalPriority.HIGH
        assert self.signal_manager.strategy_priorities['svwap'] == SignalPriority.MEDIUM
        assert self.signal_manager.strategy_priorities['sweep'] == SignalPriority.LOW
    
    def test_detect_signal_conflicts(self):
        """Test signal conflict detection."""
        from src.signals.signal_manager import SignalContext, SignalPriority
        from src.signals.orb import ORBSignal
        from datetime import datetime
        
        # Create conflicting signals (opposite directions)
        long_signal = ORBSignal(
            signal_type="long_breakout", market="KRW-BTC", timestamp=datetime.now(),
            entry_price=50000, stop_loss=49500, take_profit=51000,
            orb_box=Mock(), breakout_price=50000, volume_ratio=2.0, atr=1000,
            risk_amount=500, reward_amount=1000, risk_reward_ratio=2.0,
            confidence_score=0.8, volume_confirmation=True, trend_alignment=True
        )
        
        short_signal = ORBSignal(
            signal_type="short_breakout", market="KRW-BTC", timestamp=datetime.now(),
            entry_price=49000, stop_loss=49500, take_profit=48000,
            orb_box=Mock(), breakout_price=49000, volume_ratio=2.0, atr=1000,
            risk_amount=500, reward_amount=1000, risk_reward_ratio=2.0,
            confidence_score=0.7, volume_confirmation=True, trend_alignment=True
        )
        
        signals = [
            SignalContext(long_signal, "orb", SignalPriority.HIGH, datetime.now(), True),
            SignalContext(short_signal, "orb", SignalPriority.HIGH, datetime.now(), True)
        ]
        
        conflicts = self.signal_manager.detect_signal_conflicts(signals)
        
        assert len(conflicts['direction_conflict']) > 0
    
    def test_resolve_conflicts(self):
        """Test conflict resolution."""
        from src.signals.signal_manager import SignalContext, SignalPriority
        from src.signals.orb import ORBSignal
        from datetime import datetime
        
        # High priority signal
        high_priority_signal = ORBSignal(
            signal_type="long_breakout", market="KRW-BTC", timestamp=datetime.now(),
            entry_price=50000, stop_loss=49500, take_profit=51000,
            orb_box=Mock(), breakout_price=50000, volume_ratio=2.0, atr=1000,
            risk_amount=500, reward_amount=1000, risk_reward_ratio=2.0,
            confidence_score=0.8, volume_confirmation=True, trend_alignment=True
        )
        
        # Low priority signal
        low_priority_signal = ORBSignal(
            signal_type="short_breakout", market="KRW-BTC", timestamp=datetime.now(),
            entry_price=49000, stop_loss=49500, take_profit=48000,
            orb_box=Mock(), breakout_price=49000, volume_ratio=2.0, atr=1000,
            risk_amount=500, reward_amount=1000, risk_reward_ratio=2.0,
            confidence_score=0.9, volume_confirmation=True, trend_alignment=True
        )
        
        signals = [
            SignalContext(high_priority_signal, "orb", SignalPriority.HIGH, datetime.now(), True),
            SignalContext(low_priority_signal, "svwap", SignalPriority.MEDIUM, datetime.now(), True)
        ]
        
        conflicts = {"direction_conflict": signals}
        resolved = self.signal_manager.resolve_conflicts(signals, conflicts)
        
        # Should select high priority signal
        assert len(resolved) == 1
        assert resolved[0].priority == SignalPriority.HIGH
