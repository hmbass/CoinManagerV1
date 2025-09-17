"""Structured logging utilities for trading system.

This module provides JSON-structured logging with correlation IDs,
log rotation, and multiple output destinations as specified in
requirement.md FR-8: Logging/Reporting/Journal.
"""

import json
import logging
import logging.handlers
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Union, List
import structlog
from structlog.typing import FilteringBoundLogger

from .time_utils import get_kst_now
from .config import Config, LoggingConfig


# Global correlation ID for request tracing
_correlation_id: Optional[str] = None


def generate_correlation_id() -> str:
    """Generate a new correlation ID for request tracing.
    
    Returns:
        UUID-based correlation ID
    """
    return str(uuid.uuid4())[:8]


def set_correlation_id(correlation_id: Optional[str] = None) -> str:
    """Set the current correlation ID.
    
    Args:
        correlation_id: Optional correlation ID (generates new if None)
        
    Returns:
        The correlation ID that was set
    """
    global _correlation_id
    
    if correlation_id is None:
        correlation_id = generate_correlation_id()
    
    _correlation_id = correlation_id
    return correlation_id


def get_correlation_id() -> Optional[str]:
    """Get the current correlation ID.
    
    Returns:
        Current correlation ID or None
    """
    return _correlation_id


def clear_correlation_id() -> None:
    """Clear the current correlation ID."""
    global _correlation_id
    _correlation_id = None


class StructuredFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""
    
    def __init__(self, include_fields: List[str]):
        """Initialize the formatter.
        
        Args:
            include_fields: List of fields to include in log output
        """
        super().__init__()
        self.include_fields = include_fields
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as structured JSON.
        
        Args:
            record: Log record to format
            
        Returns:
            JSON-formatted log string
        """
        # Base log entry
        log_entry: Dict[str, Any] = {}
        
        # Add standard fields
        if "timestamp" in self.include_fields:
            log_entry["timestamp"] = get_kst_now().isoformat()
        
        if "level" in self.include_fields:
            log_entry["level"] = record.levelname
        
        if "module" in self.include_fields:
            log_entry["module"] = record.name
        
        if "message" in self.include_fields:
            log_entry["message"] = record.getMessage()
        
        if "correlation_id" in self.include_fields:
            correlation_id = get_correlation_id()
            if correlation_id:
                log_entry["correlation_id"] = correlation_id
        
        # Add structured data if present
        if "data" in self.include_fields and hasattr(record, 'data'):
            log_entry["data"] = record.data
        
        # Add exception information
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields from record
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'levelname', 'levelno',
                          'pathname', 'filename', 'module', 'exc_info',
                          'exc_text', 'stack_info', 'lineno', 'funcName',
                          'created', 'msecs', 'relativeCreated', 'thread',
                          'threadName', 'processName', 'process', 'data']:
                log_entry[key] = value
        
        return json.dumps(log_entry, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Custom text formatter for human-readable logging."""
    
    def __init__(self):
        """Initialize the formatter."""
        format_str = "%(asctime)s [%(levelname)8s] %(name)s: %(message)s"
        super().__init__(format_str, datefmt="%Y-%m-%d %H:%M:%S")
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as text.
        
        Args:
            record: Log record to format
            
        Returns:
            Formatted log string
        """
        # Add correlation ID to message if present
        correlation_id = get_correlation_id()
        if correlation_id:
            record.msg = f"[{correlation_id}] {record.msg}"
        
        formatted = super().format(record)
        
        # Add structured data if present
        if hasattr(record, 'data') and record.data:
            data_str = json.dumps(record.data, ensure_ascii=False, default=str)
            formatted += f" | Data: {data_str}"
        
        return formatted


def create_file_handler(
    log_file: Union[str, Path],
    level: str,
    formatter: logging.Formatter,
    max_bytes: int = 50 * 1024 * 1024,  # 50MB
    backup_count: int = 10
) -> logging.Handler:
    """Create a rotating file handler.
    
    Args:
        log_file: Path to log file
        level: Log level
        formatter: Log formatter
        max_bytes: Maximum file size before rotation
        backup_count: Number of backup files to keep
        
    Returns:
        Configured file handler
    """
    # Ensure log directory exists
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    handler = logging.handlers.RotatingFileHandler(
        filename=log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    
    handler.setLevel(getattr(logging, level.upper()))
    handler.setFormatter(formatter)
    
    return handler


def create_console_handler(level: str, formatter: logging.Formatter) -> logging.Handler:
    """Create a console handler.
    
    Args:
        level: Log level
        formatter: Log formatter
        
    Returns:
        Configured console handler
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, level.upper()))
    handler.setFormatter(formatter)
    
    return handler


