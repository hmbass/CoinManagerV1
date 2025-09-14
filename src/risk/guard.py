"""Risk Guard System Implementation.

This module implements comprehensive risk management as specified
in requirement.md FR-7: Risk Guard.

Features:
- Position sizing (0.3~0.5% per trade)
- Daily drawdown limit (-1% stop)
- Consecutive loss prevention (2 losses = symbol ban)
- Risk-reward ratio validation
- Account balance monitoring
"""

import json
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path

from ..utils.config import RiskConfig
from ..utils.logging import get_trading_logger, log_performance
from ..utils.time_utils import get_kst_now, get_trading_day_start, get_trading_day_end
from ..utils.telegram import send_risk_notification
from ..signals.signal_manager import TradingSignal


logger = get_trading_logger(__name__)


@dataclass
class TradeRisk:
    """Risk metrics for a trade."""
    
    market: str
    entry_price: float
    stop_loss: float
    position_size: float
    risk_amount: float
    risk_percentage: float
    reward_amount: float
    risk_reward_ratio: float
    max_position_value: float


@dataclass
class DailyRisk:
    """Daily risk tracking."""
    
    date: str
    starting_balance: float
    current_balance: float
    daily_pnl: float
    daily_pnl_percentage: float
    max_daily_loss: float
    trades_today: int
    losing_trades_today: int
    is_ddl_hit: bool  # Daily Drawdown Limit


@dataclass
class MarketRisk:
    """Per-market risk tracking."""
    
    market: str
    consecutive_losses: int
    last_loss_date: Optional[str]
    total_trades: int
    winning_trades: int
    losing_trades: int
    is_banned: bool
    ban_expiry_date: Optional[str]


@dataclass
class RiskAssessment:
    """Risk assessment result."""
    
    is_allowed: bool
    trade_risk: Optional[TradeRisk]
    daily_risk: DailyRisk
    market_risk: MarketRisk
    rejection_reasons: List[str]
    warnings: List[str]


