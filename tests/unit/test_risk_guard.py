"""Unit tests for risk management module."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock

from src.risk.guard import RiskGuard, TradeRisk, DailyRisk, MarketRisk
from src.utils.config import RiskConfig
from src.signals.orb import ORBSignal


@pytest.mark.unit
class TestRiskGuard:
    """Test risk management functionality."""
    
    def setup_method(self, temp_data_dir):
        """Set up test fixtures."""
        config = RiskConfig(
            per_trade_risk_pct=0.01,  # 1% per trade
            min_position_krw=10000,
            max_position_krw=100000,
            daily_drawdown_stop_pct=0.05,  # 5% daily limit
            same_symbol_consecutive_losses_stop=2,
            min_risk_reward_ratio=1.5
        )
        self.risk_guard = RiskGuard(config, temp_data_dir)
        self.risk_guard.update_account_balance(1000000)  # 1M KRW
    
    def test_update_account_balance(self):
        """Test account balance updates."""
        initial_balance = 1000000
        self.risk_guard.update_account_balance(initial_balance)
        
        assert self.risk_guard.current_balance == initial_balance
        assert self.risk_guard.daily_risk is not None
        assert self.risk_guard.daily_risk.starting_balance == initial_balance
    
    def test_calculate_position_size_basic(self):
        """Test basic position size calculation."""
        entry_price = 50000
        stop_loss = 49000  # 1000 KRW risk per unit
        
        position_size, risk_amount = self.risk_guard.calculate_position_size(
            entry_price, stop_loss, risk_percentage=0.01
        )
        
        expected_risk = 1000000 * 0.01  # 10,000 KRW max risk
        expected_position_size = expected_risk / 1000  # 10 units
        
        assert abs(position_size - expected_position_size) < 0.01
        assert abs(risk_amount - expected_risk) < 1
    
    def test_calculate_position_size_limits(self):
        """Test position size limits."""
        entry_price = 50000
        stop_loss = 49999  # Very small risk per unit
        
        position_size, risk_amount = self.risk_guard.calculate_position_size(
            entry_price, stop_loss
        )
        
        # Should hit minimum position value limit
        min_position_value = self.risk_guard.config.min_position_krw
        expected_position_size = min_position_value / entry_price
        
        assert abs(position_size - expected_position_size) < 0.01
    
    def test_assess_trade_risk_allowed(self):
        """Test trade risk assessment - allowed trade."""
        signal = Mock()
        signal.market = "KRW-BTC"
        signal.entry_price = 50000
        signal.stop_loss = 49000
        signal.take_profit = 52000
        signal.signal_type = "long_breakout"
        
        assessment = self.risk_guard.assess_trade_risk("KRW-BTC", signal)
        
        assert assessment.is_allowed
        assert assessment.trade_risk is not None
        assert assessment.trade_risk.risk_reward_ratio > 1.0
        assert len(assessment.rejection_reasons) == 0
    
    def test_assess_trade_risk_rejected_ddl(self):
        """Test trade risk assessment - rejected due to DDL."""
        # Simulate DDL hit
        self.risk_guard.daily_risk.is_ddl_hit = True
        
        signal = Mock()
        signal.market = "KRW-BTC"
        signal.entry_price = 50000
        signal.stop_loss = 49000
        
        assessment = self.risk_guard.assess_trade_risk("KRW-BTC", signal)
        
        assert not assessment.is_allowed
        assert any("Daily Drawdown Limit" in reason for reason in assessment.rejection_reasons)
    
    def test_assess_trade_risk_rejected_banned_market(self):
        """Test trade risk assessment - rejected due to banned market."""
        # Ban a market
        self.risk_guard.market_risks["KRW-BTC"] = MarketRisk(
            market="KRW-BTC",
            consecutive_losses=2,
            last_loss_date=datetime.now().date().isoformat(),
            total_trades=5,
            winning_trades=2,
            losing_trades=3,
            is_banned=True,
            ban_expiry_date=(datetime.now() + timedelta(days=1)).date().isoformat()
        )
        
        signal = Mock()
        signal.market = "KRW-BTC"
        signal.entry_price = 50000
        signal.stop_loss = 49000
        
        assessment = self.risk_guard.assess_trade_risk("KRW-BTC", signal)
        
        assert not assessment.is_allowed
        assert any("banned" in reason for reason in assessment.rejection_reasons)
    
    def test_record_trade_result_winning(self):
        """Test recording winning trade result."""
        market = "KRW-BTC"
        initial_balance = self.risk_guard.current_balance
        pnl = 5000  # 5K profit
        
        self.risk_guard.record_trade_result(
            market=market,
            entry_price=50000,
            exit_price=51000,
            position_size=10,
            is_winning_trade=True,
            pnl=pnl
        )
        
        # Check balance update
        assert self.risk_guard.current_balance == initial_balance + pnl
        
        # Check market risk update
        market_risk = self.risk_guard.market_risks[market]
        assert market_risk.winning_trades == 1
        assert market_risk.consecutive_losses == 0
        assert not market_risk.is_banned
    
    def test_record_trade_result_losing_consecutive(self):
        """Test recording consecutive losing trades."""
        market = "KRW-BTC"
        
        # First loss
        self.risk_guard.record_trade_result(
            market=market, entry_price=50000, exit_price=49000,
            position_size=10, is_winning_trade=False, pnl=-10000
        )
        
        market_risk = self.risk_guard.market_risks[market]
        assert market_risk.consecutive_losses == 1
        assert not market_risk.is_banned
        
        # Second loss (should trigger ban)
        self.risk_guard.record_trade_result(
            market=market, entry_price=50000, exit_price=49000,
            position_size=10, is_winning_trade=False, pnl=-10000
        )
        
        market_risk = self.risk_guard.market_risks[market]
        assert market_risk.consecutive_losses == 2
        assert market_risk.is_banned
        assert market_risk.ban_expiry_date is not None
    
    def test_daily_drawdown_limit_trigger(self):
        """Test daily drawdown limit trigger."""
        # Simulate large loss
        large_loss = 60000  # 6% loss (exceeds 5% DDL)
        new_balance = self.risk_guard.current_balance - large_loss
        
        self.risk_guard.update_account_balance(new_balance)
        
        assert self.risk_guard.daily_risk.is_ddl_hit
        assert self.risk_guard.daily_risk.daily_pnl_percentage <= -0.05
    
    def test_get_risk_status(self):
        """Test risk status reporting."""
        # Add some test data
        self.risk_guard.market_risks["KRW-BTC"] = MarketRisk(
            market="KRW-BTC", consecutive_losses=1, last_loss_date=None,
            total_trades=3, winning_trades=2, losing_trades=1,
            is_banned=False, ban_expiry_date=None
        )
        
        self.risk_guard.market_risks["KRW-ETH"] = MarketRisk(
            market="KRW-ETH", consecutive_losses=2, last_loss_date=None,
            total_trades=2, winning_trades=0, losing_trades=2,
            is_banned=True, ban_expiry_date=(datetime.now() + timedelta(days=1)).date().isoformat()
        )
        
        status = self.risk_guard.get_risk_status()
        
        assert "account" in status
        assert "daily" in status
        assert "markets" in status
        assert "limits" in status
        
        assert len(status["markets"]["banned_markets"]) == 1
        assert len(status["markets"]["at_risk_markets"]) == 1
        assert status["markets"]["total_markets_traded"] == 2
    
    def test_reset_daily_risk(self):
        """Test daily risk reset."""
        # Modify current daily risk
        self.risk_guard.daily_risk.trades_today = 5
        self.risk_guard.daily_risk.daily_pnl = -10000
        
        # Reset
        starting_balance = 1500000
        self.risk_guard.reset_daily_risk(starting_balance)
        
        assert self.risk_guard.daily_risk.starting_balance == starting_balance
        assert self.risk_guard.daily_risk.trades_today == 0
        assert self.risk_guard.daily_risk.daily_pnl == 0.0
        assert not self.risk_guard.daily_risk.is_ddl_hit
    
    def test_clear_market_bans(self):
        """Test clearing expired market bans."""
        # Add expired ban
        expired_date = (datetime.now() - timedelta(days=1)).date().isoformat()
        self.risk_guard.market_risks["KRW-BTC"] = MarketRisk(
            market="KRW-BTC", consecutive_losses=2, last_loss_date=None,
            total_trades=2, winning_trades=0, losing_trades=2,
            is_banned=True, ban_expiry_date=expired_date
        )
        
        # Add active ban
        future_date = (datetime.now() + timedelta(days=1)).date().isoformat()
        self.risk_guard.market_risks["KRW-ETH"] = MarketRisk(
            market="KRW-ETH", consecutive_losses=2, last_loss_date=None,
            total_trades=2, winning_trades=0, losing_trades=2,
            is_banned=True, ban_expiry_date=future_date
        )
        
        cleared_count = self.risk_guard.clear_market_bans()
        
        assert cleared_count == 1
        assert not self.risk_guard.market_risks["KRW-BTC"].is_banned
        assert self.risk_guard.market_risks["KRW-ETH"].is_banned
