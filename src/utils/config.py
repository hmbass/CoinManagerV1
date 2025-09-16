"""Configuration management using Pydantic models.

This module handles loading and validation of configuration from YAML files
and environment variables, following requirement.md specifications.
"""

import os
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field, field_validator, ConfigDict
from pydantic_settings import BaseSettings


class ExchangeConfig(BaseModel):
    """Exchange API configuration."""
    
    base_url: str = Field(default="https://api.upbit.com", description="Upbit API base URL")
    websocket_url: str = Field(default="wss://api.upbit.com/websocket/v1", description="WebSocket URL")
    timeout: int = Field(default=30, ge=1, le=300, description="Request timeout in seconds")
    max_retries: int = Field(default=3, ge=1, le=10, description="Maximum retry attempts")
    retry_backoff: float = Field(default=3.0, ge=0.1, le=10.0, description="Retry backoff multiplier")
    max_concurrent_requests: int = Field(default=3, ge=1, le=10, description="Maximum concurrent requests (conservative for rate limiting)")


class SymbolsConfig(BaseModel):
    """Market symbols configuration."""
    
    core: List[str] = Field(default=["KRW-BTC", "KRW-ETH", "KRW-SOL"], description="Core symbols for RS calculation")
    exclude_warning: bool = Field(default=True, description="Exclude warning/caution markets")
    exclude_newly_listed_days: int = Field(default=7, ge=1, le=30, description="Days to exclude newly listed symbols")
    min_volume_krw: int = Field(default=5_000_000_000, ge=0, description="Minimum daily volume in KRW (increased for rate limiting)")
    max_markets_to_scan: int = Field(default=50, ge=10, le=200, description="Maximum number of markets to scan (for rate limiting)")
    priority_markets: List[str] = Field(
        default=[
            "KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-ADA", "KRW-DOT", "KRW-AVAX", 
            "KRW-MATIC", "KRW-ATOM", "KRW-LINK", "KRW-XRP", "KRW-NEAR", "KRW-UNI",
            "KRW-MANA", "KRW-SAND", "KRW-CRO", "KRW-SHIB", "KRW-DOGE", "KRW-TRX",
            "KRW-ETC", "KRW-BCH", "KRW-LTC", "KRW-EOS", "KRW-XLM", "KRW-VET"
        ],
        description="Priority markets to always include in scanning"
    )


class TrendConfig(BaseModel):
    """Trend detection configuration."""
    
    use_vwap: bool = Field(default=True, description="Use session VWAP in trend calculation")
    ema_fast: int = Field(default=20, ge=5, le=50, description="Fast EMA period")
    ema_slow: int = Field(default=50, ge=20, le=200, description="Slow EMA period")


class ScoreWeightsConfig(BaseModel):
    """Scoring weights configuration (requirement.md: 0.4×RS + 0.3×RVOL_Z + 0.2×Trend + 0.1×Depth)."""
    
    rs: float = Field(default=0.4, ge=0.0, le=1.0, description="Relative strength weight")
    rvol: float = Field(default=0.3, ge=0.0, le=1.0, description="RVOL weight")
    trend: float = Field(default=0.2, ge=0.0, le=1.0, description="Trend weight")
    depth: float = Field(default=0.1, ge=0.0, le=1.0, description="Depth weight")
    
    @field_validator('rs', 'rvol', 'trend', 'depth')
    @classmethod
    def weights_sum_to_one(cls, v, info):
        """Ensure all weights sum to 1.0."""
        if info.data and len(info.data) == 3:  # All other weights are set
            total = sum(info.data.values()) + v
            if abs(total - 1.0) > 0.01:
                raise ValueError(f"Weights must sum to 1.0, got {total}")
        return v


