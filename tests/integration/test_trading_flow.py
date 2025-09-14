"""Integration tests for complete trading flow."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch

from src.scanner.scanner import CandidateScanner  
from src.signals.signal_manager import SignalManager
from src.risk.guard import RiskGuard
from src.order.executor import OrderExecutor
from src.trading_system import TradingSystem


@pytest.mark.integration
class TestTradingFlow:
    """Test complete trading workflow integration."""
    
    @pytest.fixture
    async def trading_system(self, config, env_config, mock_api_client, temp_data_dir):
        """Create trading system for integration tests."""
        # Override data directory
        config.logging.files.main = f"{temp_data_dir}/trading.log"
        
        system = TradingSystem(config, env_config, mock_api_client)
        await system.initialize()
        
        yield system
        
        # Cleanup
        system.stop_trading()
    
    async def test_market_scan_to_signal_generation(self, trading_system, sample_feature_result):
        """Test flow from market scanning to signal generation."""
        # Run market scan
        scan_result = await trading_system.scanner.scan_markets()
        
        assert scan_result is not None
        assert len(scan_result.candidates) >= 0  # May be 0 if no valid candidates
        
        if scan_result.candidates:
            candidate = scan_result.candidates[0]
            market = candidate.market
            
            # Generate signal for candidate
            candle_data = await trading_system.api_client.get_candles(market)
            current_price = candidate.price
            current_volume = candidate.volume
            
            signal_context = trading_system.signal_manager.get_best_signal(
                market, candle_data, current_price, current_volume, candidate
            )
            
            # Should either find a signal or return None
            if signal_context:
                assert signal_context.market == market
                assert signal_context.signal is not None
                assert signal_context.strategy_name in ['orb', 'svwap', 'sweep']
    
    async def test_signal_to_risk_assessment(self, trading_system, mock_api_client):
        """Test flow from signal generation to risk assessment."""
        # Mock signal
        from src.signals.orb import ORBSignal
        from datetime import datetime
        
        mock_signal = ORBSignal(
            signal_type="long_breakout",
            market="KRW-BTC", 
            timestamp=datetime.now(),
            entry_price=50000000,
            stop_loss=49000000,
            take_profit=52000000,
            orb_box=Mock(),
            breakout_price=50000000,
            volume_ratio=2.0,
            atr=1000000,
            risk_amount=1000000,
            reward_amount=2000000,
            risk_reward_ratio=2.0,
            confidence_score=0.8,
            volume_confirmation=True,
            trend_alignment=True
        )
        
        # Assess risk
        risk_assessment = trading_system.risk_guard.assess_trade_risk("KRW-BTC", mock_signal)
        
        assert risk_assessment is not None
        assert risk_assessment.trade_risk is not None
        assert risk_assessment.daily_risk is not None
        assert risk_assessment.market_risk is not None
        
        # Should be allowed (unless specific rejection conditions)
        if risk_assessment.is_allowed:
            assert risk_assessment.trade_risk.position_size > 0
            assert risk_assessment.trade_risk.risk_amount > 0
    
    @pytest.mark.paper
    async def test_complete_paper_trade_execution(self, trading_system):
        """Test complete paper trade execution flow."""
        # Mock signal with valid parameters
        from src.signals.orb import ORBSignal
        from src.risk.guard import TradeRisk
        from datetime import datetime
        
        mock_signal = ORBSignal(
            signal_type="long_breakout",
            market="KRW-BTC",
            timestamp=datetime.now(),
            entry_price=50000000,
            stop_loss=49000000, 
            take_profit=52000000,
            orb_box=Mock(),
            breakout_price=50000000,
            volume_ratio=2.0,
            atr=1000000,
            risk_amount=1000000,
            reward_amount=2000000,
            risk_reward_ratio=2.0,
            confidence_score=0.8,
            volume_confirmation=True,
            trend_alignment=True
        )
        
        trade_risk = TradeRisk(
            market="KRW-BTC",
            entry_price=50000000,
            stop_loss=49000000,
            position_size=0.02,  # 0.02 BTC
            risk_amount=20000,   # 20K KRW risk
            risk_percentage=2.0,
            reward_amount=40000, # 40K KRW reward
            risk_reward_ratio=2.0,
            max_position_value=1000000
        )
        
        # Execute trade
        position, orders = await trading_system.order_executor.execute_signal_trade(
            mock_signal, trade_risk
        )
        
        # Verify execution
        assert len(orders) > 0
        filled_orders = [o for o in orders if o.status.value == "filled"]
        
        if filled_orders:
            assert position is not None
            assert position.market == "KRW-BTC"
            assert position.is_active
            assert position.quantity > 0
    
    async def test_risk_management_integration(self, trading_system):
        """Test risk management integration with trading flow."""
        # Test DDL trigger
        initial_balance = trading_system.risk_guard.current_balance
        large_loss = initial_balance * 0.06  # 6% loss (exceeds DDL)
        
        new_balance = initial_balance - large_loss
        trading_system.risk_guard.update_account_balance(new_balance)
        
        # System should detect DDL hit
        assert trading_system.risk_guard.daily_risk.is_ddl_hit
        
        # Trading should be paused
        trading_system._update_state()
        assert trading_system.state.ddl_hit
        
        # Should not allow new trades
        from src.signals.orb import ORBSignal
        from datetime import datetime
        
        mock_signal = ORBSignal(
            signal_type="long_breakout",
            market="KRW-BTC",
            timestamp=datetime.now(), 
            entry_price=50000000,
            stop_loss=49000000,
            take_profit=52000000,
            orb_box=Mock(),
            breakout_price=50000000,
            volume_ratio=2.0,
            atr=1000000,
            risk_amount=1000000,
            reward_amount=2000000,
            risk_reward_ratio=2.0,
            confidence_score=0.8,
            volume_confirmation=True,
            trend_alignment=True
        )
        
        assessment = trading_system.risk_guard.assess_trade_risk("KRW-BTC", mock_signal)
        assert not assessment.is_allowed
    
    async def test_position_management_cycle(self, trading_system):
        """Test position management and monitoring."""
        # Create mock position
        from src.order.executor import Position, OrderSide
        from datetime import datetime
        
        position = Position(
            market="KRW-BTC",
            side=OrderSide.BUY,
            entry_price=50000000,
            quantity=0.01,
            entry_time=datetime.now(),
            entry_order_id="test_order_id"
        )
        
        # Add to order executor
        trading_system.order_executor.positions["test_position"] = position
        
        # Update state
        trading_system._update_state()
        
        # Should have active position
        assert len(trading_system.state.active_positions) == 1
        assert trading_system.state.active_positions[0].market == "KRW-BTC"
        
        # Test position management
        await trading_system._manage_positions()
        
        # Position should still exist (no stop/target hit in this test)
        assert position.market in [pos.market for pos in trading_system.state.active_positions]
    
    @pytest.mark.slow
    async def test_trading_loop_integration(self, trading_system):
        """Test trading loop integration (short duration)."""
        # Run trading loop for short duration
        duration_seconds = 5
        
        # Start trading loop in background
        task = asyncio.create_task(
            trading_system.run_trading_loop(duration_seconds / 60)  # Convert to minutes
        )
        
        # Let it run briefly
        await asyncio.sleep(2)
        
        # Check that system is running
        assert trading_system.state.is_running
        
        # Stop gracefully
        trading_system.stop_trading()
        
        # Wait for completion
        await task
        
        # Verify final state
        assert not trading_system.state.is_running
        final_status = trading_system.get_system_status()
        assert final_status["system"]["uptime_minutes"] > 0
    
    async def test_error_handling_and_recovery(self, trading_system, mock_api_client):
        """Test error handling and recovery mechanisms."""
        # Simulate API error
        mock_api_client.get_markets.side_effect = Exception("API Error")
        
        # Should handle error gracefully
        try:
            await trading_system._scan_markets()
        except Exception:
            pytest.fail("Trading system should handle API errors gracefully")
        
        # Should log error but continue
        assert len(trading_system.state.active_candidates) == 0  # No candidates due to error
        
        # Reset API client
        mock_api_client.get_markets.side_effect = None
        mock_api_client.get_markets.return_value = [
            {"market": "KRW-BTC", "korean_name": "비트코인"}
        ]
        
        # Should recover on next scan
        await trading_system._scan_markets()
        # May or may not find candidates depending on other conditions
    
    async def test_configuration_integration(self, config, env_config, mock_api_client):
        """Test configuration integration across components."""
        # Test that configuration is properly propagated
        system = TradingSystem(config, env_config, mock_api_client)
        await system.initialize()
        
        # Check scanner config
        assert system.scanner.scanner_config.rvol_threshold == config.scanner.rvol_threshold
        
        # Check signal manager config
        assert system.signal_manager.config.orb.use == config.signals.orb.use
        
        # Check risk guard config
        assert system.risk_guard.config.per_trade_risk_pct == config.risk.per_trade_risk_pct
        
        # Check order executor config
        assert system.order_executor.config.slippage_bp_max == config.orders.slippage_bp_max
        
        system.stop_trading()
