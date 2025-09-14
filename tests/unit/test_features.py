"""Unit tests for feature calculation module."""

import pytest
import numpy as np
from unittest.mock import Mock

from src.data.features import FeatureCalculator, FeatureResult
from src.utils.config import ScannerConfig


@pytest.mark.unit
class TestFeatureCalculator:
    """Test feature calculation functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.calculator = FeatureCalculator()
    
    def test_calculate_rvol_basic(self):
        """Test basic RVOL calculation."""
        # Test data: recent volume = 200, historical average = 100
        volumes = [100] * 20 + [200]  # 20 historical + 1 recent
        
        rvol = self.calculator.calculate_rvol(volumes, window=20)
        
        assert rvol == 2.0
    
    def test_calculate_rvol_insufficient_data(self):
        """Test RVOL calculation with insufficient data."""
        volumes = [100, 150]  # Only 2 data points
        
        rvol = self.calculator.calculate_rvol(volumes, window=20)
        
        assert rvol == 1.0  # Should return default value
    
    def test_calculate_rvol_zero_average(self):
        """Test RVOL calculation with zero average volume."""
        volumes = [0] * 20 + [100]  # Zero historical volumes
        
        rvol = self.calculator.calculate_rvol(volumes, window=20)
        
        assert rvol == 1.0  # Should return default value
    
    def test_calculate_returns(self):
        """Test return calculation."""
        prices = [100, 105, 110, 115, 120]  # 20% total return over 4 periods
        
        returns = self.calculator.calculate_returns(prices, periods=4)
        
        assert abs(returns - 0.20) < 0.001  # 20% return
    
    def test_calculate_relative_strength(self):
        """Test relative strength calculation."""
        # Symbol prices: 10% return
        symbol_prices = [100, 105, 110]
        # BTC prices: 5% return  
        btc_prices = [1000, 1025, 1050]
        
        rs = self.calculator.calculate_relative_strength(
            symbol_prices, btc_prices, window_minutes=10, candle_unit=5
        )
        
        # RS should be ~5% (10% - 5%)
        assert abs(rs - 0.05) < 0.01
    
    def test_calculate_session_vwap(self):
        """Test session VWAP calculation."""
        prices = np.array([100, 105, 110])
        volumes = np.array([10, 20, 30])
        
        # Expected VWAP = (100*10 + 105*20 + 110*30) / (10+20+30)
        expected_vwap = (1000 + 2100 + 3300) / 60  # = 106.67
        
        vwap = self.calculator.calculate_session_vwap(prices, volumes)
        
        assert abs(vwap - expected_vwap) < 0.01
    
    def test_calculate_ema(self):
        """Test EMA calculation."""
        prices = np.array([100, 102, 104, 106, 108])
        
        ema_values = self.calculator.calculate_ema(prices, period=3)
        
        # EMA should be increasing and last value should be close to recent prices
        assert len(ema_values) == len(prices)
        assert ema_values[-1] > ema_values[0]  # Trending up
        assert ema_values[-1] > 105  # Should be above middle values
    
    def test_calculate_atr(self):
        """Test ATR calculation."""
        highs = np.array([105, 107, 109, 111, 113])
        lows = np.array([95, 97, 99, 101, 103])
        closes = np.array([100, 102, 104, 106, 108])
        
        atr = self.calculator.calculate_atr(highs, lows, closes, period=3)
        
        # ATR should be positive and reasonable
        assert atr > 0
        assert atr < 20  # Should be reasonable given the range
    
    def test_calculate_trend(self):
        """Test trend calculation."""
        # Uptrend: EMA20 > EMA50, close > sVWAP
        prices = np.array([100, 102, 104, 106, 108, 110])  # Trending up
        volumes = np.array([100, 100, 100, 100, 100, 100])
        
        trend, ema20, ema50, svwap = self.calculator.calculate_trend(
            prices, volumes, ema_fast=2, ema_slow=3
        )
        
        # With uptrending prices, should detect uptrend
        assert trend in [0, 1]
        assert ema20 > 0
        assert ema50 > 0
        assert svwap > 0
    
    def test_normalize_rvol(self):
        """Test RVOL normalization."""
        # Test normal case
        rvol = 3.0
        normalized = self.calculator.normalize_rvol(rvol)
        assert normalized == 2.0  # (3.0 - 1.0) / 1.0 = 2.0
        
        # Test clipping
        rvol = 10.0
        normalized = self.calculator.normalize_rvol(rvol)
        assert normalized == 3.0  # Should be clipped to 3.0
        
        # Test negative (should be clipped to 0)
        rvol = 0.5
        normalized = self.calculator.normalize_rvol(rvol)
        assert normalized == 0.0
    
    def test_calculate_depth_score(self):
        """Test depth score calculation."""
        orderbook_data = {
            "orderbook_units": [
                {"bid_size": 10.0, "ask_size": 15.0},
                {"bid_size": 8.0, "ask_size": 12.0},
                {"bid_size": 6.0, "ask_size": 10.0}
            ]
        }
        
        depth_score = self.calculator.calculate_depth_score(orderbook_data)
        
        assert 0 <= depth_score <= 1.0
        assert depth_score > 0  # Should have some depth
    
    def test_calculate_spread_bp(self):
        """Test spread calculation in basis points."""
        orderbook_data = {
            "orderbook_units": [
                {"bid_price": 49950, "ask_price": 50050}  # 100 KRW spread on 50000
            ]
        }
        
        spread_bp = self.calculator.calculate_spread_bp(orderbook_data)
        
        # Spread = 100 / 50000 * 10000 = 20 bp
        assert abs(spread_bp - 20) < 1
    
    def test_calculate_score(self):
        """Test final score calculation."""
        rs = 0.02  # 2% relative strength
        rvol_z = 2.0  # 2.0 normalized RVOL
        trend = 1  # Uptrend
        depth_score = 0.5
        
        score = self.calculator.calculate_score(rs, rvol_z, trend, depth_score)
        
        # Score = 0.4*0.02 + 0.3*2.0 + 0.2*1 + 0.1*0.5 = 0.008 + 0.6 + 0.2 + 0.05 = 0.858
        expected_score = 0.4 * rs + 0.3 * rvol_z + 0.2 * trend + 0.1 * depth_score
        
        assert abs(score - expected_score) < 0.001
    
    def test_validate_features(self):
        """Test feature validation."""
        config = ScannerConfig()
        
        # Valid features
        valid_result = FeatureResult(
            rvol=2.5, rs=0.01, svwap=50000, atr_14=1000, ema_20=49500, ema_50=49000,
            trend=1, rvol_z=1.5, depth_score=0.7, final_score=0.75,
            price=50000, volume=150, spread_bp=3.0,
            market="KRW-BTC", timestamp="2024-01-01T10:00:00", data_points=200
        )
        
        is_valid, failed_criteria = self.calculator.validate_features(valid_result, config)
        
        assert is_valid
        assert len(failed_criteria) == 0
        
        # Invalid features (low RVOL)
        invalid_result = FeatureResult(
            rvol=1.0, rs=0.01, svwap=50000, atr_14=1000, ema_20=49500, ema_50=49000,
            trend=1, rvol_z=0.0, depth_score=0.7, final_score=0.4,
            price=50000, volume=150, spread_bp=3.0,
            market="KRW-BTC", timestamp="2024-01-01T10:00:00", data_points=200
        )
        
        is_valid, failed_criteria = self.calculator.validate_features(invalid_result, config)
        
        assert not is_valid
        assert len(failed_criteria) > 0
        assert any("RVOL" in criterion for criterion in failed_criteria)