class ScannerConfig(BaseModel):
    """Scanner configuration (FR-4: Candidate Scoring & Selection)."""
    
    # Candle data requirements
    candle_unit: int = Field(default=5, ge=1, le=60, description="Candle unit in minutes")
    candle_count: int = Field(default=200, ge=100, le=1000, description="Number of candles to fetch")
    
    # RVOL threshold (requirement.md: 2.0, range: 1.5~3.0)
    rvol_threshold: float = Field(default=2.0, ge=1.5, le=3.0, description="RVOL threshold")
    rvol_window: int = Field(default=20, ge=10, le=50, description="RVOL calculation window")
    
    # Spread threshold (requirement.md: 5bp for KRW market)
    spread_bp_max: int = Field(default=5, ge=1, le=100, description="Maximum spread in basis points")
    
    # Relative Strength parameters
    rs_window_minutes: int = Field(default=60, ge=30, le=240, description="RS calculation window in minutes")
    rs_reference_symbol: str = Field(default="KRW-BTC", description="Reference symbol for RS calculation")
    
    # Trend configuration
    trend: TrendConfig = Field(default_factory=TrendConfig)
    
    # Depth scoring
    depth_normalize: str = Field(default="log", pattern="^(log|linear)$", description="Depth normalization method")
    depth_levels: int = Field(default=5, ge=1, le=20, description="Orderbook levels to consider")
    
    # Score weighting
    score_weights: ScoreWeightsConfig = Field(default_factory=ScoreWeightsConfig)
    
    # Selection criteria
    candidate_count: int = Field(default=3, ge=2, le=5, description="Number of top candidates to return")
    min_score: float = Field(default=0.5, ge=0.0, le=1.0, description="Minimum candidate score")


class ORBConfig(BaseModel):
    """ORB (Opening Range Breakout) strategy configuration."""
    
    use: bool = Field(default=True, description="Enable ORB strategy")
    box_window: str = Field(default="09:00-10:00", description="Opening range time window")
    breakout_atr_mult: float = Field(default=0.1, ge=0.0, le=1.0, description="ATR multiplier for breakout confirmation")
    volume_spike_mult: float = Field(default=1.5, ge=1.0, le=5.0, description="Volume spike multiplier")
    volume_lookback: int = Field(default=20, ge=5, le=100, description="Volume lookback periods")


class SVWAPPullbackConfig(BaseModel):
    """sVWAP Pullback strategy configuration."""
    
    use: bool = Field(default=True, description="Enable sVWAP pullback strategy")
    zone_atr_mult: float = Field(default=0.25, ge=0.1, le=1.0, description="ATR multiplier for entry zone")
    require_ema_alignment: bool = Field(default=True, description="Require EMA alignment")
    min_pullback_pct: float = Field(default=0.5, ge=0.1, le=5.0, description="Minimum pullback percentage")
    max_pullback_pct: float = Field(default=2.0, ge=1.0, le=10.0, description="Maximum pullback percentage")


class SweepReversalConfig(BaseModel):
    """Liquidity Sweep Reversal strategy configuration."""
    
    use: bool = Field(default=False, description="Enable sweep reversal strategy")
    swing_lookback: int = Field(default=50, ge=20, le=200, description="Swing level lookback periods")
    penetration_atr_mult: float = Field(default=0.05, ge=0.01, le=0.5, description="Penetration ATR multiplier")
    recovery_time_minutes: int = Field(default=15, ge=5, le=60, description="Recovery time requirement")
    volume_spike_mult: float = Field(default=2.0, ge=1.5, le=5.0, description="Volume spike multiplier")


class SignalsConfig(BaseModel):
    """Signals configuration (FR-5: Entry Signal Engine)."""
    
    orb: ORBConfig = Field(default_factory=ORBConfig)
    svwap_pullback: SVWAPPullbackConfig = Field(default_factory=SVWAPPullbackConfig)
    sweep_reversal: SweepReversalConfig = Field(default_factory=SweepReversalConfig)