def setup_logging(config: Optional[LoggingConfig] = None) -> None:
    """Setup structured logging system.
    
    Args:
        config: Logging configuration (uses default if None)
    """
    if config is None:
        from .config import get_config
        config = get_config().logging
    
    # Clear any existing handlers
    logging.root.handlers.clear()
    
    # Set root logger level
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, config.level.upper()))
    
    # Create formatters
    if config.format == "json":
        formatter = StructuredFormatter(config.include_fields)
    else:
        formatter = TextFormatter()
    
    # Console handler (always enabled)
    console_handler = create_console_handler(config.level, formatter)
    root_logger.addHandler(console_handler)
    
    # File handlers
    max_size_bytes = config.max_file_size_mb * 1024 * 1024
    
    # Main log file
    if config.files.main:
        main_handler = create_file_handler(
            config.files.main,
            config.level,
            formatter,
            max_size_bytes,
            config.backup_count
        )
        root_logger.addHandler(main_handler)
    
    # Error log file (ERROR level and above)
    if config.files.error:
        error_formatter = StructuredFormatter(config.include_fields) if config.format == "json" else TextFormatter()
        error_handler = create_file_handler(
            config.files.error,
            "ERROR",
            error_formatter,
            max_size_bytes,
            config.backup_count
        )
        root_logger.addHandler(error_handler)
    
    # Debug log file (if debug level)
    if config.files.debug and config.level.upper() == "DEBUG":
        debug_formatter = StructuredFormatter(config.include_fields) if config.format == "json" else TextFormatter()
        debug_handler = create_file_handler(
            config.files.debug,
            "DEBUG",
            debug_formatter,
            max_size_bytes,
            config.backup_count
        )
        root_logger.addHandler(debug_handler)
    
    # API log file (for API-specific logging)
    if config.files.api:
        api_formatter = StructuredFormatter(config.include_fields) if config.format == "json" else TextFormatter()
        api_handler = create_file_handler(
            config.files.api,
            config.level,
            api_formatter,
            max_size_bytes,
            config.backup_count
        )
        
        # Only add API logs to this handler
        api_logger = logging.getLogger("trading.api")
        api_logger.addHandler(api_handler)
        api_logger.propagate = False  # Don't propagate to root logger
    
    # Orders log file (for order-specific logging)
    if config.files.orders:
        orders_formatter = StructuredFormatter(config.include_fields) if config.format == "json" else TextFormatter()
        orders_handler = create_file_handler(
            config.files.orders,
            config.level,
            orders_formatter,
            max_size_bytes,
            config.backup_count
        )
        
        # Only add order logs to this handler
        orders_logger = logging.getLogger("trading.orders")
        orders_logger.addHandler(orders_handler)
        orders_logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the specified name.
    
    Args:
        name: Logger name (typically module name)
        
    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


class TradingLogger:
    """Enhanced logger with structured data support."""
    
    def __init__(self, name: str):
        """Initialize the trading logger.
        
        Args:
            name: Logger name
        """
        self.logger = logging.getLogger(name)
    
    def _log(self, level: str, message: str, data: Optional[Dict[str, Any]] = None, **kwargs) -> None:
        """Internal log method with structured data support.
        
        Args:
            level: Log level
            message: Log message
            data: Structured data to include
            **kwargs: Additional keyword arguments
        """
        # Create log record with structured data
        extra = kwargs.copy()
        if data:
            extra['data'] = data
        
        getattr(self.logger, level.lower())(message, extra=extra)
    
    def debug(self, message: str, data: Optional[Dict[str, Any]] = None, **kwargs) -> None:
        """Log debug message with structured data."""
        self._log("DEBUG", message, data, **kwargs)
    
    def info(self, message: str, data: Optional[Dict[str, Any]] = None, **kwargs) -> None:
        """Log info message with structured data."""
        self._log("INFO", message, data, **kwargs)
    
    def warning(self, message: str, data: Optional[Dict[str, Any]] = None, **kwargs) -> None:
        """Log warning message with structured data."""
        self._log("WARNING", message, data, **kwargs)
    
    def error(self, message: str, data: Optional[Dict[str, Any]] = None, **kwargs) -> None:
        """Log error message with structured data."""
        self._log("ERROR", message, data, **kwargs)
    
    def critical(self, message: str, data: Optional[Dict[str, Any]] = None, **kwargs) -> None:
        """Log critical message with structured data."""
        self._log("CRITICAL", message, data, **kwargs)
    
    def trade(self, message: str, trade_data: Dict[str, Any], **kwargs) -> None:
        """Log trade-specific message with trade data.
        
        Args:
            message: Log message
            trade_data: Trade-specific data
            **kwargs: Additional keyword arguments
        """
        # Set correlation ID for trade tracking
        if 'trade_id' in trade_data:
            set_correlation_id(str(trade_data['trade_id']))
        
        self.info(message, data=trade_data, **kwargs)
    
    def api_call(self, endpoint: str, method: str = "GET", data: Optional[Dict[str, Any]] = None, **kwargs) -> None:
        """Log API call with structured data.
        
        Args:
            endpoint: API endpoint
            method: HTTP method
            data: API call data
            **kwargs: Additional keyword arguments
        """
        api_data = {
            "endpoint": endpoint,
            "method": method,
            "timestamp": get_kst_now().isoformat()
        }
        
        if data:
            api_data.update(data)
        
        # Use API-specific logger
        api_logger = logging.getLogger("trading.api")
        extra = kwargs.copy()
        extra['data'] = api_data
        
        api_logger.info(f"API {method} {endpoint}", extra=extra)
    
    def order_event(self, event: str, order_data: Dict[str, Any], **kwargs) -> None:
        """Log order event with structured data.
        
        Args:
            event: Order event type (place, fill, cancel, etc.)
            order_data: Order-specific data
            **kwargs: Additional keyword arguments
        """
        # Use order-specific logger
        orders_logger = logging.getLogger("trading.orders")
        
        order_event_data = {
            "event": event,
            "timestamp": get_kst_now().isoformat(),
            **order_data
        }
        
        extra = kwargs.copy()
        extra['data'] = order_event_data
        
        orders_logger.info(f"Order {event}", extra=extra)


