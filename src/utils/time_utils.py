"""Time utility functions for Korean timezone (KST) handling.

This module provides timezone-aware datetime utilities specifically for
Korean markets (Asia/Seoul timezone) as required by requirement.md.
"""

import pytz
from datetime import datetime, time, timedelta
from typing import List, Tuple, Optional, Union
import re


# Korean timezone (requirement.md: Asia/Seoul fixed)
KST = pytz.timezone('Asia/Seoul')
UTC = pytz.UTC


def get_kst_now() -> datetime:
    """Get current time in Korean timezone.
    
    Returns:
        Current datetime in KST timezone
    """
    return datetime.now(KST)


def get_utc_now() -> datetime:
    """Get current time in UTC.
    
    Returns:
        Current datetime in UTC timezone
    """
    return datetime.now(UTC)


def to_kst(dt: datetime) -> datetime:
    """Convert datetime to KST timezone.
    
    Args:
        dt: Input datetime (naive or timezone-aware)
        
    Returns:
        Datetime converted to KST
    """
    if dt.tzinfo is None:
        # Assume UTC if naive
        dt = UTC.localize(dt)
    
    return dt.astimezone(KST)


def to_utc(dt: datetime) -> datetime:
    """Convert datetime to UTC timezone.
    
    Args:
        dt: Input datetime (naive or timezone-aware)
        
    Returns:
        Datetime converted to UTC
    """
    if dt.tzinfo is None:
        # Assume KST if naive
        dt = KST.localize(dt)
    
    return dt.astimezone(UTC)


def parse_kst_time(time_str: str) -> time:
    """Parse time string in HH:MM format as KST time.
    
    Args:
        time_str: Time string in "HH:MM" format
        
    Returns:
        time object
        
    Raises:
        ValueError: If time format is invalid
    """
    if not re.match(r'^\d{2}:\d{2}$', time_str):
        raise ValueError(f"Invalid time format: {time_str}. Expected HH:MM")
    
    try:
        hour, minute = map(int, time_str.split(':'))
        return time(hour=hour, minute=minute)
    except ValueError as e:
        raise ValueError(f"Invalid time values in {time_str}: {e}")


def format_kst_time(dt: datetime) -> str:
    """Format datetime as KST time string.
    
    Args:
        dt: Input datetime
        
    Returns:
        Formatted time string in "HH:MM" format
    """
    kst_dt = to_kst(dt)
    return kst_dt.strftime("%H:%M")


def parse_time_window(window_str: str) -> Tuple[time, time]:
    """Parse time window string into start and end times.
    
    Args:
        window_str: Time window string in "HH:MM-HH:MM" format
        
    Returns:
        Tuple of (start_time, end_time)
        
    Raises:
        ValueError: If window format is invalid
    """
    if '-' not in window_str:
        raise ValueError(f"Invalid window format: {window_str}. Expected HH:MM-HH:MM")
    
    try:
        start_str, end_str = window_str.split('-', 1)
        start_time = parse_kst_time(start_str.strip())
        end_time = parse_kst_time(end_str.strip())
        
        return start_time, end_time
    except ValueError as e:
        raise ValueError(f"Invalid time window {window_str}: {e}")


def is_time_in_window(current_time: Union[datetime, time], window: str) -> bool:
    """Check if current time is within a time window.
    
    Args:
        current_time: Current time to check
        window: Time window string in "HH:MM-HH:MM" format
        
    Returns:
        True if current time is within the window
    """
    if isinstance(current_time, datetime):
        current_time = to_kst(current_time).time()
    
    start_time, end_time = parse_time_window(window)
    
    # Handle overnight windows (e.g., "22:00-02:00")
    if start_time <= end_time:
        return start_time <= current_time <= end_time
    else:
        return current_time >= start_time or current_time <= end_time


def is_trading_hours(dt: Optional[datetime] = None, session_windows: Optional[List[str]] = None) -> bool:
    """Check if given time is within trading hours.
    
    Args:
        dt: Datetime to check (default: current KST time)
        session_windows: Trading session windows (default: requirement.md sessions)
        
    Returns:
        True if within trading hours
    """
    if dt is None:
        dt = get_kst_now()
    
    if session_windows is None:
        # Default sessions from requirement.md: 09:10–13:00, 17:10–19:00
        session_windows = ["09:10-13:00", "17:10-19:00"]
    
    current_time = to_kst(dt).time()
    
    for window in session_windows:
        if is_time_in_window(current_time, window):
            return True
    
    return False


def get_next_trading_session(dt: Optional[datetime] = None, session_windows: Optional[List[str]] = None) -> Optional[datetime]:
    """Get the start time of the next trading session.
    
    Args:
        dt: Reference datetime (default: current KST time)
        session_windows: Trading session windows
        
    Returns:
        Datetime of next trading session start, or None if no future session today
    """
    if dt is None:
        dt = get_kst_now()
    
    if session_windows is None:
        session_windows = ["09:10-13:00", "17:10-19:00"]
    
    kst_dt = to_kst(dt)
    current_date = kst_dt.date()
    current_time = kst_dt.time()
    
    # Check sessions for today
    for window in session_windows:
        start_time, _ = parse_time_window(window)
        
        if current_time < start_time:
            session_start = KST.localize(
                datetime.combine(current_date, start_time)
            )
            return session_start
    
    # No more sessions today, return tomorrow's first session
    if session_windows:
        tomorrow = current_date + timedelta(days=1)
        first_session_start, _ = parse_time_window(session_windows[0])
        return KST.localize(
            datetime.combine(tomorrow, first_session_start)
        )
    
    return None