class RiskConfig(BaseModel):
    """Risk management configuration (FR-7: Risk Guard)."""
    
    # Position sizing (requirement.md: 0.3~0.5% per trade)
    per_trade_risk_pct: float = Field(default=0.004, ge=0.001, le=0.01, description="Per-trade risk as % of account")
    min_position_krw: int = Field(default=10_000, ge=5_000, description="Minimum position size in KRW")
    max_position_krw: int = Field(default=500_000, ge=10_000, description="Maximum position size in KRW")
    
    # Daily drawdown limit (requirement.md: -1.0% stop)
    daily_drawdown_stop_pct: float = Field(default=0.01, ge=0.005, le=0.05, description="Daily drawdown stop %")
    
    # Consecutive loss protection (requirement.md: 2 losses = symbol ban)
    max_retries_per_setup: int = Field(default=2, ge=1, le=10, description="Max retries per setup")
    same_symbol_consecutive_losses_stop: int = Field(default=2, ge=1, le=5, description="Consecutive losses before symbol ban")
    
    # Risk-Reward ratios
    min_risk_reward_ratio: float = Field(default=1.0, ge=0.5, le=3.0, description="Minimum R:R ratio")
    target_risk_reward_ratio: float = Field(default=1.5, ge=1.0, le=5.0, description="Target R:R ratio")


class PaperModeConfig(BaseModel):
    """Paper trading simulation configuration."""
    
    simulate_slippage: bool = Field(default=True, description="Simulate realistic slippage")
    slippage_bp_range: List[int] = Field(default=[0, 3], description="Slippage range in bp")
    fill_probability: float = Field(default=0.95, ge=0.5, le=1.0, description="Fill probability")
    fill_delay_ms: List[int] = Field(default=[100, 500], description="Fill delay range in ms")


class OrdersConfig(BaseModel):
    """Orders configuration (FR-6: Order/Fill Module)."""
    
    # Slippage protection (requirement.md: 5bp deviation limit)
    slippage_bp_max: int = Field(default=5, ge=1, le=50, description="Maximum slippage in bp")
    
    # Order types (requirement.md: IOC/FOK/BEST support)
    order_type: str = Field(default="limit", pattern="^(limit|market)$", description="Default order type")
    time_in_force: str = Field(default="IOC", pattern="^(IOC|FOK|GTC)$", description="Time in force")
    
    # Order size limits
    min_order_krw: int = Field(default=5_000, ge=5_000, description="Minimum order size (Upbit limit)")
    max_order_krw: int = Field(default=1_000_000, ge=10_000, description="Maximum order size per order")
    
    # OCO-like implementation
    use_oco_simulation: bool = Field(default=True, description="Use OCO simulation with separate orders")
    fill_timeout_seconds: int = Field(default=300, ge=30, le=3600, description="Order fill timeout")
    
    # Paper trading
    paper_mode: PaperModeConfig = Field(default_factory=PaperModeConfig)


class RuntimeConfig(BaseModel):
    """Runtime configuration."""
    
    # Trading sessions (requirement.md: 09:10–13:00, 17:10–19:00 KST)
    session_windows: List[str] = Field(
        default=["09:10-13:00", "17:10-19:00"], 
        description="Trading session time windows"
    )
    timezone: str = Field(default="Asia/Seoul", description="Trading timezone")
    
    # Intervals
    scan_interval_minutes: int = Field(default=5, ge=1, le=60, description="Full scan interval")
    signal_check_interval_seconds: int = Field(default=30, ge=1, le=300, description="Signal check interval")
    
    # Data refresh
    market_data_refresh_minutes: int = Field(default=1, ge=1, le=60, description="Market data refresh interval")
    candle_refresh_seconds: int = Field(default=30, ge=10, le=300, description="Candle refresh interval")
    orderbook_refresh_seconds: int = Field(default=5, ge=1, le=60, description="Orderbook refresh interval")
    
    # Performance
    max_concurrent_requests: int = Field(default=10, ge=1, le=50, description="API concurrency limit")
    websocket_ping_interval: int = Field(default=30, ge=10, le=300, description="WebSocket ping interval")
    
    # Caching
    enable_data_cache: bool = Field(default=True, description="Enable data caching")
    cache_ttl_minutes: int = Field(default=5, ge=1, le=60, description="Cache TTL")
    cache_max_size_mb: int = Field(default=100, ge=10, le=1000, description="Max cache size")