# Convenience functions for getting specialized loggers
def get_trading_logger(name: str) -> TradingLogger:
    """Get a trading logger with enhanced functionality.
    
    Args:
        name: Logger name
        
    Returns:
        TradingLogger instance
    """
    return TradingLogger(name)


def get_api_logger() -> TradingLogger:
    """Get API-specific logger.
    
    Returns:
        TradingLogger for API operations
    """
    return TradingLogger("trading.api")


def get_orders_logger() -> TradingLogger:
    """Get orders-specific logger.
    
    Returns:
        TradingLogger for order operations
    """
    return TradingLogger("trading.orders")


def log_performance(func):
    """Decorator to log function execution time (only in DEBUG mode).
    
    Args:
        func: Function to wrap
        
    Returns:
        Wrapped function with performance logging
    """
    def wrapper(*args, **kwargs):
        # Check if DEBUG logging is enabled
        root_logger = logging.getLogger()
        if root_logger.level > logging.DEBUG:
            # Skip performance logging in production
            return func(*args, **kwargs)
        
        logger = get_trading_logger(f"performance.{func.__module__}.{func.__name__}")
        
        start_time = datetime.now()
        correlation_id = set_correlation_id()
        
        try:
            result = func(*args, **kwargs)
            
            end_time = datetime.now()
            duration_ms = (end_time - start_time).total_seconds() * 1000
            
            # Only log if duration is significant (>10ms)
            if duration_ms > 10:
                logger.debug(
                    f"Function {func.__name__} completed",
                    data={
                        "function": func.__name__,
                        "module": func.__module__,
                        "duration_ms": round(duration_ms, 2),
                        "status": "success"
                    }
                )
            
            return result
            
        except Exception as e:
            end_time = datetime.now()
            duration_ms = (end_time - start_time).total_seconds() * 1000
            
            logger.error(
                f"Function {func.__name__} failed",
                data={
                    "function": func.__name__,
                    "module": func.__module__,
                    "duration_ms": round(duration_ms, 2),
                    "status": "error",
                    "error": str(e)
                }
            )
            
            raise
        
        finally:
            clear_correlation_id()
    
    return wrapper


# Context manager for correlation ID tracking
class correlation_context:
    """Context manager for correlation ID tracking."""
    
    def __init__(self, correlation_id: Optional[str] = None):
        """Initialize correlation context.
        
        Args:
            correlation_id: Correlation ID to use (generates new if None)
        """
        self.correlation_id = correlation_id
        self.previous_correlation_id = None
    
    def __enter__(self) -> str:
        """Enter correlation context."""
        self.previous_correlation_id = get_correlation_id()
        return set_correlation_id(self.correlation_id)
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit correlation context."""
        if self.previous_correlation_id:
            set_correlation_id(self.previous_correlation_id)
        else:
            clear_correlation_id()


# Module-level convenience logger
logger = get_trading_logger(__name__)
