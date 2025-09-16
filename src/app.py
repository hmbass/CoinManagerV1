"""Main CLI application for Upbit Day-Trade Automator (UDA).

This module provides the command-line interface for the trading system,
supporting scan, run, and backtest operations.
"""

import asyncio
import sys
from typing import Optional
import click
from rich.console import Console
from rich.table import Table
from rich import print as rprint

from .utils.config import get_config, get_env_config, load_config, load_environment_config
from .utils.logging import setup_logging, get_trading_logger
from .utils.time_utils import get_kst_now, format_kst_time
from .api.upbit_rest import UpbitRestClient
from .scanner.scanner import CandidateScanner


console = Console()
logger = get_trading_logger(__name__)


class TradingApp:
    """Main trading application."""
    
    def __init__(self):
        """Initialize the trading application."""
        self.config = None
        self.env_config = None
        self.api_client = None
        self.scanner = None
        
    async def initialize(self):
        """Initialize application components."""
        try:
            # Load configurations
            self.config = get_config()
            self.env_config = get_env_config()
            
            # Setup logging
            setup_logging(self.config.logging)
            
            logger.info("Initializing Upbit Day-Trade Automator")
            
            # Initialize API client
            self.api_client = UpbitRestClient(
                self.config.exchange,
                self.env_config
            )
            
            # Initialize scanner
            self.scanner = CandidateScanner(self.config, self.api_client)
            
            logger.info("Application initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize application: {e}")
            raise
    
    async def cleanup(self):
        """Cleanup application resources."""
        if self.api_client:
            await self.api_client.close()
        
        logger.info("Application cleanup completed")


# Global app instance
app = TradingApp()


@click.group()
@click.version_option(version='0.1.0')
def cli():
    """🚀 Upbit Day-Trade Automator (UDA) - Rule-based trading system."""
    pass


@cli.command()
@click.option('--config', '-c', help='Configuration file path')
@click.option('--format', 'output_format', default='table', 
              type=click.Choice(['table', 'json']), help='Output format')
def scan(config: Optional[str], output_format: str):
    """📊 Scan markets and show top candidates.
    
    Performs market scanning according to requirement.md FR-4 specification:
    - Filters tradable markets (KRW, no warnings)
    - Calculates technical features (RVOL, RS, sVWAP, etc.)
    - Applies scoring algorithm (0.4×RS + 0.3×RVOL + 0.2×Trend + 0.1×Depth)
    - Returns top 2-3 candidates
    """
    async def _scan():
        try:
            # Load custom config if provided
            if config:
                app.config = load_config(config)
            
            await app.initialize()
            
            console.print("\n🔍 [bold blue]Starting market scan...[/bold blue]")
            
            # Perform scan
            scan_result = await app.scanner.scan_markets()
            
            # Display results
            if output_format == 'json':
                import json
                from dataclasses import asdict
                
                result_dict = {
                    'timestamp': scan_result.timestamp,
                    'scan_duration_seconds': scan_result.scan_duration_seconds,
                    'total_markets': scan_result.total_markets,
                    'processed_markets': scan_result.processed_markets,
                    'filtered_markets': scan_result.filtered_markets,
                    'candidates': [asdict(candidate) for candidate in scan_result.candidates]
                }
                print(json.dumps(result_dict, indent=2, ensure_ascii=False))
                
            else:
                # Table format
                display_scan_results(scan_result)
            
        except Exception as e:
            console.print(f"\n❌ [bold red]Scan failed: {e}[/bold red]")
            logger.error(f"Scan failed: {e}")
            sys.exit(1)
        finally:
            await app.cleanup()
    
    asyncio.run(_scan())


