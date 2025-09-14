"""Feature calculation engine for trading system.

This module implements all technical indicators and features as specified
in requirement.md Section 6: Algorithm Details.

Features implemented:
- RVOL: rv = vol[-1] / mean(vol[-21:-1])
- RS(60m): rs = ret60(sym) − ret60(KRW-BTC)  
- sVWAP: cumsum(price*volume)/cumsum(volume)
- ATR(14): Standard TR-based 14-period simple moving average
- Trend: (EMA20>EMA50) and (close > sVWAP) → {0,1}
- Score: 0.4*RS + 0.3*RVOL_Z + 0.2*Trend + 0.1*Depth
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass

from ..utils.config import ScannerConfig
from ..utils.logging import get_trading_logger, log_performance
from ..utils.time_utils import get_kst_now, get_session_vwap_start


logger = get_trading_logger(__name__)


@dataclass
class FeatureResult:
    """Container for calculated features."""
    
    # Core features (requirement.md)
    rvol: float
    rs: float
    svwap: float
    atr_14: float
    ema_20: float
    ema_50: float
    trend: int  # {0, 1}
    
    # Score components
    rvol_z: float
    depth_score: float
    final_score: float
    
    # Additional metrics
    price: float
    volume: float
    spread_bp: float
    
    # Metadata
    market: str
    timestamp: str
    data_points: int


class FeatureCalculator:
    """Technical feature calculation engine.
    
    Implements all features according to requirement.md specifications
    with NumPy vectorization for optimal performance.
    """
    
    def __init__(self, config: Optional[ScannerConfig] = None):
        """Initialize feature calculator.
        
        Args:
            config: Scanner configuration (uses default if None)
        """
        if config is None:
            from ..utils.config import get_config
            config = get_config().scanner
        
        self.config = config
        self.logger = logger
    
    @log_performance
    def calculate_rvol(self, volumes: Union[pd.Series, np.ndarray], window: int = 20) -> float:
        """Calculate RVOL (Relative Volume).
        
        Formula: rv = vol[-1] / mean(vol[-21:-1])
        requirement.md: "최근 5분 거래량 ÷ 과거 5분 평균 거래량(최근 20개)"
        
        Args:
            volumes: Volume series
            window: Lookback window for average (default: 20)
            
        Returns:
            RVOL value
        """
        if isinstance(volumes, pd.Series):
            volumes = volumes.values
        
        if len(volumes) < window + 1:
            self.logger.debug(f"Insufficient data for RVOL calculation: {len(volumes)} < {window + 1}")
            return 1.0  # Default value when insufficient data
        
        # Get most recent volume
        recent_volume = volumes[-1]
        
        # Get historical volumes (excluding most recent)
        historical_volumes = volumes[-(window+1):-1]
        
        # Calculate average of historical volumes
        avg_volume = np.mean(historical_volumes)
        
        # Avoid division by zero
        if avg_volume <= 0:
            return 1.0
        
        rvol = recent_volume / avg_volume
        
        # Sanity check
        if not np.isfinite(rvol) or rvol < 0:
            return 1.0
        
        return float(rvol)
    
    @log_performance
    def calculate_returns(self, prices: Union[pd.Series, np.ndarray], periods: int = 12) -> float:
        """Calculate returns over specified periods.
        
        Args:
            prices: Price series
            periods: Number of periods for return calculation
            
        Returns:
            Return as decimal (e.g., 0.05 for 5%)
        """
        if isinstance(prices, pd.Series):
            prices = prices.values
        
        if len(prices) < periods + 1:
            return 0.0
        
        start_price = prices[-(periods+1)]
        end_price = prices[-1]
        
        if start_price <= 0:
            return 0.0
        
        return (end_price - start_price) / start_price
    
    @log_performance
    def calculate_relative_strength(
        self,
        symbol_prices: Union[pd.Series, np.ndarray],
        btc_prices: Union[pd.Series, np.ndarray],
        window_minutes: int = 60,
        candle_unit: int = 5
    ) -> float:
        """Calculate Relative Strength vs BTC.
        
        Formula: rs = ret60(sym) − ret60(KRW-BTC)
        requirement.md: "종목의 최근 60분 수익률 − KRW-BTC의 최근 60분 수익률"
        
        Args:
            symbol_prices: Symbol price series
            btc_prices: BTC price series
            window_minutes: Window in minutes (default: 60)
            candle_unit: Candle unit in minutes (default: 5)
            
        Returns:
            Relative strength as decimal
        """
        # Calculate number of periods for the window
        periods = window_minutes // candle_unit
        
        # Calculate returns for both assets
        symbol_return = self.calculate_returns(symbol_prices, periods)
        btc_return = self.calculate_returns(btc_prices, periods)
        
        # Relative strength is the difference
        rs = symbol_return - btc_return
        
        return float(rs)
    
    @log_performance
    def calculate_session_vwap(
        self,
        prices: Union[pd.Series, np.ndarray],
        volumes: Union[pd.Series, np.ndarray],
        timestamps: Optional[Union[pd.Series, np.ndarray]] = None
    ) -> float:
        """Calculate session VWAP from start of day.
        
        Formula: vwap_t = cumsum(price*volume)/cumsum(volume)
        requirement.md: "당일 00:00(KST) 이후 누적 거래량 가중 평균가"
        
        Args:
            prices: Price series
            volumes: Volume series  
            timestamps: Timestamp series (optional, uses all data if None)
            
        Returns:
            Session VWAP value
        """
        if isinstance(prices, pd.Series):
            prices = prices.values
        if isinstance(volumes, pd.Series):
            volumes = volumes.values
        
        if len(prices) != len(volumes):
            raise ValueError("Price and volume series must have same length")
        
        if len(prices) == 0:
            return 0.0
        
        # If timestamps provided, filter to session start
        if timestamps is not None:
            # This is a simplified implementation
            # In production, filter by session start time
            pass
        
        # Calculate VWAP using all available data
        price_volume = prices * volumes
        total_pv = np.sum(price_volume)
        total_volume = np.sum(volumes)
        
        if total_volume <= 0:
            return prices[-1] if len(prices) > 0 else 0.0
        
        vwap = total_pv / total_volume
        
        return float(vwap)
    
    @log_performance
    def calculate_ema(self, prices: Union[pd.Series, np.ndarray], period: int) -> np.ndarray:
        """Calculate Exponential Moving Average.
        
        Args:
            prices: Price series
            period: EMA period
            
        Returns:
            EMA values array
        """
        if isinstance(prices, pd.Series):
            prices = prices.values
        
        if len(prices) == 0:
            return np.array([])
        
        # Calculate EMA using pandas for efficiency
        price_series = pd.Series(prices)
        ema_values = price_series.ewm(span=period, adjust=False).mean().values
        
        return ema_values
    
    @log_performance
    def calculate_atr(
        self,
        high_prices: Union[pd.Series, np.ndarray],
        low_prices: Union[pd.Series, np.ndarray],
        close_prices: Union[pd.Series, np.ndarray],
        period: int = 14
    ) -> float:
        """Calculate Average True Range.
        
        requirement.md: "표준 TR 기반 14기간 단순이동 평균"
        
        Args:
            high_prices: High price series
            low_prices: Low price series
            close_prices: Close price series
            period: ATR period (default: 14)
            
        Returns:
            ATR value
        """
        if isinstance(high_prices, pd.Series):
            high_prices = high_prices.values
        if isinstance(low_prices, pd.Series):
            low_prices = low_prices.values
        if isinstance(close_prices, pd.Series):
            close_prices = close_prices.values
        
        if len(high_prices) < period + 1:
            # Fallback to simple range if insufficient data
            if len(high_prices) > 0:
                return float(np.mean(high_prices - low_prices))
            return 0.0
        
        # Calculate True Range
        # TR = max(H-L, |H-C_prev|, |L-C_prev|)
        hl = high_prices - low_prices
        hc = np.abs(high_prices[1:] - close_prices[:-1])
        lc = np.abs(low_prices[1:] - close_prices[:-1])
        
        # Pad hc and lc to match hl length
        hc = np.concatenate([[hl[0]], hc])
        lc = np.concatenate([[hl[0]], lc])
        
        true_range = np.maximum(hl, np.maximum(hc, lc))
        
        # Calculate ATR as simple moving average of TR
        if len(true_range) >= period:
            atr = np.mean(true_range[-period:])
        else:
            atr = np.mean(true_range)
        
        return float(atr)
    
    @log_performance
    def calculate_trend(
        self,
        close_prices: Union[pd.Series, np.ndarray],
        volumes: Union[pd.Series, np.ndarray],
        ema_fast: int = 20,
        ema_slow: int = 50
    ) -> Tuple[int, float, float, float]:
        """Calculate trend indicator.
        
        requirement.md: "(EMA20>EMA50) and (close > sVWAP) → {0,1}"
        
        Args:
            close_prices: Close price series
            volumes: Volume series
            ema_fast: Fast EMA period (default: 20)
            ema_slow: Slow EMA period (default: 50)
            
        Returns:
            Tuple of (trend_value, ema20, ema50, svwap)
        """
        # Calculate EMAs
        ema_20_values = self.calculate_ema(close_prices, ema_fast)
        ema_50_values = self.calculate_ema(close_prices, ema_slow)
        
        # Calculate session VWAP
        svwap = self.calculate_session_vwap(close_prices, volumes)
        
        if len(ema_20_values) == 0 or len(ema_50_values) == 0:
            return 0, 0.0, 0.0, svwap
        
        # Get most recent EMA values
        ema_20 = ema_20_values[-1]
        ema_50 = ema_50_values[-1]
        current_price = close_prices.iloc[-1] if isinstance(close_prices, pd.Series) else close_prices[-1]
        
        # Trend conditions: EMA20 > EMA50 AND close > sVWAP
        ema_condition = ema_20 > ema_50
        vwap_condition = current_price > svwap
        
        trend = 1 if (ema_condition and vwap_condition) else 0
        
        return trend, float(ema_20), float(ema_50), svwap
    
    def normalize_rvol(self, rvol: float, method: str = "clip") -> float:
        """Normalize RVOL for scoring.
        
        requirement.md: "RVOL_Z: (RVOL−1)/1.0 을 0~3 범위로 클리핑"
        
        Args:
            rvol: Raw RVOL value
            method: Normalization method (default: "clip")
            
        Returns:
            Normalized RVOL value
        """
        if method == "clip":
            # Simple scaling and clipping as per requirement
            rvol_z = (rvol - 1.0) / 1.0
            return float(np.clip(rvol_z, 0.0, 3.0))
        else:
            # Alternative normalization methods could be added
            return float(rvol)
    
    def calculate_depth_score(self, orderbook_data: Dict, method: str = "log") -> float:
        """Calculate orderbook depth score.
        
        requirement.md: "Depth: log 스케일로 0~1 정규화(오더북 총호가량 기반)"
        
        Args:
            orderbook_data: Orderbook data with bid/ask information
            method: Scoring method (default: "log")
            
        Returns:
            Normalized depth score (0~1)
        """
        try:
            # Extract orderbook units
            units = orderbook_data.get('orderbook_units', [])
            if not units:
                return 0.0
            
            # Calculate total depth (bid + ask sizes)
            total_bid_size = sum(float(unit.get('bid_size', 0)) for unit in units)
            total_ask_size = sum(float(unit.get('ask_size', 0)) for unit in units)
            total_depth = total_bid_size + total_ask_size
            
            if total_depth <= 0:
                return 0.0
            
            if method == "log":
                # Log scale normalization
                log_depth = np.log1p(total_depth)  # log(1 + x) to handle zero
                # Normalize to 0-1 range (assuming reasonable depth ranges)
                # This is a simplified normalization - in production, use historical data
                normalized = min(log_depth / 10.0, 1.0)
                return float(normalized)
            else:
                # Linear normalization
                return min(total_depth / 1000000.0, 1.0)  # Assuming max depth of 1M
                
        except Exception as e:
            self.logger.warning(f"Error calculating depth score: {e}")
            return 0.0
    
    def calculate_spread_bp(self, orderbook_data: Dict) -> float:
        """Calculate bid-ask spread in basis points.
        
        Args:
            orderbook_data: Orderbook data
            
        Returns:
            Spread in basis points
        """
        try:
            units = orderbook_data.get('orderbook_units', [])
            if not units:
                return float('inf')
            
            best_bid = float(units[0].get('bid_price', 0))
            best_ask = float(units[0].get('ask_price', 0))
            
            if best_bid <= 0 or best_ask <= 0:
                return float('inf')
            
            spread = best_ask - best_bid
            mid_price = (best_bid + best_ask) / 2
            
            if mid_price <= 0:
                return float('inf')
            
            spread_bp = (spread / mid_price) * 10000
            return float(spread_bp)
            
        except Exception as e:
            self.logger.warning(f"Error calculating spread: {e}")
            return float('inf')
    
    @log_performance
    def calculate_score(
        self,
        rs: float,
        rvol_z: float,
        trend: int,
        depth_score: float,
        weights: Optional[Dict[str, float]] = None
    ) -> float:
        """Calculate final candidate score.
        
        requirement.md: "0.4*RS + 0.3*RVOL_Z + 0.2*Trend + 0.1*Depth"
        
        Args:
            rs: Relative strength
            rvol_z: Normalized RVOL
            trend: Trend indicator (0 or 1)
            depth_score: Depth score
            weights: Custom weights (uses config if None)
            
        Returns:
            Final score
        """
        if weights is None:
            weights = {
                'rs': self.config.score_weights.rs,
                'rvol': self.config.score_weights.rvol,
                'trend': self.config.score_weights.trend,
                'depth': self.config.score_weights.depth
            }
        
        score = (
            weights['rs'] * rs +
            weights['rvol'] * rvol_z +
            weights['trend'] * trend +
            weights['depth'] * depth_score
        )
        
        return float(score)
    
    @log_performance
    def calculate_all_features(
        self,
        market: str,
        candle_data: List[Dict],
        btc_candle_data: List[Dict],
        orderbook_data: Dict,
        ticker_data: Optional[Dict] = None
    ) -> Optional[FeatureResult]:
        """Calculate all features for a market.
        
        Args:
            market: Market symbol
            candle_data: Candle data for the symbol
            btc_candle_data: BTC candle data for RS calculation
            orderbook_data: Current orderbook data
            ticker_data: Optional ticker data
            
        Returns:
            FeatureResult with all calculated features, or None if calculation fails
        """
        try:
            # Convert candle data to arrays
            if not candle_data or len(candle_data) < 2:
                self.logger.debug(f"Insufficient candle data for {market}: {len(candle_data)}")
                return None
            
            # Extract price and volume arrays
            close_prices = np.array([float(candle['trade_price']) for candle in candle_data])
            high_prices = np.array([float(candle['high_price']) for candle in candle_data])
            low_prices = np.array([float(candle['low_price']) for candle in candle_data])
            volumes = np.array([float(candle['candle_acc_trade_volume']) for candle in candle_data])
            
            # BTC prices for RS calculation
            btc_close_prices = np.array([float(candle['trade_price']) for candle in btc_candle_data])
            
            # Calculate core features
            rvol = self.calculate_rvol(volumes, self.config.rvol_window)
            rs = self.calculate_relative_strength(
                close_prices, btc_close_prices,
                self.config.rs_window_minutes, self.config.candle_unit
            )
            svwap = self.calculate_session_vwap(close_prices, volumes)
            atr_14 = self.calculate_atr(high_prices, low_prices, close_prices, 14)
            
            # Calculate trend
            trend, ema_20, ema_50, _ = self.calculate_trend(
                close_prices, volumes,
                self.config.trend.ema_fast, self.config.trend.ema_slow
            )
            
            # Calculate scoring components
            rvol_z = self.normalize_rvol(rvol)
            depth_score = self.calculate_depth_score(orderbook_data, self.config.depth_normalize)
            spread_bp = self.calculate_spread_bp(orderbook_data)
            
            # Calculate final score
            final_score = self.calculate_score(rs, rvol_z, trend, depth_score)
            
            # Create result
            result = FeatureResult(
                rvol=rvol,
                rs=rs,
                svwap=svwap,
                atr_14=atr_14,
                ema_20=ema_20,
                ema_50=ema_50,
                trend=trend,
                rvol_z=rvol_z,
                depth_score=depth_score,
                final_score=final_score,
                price=float(close_prices[-1]),
                volume=float(volumes[-1]),
                spread_bp=spread_bp,
                market=market,
                timestamp=get_kst_now().isoformat(),
                data_points=len(candle_data)
            )
            
            self.logger.debug(
                f"Calculated features for {market}",
                data={
                    "market": market,
                    "score": final_score,
                    "rvol": rvol,
                    "rs": rs,
                    "trend": trend,
                    "spread_bp": spread_bp
                }
            )
            
            return result
            
        except Exception as e:
            self.logger.error(f"Failed to calculate features for {market}: {e}")
            return None
    
    def validate_features(self, result: FeatureResult, config: ScannerConfig) -> Tuple[bool, List[str]]:
        """Validate calculated features against filters.
        
        requirement.md FR-4: "선행 필터: RVOL≥2, 스프레드≤5bp, Trend=1"
        
        Args:
            result: Feature calculation result
            config: Scanner configuration
            
        Returns:
            Tuple of (is_valid, failed_criteria)
        """
        failed_criteria = []
        
        # RVOL threshold
        if result.rvol < config.rvol_threshold:
            failed_criteria.append(f"RVOL {result.rvol:.2f} < {config.rvol_threshold}")
        
        # Spread threshold
        if result.spread_bp > config.spread_bp_max:
            failed_criteria.append(f"Spread {result.spread_bp:.2f}bp > {config.spread_bp_max}bp")
        
        # Trend requirement
        if result.trend != 1:
            failed_criteria.append(f"Trend {result.trend} != 1")
        
        # Minimum score
        if result.final_score < config.min_score:
            failed_criteria.append(f"Score {result.final_score:.3f} < {config.min_score}")
        
        is_valid = len(failed_criteria) == 0
        
        return is_valid, failed_criteria
