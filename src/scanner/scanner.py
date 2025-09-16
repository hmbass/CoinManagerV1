"""Candidate scanner and scoring system (FR-4).

This module implements the market scanning and candidate selection logic
as specified in requirement.md FR-4: Candidate Scoring & Selection.
"""

import asyncio
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

from ..api.upbit_rest import UpbitRestClient
from ..data.features import FeatureCalculator, FeatureResult
from ..data.candles import CandleProcessor
from ..utils.config import Config, ScannerConfig
from ..utils.logging import get_trading_logger, log_performance, correlation_context


logger = get_trading_logger(__name__)


@dataclass
class ScanResult:
    """Result of market scan."""
    
    candidates: List[FeatureResult]
    total_markets: int
    processed_markets: int
    filtered_markets: int
    scan_duration_seconds: float
    timestamp: str


class CandidateScanner:
    """Market scanner for identifying trading candidates.
    
    Implements requirement.md FR-4:
    - Market filtering (exclude warnings, newly listed)
    - Feature calculation for all candidates
    - Scoring and ranking
    - Top 2~3 selection
    """
    
    def __init__(
        self,
        config: Config,
        api_client: UpbitRestClient
    ):
        """Initialize scanner.
        
        Args:
            config: System configuration
            api_client: Upbit API client
        """
        self.config = config
        self.scanner_config = config.scanner
        self.api_client = api_client
        
        self.feature_calculator = FeatureCalculator(self.scanner_config)
        self.candle_processor = CandleProcessor(self.scanner_config.candle_unit)
        
        self.logger = logger
    
    @log_performance
    async def get_tradable_markets(self) -> List[str]:
        """Get list of tradable markets after filtering with rate limit optimization.
        
        Returns:
            List of market codes (limited for rate limiting)
        """
        with correlation_context():
            # Get all markets with details
            all_markets = await self.api_client.get_markets(is_details=True)
            
            tradable_markets = []
            priority_markets_found = []
            
            # First pass: collect all valid markets
            for market in all_markets:
                market_code = market.get('market', '')
                
                # Filter 1: KRW markets only
                if not market_code.startswith('KRW-'):
                    continue
                
                # Filter 2: Exclude warning/caution markets
                if self.config.symbols.exclude_warning:
                    market_warning = market.get('market_warning')
                    if market_warning and market_warning != 'NONE':
                        self.logger.debug(f"Excluded warning market: {market_code} ({market_warning})")
                        continue
                
                # Filter 3: Exclude newly listed (simplified - no listing date check)
                # In production, implement proper listing date check
                
                # Check if this is a priority market
                if market_code in self.config.symbols.priority_markets:
                    priority_markets_found.append(market_code)
                else:
                    tradable_markets.append(market_code)
            
            # Second pass: apply market limits for rate limiting
            final_markets = []
            
            # Always include priority markets first
            final_markets.extend(priority_markets_found)
            
            # Add remaining markets up to limit
            remaining_slots = self.config.symbols.max_markets_to_scan - len(priority_markets_found)
            if remaining_slots > 0:
                # Sort remaining markets alphabetically for consistency
                tradable_markets.sort()
                final_markets.extend(tradable_markets[:remaining_slots])
            
            self.logger.info(
                f"Market filtering complete (rate limit optimized)",
                data={
                    "total_markets": len(all_markets),
                    "krw_markets": len([m for m in all_markets if m.get('market', '').startswith('KRW-')]),
                    "priority_markets": len(priority_markets_found),
                    "additional_markets": len(final_markets) - len(priority_markets_found),
                    "final_tradable_markets": len(final_markets),
                    "max_limit": self.config.symbols.max_markets_to_scan
                }
            )
            
            return final_markets
    
    async def get_market_data(
        self,
        markets: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """Get comprehensive market data for candidates.
        
        Args:
            markets: List of market codes
            
        Returns:
            Dict mapping market codes to their data
        """
        with correlation_context():
            market_data = {}
            
            # Get candle data for all markets
            self.logger.info(f"Fetching candle data for {len(markets)} markets")
            candle_data = await self.api_client.get_multiple_candles(
                markets, 
                self.scanner_config.candle_unit,
                self.scanner_config.candle_count
            )
            
            # Get BTC candles for RS calculation
            btc_candles = await self.api_client.get_candles(
                self.scanner_config.rs_reference_symbol,
                self.scanner_config.candle_unit,
                self.scanner_config.candle_count
            )
            
            # Get orderbook data
            self.logger.info(f"Fetching orderbook data for {len(markets)} markets")
            try:
                orderbooks = await self.api_client.get_orderbook(markets)
                orderbook_dict = {ob['market']: ob for ob in orderbooks}
            except Exception as e:
                self.logger.error(f"Failed to fetch orderbooks: {e}")
                orderbook_dict = {}
            
            # Combine data
            for market in markets:
                if market in candle_data:
                    market_data[market] = {
                        'candles': candle_data[market],
                        'btc_candles': btc_candles,
                        'orderbook': orderbook_dict.get(market, {})
                    }
            
            self.logger.info(f"Retrieved data for {len(market_data)} markets")
            return market_data
    
    @log_performance
    async def calculate_features_for_markets(
        self,
        market_data: Dict[str, Dict[str, Any]]
    ) -> List[FeatureResult]:
        """Calculate features for all markets.
        
        Args:
            market_data: Market data dict
            
        Returns:
            List of feature calculation results
        """
        feature_results = []
        
        for market, data in market_data.items():
            try:
                # Process candle data
                processed_candles, validation_result = self.candle_processor.process_candles(
                    data['candles'], market
                )
                
                if not validation_result.is_valid:
                    self.logger.warning(f"Skipping {market} due to data quality issues")
                    continue
                
                # Calculate features
                features = self.feature_calculator.calculate_all_features(
                    market=market,
                    candle_data=processed_candles,
                    btc_candle_data=data['btc_candles'],
                    orderbook_data=data['orderbook']
                )
                
                if features:
                    feature_results.append(features)
                
            except Exception as e:
                self.logger.error(f"Error calculating features for {market}: {e}")
                continue
        
        self.logger.info(f"Calculated features for {len(feature_results)} markets")
        return feature_results
    
    def filter_candidates(self, feature_results: List[FeatureResult]) -> List[FeatureResult]:
        """Apply filtering criteria to candidates.
        
        requirement.md FR-4: "선행 필터: RVOL≥2, 스프레드≤5bp, Trend=1"
        
        Args:
            feature_results: List of feature results
            
        Returns:
            Filtered candidates
        """
        filtered_candidates = []
        
        for result in feature_results:
            is_valid, failed_criteria = self.feature_calculator.validate_features(
                result, self.scanner_config
            )
            
            if is_valid:
                filtered_candidates.append(result)
            else:
                self.logger.debug(
                    f"Filtered out {result.market}: {', '.join(failed_criteria)}",
                    data={
                        "market": result.market,
                        "failed_criteria": failed_criteria,
                        "score": result.final_score
                    }
                )
        
        self.logger.info(
            f"Candidate filtering complete",
            data={
                "input_candidates": len(feature_results),
                "filtered_candidates": len(filtered_candidates),
                "filter_rate": len(filtered_candidates) / max(len(feature_results), 1)
            }
        )
        
        return filtered_candidates
    
    def rank_candidates(self, candidates: List[FeatureResult]) -> List[FeatureResult]:
        """Rank candidates by score and return top N.
        
        requirement.md FR-4: "상위 2~3개 반환"
        
        Args:
            candidates: Filtered candidates
            
        Returns:
            Top-ranked candidates (2~3)
        """
        if not candidates:
            return []
        
        # Sort by score (descending)
        ranked_candidates = sorted(
            candidates,
            key=lambda x: x.final_score,
            reverse=True
        )
        
        # Return top N candidates
        top_candidates = ranked_candidates[:self.scanner_config.candidate_count]
        
        self.logger.info(
            f"Selected top {len(top_candidates)} candidates",
            data={
                "total_candidates": len(candidates),
                "selected_candidates": [
                    {
                        "market": c.market,
                        "score": c.final_score,
                        "rvol": c.rvol,
                        "rs": c.rs,
                        "trend": c.trend
                    }
                    for c in top_candidates
                ]
            }
        )
        
        return top_candidates
    
    @log_performance
    async def scan_markets(self) -> ScanResult:
        """Perform complete market scan.
        
        Returns:
            Scan result with top candidates
        """
        import time
        start_time = time.time()
        
        with correlation_context():
            self.logger.info("Starting market scan")
            
            # Step 1: Get tradable markets
            tradable_markets = await self.get_tradable_markets()
            
            if not tradable_markets:
                self.logger.warning("No tradable markets found")
                return ScanResult(
                    candidates=[],
                    total_markets=0,
                    processed_markets=0,
                    filtered_markets=0,
                    scan_duration_seconds=time.time() - start_time,
                    timestamp=self.config.runtime.timezone
                )
            
            # Step 2: Get market data
            market_data = await self.get_market_data(tradable_markets)
            
            # Step 3: Calculate features
            feature_results = await self.calculate_features_for_markets(market_data)
            
            # Step 4: Filter candidates
            filtered_candidates = self.filter_candidates(feature_results)
            
            # Step 5: Rank and select top candidates
            top_candidates = self.rank_candidates(filtered_candidates)
            
            scan_duration = time.time() - start_time
            
            scan_result = ScanResult(
                candidates=top_candidates,
                total_markets=len(tradable_markets),
                processed_markets=len(feature_results),
                filtered_markets=len(filtered_candidates),
                scan_duration_seconds=scan_duration,
                timestamp=self.config.runtime.timezone
            )
            
            self.logger.info(
                f"Market scan completed",
                data={
                    "duration_seconds": scan_duration,
                    "total_markets": scan_result.total_markets,
                    "processed_markets": scan_result.processed_markets,
                    "filtered_markets": scan_result.filtered_markets,
                    "final_candidates": len(scan_result.candidates)
                }
            )
            
            return scan_result