class RiskGuard:
    """Comprehensive risk management system.
    
    Implements requirement.md FR-7 specification:
    - 포지션 크기: 1회 거래당 0.3~0.5% 위험도
    - 일손실 한도: -1% 도달 시 당일 거래 중단
    - 연속 손절: 동일 종목 2회 연속 손절 시 거래 금지
    """
    
    def __init__(self, config: Optional[RiskConfig] = None, data_dir: str = "runtime/data"):
        """Initialize risk guard.
        
        Args:
            config: Risk management configuration
            data_dir: Directory for risk data storage
        """
        if config is None:
            from ..utils.config import get_config
            config = get_config().risk
        
        self.config = config
        self.logger = logger
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Risk tracking files
        self.daily_risk_file = self.data_dir / "daily_risk.json"
        self.market_risk_file = self.data_dir / "market_risk.json"
        
        # In-memory tracking
        self.current_balance: float = 0.0
        self.daily_risk: Optional[DailyRisk] = None
        self.market_risks: Dict[str, MarketRisk] = {}
        
        # Load existing risk data
        self._load_risk_data()
    
    def _load_risk_data(self) -> None:
        """Load risk tracking data from files."""
        # Load daily risk
        if self.daily_risk_file.exists():
            try:
                with open(self.daily_risk_file, 'r') as f:
                    data = json.load(f)
                    self.daily_risk = DailyRisk(**data)
            except Exception as e:
                self.logger.error(f"Error loading daily risk data: {e}")
                self.daily_risk = None
        
        # Load market risks
        if self.market_risk_file.exists():
            try:
                with open(self.market_risk_file, 'r') as f:
                    data = json.load(f)
                    self.market_risks = {
                        market: MarketRisk(**risk_data)
                        for market, risk_data in data.items()
                    }
            except Exception as e:
                self.logger.error(f"Error loading market risk data: {e}")
                self.market_risks = {}
    
    def _save_risk_data(self) -> None:
        """Save risk tracking data to files."""
        # Save daily risk
        if self.daily_risk:
            try:
                with open(self.daily_risk_file, 'w') as f:
                    json.dump(asdict(self.daily_risk), f, indent=2)
            except Exception as e:
                self.logger.error(f"Error saving daily risk data: {e}")
        
        # Save market risks
        try:
            data = {
                market: asdict(risk)
                for market, risk in self.market_risks.items()
            }
            with open(self.market_risk_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving market risk data: {e}")
    
    @log_performance
    def update_account_balance(self, balance: float) -> None:
        """Update current account balance.
        
        Args:
            balance: Current account balance in KRW
        """
        previous_balance = self.current_balance
        self.current_balance = balance
        
        # Initialize or update daily risk
        today = get_kst_now().date().isoformat()
        
        if not self.daily_risk or self.daily_risk.date != today:
            # New trading day
            self.daily_risk = DailyRisk(
                date=today,
                starting_balance=balance,
                current_balance=balance,
                daily_pnl=0.0,
                daily_pnl_percentage=0.0,
                max_daily_loss=balance * self.config.daily_drawdown_stop_pct,
                trades_today=0,
                losing_trades_today=0,
                is_ddl_hit=False
            )
        else:
            # Update existing day
            self.daily_risk.current_balance = balance
            self.daily_risk.daily_pnl = balance - self.daily_risk.starting_balance
            self.daily_risk.daily_pnl_percentage = (
                self.daily_risk.daily_pnl / self.daily_risk.starting_balance
            ) if self.daily_risk.starting_balance > 0 else 0.0
            
            # Check DDL
            if self.daily_risk.daily_pnl_percentage <= -self.config.daily_drawdown_stop_pct:
                if not self.daily_risk.is_ddl_hit:
                    self.daily_risk.is_ddl_hit = True
                    self.logger.warning(
                        f"Daily Drawdown Limit hit: {self.daily_risk.daily_pnl_percentage:.2%}",
                        data={
                            "daily_pnl": self.daily_risk.daily_pnl,
                            "daily_pnl_pct": self.daily_risk.daily_pnl_percentage,
                            "ddl_threshold": -self.config.daily_drawdown_stop_pct
                        }
                    )
                    
                    # Send Telegram alert for DDL
                    try:
                        import asyncio
                        asyncio.create_task(send_risk_notification(
                            "DAILY_DRAWDOWN_LIMIT",
                            f"Daily loss limit reached: {self.daily_risk.daily_pnl_percentage:.2%}\n"
                            f"Trading has been automatically suspended for today.\n"
                            f"Loss amount: {self.daily_risk.daily_pnl:,.0f} KRW",
                            "CRITICAL"
                        ))
                    except Exception as e:
                        self.logger.warning(f"Failed to send DDL Telegram alert: {e}")
        
        self._save_risk_data()
        
        self.logger.debug(
            f"Account balance updated: {previous_balance:,.0f} -> {balance:,.0f}",
            data={
                "previous_balance": previous_balance,
                "current_balance": balance,
                "daily_pnl": self.daily_risk.daily_pnl if self.daily_risk else 0,
                "daily_pnl_pct": self.daily_risk.daily_pnl_percentage if self.daily_risk else 0
            }
        )
    
    @log_performance
    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss: float,
        risk_percentage: Optional[float] = None
    ) -> Tuple[float, float]:
        """Calculate position size based on risk parameters.
        
        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            risk_percentage: Custom risk percentage (default: config value)
            
        Returns:
            Tuple of (position_size, risk_amount)
        """
        if risk_percentage is None:
            risk_percentage = self.config.per_trade_risk_pct
        
        if self.current_balance <= 0:
            self.logger.error("Cannot calculate position size: balance not set")
            return 0.0, 0.0
        
        # Calculate risk per unit
        risk_per_unit = abs(entry_price - stop_loss)
        
        if risk_per_unit <= 0:
            self.logger.error("Cannot calculate position size: invalid price levels")
            return 0.0, 0.0
        
        # Calculate maximum risk amount
        max_risk_amount = self.current_balance * risk_percentage
        
        # Calculate position size
        position_size = max_risk_amount / risk_per_unit
        
        # Apply position size limits
        min_position_value = self.config.min_position_krw
        max_position_value = self.config.max_position_krw
        
        position_value = position_size * entry_price
        
        if position_value < min_position_value:
            position_size = min_position_value / entry_price
        elif position_value > max_position_value:
            position_size = max_position_value / entry_price
        
        # Recalculate actual risk amount
        actual_risk_amount = position_size * risk_per_unit
        
        self.logger.debug(
            f"Position size calculated",
            data={
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "risk_per_unit": risk_per_unit,
                "position_size": position_size,
                "position_value": position_value,
                "risk_amount": actual_risk_amount,
                "risk_percentage": risk_percentage
            }
        )
        
        return position_size, actual_risk_amount
    
    @log_performance
    def assess_trade_risk(
        self,
        market: str,
        signal: TradingSignal,
        custom_risk_pct: Optional[float] = None
    ) -> RiskAssessment:
        """Assess risk for a potential trade.
        
        Args:
            market: Market symbol
            signal: Trading signal
            custom_risk_pct: Custom risk percentage
            
        Returns:
            Risk assessment result
        """
        rejection_reasons = []
        warnings = []
        
        # Get current daily risk
        if not self.daily_risk:
            self.update_account_balance(self.current_balance)
        
        daily_risk = self.daily_risk
        
        # Get or create market risk
        if market not in self.market_risks:
            self.market_risks[market] = MarketRisk(
                market=market,
                consecutive_losses=0,
                last_loss_date=None,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                is_banned=False,
                ban_expiry_date=None
            )
        
        market_risk = self.market_risks[market]
        
        # Check DDL
        if daily_risk.is_ddl_hit:
            rejection_reasons.append(f"Daily Drawdown Limit hit: {daily_risk.daily_pnl_percentage:.2%}")
        
        # Check market ban
        if market_risk.is_banned:
            today = get_kst_now().date().isoformat()
            if market_risk.ban_expiry_date and today >= market_risk.ban_expiry_date:
                # Ban expired
                market_risk.is_banned = False
                market_risk.ban_expiry_date = None
                market_risk.consecutive_losses = 0
            else:
                rejection_reasons.append(f"Market {market} is banned due to consecutive losses")
        
        # Check account balance
        if self.current_balance <= 0:
            rejection_reasons.append("Account balance not available")
        
        trade_risk = None
        
        if not rejection_reasons:
            # Calculate trade risk
            position_size, risk_amount = self.calculate_position_size(
                signal.entry_price,
                signal.stop_loss,
                custom_risk_pct
            )
            
            position_value = position_size * signal.entry_price
            risk_percentage = (risk_amount / self.current_balance) * 100 if self.current_balance > 0 else 0
            
            # Calculate reward amount
            if hasattr(signal, 'take_profit'):
                reward_amount = abs(signal.take_profit - signal.entry_price) * position_size
            else:
                reward_amount = risk_amount * 1.5  # Default 1.5R
            
            risk_reward_ratio = reward_amount / risk_amount if risk_amount > 0 else 0
            
            trade_risk = TradeRisk(
                market=market,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                position_size=position_size,
                risk_amount=risk_amount,
                risk_percentage=risk_percentage,
                reward_amount=reward_amount,
                risk_reward_ratio=risk_reward_ratio,
                max_position_value=position_value
            )
            
            # Validate risk-reward ratio
            if risk_reward_ratio < self.config.min_risk_reward_ratio:
                rejection_reasons.append(f"Poor risk-reward ratio: {risk_reward_ratio:.2f}")
            
            # Check position size limits
            if position_value < self.config.min_position_krw:
                warnings.append(f"Position size below minimum: {position_value:,.0f} KRW")
            elif position_value > self.config.max_position_krw:
                warnings.append(f"Position size capped at maximum: {self.config.max_position_krw:,.0f} KRW")
            
            # Warn about consecutive losses
            if market_risk.consecutive_losses >= 1:
                warnings.append(f"Market has {market_risk.consecutive_losses} consecutive losses")
        
        is_allowed = len(rejection_reasons) == 0
        
        assessment = RiskAssessment(
            is_allowed=is_allowed,
            trade_risk=trade_risk,
            daily_risk=daily_risk,
            market_risk=market_risk,
            rejection_reasons=rejection_reasons,
            warnings=warnings
        )
        
        self.logger.info(
            f"Trade risk assessment for {market}: {'ALLOWED' if is_allowed else 'REJECTED'}",
            data={
                "market": market,
                "is_allowed": is_allowed,
                "position_size": trade_risk.position_size if trade_risk else 0,
                "risk_amount": trade_risk.risk_amount if trade_risk else 0,
                "risk_reward_ratio": trade_risk.risk_reward_ratio if trade_risk else 0,
                "rejection_reasons": rejection_reasons,
                "warnings": warnings
            }
        )
        
        return assessment
    
    def record_trade_result(
        self,
        market: str,
        entry_price: float,
        exit_price: float,
        position_size: float,
        is_winning_trade: bool,
        pnl: float
    ) -> None:
        """Record trade result for risk tracking.
        
        Args:
            market: Market symbol
            entry_price: Entry price
            exit_price: Exit price
            position_size: Position size
            is_winning_trade: Whether trade was profitable
            pnl: Profit/loss amount
        """
        # Update daily risk
        if self.daily_risk:
            self.daily_risk.trades_today += 1
            if not is_winning_trade:
                self.daily_risk.losing_trades_today += 1
        
        # Update market risk
        if market not in self.market_risks:
            self.market_risks[market] = MarketRisk(
                market=market,
                consecutive_losses=0,
                last_loss_date=None,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                is_banned=False,
                ban_expiry_date=None
            )
        
        market_risk = self.market_risks[market]
        market_risk.total_trades += 1
        
        if is_winning_trade:
            market_risk.winning_trades += 1
            market_risk.consecutive_losses = 0  # Reset consecutive losses
        else:
            market_risk.losing_trades += 1
            market_risk.consecutive_losses += 1
            market_risk.last_loss_date = get_kst_now().date().isoformat()
            
            # Check if market should be banned
            if market_risk.consecutive_losses >= self.config.same_symbol_consecutive_losses_stop:
                market_risk.is_banned = True
                # Ban for 1 day
                ban_date = get_kst_now().date() + timedelta(days=1)
                market_risk.ban_expiry_date = ban_date.isoformat()
                
                self.logger.warning(
                    f"Market {market} banned due to {market_risk.consecutive_losses} consecutive losses",
                    data={
                        "market": market,
                        "consecutive_losses": market_risk.consecutive_losses,
                        "ban_expiry": market_risk.ban_expiry_date
                    }
                )
                
                # Send Telegram alert for market ban
                try:
                    import asyncio
                    asyncio.create_task(send_risk_notification(
                        "MARKET_BANNED",
                        f"Market {market} has been banned from trading.\n"
                        f"Reason: {market_risk.consecutive_losses} consecutive losses\n"
                        f"Ban expires: {ban_date.strftime('%Y-%m-%d')}",
                        "WARNING"
                    ))
                except Exception as e:
                    self.logger.warning(f"Failed to send market ban Telegram alert: {e}")
        
        # Update account balance (this will also update daily risk)
        new_balance = self.current_balance + pnl
        self.update_account_balance(new_balance)
        
        self._save_risk_data()
        
        self.logger.info(
            f"Trade result recorded for {market}",
            data={
                "market": market,
                "is_winning": is_winning_trade,
                "pnl": pnl,
                "consecutive_losses": market_risk.consecutive_losses,
                "is_banned": market_risk.is_banned,
                "daily_trades": self.daily_risk.trades_today if self.daily_risk else 0
            }
        )
    
    def get_risk_status(self) -> Dict[str, Any]:
        """Get current risk status summary.
        
        Returns:
            Risk status dictionary
        """
        status = {
            "account": {
                "current_balance": self.current_balance,
                "daily_pnl": self.daily_risk.daily_pnl if self.daily_risk else 0,
                "daily_pnl_pct": self.daily_risk.daily_pnl_percentage if self.daily_risk else 0,
                "ddl_hit": self.daily_risk.is_ddl_hit if self.daily_risk else False
            },
            "daily": {
                "trades_today": self.daily_risk.trades_today if self.daily_risk else 0,
                "losing_trades_today": self.daily_risk.losing_trades_today if self.daily_risk else 0,
                "max_daily_loss": self.daily_risk.max_daily_loss if self.daily_risk else 0
            },
            "markets": {
                "banned_markets": [
                    market for market, risk in self.market_risks.items()
                    if risk.is_banned
                ],
                "at_risk_markets": [
                    market for market, risk in self.market_risks.items()
                    if risk.consecutive_losses >= 1 and not risk.is_banned
                ],
                "total_markets_traded": len(self.market_risks)
            },
            "limits": {
                "per_trade_risk_pct": self.config.per_trade_risk_pct * 100,
                "daily_drawdown_limit_pct": self.config.daily_drawdown_stop_pct * 100,
                "consecutive_loss_limit": self.config.same_symbol_consecutive_losses_stop,
                "min_position_krw": self.config.min_position_krw,
                "max_position_krw": self.config.max_position_krw
            }
        }
        
        return status
    
    def reset_daily_risk(self, starting_balance: Optional[float] = None) -> None:
        """Reset daily risk tracking (for new trading day).
        
        Args:
            starting_balance: Starting balance for new day (default: current balance)
        """
        if starting_balance is None:
            starting_balance = self.current_balance
        
        today = get_kst_now().date().isoformat()
        
        self.daily_risk = DailyRisk(
            date=today,
            starting_balance=starting_balance,
            current_balance=starting_balance,
            daily_pnl=0.0,
            daily_pnl_percentage=0.0,
            max_daily_loss=starting_balance * self.config.daily_drawdown_stop_pct,
            trades_today=0,
            losing_trades_today=0,
            is_ddl_hit=False
        )
        
        self._save_risk_data()
        
        self.logger.info(
            f"Daily risk reset for {today}",
            data={
                "date": today,
                "starting_balance": starting_balance,
                "max_daily_loss": self.daily_risk.max_daily_loss
            }
        )
    
    def clear_market_bans(self) -> int:
        """Clear expired market bans.
        
        Returns:
            Number of bans cleared
        """
        cleared_count = 0
        today = get_kst_now().date().isoformat()
        
        for market, risk in self.market_risks.items():
            if risk.is_banned and risk.ban_expiry_date and today >= risk.ban_expiry_date:
                risk.is_banned = False
                risk.ban_expiry_date = None
                risk.consecutive_losses = 0
                cleared_count += 1
                
                self.logger.info(f"Market ban cleared for {market}")
        
        if cleared_count > 0:
            self._save_risk_data()
        
        return cleared_count