def get_session_vwap_start(dt: Optional[datetime] = None) -> datetime:
    """Get the session VWAP calculation start time (00:00 KST).
    
    Args:
        dt: Reference datetime (default: current KST time)
        
    Returns:
        Start of trading day (00:00 KST) for sVWAP calculation
    """
    if dt is None:
        dt = get_kst_now()
    
    kst_dt = to_kst(dt)
    session_start = KST.localize(
        datetime.combine(kst_dt.date(), time(0, 0, 0))
    )
    
    return session_start


def get_orb_window_times(window_str: str = "09:00-10:00") -> Tuple[datetime, datetime]:
    """Get ORB (Opening Range Box) window start and end times for today.
    
    Args:
        window_str: ORB window string (requirement.md: "09:00-10:00")
        
    Returns:
        Tuple of (start_datetime, end_datetime) in KST
    """
    start_time, end_time = parse_time_window(window_str)
    today = get_kst_now().date()
    
    start_dt = KST.localize(datetime.combine(today, start_time))
    end_dt = KST.localize(datetime.combine(today, end_time))
    
    return start_dt, end_dt


def minutes_until_next_candle(candle_unit: int = 5, dt: Optional[datetime] = None) -> int:
    """Calculate minutes until the next candle close.
    
    Args:
        candle_unit: Candle unit in minutes (default: 5)
        dt: Reference datetime (default: current KST time)
        
    Returns:
        Minutes until next candle close
    """
    if dt is None:
        dt = get_kst_now()
    
    kst_dt = to_kst(dt)
    
    # Calculate minutes since midnight
    minutes_since_midnight = kst_dt.hour * 60 + kst_dt.minute
    
    # Calculate minutes until next candle
    minutes_to_next = candle_unit - (minutes_since_midnight % candle_unit)
    
    return minutes_to_next


def round_to_candle_time(dt: datetime, candle_unit: int = 5) -> datetime:
    """Round datetime to the nearest candle open time.
    
    Args:
        dt: Input datetime
        candle_unit: Candle unit in minutes
        
    Returns:
        Datetime rounded to candle open time
    """
    kst_dt = to_kst(dt)
    
    # Calculate minutes since midnight
    total_minutes = kst_dt.hour * 60 + kst_dt.minute
    
    # Round down to nearest candle interval
    rounded_minutes = (total_minutes // candle_unit) * candle_unit
    
    # Create new datetime with rounded time
    rounded_time = time(
        hour=rounded_minutes // 60,
        minute=rounded_minutes % 60,
        second=0,
        microsecond=0
    )
    
    return KST.localize(
        datetime.combine(kst_dt.date(), rounded_time)
    )


def get_candle_open_time(dt: datetime, candle_unit: int = 5) -> datetime:
    """Get the candle open time for the given datetime.
    
    Args:
        dt: Input datetime
        candle_unit: Candle unit in minutes
        
    Returns:
        Candle open datetime
    """
    return round_to_candle_time(dt, candle_unit)


def is_market_holiday(dt: Optional[datetime] = None) -> bool:
    """Check if given date is a market holiday (basic implementation).
    
    Note: This is a basic implementation. For production use, consider
    integrating with a proper Korean market calendar service.
    
    Args:
        dt: Date to check (default: current KST date)
        
    Returns:
        True if market holiday (currently only checks weekends)
    """
    if dt is None:
        dt = get_kst_now()
    
    kst_dt = to_kst(dt)
    
    # Basic check: weekends are holidays
    # In production, add Korean national holidays
    return kst_dt.weekday() >= 5  # Saturday = 5, Sunday = 6


def get_market_open_datetime(dt: Optional[datetime] = None) -> datetime:
    """Get the market open datetime for the given date.
    
    Args:
        dt: Reference date (default: current KST date)
        
    Returns:
        Market open datetime (09:00 KST)
    """
    if dt is None:
        dt = get_kst_now()
    
    kst_dt = to_kst(dt)
    market_open_time = time(9, 0, 0)  # 09:00 KST
    
    return KST.localize(
        datetime.combine(kst_dt.date(), market_open_time)
    )


def format_duration(seconds: int) -> str:
    """Format duration in seconds to human-readable format.
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Formatted duration string (e.g., "1h 23m 45s")
    """
    if seconds < 0:
        return "0s"
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if seconds > 0 or not parts:
        parts.append(f"{seconds}s")
    
    return " ".join(parts)


def create_kst_datetime(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    """Create a KST timezone-aware datetime.
    
    Args:
        year: Year
        month: Month
        day: Day
        hour: Hour (default: 0)
        minute: Minute (default: 0)
        second: Second (default: 0)
        
    Returns:
        KST timezone-aware datetime
    """
    return KST.localize(
        datetime(year, month, day, hour, minute, second)
    )


def get_trading_day_start(dt: Optional[datetime] = None) -> datetime:
    """Get the start of the trading day (00:00 KST).
    
    This is used for session VWAP calculation and daily metrics.
    
    Args:
        dt: Reference datetime (default: current KST time)
        
    Returns:
        Start of trading day (00:00 KST)
    """
    return get_session_vwap_start(dt)


def get_trading_day_end(dt: Optional[datetime] = None) -> datetime:
    """Get the end of the trading day (23:59:59 KST).
    
    Args:
        dt: Reference datetime (default: current KST time)
        
    Returns:
        End of trading day (23:59:59 KST)
    """
    if dt is None:
        dt = get_kst_now()
    
    kst_dt = to_kst(dt)
    day_end = KST.localize(
        datetime.combine(kst_dt.date(), time(23, 59, 59))
    )
    
    return day_end