def display_scan_results(scan_result):
    """Display scan results in a formatted table."""
    console.print(f"\n📈 [bold green]Market Scan Results[/bold green]")
    console.print(f"⏱️  Scan Duration: {scan_result.scan_duration_seconds:.2f}s")
    console.print(f"🏪 Total Markets: {scan_result.total_markets}")
    console.print(f"✅ Processed Markets: {scan_result.processed_markets}")
    console.print(f"🎯 Filtered Candidates: {scan_result.filtered_markets}")
    console.print(f"🏆 Final Candidates: {len(scan_result.candidates)}")
    
    if not scan_result.candidates:
        console.print("\n⚠️  [yellow]No candidates found matching criteria[/yellow]")
        return
    
    # Create candidates table
    table = Table(title="📊 Top Trading Candidates", show_header=True, header_style="bold magenta")
    
    table.add_column("Rank", style="dim", width=6)
    table.add_column("Market", style="cyan", width=12)
    table.add_column("Score", style="green", width=8)
    table.add_column("Price", style="white", width=12)
    table.add_column("RVOL", style="blue", width=8)
    table.add_column("RS (%)", style="yellow", width=8)
    table.add_column("Trend", style="magenta", width=6)
    table.add_column("Spread (bp)", style="red", width=10)
    
    for i, candidate in enumerate(scan_result.candidates, 1):
        # Format values
        rank = f"#{i}"
        market = candidate.market.replace('KRW-', '')
        score = f"{candidate.final_score:.3f}"
        price = f"{candidate.price:,.0f}"
        rvol = f"{candidate.rvol:.2f}"
        rs = f"{candidate.rs * 100:+.2f}"  # Convert to percentage
        trend = "✅" if candidate.trend == 1 else "❌"
        spread = f"{candidate.spread_bp:.2f}"
        
        # Color coding based on rank
        rank_style = "bold green" if i == 1 else "bold yellow" if i == 2 else "white"
        
        table.add_row(
            f"[{rank_style}]{rank}[/{rank_style}]",
            f"[{rank_style}]{market}[/{rank_style}]",
            f"[{rank_style}]{score}[/{rank_style}]",
            price,
            rvol,
            rs,
            trend,
            spread
        )
    
    console.print(table)
    
    # Show feature details for top candidate
    if scan_result.candidates:
        top = scan_result.candidates[0]
        console.print(f"\n📋 [bold]Top Candidate Details ({top.market})[/bold]")
        console.print(f"• EMA20: {top.ema_20:,.2f} | EMA50: {top.ema_50:,.2f}")
        console.print(f"• sVWAP: {top.svwap:,.2f} | ATR(14): {top.atr_14:,.2f}")
        console.print(f"• Volume: {top.volume:,.0f} | Data Points: {top.data_points}")


@cli.command()
@click.option('--mode', default='paper', type=click.Choice(['paper', 'live']), 
              help='Trading mode (CAUTION: live mode uses real money!)')
@click.option('--config', '-c', help='Configuration file path')
@click.option('--duration', '-d', default=60, help='Run duration in minutes')
def run(mode: str, config: Optional[str], duration: int):
    """🏃 Run the automated trading system.
    
    ⚠️  CAUTION: 'live' mode trades with real money!
    Always test thoroughly with 'paper' mode first.
    
    This command runs the complete trading system:
    - Market scanning and candidate selection
    - Signal generation from multiple strategies
    - Risk management and position sizing
    - Order execution with monitoring
    - Performance tracking and reporting
    """
    async def _run():
        try:
            # Safety check for live mode
            if mode == 'live':
                console.print("\n⚠️  [bold red]WARNING: LIVE TRADING MODE[/bold red]")
                console.print("This mode will execute REAL trades with REAL money!")
                console.print("💸 You could lose significant amounts of money!")
                console.print("📊 Make sure you've tested extensively in paper mode first!")
                
                if not click.confirm("Are you absolutely sure you want to proceed?", default=False):
                    console.print("🛡️  [green]Live trading cancelled - staying safe![/green]")
                    return
                
                # Double confirmation
                console.print(f"\n⚠️  [bold red]FINAL WARNING[/bold red]")
                console.print(f"You are about to start LIVE trading for {duration} minutes.")
                console.print("The system will place REAL orders with REAL money.")
                
                if not click.confirm("This is your FINAL confirmation. Proceed with live trading?", default=False):
                    console.print("🛡️  [green]Live trading cancelled - wise choice![/green]")
                    return
            
            # Initialize app first
            await app.initialize()
            
            # Load custom config if provided
            if config:
                app.config = load_config(config)
            
            # Override trading mode in environment config
            app.env_config.trading_mode = mode
            
            # Initialize trading system
            from .trading_system import TradingSystem
            trading_system = TradingSystem(app.config, app.env_config, app.api_client)
            await trading_system.initialize()
            
            mode_emoji = "📝" if mode == 'paper' else "💰"
            console.print(f"\n{mode_emoji} [bold blue]Starting {mode} trading mode...[/bold blue]")
            console.print(f"⏰ Duration: {duration} minutes")
            console.print(f"🎯 Strategies: ORB, sVWAP Pullback, Liquidity Sweep")
            console.print(f"🛡️  Risk Management: Active")
            console.print(f"📊 Monitoring: Real-time")
            
            if mode == 'paper':
                console.print(f"✅ [green]Paper Trading Mode - No real money at risk[/green]")
            else:
                console.print(f"⚠️  [bold red]LIVE Trading Mode - REAL MONEY AT RISK![/bold red]")
            
            console.print(f"\n🚀 [bold green]Trading system starting...[/bold green]")
            
            # Run the trading loop
            await trading_system.run_trading_loop(duration)
            
            # Get final status
            final_status = trading_system.get_system_status()
            
            console.print(f"\n📊 [bold blue]Trading Session Complete[/bold blue]")
            console.print(f"⏱️  Duration: {final_status['system']['uptime_minutes']:.1f} minutes")
            console.print(f"📈 Total Trades: {final_status['performance']['total_trades']}")
            console.print(f"🏆 Winning Trades: {final_status['performance']['winning_trades']}")
            
            if final_status['performance']['total_trades'] > 0:
                win_rate = final_status['performance']['winning_trades'] / final_status['performance']['total_trades'] * 100
                console.print(f"📊 Win Rate: {win_rate:.1f}%")
            
            console.print(f"💰 Total P&L: {final_status['performance']['total_pnl']:,.0f} KRW")
            console.print(f"📅 Daily P&L: {final_status['performance']['daily_pnl']:,.0f} KRW")
            
            if final_status['performance']['total_pnl'] > 0:
                console.print(f"🎉 [bold green]Profitable session![/bold green]")
            elif final_status['performance']['total_pnl'] < 0:
                console.print(f"📉 [bold red]Loss incurred[/bold red]")
            else:
                console.print(f"⚖️  [yellow]Break-even session[/yellow]")
            
            # Risk warnings
            if final_status['risk']['ddl_hit']:
                console.print(f"⚠️  [bold red]Daily Drawdown Limit was hit during session[/bold red]")
            
            if final_status['risk']['banned_markets_count'] > 0:
                console.print(f"🚫 [yellow]{final_status['risk']['banned_markets_count']} markets banned due to losses[/yellow]")
            
            console.print(f"\n📄 Detailed logs available in runtime/logs/")
            console.print(f"📊 Trading report saved in runtime/reports/")
            
        except KeyboardInterrupt:
            console.print(f"\n\n⏹️  [yellow]Trading interrupted by user[/yellow]")
            console.print(f"🔄 System shutting down gracefully...")
        except Exception as e:
            console.print(f"\n❌ [bold red]Trading system error: {e}[/bold red]")
            logger.error(f"Trading system error: {e}")
            sys.exit(1)
        finally:
            # Always cleanup
            try:
                if 'trading_system' in locals():
                    trading_system.stop_trading()
                await app.cleanup()
            except Exception as cleanup_error:
                console.print(f"⚠️  Cleanup error: {cleanup_error}")
    
    asyncio.run(_run())


