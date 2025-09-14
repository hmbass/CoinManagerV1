"""Pytest configuration and shared fixtures."""

import pytest
import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock
from pathlib import Path

from src.utils.config import Config, EnvironmentConfig, get_config
from src.utils.time_utils import get_kst_now
from src.api.upbit_rest import UpbitRestClient
from src.data.features import FeatureResult


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def config():
    """Provide test configuration."""
    return get_config()


@pytest.fixture
def env_config():
    """Provide test environment configuration."""
    return EnvironmentConfig(
        upbit_access_key="test_access_key",
        upbit_secret_key="test_secret_key",
        trading_mode="paper",
        environment="test"
    )


@pytest.fixture
def mock_api_client():
    """Provide mocked Upbit API client."""
    client = Mock(spec=UpbitRestClient)
    
    # Mock common API responses
    client.get_markets = AsyncMock(return_value=[
        {"market": "KRW-BTC", "korean_name": "비트코인", "english_name": "Bitcoin"},
        {"market": "KRW-ETH", "korean_name": "이더리움", "english_name": "Ethereum"},
        {"market": "KRW-SOL", "korean_name": "솔라나", "english_name": "Solana"}
    ])
    
    client.get_candles = AsyncMock(return_value=generate_mock_candles())
    
    client.get_tickers = AsyncMock(return_value=[{
        "market": "KRW-BTC",
        "trade_price": 50000000,
        "acc_trade_volume_24h": 1000000
    }])
    
    client.get_orderbook = AsyncMock(return_value=[{
        "market": "KRW-BTC",
        "orderbook_units": [
            {"ask_price": 50001000, "bid_price": 49999000, "ask_size": 0.1, "bid_size": 0.1}
        ]
    }])
    
    client.get_accounts = AsyncMock(return_value=[
        {"currency": "KRW", "balance": "1000000.0", "locked": "0.0"}
    ])
    
    client.health_check = AsyncMock(return_value=True)
    client.close = AsyncMock()
    
    return client


def generate_mock_candles(count: int = 200, base_price: float = 50000000) -> list:
    """Generate mock candle data for testing."""
    candles = []
    current_time = get_kst_now()
    
    for i in range(count):
        timestamp = current_time - timedelta(minutes=(count - i) * 5)
        
        # Generate realistic OHLCV data
        open_price = base_price * (1 + (i * 0.001))
        high_price = open_price * 1.02
        low_price = open_price * 0.98
        close_price = open_price * (1 + ((i % 10 - 5) * 0.005))
        volume = 100 + (i % 50)
        
        candles.append({
            "candle_date_time_kst": timestamp.isoformat(),
            "opening_price": open_price,
            "high_price": high_price,
            "low_price": low_price,
            "trade_price": close_price,
            "candle_acc_trade_volume": volume,
            "timestamp": int(timestamp.timestamp() * 1000)
        })
    
    return candles


@pytest.fixture
def sample_candles():
    """Provide sample candle data."""
    return generate_mock_candles()


@pytest.fixture
def sample_feature_result():
    """Provide sample feature calculation result."""
    return FeatureResult(
        rvol=2.5,
        rs=0.015,  # 1.5% relative strength
        svwap=50000000,
        atr_14=1000000,
        ema_20=49500000,
        ema_50=49000000,
        trend=1,
        rvol_z=1.5,
        depth_score=0.7,
        final_score=0.75,
        price=50000000,
        volume=150,
        spread_bp=2.0,
        market="KRW-BTC",
        timestamp=get_kst_now().isoformat(),
        data_points=200
    )


@pytest.fixture
def temp_data_dir(tmp_path):
    """Provide temporary directory for test data."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return str(data_dir)


@pytest.mark.unit
def unit_test():
    """Marker for unit tests."""
    pass


@pytest.mark.integration  
def integration_test():
    """Marker for integration tests."""
    pass


@pytest.mark.e2e
def e2e_test():
    """Marker for end-to-end tests."""
    pass


@pytest.mark.paper
def paper_test():
    """Marker for paper trading tests."""
    pass


@pytest.mark.slow
def slow_test():
    """Marker for slow-running tests."""
    pass