class LogFilesConfig(BaseModel):
    """Log files configuration."""
    
    main: str = Field(default="runtime/logs/trading.log", description="Main log file")
    error: str = Field(default="runtime/logs/error.log", description="Error log file")
    debug: str = Field(default="runtime/logs/debug.log", description="Debug log file")
    api: str = Field(default="runtime/logs/api.log", description="API log file")
    orders: str = Field(default="runtime/logs/orders.log", description="Orders log file")


class LoggingConfig(BaseModel):
    """Logging configuration (FR-8: Logging/Reporting/Journal)."""
    
    level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$", description="Log level")
    format: str = Field(default="json", pattern="^(json|text)$", description="Log format")
    
    files: LogFilesConfig = Field(default_factory=LogFilesConfig)
    
    # Log rotation
    max_file_size_mb: int = Field(default=50, ge=1, le=1000, description="Max log file size")
    backup_count: int = Field(default=10, ge=1, le=100, description="Number of backup files")
    
    # Structured logging fields
    include_fields: List[str] = Field(
        default=["timestamp", "level", "module", "message", "data", "correlation_id"],
        description="Fields to include in structured logs"
    )


class DailyReportConfig(BaseModel):
    """Daily report configuration."""
    
    enabled: bool = Field(default=True, description="Enable daily reports")
    time: str = Field(default="23:59", description="Report generation time")
    include_charts: bool = Field(default=False, description="Include charts in reports")


class WeeklyReportConfig(BaseModel):
    """Weekly report configuration."""
    
    enabled: bool = Field(default=True, description="Enable weekly reports")
    day: str = Field(default="sunday", pattern="^(monday|tuesday|wednesday|thursday|friday|saturday|sunday)$")
    time: str = Field(default="23:59", description="Report generation time")


class TradeJournalConfig(BaseModel):
    """Trade journal configuration."""
    
    enabled: bool = Field(default=True, description="Enable trade journal")
    include_screenshots: bool = Field(default=False, description="Include screenshots")


class AlertsConfig(BaseModel):
    """Alerts configuration."""
    
    daily_loss_pct: float = Field(default=0.5, ge=0.1, le=2.0, description="Daily loss alert threshold %")
    consecutive_losses: int = Field(default=3, ge=2, le=10, description="Consecutive losses alert threshold")
    api_error_rate: float = Field(default=0.1, ge=0.01, le=1.0, description="API error rate alert threshold")


class ReportingConfig(BaseModel):
    """Reporting configuration."""
    
    output_dir: str = Field(default="runtime/reports", description="Reports output directory")
    
    daily_report: DailyReportConfig = Field(default_factory=DailyReportConfig)
    weekly_report: WeeklyReportConfig = Field(default_factory=WeeklyReportConfig)
    trade_journal: TradeJournalConfig = Field(default_factory=TradeJournalConfig)
    
    # Performance metrics
    metrics: List[str] = Field(
        default=[
            "pnl_total", "pnl_daily", "win_rate", "avg_r_multiple",
            "max_drawdown", "sharpe_ratio", "profit_factor", "trades_count"
        ],
        description="Metrics to track"
    )
    
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)


