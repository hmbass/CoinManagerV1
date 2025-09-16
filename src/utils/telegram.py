"""Telegram notification service for trading alerts.

This module provides Telegram bot integration for sending trading notifications
including trade executions, risk alerts, and system status updates.
"""

import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

import httpx
from src.utils.logging import get_trading_logger
from src.utils.time_utils import get_kst_now


logger = get_trading_logger(__name__)


class TelegramNotifier:
    """Telegram notification service for trading system.
    
    Sends real-time notifications for:
    - Trade executions (buy/sell orders)
    - Risk management alerts (DDL hit, market bans)
    - System status updates
    - Performance summaries
    """
    
    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        """Initialize Telegram notifier.
        
        Args:
            bot_token: Telegram bot token
            chat_id: Telegram chat ID to send messages to
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = bool(bot_token and chat_id)
        self.logger = logger
        
        if self.enabled:
            self.base_url = f"https://api.telegram.org/bot{bot_token}"
        else:
            self.logger.warning("Telegram notifications disabled - missing bot_token or chat_id")
    
    async def send_message(
        self,
        message: str,
        parse_mode: str = "HTML",
        disable_notification: bool = False
    ) -> bool:
        """Send message via Telegram.
        
        Args:
            message: Message text to send
            parse_mode: Telegram parse mode (HTML/Markdown)
            disable_notification: Send silently
            
        Returns:
            True if message sent successfully
        """
        if not self.enabled:
            self.logger.debug(f"Telegram disabled - would send: {message}")
            return False
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": message,
                        "parse_mode": parse_mode,
                        "disable_notification": disable_notification
                    }
                )
                
                if response.status_code == 200:
                    self.logger.debug("Telegram message sent successfully")
                    return True
                else:
                    self.logger.error(f"Telegram API error: {response.status_code} - {response.text}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Failed to send Telegram message: {e}")
            return False
    
    async def send_trade_alert(
        self,
        trade_type: str,  # "BUY" or "SELL"
        market: str,
        quantity: float,
        price: float,
        total_value: float,
        strategy: str,
        is_paper: bool = False,
        reason: Optional[str] = None,
        score: Optional[float] = None,
        indicators: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Send trading execution alert.
        
        Args:
            trade_type: "BUY" or "SELL"
            market: Market symbol
            quantity: Quantity traded
            price: Execution price
            total_value: Total trade value in KRW
            strategy: Trading strategy used
            is_paper: Whether this is paper trading
            reason: Trading reason/signal description
            score: Trading signal score
            indicators: Technical indicators used
            
        Returns:
            True if sent successfully
        """
        mode_emoji = "📝" if is_paper else "💰"
        type_emoji = "🟢" if trade_type == "BUY" else "🔴"
        
        timestamp = get_kst_now().strftime("%H:%M:%S")
        
        # Base message
        message = f"""
{mode_emoji} <b>{'PAPER' if is_paper else 'LIVE'} TRADING ALERT</b>

{type_emoji} <b>{trade_type} EXECUTED</b>
🏪 Market: <code>{market}</code>
📊 Strategy: <code>{strategy}</code>

💎 Quantity: <code>{quantity:.8f}</code>
💰 Price: <code>{price:,.0f} KRW</code>
💸 Total: <code>{total_value:,.0f} KRW</code>"""
        
        # Add score if provided
        if score is not None:
            message += f"\n🎯 Score: <code>{score:.3f}</code>"
        
        # Add reason if provided
        if reason:
            message += f"\n📋 Reason: <code>{reason}</code>"
        
        # Add indicators if provided
        if indicators:
            message += "\n\n📈 <b>Technical Indicators:</b>"
            if 'rvol' in indicators:
                message += f"\n• RVOL: <code>{indicators['rvol']:.2f}</code>"
            if 'rs' in indicators:
                rs_pct = indicators['rs'] * 100
                message += f"\n• RS: <code>{rs_pct:+.2f}%</code>"
            if 'trend' in indicators:
                trend_emoji = "✅" if indicators['trend'] else "❌"
                message += f"\n• Trend: {trend_emoji}"
            if 'ema20' in indicators and 'ema50' in indicators:
                message += f"\n• EMA20: <code>{indicators['ema20']:,.0f}</code>"
                message += f"\n• EMA50: <code>{indicators['ema50']:,.0f}</code>"
            if 'svwap' in indicators:
                message += f"\n• sVWAP: <code>{indicators['svwap']:,.0f}</code>"
            if 'atr' in indicators:
                message += f"\n• ATR: <code>{indicators['atr']:.2f}</code>"
        
        message += f"\n\n⏰ Time: <code>{timestamp} KST</code>"
        
        # Add paper mode reminder
        if is_paper:
            message += "\n\n📝 <i>This is a paper trading simulation</i>"
        
        return await self.send_message(message.strip())
    
    async def send_candidate_alert(
        self,
        candidates: list,
        scan_duration: float,
        total_markets: int,
        is_paper: bool = False
    ) -> bool:
        """Send market scan candidates alert.
        
        Args:
            candidates: List of trading candidates
            scan_duration: Scan duration in seconds
            total_markets: Total markets scanned
            is_paper: Whether this is paper trading mode
            
        Returns:
            True if sent successfully
        """
        mode_emoji = "📝" if is_paper else "💰"
        timestamp = get_kst_now().strftime("%H:%M:%S")
        
        message = f"""
{mode_emoji} <b>{'PAPER' if is_paper else 'LIVE'} MARKET SCAN COMPLETE</b>

🔍 <b>Scan Results:</b>
📊 Markets Scanned: <code>{total_markets}</code>
🎯 Candidates Found: <code>{len(candidates)}</code>
⏱️ Duration: <code>{scan_duration:.1f}s</code>
        """
        
        if candidates:
            message += "\n\n🏆 <b>Top Candidates:</b>"
            for i, candidate in enumerate(candidates[:3], 1):
                market = candidate.get('market', 'N/A')
                score = candidate.get('score', 0)
                rvol = candidate.get('rvol', 0)
                rs = candidate.get('rs', 0) * 100  # Convert to percentage
                trend = candidate.get('trend', 0)
                
                trend_emoji = "✅" if trend else "❌"
                
                message += f"""
#{i} <code>{market}</code>
   Score: <code>{score:.3f}</code> | RVOL: <code>{rvol:.2f}</code>
   RS: <code>{rs:+.2f}%</code> | Trend: {trend_emoji}"""
        else:
            message += "\n\n❌ <b>No candidates found this scan</b>"
        
        message += f"\n\n⏰ Time: <code>{timestamp} KST</code>"
        
        if is_paper:
            message += "\n\n📝 <i>Paper trading mode - Ready for simulation</i>"
        
        return await self.send_message(message.strip())
    
    async def send_position_update(
        self,
        market: str,
        action: str,  # "OPENED", "CLOSED", "UPDATED"
        current_pnl: float,
        current_pnl_pct: float,
        entry_price: float,
        current_price: float,
        quantity: float,
        reason: Optional[str] = None,
        is_paper: bool = False
    ) -> bool:
        """Send position update alert.
        
        Args:
            market: Market symbol
            action: Position action
            current_pnl: Current P&L in KRW
            current_pnl_pct: Current P&L percentage
            entry_price: Entry price
            current_price: Current price
            quantity: Position quantity
            reason: Update reason
            is_paper: Whether this is paper trading
            
        Returns:
            True if sent successfully
        """
        mode_emoji = "📝" if is_paper else "💰"
        
        # Action emojis
        action_emojis = {
            "OPENED": "🟢",
            "CLOSED": "🔴" if current_pnl < 0 else "🟢",
            "UPDATED": "🔄"
        }
        
        action_emoji = action_emojis.get(action, "📊")
        pnl_emoji = "📈" if current_pnl >= 0 else "📉"
        
        timestamp = get_kst_now().strftime("%H:%M:%S")
        
        message = f"""
{mode_emoji} <b>{'PAPER' if is_paper else 'LIVE'} POSITION {action}</b>

{action_emoji} <b>{market}</b>
📊 Quantity: <code>{quantity:.8f}</code>
💰 Entry: <code>{entry_price:,.0f} KRW</code>
📈 Current: <code>{current_price:,.0f} KRW</code>

{pnl_emoji} <b>P&L: {current_pnl:+,.0f} KRW ({current_pnl_pct:+.2f}%)</b>"""
        
        if reason:
            message += f"\n📋 Reason: <code>{reason}</code>"
        
        message += f"\n\n⏰ Time: <code>{timestamp} KST</code>"
        
        if is_paper:
            message += "\n\n📝 <i>Paper trading simulation</i>"
        
        return await self.send_message(message.strip())
    
    async def send_risk_alert(
        self,
        alert_type: str,
        message: str,
        severity: str = "WARNING"
    ) -> bool:
        """Send risk management alert.
        
        Args:
            alert_type: Type of alert (DDL_HIT, MARKET_BANNED, etc.)
            message: Alert message
            severity: Severity level
            
        Returns:
            True if sent successfully
        """
        severity_emojis = {
            "INFO": "ℹ️",
            "WARNING": "⚠️",
            "CRITICAL": "🚨"
        }
        
        emoji = severity_emojis.get(severity, "⚠️")
        timestamp = get_kst_now().strftime("%H:%M:%S")
        
        alert_message = f"""
{emoji} <b>RISK ALERT - {severity}</b>

🔥 Alert Type: <code>{alert_type}</code>
📝 Message: {message}

⏰ Time: <code>{timestamp} KST</code>
        """.strip()
        
        return await self.send_message(alert_message)
    
    async def send_position_update(
        self,
        market: str,
        action: str,  # "OPENED", "CLOSED", "UPDATED"
        entry_price: Optional[float] = None,
        exit_price: Optional[float] = None,
        pnl: Optional[float] = None,
        reason: Optional[str] = None,
        is_paper: bool = False
    ) -> bool:
        """Send position update notification.
        
        Args:
            market: Market symbol
            action: Position action
            entry_price: Entry price (for OPENED)
            exit_price: Exit price (for CLOSED)
            pnl: P&L amount (for CLOSED)
            reason: Reason for action
            is_paper: Whether this is paper trading
            
        Returns:
            True if sent successfully
        """
        mode_emoji = "📝" if is_paper else "💰"
        
        if action == "OPENED":
            action_emoji = "🎯"
            price_info = f"💰 Entry: <code>{entry_price:,.0f} KRW</code>"
        elif action == "CLOSED":
            action_emoji = "🏁"
            pnl_emoji = "🎉" if pnl > 0 else "😞" if pnl < 0 else "😐"
            price_info = f"""💰 Exit: <code>{exit_price:,.0f} KRW</code>
{pnl_emoji} P&L: <code>{pnl:+,.0f} KRW</code>"""
        else:
            action_emoji = "📊"
            price_info = ""
        
        timestamp = get_kst_now().strftime("%H:%M:%S")
        
        message = f"""
{mode_emoji} <b>POSITION {action}</b>

{action_emoji} <b>{market}</b>
{price_info}
        """.strip()
        
        if reason:
            message += f"\n📋 Reason: <code>{reason}</code>"
        
        message += f"\n⏰ Time: <code>{timestamp} KST</code>"
        
        return await self.send_message(message)
    
    async def send_daily_summary(
        self,
        total_trades: int,
        winning_trades: int,
        total_pnl: float,
        win_rate: float,
        best_trade: Optional[float] = None,
        worst_trade: Optional[float] = None,
        is_paper: bool = False,
        strategies_used: Optional[Dict[str, int]] = None,
        total_scans: Optional[int] = None,
        avg_scan_duration: Optional[float] = None
    ) -> bool:
        """Send daily trading summary.
        
        Args:
            total_trades: Total number of trades
            winning_trades: Number of winning trades
            total_pnl: Total P&L for the day
            win_rate: Win rate percentage
            best_trade: Best trade P&L
            worst_trade: Worst trade P&L
            is_paper: Whether this is paper trading
            strategies_used: Dictionary of strategies and their usage count
            total_scans: Total number of market scans
            avg_scan_duration: Average scan duration
            
        Returns:
            True if sent successfully
        """
        mode_emoji = "📝" if is_paper else "💰"
        pnl_emoji = "📈" if total_pnl > 0 else "📉" if total_pnl < 0 else "➡️"
        
        today = get_kst_now().strftime("%Y-%m-%d")
        
        # Header with mode indication
        mode_text = "PAPER TRADING" if is_paper else "LIVE TRADING"
        message = f"""
{mode_emoji} <b>{mode_text} DAILY SUMMARY</b>
📅 <b>{today}</b>

📊 <b>Trading Performance</b>
🎯 Total Trades: <code>{total_trades}</code>
🏆 Winning Trades: <code>{winning_trades}</code>
📈 Win Rate: <code>{win_rate:.1f}%</code>

{pnl_emoji} <b>P&L Summary</b>
💰 Total P&L: <code>{total_pnl:+,.0f} KRW</code>"""
        
        if best_trade is not None:
            message += f"\n🎉 Best Trade: <code>{best_trade:+,.0f} KRW</code>"
        
        if worst_trade is not None:
            message += f"\n😞 Worst Trade: <code>{worst_trade:+,.0f} KRW</code>"
        
        # Add scanning statistics for paper mode
        if is_paper and total_scans is not None:
            message += f"\n\n🔍 <b>Scanning Statistics</b>"
            message += f"\n📊 Total Scans: <code>{total_scans}</code>"
            if avg_scan_duration is not None:
                message += f"\n⏱️ Avg Duration: <code>{avg_scan_duration:.1f}s</code>"
        
        # Add strategy breakdown
        if strategies_used:
            message += f"\n\n📊 <b>Strategies Used</b>"
            for strategy, count in strategies_used.items():
                message += f"\n• {strategy}: <code>{count}</code> trades"
        
        # Add paper mode reminder
        if is_paper:
            message += f"\n\n📝 <i>Paper trading test results</i>"
            message += f"\n💡 <i>Monitor performance before going live!</i>"
        
        return await self.send_message(message)
    
    async def send_system_status(
        self,
        status: str,  # "STARTED", "STOPPED", "ERROR"
        uptime_minutes: Optional[float] = None,
        error_message: Optional[str] = None
    ) -> bool:
        """Send system status notification.
        
        Args:
            status: System status
            uptime_minutes: System uptime in minutes
            error_message: Error message if status is ERROR
            
        Returns:
            True if sent successfully
        """
        status_emojis = {
            "STARTED": "🚀",
            "STOPPED": "⏹️",
            "ERROR": "🚨",
            "HEALTHY": "💚"
        }
        
        emoji = status_emojis.get(status, "ℹ️")
        timestamp = get_kst_now().strftime("%H:%M:%S")
        
        message = f"""
{emoji} <b>SYSTEM {status}</b>

⏰ Time: <code>{timestamp} KST</code>
        """.strip()
        
        if uptime_minutes is not None:
            hours = int(uptime_minutes // 60)
            minutes = int(uptime_minutes % 60)
            message += f"\n⏱️ Uptime: <code>{hours}h {minutes}m</code>"
        
        if error_message:
            message += f"\n❌ Error: <code>{error_message}</code>"
        
        return await self.send_message(message)
    
    async def test_connection(self) -> bool:
        """Test Telegram bot connection.
        
        Returns:
            True if connection is successful
        """
        if not self.enabled:
            return False
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/getMe")
                
                if response.status_code == 200:
                    bot_info = response.json()
                    bot_name = bot_info.get('result', {}).get('first_name', 'Unknown')
                    self.logger.info(f"Telegram bot connection successful: {bot_name}")
                    
                    # Send test message
                    await self.send_message(
                        "🤖 <b>Bot Connection Test</b>\n\n✅ Telegram notifications are working!",
                        disable_notification=True
                    )
                    
                    return True
                else:
                    self.logger.error(f"Telegram bot connection failed: {response.status_code}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Telegram connection test failed: {e}")
            return False


# Global notifier instance
_telegram_notifier: Optional[TelegramNotifier] = None


def get_telegram_notifier() -> Optional[TelegramNotifier]:
    """Get global Telegram notifier instance.
    
    Returns:
        TelegramNotifier instance or None if not configured
    """
    global _telegram_notifier
    
    if _telegram_notifier is None:
        try:
            import os
            from dotenv import load_dotenv
            
            load_dotenv()
            
            bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
            chat_id = os.getenv('TELEGRAM_CHAT_ID')
            
            if bot_token and chat_id:
                _telegram_notifier = TelegramNotifier(bot_token, chat_id)
            else:
                _telegram_notifier = TelegramNotifier()  # Disabled instance
                
        except Exception as e:
            logger.error(f"Failed to initialize Telegram notifier: {e}")
            _telegram_notifier = TelegramNotifier()  # Disabled instance
    
    return _telegram_notifier


async def send_trade_notification(
    trade_type: str,
    market: str, 
    quantity: float,
    price: float,
    total_value: float,
    strategy: str,
    is_paper: bool = False
) -> bool:
    """Convenience function to send trade notification.
    
    Args:
        trade_type: "BUY" or "SELL"
        market: Market symbol
        quantity: Quantity traded
        price: Execution price
        total_value: Total trade value
        strategy: Trading strategy
        is_paper: Whether paper trading
        
    Returns:
        True if sent successfully
    """
    notifier = get_telegram_notifier()
    if notifier and notifier.enabled:
        return await notifier.send_trade_alert(
            trade_type, market, quantity, price, total_value, strategy, is_paper
        )
    return False


async def send_risk_notification(alert_type: str, message: str, severity: str = "WARNING") -> bool:
    """Convenience function to send risk notification.
    
    Args:
        alert_type: Type of alert
        message: Alert message
        severity: Severity level
        
    Returns:
        True if sent successfully
    """
    notifier = get_telegram_notifier()
    if notifier and notifier.enabled:
        return await notifier.send_risk_alert(alert_type, message, severity)
    return False