@cli.command()
@click.option('--start', help='Start date (YYYY-MM-DD)')
@click.option('--end', help='End date (YYYY-MM-DD)')
@click.option('--config', '-c', help='Configuration file path')
def backtest(start: Optional[str], end: Optional[str], config: Optional[str]):
    """📈 Run historical backtest.
    
    Test trading strategies against historical data to evaluate performance.
    """
    console.print("\n📈 [bold blue]Backtest Mode[/bold blue]")
    console.print("🚧 [yellow]Backtest implementation coming soon...[/yellow]")
    
    if start:
        console.print(f"📅 Start Date: {start}")
    if end:
        console.print(f"📅 End Date: {end}")
    
    console.print("\n📋 Planned backtest features:")
    console.print("  • Historical data replay")
    console.print("  • Strategy performance metrics")
    console.print("  • Risk analysis")
    console.print("  • Detailed trade journal")


@cli.command()
@click.option('--config', '-c', help='Configuration file path')
def monitor(config: Optional[str]):
    """👁️  Monitor running trading system.
    
    Display real-time metrics and system status.
    """
    console.print("\n👁️  [bold blue]System Monitor[/bold blue]")
    console.print("🚧 [yellow]Monitor implementation coming soon...[/yellow]")
    
    console.print("\n📋 Planned monitoring features:")
    console.print("  • Real-time P&L tracking")
    console.print("  • Order status monitoring")
    console.print("  • System health metrics")
    console.print("  • Alert notifications")


