"""Candle data processing and validation module.

This module handles raw candle data preprocessing, validation, and transformation
as required by requirement.md FR-2 (Data Collection).

Features:
- Data validation and cleaning
- Time-based sorting and filtering
- Missing data detection and handling
- Data type conversion and normalization
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass

from ..utils.logging import get_trading_logger, log_performance
from ..utils.time_utils import get_kst_now, to_kst, parse_kst_time, KST


logger = get_trading_logger(__name__)


@dataclass
class CandleValidationResult:
    """Result of candle data validation."""
    
    is_valid: bool
    total_candles: int
    valid_candles: int
    missing_data_points: int
    time_gaps: List[Tuple[datetime, datetime]]
    data_quality_score: float
    warnings: List[str]
    errors: List[str]


class CandleProcessor:
    """Candle data processor with validation and cleaning capabilities.
    
    Handles:
    - Data validation and quality checks
    - Time-based sorting and filtering  
    - Missing data detection
    - Data type conversion
    - Outlier detection and filtering
    """
    
    def __init__(self, candle_unit: int = 5):
        """Initialize candle processor.
        
        Args:
            candle_unit: Candle unit in minutes (default: 5)
        """
        self.candle_unit = candle_unit
        self.logger = logger
    
    @log_performance
    def validate_candle_data(self, candles: List[Dict[str, Any]], market: str) -> CandleValidationResult:
        """Validate raw candle data quality.
        
        Args:
            candles: List of candle dictionaries
            market: Market symbol for logging
            
        Returns:
            Validation result with quality metrics
        """
        warnings = []
        errors = []
        valid_candles = 0
        missing_data_points = 0
        time_gaps = []
        
        if not candles:
            errors.append("No candle data provided")
            return CandleValidationResult(
                is_valid=False,
                total_candles=0,
                valid_candles=0,
                missing_data_points=0,
                time_gaps=[],
                data_quality_score=0.0,
                warnings=warnings,
                errors=errors
            )
        
        required_fields = [
            'candle_date_time_kst', 'opening_price', 'high_price',
            'low_price', 'trade_price', 'candle_acc_trade_volume'
        ]
        
        previous_timestamp = None
        
        for i, candle in enumerate(candles):
            candle_valid = True
            
            # Check required fields
            for field in required_fields:
                if field not in candle:
                    errors.append(f"Missing field '{field}' in candle {i}")
                    candle_valid = False
                    missing_data_points += 1
                elif candle[field] is None:
                    warnings.append(f"Null value for '{field}' in candle {i}")
                    missing_data_points += 1
            
            if not candle_valid:
                continue
            
            try:
                # Validate numeric fields
                prices = [
                    float(candle['opening_price']),
                    float(candle['high_price']),
                    float(candle['low_price']),
                    float(candle['trade_price'])
                ]
                
                volume = float(candle['candle_acc_trade_volume'])
                
                # Check price relationships
                high = prices[1]
                low = prices[2]
                open_price = prices[0]
                close_price = prices[3]
                
                if high < low:
                    errors.append(f"High price < Low price in candle {i}")
                    candle_valid = False
                
                if not (low <= open_price <= high):
                    warnings.append(f"Open price outside High-Low range in candle {i}")
                
                if not (low <= close_price <= high):
                    warnings.append(f"Close price outside High-Low range in candle {i}")
                
                # Check for negative or zero prices
                if any(p <= 0 for p in prices):
                    errors.append(f"Non-positive prices in candle {i}")
                    candle_valid = False
                
                # Check volume
                if volume < 0:
                    errors.append(f"Negative volume in candle {i}")
                    candle_valid = False
                
                # Validate timestamp
                timestamp_str = candle['candle_date_time_kst']
                timestamp = pd.to_datetime(timestamp_str)
                
                # Check time sequence
                if previous_timestamp and timestamp <= previous_timestamp:
                    warnings.append(f"Time sequence issue at candle {i}: {timestamp} <= {previous_timestamp}")
                
                # Check for time gaps
                if previous_timestamp:
                    expected_gap = timedelta(minutes=self.candle_unit)
                    actual_gap = timestamp - previous_timestamp
                    
                    if actual_gap > expected_gap * 1.5:  # Allow 50% tolerance
                        time_gaps.append((previous_timestamp, timestamp))
                
                previous_timestamp = timestamp
                
            except (ValueError, TypeError) as e:
                errors.append(f"Data conversion error in candle {i}: {e}")
                candle_valid = False
            
            if candle_valid:
                valid_candles += 1
        
        # Calculate data quality score
        total_candles = len(candles)
        if total_candles > 0:
            completeness = valid_candles / total_candles
            gap_penalty = min(len(time_gaps) * 0.1, 0.5)  # Up to 50% penalty for gaps
            data_quality_score = max(0.0, completeness - gap_penalty)
        else:
            data_quality_score = 0.0
        
        is_valid = (
            len(errors) == 0 and
            valid_candles >= total_candles * 0.9 and  # At least 90% valid
            data_quality_score >= 0.7  # Quality score >= 70%
        )
        
        self.logger.debug(
            f"Candle validation for {market}",
            data={
                "market": market,
                "total_candles": total_candles,
                "valid_candles": valid_candles,
                "quality_score": data_quality_score,
                "is_valid": is_valid,
                "warnings_count": len(warnings),
                "errors_count": len(errors)
            }
        )
        
        return CandleValidationResult(
            is_valid=is_valid,
            total_candles=total_candles,
            valid_candles=valid_candles,
            missing_data_points=missing_data_points,
            time_gaps=time_gaps,
            data_quality_score=data_quality_score,
            warnings=warnings,
            errors=errors
        )
    
    @log_performance
    def clean_candle_data(self, candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Clean and normalize candle data.
        
        Args:
            candles: Raw candle data
            
        Returns:
            Cleaned candle data
        """
        if not candles:
            return []
        
        cleaned_candles = []
        
        for candle in candles:
            try:
                cleaned_candle = {
                    'candle_date_time_kst': candle['candle_date_time_kst'],
                    'opening_price': float(candle['opening_price']),
                    'high_price': float(candle['high_price']),
                    'low_price': float(candle['low_price']),
                    'trade_price': float(candle['trade_price']),
                    'candle_acc_trade_volume': float(candle['candle_acc_trade_volume']),
                }
                
                # Add optional fields if present
                if 'candle_acc_trade_price' in candle:
                    cleaned_candle['candle_acc_trade_price'] = float(candle['candle_acc_trade_price'])
                
                if 'timestamp' in candle:
                    cleaned_candle['timestamp'] = candle['timestamp']
                
                # Basic validation
                prices = [
                    cleaned_candle['opening_price'],
                    cleaned_candle['high_price'],
                    cleaned_candle['low_price'],
                    cleaned_candle['trade_price']
                ]
                
                if all(p > 0 for p in prices) and cleaned_candle['candle_acc_trade_volume'] >= 0:
                    cleaned_candles.append(cleaned_candle)
                
            except (ValueError, KeyError, TypeError):
                # Skip invalid candles
                continue
        
        return cleaned_candles
    
    @log_performance
    def sort_candles_by_time(self, candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort candles by timestamp (oldest to newest).
        
        requirement.md FR-2: "데이터 누락/역정렬 방지(과거→현재 정렬)"
        
        Args:
            candles: Candle data
            
        Returns:
            Time-sorted candle data
        """
        if not candles:
            return []
        
        try:
            # Sort by timestamp
            sorted_candles = sorted(
                candles,
                key=lambda x: pd.to_datetime(x['candle_date_time_kst'])
            )
            
            self.logger.debug(f"Sorted {len(candles)} candles by timestamp")
            return sorted_candles
            
        except Exception as e:
            self.logger.error(f"Error sorting candles: {e}")
            return candles
    
    @log_performance
    def to_dataframe(self, candles: List[Dict[str, Any]]) -> pd.DataFrame:
        """Convert candle list to pandas DataFrame.
        
        Args:
            candles: Candle data
            
        Returns:
            DataFrame with proper data types and index
        """
        if not candles:
            return pd.DataFrame()
        
        try:
            df = pd.DataFrame(candles)
            
            # Convert timestamp column
            df['candle_date_time_kst'] = pd.to_datetime(df['candle_date_time_kst'])
            
            # Set timestamp as index
            df.set_index('candle_date_time_kst', inplace=True)
            
            # Ensure numeric columns
            numeric_columns = [
                'opening_price', 'high_price', 'low_price', 'trade_price',
                'candle_acc_trade_volume'
            ]
            
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # Add optional columns if present
            if 'candle_acc_trade_price' in df.columns:
                df['candle_acc_trade_price'] = pd.to_numeric(df['candle_acc_trade_price'], errors='coerce')
            
            # Remove rows with NaN values
            df.dropna(inplace=True)
            
            self.logger.debug(f"Converted {len(df)} candles to DataFrame")
            return df
            
        except Exception as e:
            self.logger.error(f"Error converting candles to DataFrame: {e}")
            return pd.DataFrame()
    
    @log_performance
    def filter_by_time_range(
        self,
        candles: List[Dict[str, Any]],
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Filter candles by time range.
        
        Args:
            candles: Candle data
            start_time: Start time (inclusive)
            end_time: End time (inclusive)
            
        Returns:
            Filtered candle data
        """
        if not candles:
            return []
        
        if not start_time and not end_time:
            return candles
        
        filtered_candles = []
        
        for candle in candles:
            try:
                timestamp = pd.to_datetime(candle['candle_date_time_kst'])
                
                # Convert to KST if needed
                if timestamp.tz is None:
                    timestamp = KST.localize(timestamp)
                else:
                    timestamp = to_kst(timestamp)
                
                # Apply filters
                if start_time and timestamp < to_kst(start_time):
                    continue
                
                if end_time and timestamp > to_kst(end_time):
                    continue
                
                filtered_candles.append(candle)
                
            except Exception:
                continue
        
        self.logger.debug(f"Filtered {len(candles)} -> {len(filtered_candles)} candles by time range")
        return filtered_candles
    
    def detect_outliers(
        self,
        candles: List[Dict[str, Any]],
        field: str = 'trade_price',
        method: str = 'iqr',
        threshold: float = 3.0
    ) -> List[int]:
        """Detect outlier candles based on price or volume.
        
        Args:
            candles: Candle data
            field: Field to analyze for outliers
            method: Detection method ('iqr', 'zscore')
            threshold: Threshold for outlier detection
            
        Returns:
            List of outlier indices
        """
        if not candles or len(candles) < 10:
            return []
        
        try:
            values = np.array([float(candle[field]) for candle in candles])
            outlier_indices = []
            
            if method == 'iqr':
                Q1 = np.percentile(values, 25)
                Q3 = np.percentile(values, 75)
                IQR = Q3 - Q1
                
                lower_bound = Q1 - threshold * IQR
                upper_bound = Q3 + threshold * IQR
                
                outlier_indices = [
                    i for i, value in enumerate(values)
                    if value < lower_bound or value > upper_bound
                ]
                
            elif method == 'zscore':
                mean = np.mean(values)
                std = np.std(values)
                
                if std > 0:
                    z_scores = np.abs((values - mean) / std)
                    outlier_indices = [
                        i for i, z_score in enumerate(z_scores)
                        if z_score > threshold
                    ]
            
            if outlier_indices:
                self.logger.debug(
                    f"Detected {len(outlier_indices)} outliers in {field}",
                    data={"field": field, "method": method, "outliers": len(outlier_indices)}
                )
            
            return outlier_indices
            
        except Exception as e:
            self.logger.error(f"Error detecting outliers: {e}")
            return []
    
    @log_performance
    def fill_missing_candles(
        self,
        candles: List[Dict[str, Any]],
        method: str = 'forward_fill'
    ) -> List[Dict[str, Any]]:
        """Fill missing candles in the time series.
        
        Args:
            candles: Candle data (must be time-sorted)
            method: Fill method ('forward_fill', 'interpolate', 'skip')
            
        Returns:
            Candle data with missing periods filled
        """
        if not candles or len(candles) < 2:
            return candles
        
        if method == 'skip':
            return candles
        
        try:
            filled_candles = []
            candle_delta = timedelta(minutes=self.candle_unit)
            
            for i in range(len(candles)):
                filled_candles.append(candles[i])
                
                # Check if next candle exists and calculate time gap
                if i < len(candles) - 1:
                    current_time = pd.to_datetime(candles[i]['candle_date_time_kst'])
                    next_time = pd.to_datetime(candles[i + 1]['candle_date_time_kst'])
                    
                    gap = next_time - current_time
                    expected_gap = candle_delta
                    
                    # If gap is larger than expected, fill missing candles
                    if gap > expected_gap * 1.5:
                        missing_periods = int(gap.total_seconds() / (self.candle_unit * 60)) - 1
                        
                        for j in range(1, min(missing_periods + 1, 10)):  # Limit to 10 missing candles
                            missing_time = current_time + candle_delta * j
                            
                            if method == 'forward_fill':
                                # Use previous candle values
                                missing_candle = candles[i].copy()
                                missing_candle['candle_date_time_kst'] = missing_time.isoformat()
                                missing_candle['candle_acc_trade_volume'] = 0  # No volume for missing periods
                                
                                filled_candles.append(missing_candle)
            
            self.logger.debug(f"Filled missing candles: {len(candles)} -> {len(filled_candles)}")
            return filled_candles
            
        except Exception as e:
            self.logger.error(f"Error filling missing candles: {e}")
            return candles
    
    @log_performance
    def process_candles(
        self,
        raw_candles: List[Dict[str, Any]],
        market: str,
        validate: bool = True,
        clean: bool = True,
        sort_by_time: bool = True,
        fill_missing: bool = False,
        remove_outliers: bool = False
    ) -> Tuple[List[Dict[str, Any]], CandleValidationResult]:
        """Complete candle processing pipeline.
        
        Args:
            raw_candles: Raw candle data
            market: Market symbol
            validate: Whether to validate data
            clean: Whether to clean data
            sort_by_time: Whether to sort by time
            fill_missing: Whether to fill missing candles
            remove_outliers: Whether to remove outliers
            
        Returns:
            Tuple of (processed_candles, validation_result)
        """
        processed_candles = raw_candles
        validation_result = None
        
        # Step 1: Validation
        if validate:
            validation_result = self.validate_candle_data(processed_candles, market)
            
            if not validation_result.is_valid:
                self.logger.warning(
                    f"Candle data validation failed for {market}",
                    data={
                        "market": market,
                        "errors": len(validation_result.errors),
                        "quality_score": validation_result.data_quality_score
                    }
                )
        
        # Step 2: Cleaning
        if clean:
            processed_candles = self.clean_candle_data(processed_candles)
        
        # Step 3: Time sorting
        if sort_by_time:
            processed_candles = self.sort_candles_by_time(processed_candles)
        
        # Step 4: Fill missing candles
        if fill_missing:
            processed_candles = self.fill_missing_candles(processed_candles)
        
        # Step 5: Remove outliers
        if remove_outliers and len(processed_candles) > 10:
            price_outliers = self.detect_outliers(processed_candles, 'trade_price')
            volume_outliers = self.detect_outliers(processed_candles, 'candle_acc_trade_volume')
            
            all_outliers = set(price_outliers + volume_outliers)
            if all_outliers:
                processed_candles = [
                    candle for i, candle in enumerate(processed_candles)
                    if i not in all_outliers
                ]
                
                self.logger.debug(f"Removed {len(all_outliers)} outliers from {market}")
        
        self.logger.info(
            f"Processed candles for {market}",
            data={
                "market": market,
                "input_candles": len(raw_candles),
                "output_candles": len(processed_candles),
                "quality_score": validation_result.data_quality_score if validation_result else None
            }
        )
        
        return processed_candles, validation_result or CandleValidationResult(
            is_valid=True,
            total_candles=len(processed_candles),
            valid_candles=len(processed_candles),
            missing_data_points=0,
            time_gaps=[],
            data_quality_score=1.0,
            warnings=[],
            errors=[]
        )