class Config(BaseModel):
    """Main configuration model containing all settings."""
    model_config = ConfigDict(extra='ignore')
    
    exchange: ExchangeConfig = Field(default_factory=ExchangeConfig)
    symbols: SymbolsConfig = Field(default_factory=SymbolsConfig)
    scanner: ScannerConfig = Field(default_factory=ScannerConfig)
    signals: SignalsConfig = Field(default_factory=SignalsConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    orders: OrdersConfig = Field(default_factory=OrdersConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    reporting: ReportingConfig = Field(default_factory=ReportingConfig)
    


class EnvironmentConfig(BaseSettings):
    """Environment-specific configuration loaded from .env file."""
    
    # Upbit API credentials
    upbit_access_key: str = Field(..., description="Upbit API access key")
    upbit_secret_key: str = Field(..., description="Upbit API secret key")
    
    # Environment settings
    environment: str = Field(default="development", description="Environment name")
    trading_mode: str = Field(default="paper", pattern="^(paper|live)$", description="Trading mode")
    log_level: str = Field(default="INFO", description="Log level override")
    
    # Optional settings
    redis_url: Optional[str] = Field(default=None, description="Redis connection URL")
    slack_webhook_url: Optional[str] = Field(default=None, description="Slack webhook for alerts")
    jwt_secret: Optional[str] = Field(default=None, description="JWT secret for API auth")
    
    # Development options
    debug_mode: bool = Field(default=False, description="Enable debug mode")
    mock_trading: bool = Field(default=False, description="Use mock trading")
    log_api_requests: bool = Field(default=False, description="Log API requests")
    log_api_responses: bool = Field(default=False, description="Log API responses")
    
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


def load_config(config_path: Union[str, Path] = "configs/config.yaml") -> Config:
    """Load configuration from YAML file with validation.
    
    Args:
        config_path: Path to the configuration YAML file
        
    Returns:
        Validated Config object
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config validation fails
    """
    config_file = Path(config_path)
    
    if not config_file.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_file}")
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f)
        
        # Create Config object with validation
        config = Config(**config_data)
        
        return config
        
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in config file: {e}")
    except Exception as e:
        raise ValueError(f"Configuration validation failed: {e}")


def load_environment_config() -> EnvironmentConfig:
    """Load environment configuration from .env file.
    
    Returns:
        EnvironmentConfig object with credentials and environment settings
        
    Raises:
        ValueError: If required environment variables are missing
    """
    try:
        return EnvironmentConfig()
    except Exception as e:
        raise ValueError(f"Environment configuration failed: {e}")


def get_project_root() -> Path:
    """Get the project root directory.
    
    Returns:
        Path object pointing to project root
    """
    current = Path(__file__).parent
    while current.parent != current:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    
    # Fallback to current working directory
    return Path.cwd()


def ensure_directories(config: Config) -> None:
    """Ensure all required directories exist.
    
    Args:
        config: Configuration object containing paths
    """
    directories_to_create = [
        Path(config.logging.files.main).parent,
        Path(config.reporting.output_dir),
        Path("runtime/data"),
    ]
    
    for directory in directories_to_create:
        directory.mkdir(parents=True, exist_ok=True)


# Global configuration instance (lazy loaded)
_config_instance: Optional[Config] = None
_env_config_instance: Optional[EnvironmentConfig] = None


def get_config() -> Config:
    """Get the global configuration instance (singleton pattern).
    
    Returns:
        Global Config instance
    """
    global _config_instance
    
    if _config_instance is None:
        _config_instance = load_config()
        ensure_directories(_config_instance)
    
    return _config_instance


def get_env_config() -> EnvironmentConfig:
    """Get the global environment configuration instance (singleton pattern).
    
    Returns:
        Global EnvironmentConfig instance
    """
    global _env_config_instance
    
    if _env_config_instance is None:
        _env_config_instance = load_environment_config()
    
    return _env_config_instance


def reload_config(config_path: Union[str, Path] = "configs/config.yaml") -> Config:
    """Reload configuration from file (useful for config changes).
    
    Args:
        config_path: Path to the configuration YAML file
        
    Returns:
        New Config instance
    """
    global _config_instance
    _config_instance = load_config(config_path)
    ensure_directories(_config_instance)
    return _config_instance