@cli.command()
def status():
    """📊 Show system status and configuration.
    
    Display current configuration and system health.
    """
    try:
        # Load configs without full initialization
        config = get_config()
        env_config = get_env_config()
        
        console.print("\n📊 [bold blue]System Status[/bold blue]")
        
        # System info
        table = Table(title="🔧 Configuration Status", show_header=True, header_style="bold magenta")
        table.add_column("Component", style="cyan", width=20)
        table.add_column("Status", style="green", width=15)
        table.add_column("Details", style="white", width=40)
        
        # Environment
        env_status = "✅ Configured" if env_config.upbit_access_key else "❌ Missing API Keys"
        table.add_row("Environment", env_status, f"Mode: {env_config.trading_mode}")
        
        # Trading sessions
        sessions = ', '.join(config.runtime.session_windows)
        table.add_row("Trading Hours", "✅ Configured", sessions)
        
        # Risk settings
        risk_info = f"Per-trade: {config.risk.per_trade_risk_pct*100:.1f}%, Daily DDL: {config.risk.daily_drawdown_stop_pct*100:.1f}%"
        table.add_row("Risk Management", "✅ Configured", risk_info)
        
        # Scanner settings
        scanner_info = f"RVOL≥{config.scanner.rvol_threshold}, Spread≤{config.scanner.spread_bp_max}bp"
        table.add_row("Scanner", "✅ Configured", scanner_info)
        
        console.print(table)
        
        # Current time and trading status
        current_time = get_kst_now()
        console.print(f"\n⏰ Current Time (KST): {format_kst_time(current_time)}")
        
        from .utils.time_utils import is_trading_hours
        if is_trading_hours(current_time, config.runtime.session_windows):
            console.print("🟢 [bold green]Currently in trading hours[/bold green]")
        else:
            console.print("🔴 [bold red]Currently outside trading hours[/bold red]")
            
            from .utils.time_utils import get_next_trading_session
            next_session = get_next_trading_session(current_time, config.runtime.session_windows)
            if next_session:
                console.print(f"📅 Next trading session: {format_kst_time(next_session)}")
    
    except Exception as e:
        console.print(f"\n❌ [bold red]Failed to get system status: {e}[/bold red]")
        sys.exit(1)


@cli.command()
def health():
    """🏥 Check system health and API connectivity.
    
    Verify all components are working correctly.
    """
    async def _health():
        try:
            await app.initialize()
            
            console.print("\n🏥 [bold blue]Health Check[/bold blue]")
            
            # Test API connectivity
            console.print("🔌 Testing API connectivity...")
            
            health_ok = await app.api_client.health_check()
            
            if health_ok:
                console.print("✅ [green]API connection healthy[/green]")
            else:
                console.print("❌ [red]API connection failed[/red]")
            
            # Test market data
            console.print("📊 Testing market data access...")
            markets = await app.api_client.get_markets(is_details=False)
            
            if markets and len(markets) > 0:
                console.print(f"✅ [green]Market data OK ({len(markets)} markets)[/green]")
            else:
                console.print("❌ [red]Market data access failed[/red]")
            
            console.print("\n🎉 [bold green]Health check completed![/bold green]")
            
        except Exception as e:
            console.print(f"\n❌ [bold red]Health check failed: {e}[/bold red]")
            sys.exit(1)
        finally:
            await app.cleanup()
    
    asyncio.run(_health())


@cli.command()
def test_telegram():
    """📱 Test Telegram notification setup.
    
    Tests Telegram bot configuration and sends a test message.
    """
    async def _test_telegram():
        try:
            from .utils.telegram import get_telegram_notifier
            
            console.print(f"\n📱 [bold blue]Telegram Test[/bold blue]")
            
            notifier = get_telegram_notifier()
            
            if not notifier or not notifier.enabled:
                console.print(f"❌ [red]Telegram not configured[/red]")
                console.print(f"💡 [yellow]Configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env file[/yellow]")
                sys.exit(1)
            
            console.print(f"🔗 Testing Telegram connection...")
            success = await notifier.test_connection()
            
            if success:
                console.print(f"✅ [green]Telegram notifications working![/green]")
                console.print(f"📨 [blue]Test message sent to your chat[/blue]")
                
                # Send additional test notifications
                await notifier.send_trade_alert(
                    "BUY", "KRW-BTC", 0.001, 50000000, 50000, "TEST_STRATEGY", True
                )
                
                await notifier.send_risk_alert(
                    "TEST_ALERT",
                    "This is a test risk notification to verify your Telegram setup.",
                    "INFO"
                )
                
                console.print(f"🎯 [green]Sample trade and risk alerts sent![/green]")
                
            else:
                console.print(f"❌ [red]Telegram connection failed[/red]")
                console.print(f"💡 [yellow]Check your bot token and chat ID[/yellow]")
                sys.exit(1)
            
        except Exception as e:
            console.print(f"\n❌ [bold red]Telegram test failed: {e}[/bold red]")
            logger.error(f"Telegram test failed: {e}")
            sys.exit(1)
    
    asyncio.run(_test_telegram())


def main():
    """Main entry point for the CLI application."""
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n\n⏹️  [yellow]Operation cancelled by user[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n💥 [bold red]Unexpected error: {e}[/bold red]")
        sys.exit(1)


if __name__ == '__main__':
    main()
