"""Main Trading System Integration.

This module integrates all components into a complete automated trading system
that handles the full trading lifecycle from signal generation to order execution.
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from .api.upbit_rest import UpbitRestClient
from .scanner.scanner import CandidateScanner
from .signals.signal_manager import SignalManager, SignalContext
from .risk.guard import RiskGuard
from .order.executor import OrderExecutor, Position, OrderResult
from .utils.config import Config, EnvironmentConfig
from .utils.logging import get_trading_logger, log_performance, correlation_context
from .utils.time_utils import get_kst_now, is_trading_hours
from .utils.telegram import get_telegram_notifier


logger = get_trading_logger(__name__)


@dataclass
class TradingState:
    """Current trading system state."""
    
    is_running: bool
    start_time: datetime
    current_time: datetime
    
    # Trading session
    is_trading_hours: bool
    next_scan_time: datetime
    
    # Market state  
    active_candidates: List[str]
    active_positions: List[Position]
    
    # Performance metrics
    total_trades: int
    winning_trades: int
    total_pnl: float
    daily_pnl: float
    
    # Risk status
    ddl_hit: bool
    banned_markets: List[str]


class TradingSystem:
    """Complete automated trading system.
    
    Integrates all components:
    - Market scanning and candidate selection
    - Signal generation from multiple strategies
    - Risk management and position sizing
    - Order execution (paper/live)
    - Performance monitoring and reporting
    """
    
    def __init__(
        self,
        config: Config,
        env_config: EnvironmentConfig,
        api_client: UpbitRestClient
    ):
        """Initialize trading system.
        
        Args:
            config: System configuration
            env_config: Environment configuration
            api_client: Upbit API client
        """
        self.config = config
        self.env_config = env_config
        self.api_client = api_client
        self.logger = logger
        
        # Initialize components
        self.scanner = CandidateScanner(config, api_client)
        self.signal_manager = SignalManager(config.signals)
        self.risk_guard = RiskGuard(config.risk)
        self.order_executor = OrderExecutor(config.orders, env_config, api_client)
        
        # Trading state
        self.state = TradingState(
            is_running=False,
            start_time=get_kst_now(),
            current_time=get_kst_now(),
            is_trading_hours=False,
            next_scan_time=get_kst_now(),
            active_candidates=[],
            active_positions=[],
            total_trades=0,
            winning_trades=0,
            total_pnl=0.0,
            daily_pnl=0.0,
            ddl_hit=False,
            banned_markets=[]
        )
        
        # Control flags
        self.should_stop = False
        self.pause_trading = False
    
    async def initialize(self) -> None:
        """Initialize trading system components."""
        self.logger.info("Initializing trading system components")
        
        # Get account balance for risk management
        try:
            accounts = await self.api_client.get_accounts()
            krw_balance = 0.0
            
            for account in accounts:
                if account['currency'] == 'KRW':
                    krw_balance = float(account['balance'])
                    break
            
            if krw_balance > 0:
                self.risk_guard.update_account_balance(krw_balance)
                self.logger.info(f"Account balance: {krw_balance:,.0f} KRW")
            else:
                # Use paper trading balance
                self.risk_guard.update_account_balance(1_000_000.0)
                self.logger.info("Using paper trading balance: 1,000,000 KRW")
                
        except Exception as e:
            self.logger.error(f"Error getting account balance: {e}")
            # Default to paper trading balance
            self.risk_guard.update_account_balance(1_000_000.0)
        
        # Update initial state
        self._update_state()
        
        self.logger.info("Trading system initialized successfully")
    
    def _update_state(self) -> None:
        """Update current trading state."""
        current_time = get_kst_now()
        
        self.state.current_time = current_time
        self.state.is_trading_hours = is_trading_hours(
            current_time, 
            self.config.runtime.session_windows
        )
        
        # Update positions
        self.state.active_positions = self.order_executor.get_active_positions()
        
        # Update risk status
        risk_status = self.risk_guard.get_risk_status()
        self.state.ddl_hit = risk_status['account']['ddl_hit']
        self.state.banned_markets = risk_status['markets']['banned_markets']
        self.state.daily_pnl = risk_status['account']['daily_pnl']
        
        # Calculate total P&L from positions
        total_pnl = 0.0
        winning_trades = 0
        total_trades = 0
        
        for position in self.order_executor.positions.values():
            if not position.is_active and position.realized_pnl != 0:
                total_pnl += position.realized_pnl
                total_trades += 1
                if position.realized_pnl > 0:
                    winning_trades += 1
        
        self.state.total_pnl = total_pnl
        self.state.winning_trades = winning_trades
        self.state.total_trades = total_trades
    
    @log_performance
    async def run_trading_loop(self, duration_minutes: int = 60) -> None:
        """Run the main trading loop.
        
        Args:
            duration_minutes: How long to run (minutes)
        """
        self.state.is_running = True
        self.state.start_time = get_kst_now()
        end_time = self.state.start_time + timedelta(minutes=duration_minutes)
        
        self.logger.info(
            f"Starting trading loop for {duration_minutes} minutes",
            data={
                "start_time": self.state.start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "trading_mode": self.env_config.trading_mode
            }
        )
        
        # Send system start notification
        try:
            notifier = get_telegram_notifier()
            if notifier and notifier.enabled:
                await notifier.send_system_status(
                    "STARTED", 
                    uptime_minutes=0
                )
        except Exception as e:
            self.logger.warning(f"Failed to send system start notification: {e}")
        
        try:
            while not self.should_stop and get_kst_now() < end_time:
                with correlation_context():
                    await self._trading_cycle()
                    
                    # Wait for next cycle
                    await asyncio.sleep(self.config.runtime.signal_check_interval_seconds)
        
        except KeyboardInterrupt:
            self.logger.info("Trading loop interrupted by user")
        except Exception as e:
            self.logger.error(f"Trading loop error: {e}")
        finally:
            self.state.is_running = False
            
            # Send system stop notification
            try:
                notifier = get_telegram_notifier()
                if notifier and notifier.enabled:
                    uptime = (get_kst_now() - self.state.start_time).total_seconds() / 60
                    await notifier.send_system_status(
                        "STOPPED", 
                        uptime_minutes=uptime
                    )
            except Exception as e:
                self.logger.warning(f"Failed to send system stop notification: {e}")
            
            await self._cleanup()
    
    async def _trading_cycle(self) -> None:
        """Execute one trading cycle."""
        # Update state
        self._update_state()
        
        # Check if we should trade
        if not self._should_trade():
            return
        
        # 1. Market Scanning (if it's time)
        if get_kst_now() >= self.state.next_scan_time:
            await self._scan_markets()
        
        # 2. Signal Generation for active candidates
        if self.state.active_candidates:
            await self._process_signals()
        
        # 3. Position Management
        await self._manage_positions()
        
        # 4. Risk monitoring
        self._monitor_risk()
    
    def _should_trade(self) -> bool:
        """Check if system should continue trading.
        
        Returns:
            True if should continue trading
        """
        # Check pause flag
        if self.pause_trading:
            return False
        
        # Check DDL
        if self.state.ddl_hit:
            if not self.pause_trading:
                self.logger.warning("Trading paused due to daily drawdown limit")
                self.pause_trading = True
            return False
        
        # Check trading hours (optional - can trade outside hours for global markets)
        # For now, we'll allow trading outside hours but log it
        if not self.state.is_trading_hours:
            self.logger.debug("Outside regular trading hours")
        
        return True
    
    @log_performance
    async def _scan_markets(self) -> None:
        """Perform market scan and update candidates."""
        self.logger.info("Starting market scan")
        
        try:
            scan_result = await self.scanner.scan_markets()
            
            # Update active candidates
            self.state.active_candidates = [
                candidate.market for candidate in scan_result.candidates
            ]
            
            # Schedule next scan
            self.state.next_scan_time = get_kst_now() + timedelta(
                minutes=self.config.runtime.scan_interval_minutes
            )
            
            self.logger.info(
                f"Market scan completed: {len(scan_result.candidates)} candidates found",
                data={
                    "candidates": self.state.active_candidates,
                    "scan_duration": scan_result.scan_duration_seconds,
                    "next_scan_time": self.state.next_scan_time.isoformat()
                }
            )
            
        except Exception as e:
            self.logger.error(f"Market scan failed: {e}")
    
    @log_performance
    async def _process_signals(self) -> None:
        """Process signals for active candidates."""
        for market in self.state.active_candidates:
            try:
                await self._process_market_signals(market)
            except Exception as e:
                self.logger.error(f"Error processing signals for {market}: {e}")
    
    async def _process_market_signals(self, market: str) -> None:
        """Process signals for a specific market.
        
        Args:
            market: Market symbol to process
        """
        # Skip if market is banned
        if market in self.state.banned_markets:
            return
        
        # Skip if we already have a position in this market
        existing_position = next(
            (pos for pos in self.state.active_positions if pos.market == market),
            None
        )
        if existing_position:
            return
        
        # Get market data
        candle_data = await self.api_client.get_candles(market, unit=5, count=200)
        if not candle_data:
            return
        
        # Get current ticker
        tickers = await self.api_client.get_tickers([market])
        if not tickers:
            return
        
        current_price = float(tickers[0]['trade_price'])
        current_volume = float(tickers[0]['acc_trade_volume_24h'])
        
        # Calculate features
        from .data.features import FeatureCalculator
        feature_calc = FeatureCalculator()
        
        # Get BTC data for RS calculation  
        btc_candles = await self.api_client.get_candles("KRW-BTC", unit=5, count=200)
        
        # Get orderbook for depth calculation
        orderbooks = await self.api_client.get_orderbook([market])
        orderbook = orderbooks[0] if orderbooks else {}
        
        # Calculate features
        features = feature_calc.calculate_all_features(
            market, candle_data, btc_candles, orderbook
        )
        
        if not features:
            return
        
        # Get best signal
        signal_context = self.signal_manager.get_best_signal(
            market, candle_data, current_price, current_volume, features
        )
        
        if not signal_context or not signal_context.is_valid:
            return
        
        # Assess risk
        risk_assessment = self.risk_guard.assess_trade_risk(
            market, signal_context.signal
        )
        
        if not risk_assessment.is_allowed:
            self.logger.debug(
                f"Trade rejected for {market}: {', '.join(risk_assessment.rejection_reasons)}"
            )
            return
        
        # Execute trade
        await self._execute_trade(signal_context, risk_assessment.trade_risk)
    
    async def _execute_trade(self, signal_context: SignalContext, trade_risk) -> None:
        """Execute a trade based on signal and risk assessment.
        
        Args:
            signal_context: Signal context
            trade_risk: Trade risk assessment
        """
        market = signal_context.signal.market
        
        self.logger.info(
            f"Executing trade for {market}: {signal_context.signal.signal_type}",
            data={
                "market": market,
                "strategy": signal_context.strategy_name,
                "signal_type": signal_context.signal.signal_type,
                "entry_price": signal_context.signal.entry_price,
                "position_size": trade_risk.position_size,
                "risk_amount": trade_risk.risk_amount,
                "confidence": signal_context.signal.confidence_score
            }
        )
        
        # Execute the trade
        position, orders = await self.order_executor.execute_signal_trade(
            signal_context.signal, trade_risk
        )
        
        if position and orders:
            filled_orders = [o for o in orders if o.status.value == "filled"]
            
            if filled_orders:
                self.logger.info(
                    f"Trade executed successfully for {market}",
                    data={
                        "market": market,
                        "position_id": position.entry_order_id,
                        "filled_orders": len(filled_orders),
                        "total_cost": sum(o.quantity_filled * (o.price_filled or 0) for o in filled_orders)
                    }
                )
            else:
                self.logger.warning(f"No orders filled for {market} trade")
        else:
            self.logger.error(f"Failed to execute trade for {market}")
    
    async def _manage_positions(self) -> None:
        """Manage existing positions (stop loss, take profit, monitoring)."""
        for position in self.state.active_positions:
            try:
                await self._manage_position(position)
            except Exception as e:
                self.logger.error(f"Error managing position {position.market}: {e}")
    
    async def _manage_position(self, position: Position) -> None:
        """Manage a specific position.
        
        Args:
            position: Position to manage
        """
        # Get current price
        tickers = await self.api_client.get_tickers([position.market])
        if not tickers:
            return
        
        current_price = float(tickers[0]['trade_price'])
        
        # Calculate unrealized P&L
        if position.side.value == "buy":
            unrealized_pnl = (current_price - position.entry_price) * position.quantity
        else:
            unrealized_pnl = (position.entry_price - current_price) * position.quantity
        
        position.unrealized_pnl = unrealized_pnl
        
        # For paper trading, simulate stop loss and take profit
        if self.env_config.trading_mode == "paper":
            should_close = False
            close_reason = ""
            
            # Check stop loss (approximate, using order IDs stored in position)
            if position.stop_loss_order_id:
                # For simplicity, we'll use a basic stop check
                # In a real system, this would be more sophisticated
                if position.side.value == "buy" and current_price <= position.entry_price * 0.95:
                    should_close = True
                    close_reason = "stop_loss"
                elif position.side.value == "sell" and current_price >= position.entry_price * 1.05:
                    should_close = True
                    close_reason = "stop_loss"
            
            # Check take profit
            if position.take_profit_order_id and not should_close:
                if position.side.value == "buy" and current_price >= position.entry_price * 1.10:
                    should_close = True
                    close_reason = "take_profit"
                elif position.side.value == "sell" and current_price <= position.entry_price * 0.90:
                    should_close = True
                    close_reason = "take_profit"
            
            if should_close:
                close_result = await self.order_executor.close_position(
                    position, current_price, close_reason
                )
                
                if close_result:
                    # Record trade result in risk guard
                    is_winning = position.realized_pnl > 0
                    self.risk_guard.record_trade_result(
                        position.market,
                        position.entry_price,
                        current_price,
                        position.quantity,
                        is_winning,
                        position.realized_pnl
                    )
    
    def _monitor_risk(self) -> None:
        """Monitor risk metrics and trigger alerts if needed."""
        risk_status = self.risk_guard.get_risk_status()
        
        # Log risk metrics periodically
        if get_kst_now().minute % 10 == 0:  # Every 10 minutes
            self.logger.info(
                "Risk status update",
                data={
                    "daily_pnl": risk_status['account']['daily_pnl'],
                    "daily_pnl_pct": risk_status['account']['daily_pnl_pct'],
                    "active_positions": len(self.state.active_positions),
                    "banned_markets": len(self.state.banned_markets),
                    "ddl_hit": self.state.ddl_hit
                }
            )
    
    async def _cleanup(self) -> None:
        """Cleanup resources and generate final report."""
        self.logger.info("Cleaning up trading system")
        
        # Close API client
        if self.api_client:
            await self.api_client.close()
        
        # Generate trading summary
        await self._generate_trading_summary()
        
        self.logger.info("Trading system cleanup completed")
    
    async def _generate_trading_summary(self) -> None:
        """Generate and log trading session summary."""
        end_time = get_kst_now()
        session_duration = end_time - self.state.start_time
        
        # Get trading statistics
        trading_stats = self.order_executor.get_trading_statistics()
        risk_status = self.risk_guard.get_risk_status()
        
        summary = {
            "session": {
                "start_time": self.state.start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_minutes": session_duration.total_seconds() / 60,
                "trading_mode": self.env_config.trading_mode
            },
            "performance": {
                "total_trades": self.state.total_trades,
                "winning_trades": self.state.winning_trades,
                "win_rate": self.state.winning_trades / max(self.state.total_trades, 1),
                "total_pnl": self.state.total_pnl,
                "daily_pnl": self.state.daily_pnl
            },
            "orders": trading_stats["orders"],
            "risk": {
                "ddl_hit": self.state.ddl_hit,
                "banned_markets": self.state.banned_markets,
                "max_positions": len(self.state.active_positions)
            }
        }
        
        # Save summary to file
        summary_file = f"runtime/reports/trading_summary_{self.state.start_time.strftime('%Y%m%d_%H%M%S')}.json"
        try:
            import os
            os.makedirs("runtime/reports", exist_ok=True)
            
            with open(summary_file, 'w') as f:
                json.dump(summary, f, indent=2, default=str)
            
            self.logger.info(f"Trading summary saved: {summary_file}")
        except Exception as e:
            self.logger.error(f"Failed to save trading summary: {e}")
        
        # Log summary
        self.logger.info(
            f"Trading session completed",
            data=summary
        )
    
    def stop_trading(self) -> None:
        """Stop the trading system gracefully."""
        self.should_stop = True
        self.logger.info("Trading system stop requested")
    
    def pause_trading_temporarily(self) -> None:
        """Pause trading temporarily."""
        self.pause_trading = True
        self.logger.info("Trading paused temporarily")
    
    def resume_trading(self) -> None:
        """Resume trading if conditions allow."""
        if not self.state.ddl_hit:
            self.pause_trading = False
            self.logger.info("Trading resumed")
        else:
            self.logger.warning("Cannot resume trading: DDL still hit")
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get current system status.
        
        Returns:
            System status dictionary
        """
        self._update_state()
        
        return {
            "system": {
                "is_running": self.state.is_running,
                "is_paused": self.pause_trading,
                "uptime_minutes": (get_kst_now() - self.state.start_time).total_seconds() / 60,
                "trading_mode": self.env_config.trading_mode
            },
            "market": {
                "is_trading_hours": self.state.is_trading_hours,
                "active_candidates": len(self.state.active_candidates),
                "next_scan_time": self.state.next_scan_time.isoformat()
            },
            "positions": {
                "active": len(self.state.active_positions),
                "markets": [pos.market for pos in self.state.active_positions]
            },
            "performance": {
                "total_trades": self.state.total_trades,
                "winning_trades": self.state.winning_trades,
                "total_pnl": self.state.total_pnl,
                "daily_pnl": self.state.daily_pnl
            },
            "risk": {
                "ddl_hit": self.state.ddl_hit,
                "banned_markets_count": len(self.state.banned_markets)
            }
        }
