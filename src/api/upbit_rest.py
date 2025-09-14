"""Upbit REST API client with JWT authentication.

This module provides a comprehensive REST API client for Upbit exchange,
supporting both public and private endpoints with proper authentication,
rate limiting, and error handling.

Based on requirement.md FR-2 (Data Collection) and FR-6 (Order Module).
"""

import asyncio
import hashlib
import hmac
import json
import time
import uuid
from typing import Dict, List, Optional, Any, Union
from urllib.parse import urlencode, urlparse
import httpx
import jwt

from ..utils.config import ExchangeConfig, EnvironmentConfig
from ..utils.logging import get_api_logger, correlation_context
from ..utils.time_utils import get_kst_now


class UpbitAPIError(Exception):
    """Base exception for Upbit API errors."""
    
    def __init__(self, message: str, error_code: Optional[str] = None, status_code: Optional[int] = None):
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code


class UpbitRateLimitError(UpbitAPIError):
    """Exception raised when API rate limit is exceeded."""
    pass


class UpbitAuthenticationError(UpbitAPIError):
    """Exception raised for authentication failures."""
    pass


class UpbitRestClient:
    """Upbit REST API client with comprehensive functionality.
    
    Supports:
    - Public endpoints (market data)
    - Private endpoints (account, orders) with JWT authentication
    - Rate limiting and retry logic
    - Comprehensive error handling
    - Request/response logging
    """
    
    def __init__(
        self,
        exchange_config: ExchangeConfig,
        env_config: EnvironmentConfig,
        enable_request_logging: bool = False,
        enable_response_logging: bool = False
    ):
        """Initialize the Upbit REST client.
        
        Args:
            exchange_config: Exchange configuration
            env_config: Environment configuration with credentials
            enable_request_logging: Enable request logging
            enable_response_logging: Enable response logging
        """
        self.config = exchange_config
        self.env_config = env_config
        self.logger = get_api_logger()
        
        self.enable_request_logging = enable_request_logging or env_config.log_api_requests
        self.enable_response_logging = enable_response_logging or env_config.log_api_responses
        
        # HTTP client configuration
        self.client = httpx.AsyncClient(
            base_url=exchange_config.base_url,
            timeout=exchange_config.timeout,
            limits=httpx.Limits(
                max_connections=exchange_config.max_concurrent_requests,
                max_keepalive_connections=5
            )
        )
        
        # Rate limiting state
        self._request_times: List[float] = []
        self._rate_limit_lock = asyncio.Lock()
        
    async def __aenter__(self):
        """Async context manager entry."""
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
    
    def _generate_jwt_token(self, query_params: Optional[Dict[str, Any]] = None) -> str:
        """Generate JWT token for authenticated requests.
        
        Args:
            query_params: Query parameters to include in token
            
        Returns:
            JWT token string
            
        Raises:
            UpbitAuthenticationError: If credentials are missing
        """
        if not self.env_config.upbit_access_key or not self.env_config.upbit_secret_key:
            raise UpbitAuthenticationError("Upbit API credentials not configured")
        
        payload = {
            'access_key': self.env_config.upbit_access_key,
            'nonce': str(uuid.uuid4()),
            'timestamp': int(time.time() * 1000),
        }
        
        if query_params:
            # Create query hash for parameters
            query_string = urlencode(query_params, doseq=True)
            m = hashlib.sha512()
            m.update(query_string.encode())
            query_hash = m.hexdigest()
            
            payload['query_hash'] = query_hash
            payload['query_hash_alg'] = 'SHA512'
        
        # Create JWT token
        token = jwt.encode(
            payload,
            self.env_config.upbit_secret_key,
            algorithm='HS256'
        )
        
        return token
    
    async def _wait_for_rate_limit(self):
        """Wait if necessary to respect rate limits."""
        async with self._rate_limit_lock:
            now = time.time()
            
            # Remove old requests (older than 1 minute)
            self._request_times = [t for t in self._request_times if now - t < 60]
            
            # Check if we need to wait
            if len(self._request_times) >= 600:  # 600 requests per minute limit
                oldest_request = min(self._request_times)
                wait_time = 60 - (now - oldest_request)
                
                if wait_time > 0:
                    self.logger.warning(
                        f"Rate limit approaching, waiting {wait_time:.2f} seconds",
                        data={"wait_time": wait_time, "requests_in_window": len(self._request_times)}
                    )
                    await asyncio.sleep(wait_time)
            
            self._request_times.append(now)
    
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        require_auth: bool = False,
        retry_count: int = 0
    ) -> Dict[str, Any]:
        """Make HTTP request to Upbit API.
        
        Args:
            method: HTTP method (GET, POST, DELETE)
            endpoint: API endpoint
            params: Query parameters
            data: Request body data
            require_auth: Whether authentication is required
            retry_count: Current retry attempt
            
        Returns:
            JSON response data
            
        Raises:
            UpbitAPIError: For API errors
            UpbitRateLimitError: For rate limit errors
            UpbitAuthenticationError: For auth errors
        """
        await self._wait_for_rate_limit()
        
        # Prepare headers
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        # Add authentication if required
        if require_auth:
            query_params = params or {}
            if data:
                query_params.update(data)
            
            token = self._generate_jwt_token(query_params)
            headers['Authorization'] = f'Bearer {token}'
        
        # Log request if enabled
        if self.enable_request_logging:
            self.logger.api_call(
                endpoint=endpoint,
                method=method,
                data={
                    "params": params,
                    "require_auth": require_auth,
                    "retry_count": retry_count
                }
            )
        
        try:
            # Make request
            response = await self.client.request(
                method=method,
                url=endpoint,
                params=params,
                json=data if method != 'GET' else None,
                headers=headers
            )
            
            # Log response if enabled
            if self.enable_response_logging:
                self.logger.api_call(
                    endpoint=endpoint,
                    method=method,
                    data={
                        "status_code": response.status_code,
                        "response_size": len(response.content),
                        "retry_count": retry_count
                    }
                )
            
            # Handle different status codes
            if response.status_code == 200:
                return response.json()
            
            elif response.status_code == 429:
                # Rate limit exceeded
                if retry_count < self.config.max_retries:
                    wait_time = (2 ** retry_count) * self.config.retry_backoff
                    self.logger.warning(
                        f"Rate limit exceeded, retrying in {wait_time}s",
                        data={"retry_count": retry_count, "wait_time": wait_time}
                    )
                    await asyncio.sleep(wait_time)
                    return await self._make_request(method, endpoint, params, data, require_auth, retry_count + 1)
                else:
                    raise UpbitRateLimitError("Rate limit exceeded, max retries reached")
            
            elif response.status_code == 401:
                raise UpbitAuthenticationError("Authentication failed")
            
            else:
                # Try to parse error response
                try:
                    error_data = response.json()
                    error_message = error_data.get('error', {}).get('message', 'Unknown error')
                    error_code = error_data.get('error', {}).get('name', 'UNKNOWN_ERROR')
                except:
                    error_message = f"HTTP {response.status_code}: {response.text}"
                    error_code = f"HTTP_{response.status_code}"
                
                raise UpbitAPIError(error_message, error_code, response.status_code)
        
        except httpx.TimeoutException:
            if retry_count < self.config.max_retries:
                wait_time = (2 ** retry_count) * self.config.retry_backoff
                self.logger.warning(
                    f"Request timeout, retrying in {wait_time}s",
                    data={"retry_count": retry_count, "wait_time": wait_time}
                )
                await asyncio.sleep(wait_time)
                return await self._make_request(method, endpoint, params, data, require_auth, retry_count + 1)
            else:
                raise UpbitAPIError("Request timeout, max retries reached")
        
        except httpx.RequestError as e:
            if retry_count < self.config.max_retries:
                wait_time = (2 ** retry_count) * self.config.retry_backoff
                self.logger.warning(
                    f"Request error: {e}, retrying in {wait_time}s",
                    data={"retry_count": retry_count, "wait_time": wait_time, "error": str(e)}
                )
                await asyncio.sleep(wait_time)
                return await self._make_request(method, endpoint, params, data, require_auth, retry_count + 1)
            else:
                raise UpbitAPIError(f"Request error: {e}")
    
    # Public Market Data Endpoints (FR-2)
    
    async def get_markets(self, is_details: bool = True) -> List[Dict[str, Any]]:
        """Get market list with details.
        
        Args:
            is_details: Include detailed information (warning flags, etc.)
            
        Returns:
            List of market information
        """
        with correlation_context():
            params = {'isDetails': 'true'} if is_details else {}
            return await self._make_request('GET', '/v1/market/all', params=params)
    
    async def get_candles(
        self,
        market: str,
        unit: int = 5,
        count: int = 200,
        to: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get candle data for a market.
        
        Args:
            market: Market code (e.g., 'KRW-BTC')
            unit: Candle unit in minutes (1, 3, 5, 15, 10, 30, 60, 240)
            count: Number of candles (max 200)
            to: End datetime in ISO format
            
        Returns:
            List of candle data (requirement.md: 200+ candles)
        """
        with correlation_context():
            if unit not in [1, 3, 5, 15, 10, 30, 60, 240]:
                raise ValueError(f"Invalid candle unit: {unit}")
            
            if count > 200:
                raise ValueError("Maximum candle count is 200")
            
            params = {
                'market': market,
                'count': count
            }
            
            if to:
                params['to'] = to
            
            return await self._make_request('GET', f'/v1/candles/minutes/{unit}', params=params)
    
    async def get_multiple_candles(
        self,
        markets: List[str],
        unit: int = 5,
        count: int = 200
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get candle data for multiple markets concurrently.
        
        Args:
            markets: List of market codes
            unit: Candle unit in minutes
            count: Number of candles per market
            
        Returns:
            Dict mapping market codes to candle data
        """
        with correlation_context():
            self.logger.info(
                f"Fetching candles for {len(markets)} markets",
                data={"markets": markets, "unit": unit, "count": count}
            )
            
            # Create tasks for concurrent requests
            tasks = [
                self.get_candles(market, unit, count)
                for market in markets
            ]
            
            # Execute concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            candle_data = {}
            for market, result in zip(markets, results):
                if isinstance(result, Exception):
                    self.logger.error(
                        f"Failed to fetch candles for {market}",
                        data={"market": market, "error": str(result)}
                    )
                else:
                    candle_data[market] = result
            
            self.logger.info(
                f"Successfully fetched candles for {len(candle_data)}/{len(markets)} markets",
                data={"successful_markets": len(candle_data), "total_markets": len(markets)}
            )
            
            return candle_data
    
    async def get_orderbook(self, markets: Union[str, List[str]]) -> List[Dict[str, Any]]:
        """Get orderbook data for markets.
        
        Args:
            markets: Market code(s) to get orderbook for
            
        Returns:
            List of orderbook data
        """
        with correlation_context():
            if isinstance(markets, str):
                markets = [markets]
            
            params = {'markets': ','.join(markets)}
            return await self._make_request('GET', '/v1/orderbook', params=params)
    
    async def get_tickers(self, markets: Union[str, List[str]]) -> List[Dict[str, Any]]:
        """Get ticker data for markets.
        
        Args:
            markets: Market code(s) to get ticker for
            
        Returns:
            List of ticker data
        """
        with correlation_context():
            if isinstance(markets, str):
                markets = [markets]
            
            params = {'markets': ','.join(markets)}
            return await self._make_request('GET', '/v1/ticker', params=params)
    
    async def get_trades_ticks(
        self,
        market: str,
        count: int = 100,
        cursor: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get recent trades for a market.
        
        Args:
            market: Market code
            count: Number of trades (max 500)
            cursor: Pagination cursor
            
        Returns:
            List of trade data
        """
        with correlation_context():
            params = {
                'market': market,
                'count': min(count, 500)
            }
            
            if cursor:
                params['cursor'] = cursor
            
            return await self._make_request('GET', '/v1/trades/ticks', params=params)
    
    # Private Account Endpoints (require authentication)
    
    async def get_accounts(self) -> List[Dict[str, Any]]:
        """Get account balances.
        
        Returns:
            List of account balances
        """
        with correlation_context():
            return await self._make_request('GET', '/v1/accounts', require_auth=True)
    
    async def get_orders(
        self,
        market: Optional[str] = None,
        state: str = 'wait',
        states: Optional[List[str]] = None,
        uuids: Optional[List[str]] = None,
        identifiers: Optional[List[str]] = None,
        page: int = 1,
        limit: int = 100,
        order_by: str = 'desc'
    ) -> List[Dict[str, Any]]:
        """Get order list.
        
        Args:
            market: Market code filter
            state: Order state filter
            states: Multiple order states
            uuids: Order UUIDs
            identifiers: Order identifiers
            page: Page number
            limit: Items per page
            order_by: Sort order
            
        Returns:
            List of orders
        """
        with correlation_context():
            params = {
                'page': page,
                'limit': limit,
                'order_by': order_by
            }
            
            if market:
                params['market'] = market
            if state and not states:
                params['state'] = state
            if states:
                params['states[]'] = states
            if uuids:
                params['uuids[]'] = uuids
            if identifiers:
                params['identifiers[]'] = identifiers
            
            return await self._make_request('GET', '/v1/orders', params=params, require_auth=True)
    
    async def get_order(self, uuid: Optional[str] = None, identifier: Optional[str] = None) -> Dict[str, Any]:
        """Get specific order details.
        
        Args:
            uuid: Order UUID
            identifier: Order identifier
            
        Returns:
            Order details
        """
        with correlation_context():
            if not uuid and not identifier:
                raise ValueError("Either uuid or identifier must be provided")
            
            params = {}
            if uuid:
                params['uuid'] = uuid
            if identifier:
                params['identifier'] = identifier
            
            return await self._make_request('GET', '/v1/order', params=params, require_auth=True)
    
    # Private Order Endpoints (FR-6: Order Module)
    
    async def place_order(
        self,
        market: str,
        side: str,
        ord_type: str,
        volume: Optional[str] = None,
        price: Optional[str] = None,
        identifier: Optional[str] = None,
        time_in_force: Optional[str] = None
    ) -> Dict[str, Any]:
        """Place a new order.
        
        Args:
            market: Market code (e.g., 'KRW-BTC')
            side: Order side ('bid' for buy, 'ask' for sell)
            ord_type: Order type ('limit', 'market', 'best')
            volume: Order volume
            price: Order price (required for limit orders)
            identifier: Custom order identifier
            time_in_force: Time in force ('IOC', 'FOK')
            
        Returns:
            Order placement result
        """
        with correlation_context():
            if side not in ['bid', 'ask']:
                raise ValueError("Side must be 'bid' or 'ask'")
            
            if ord_type not in ['limit', 'market', 'best']:
                raise ValueError("Order type must be 'limit', 'market', or 'best'")
            
            if ord_type == 'limit' and not price:
                raise ValueError("Price is required for limit orders")
            
            if ord_type in ['market', 'best'] and side == 'ask' and not volume:
                raise ValueError("Volume is required for market/best sell orders")
            
            data = {
                'market': market,
                'side': side,
                'ord_type': ord_type
            }
            
            if volume:
                data['volume'] = str(volume)
            if price:
                data['price'] = str(price)
            if identifier:
                data['identifier'] = identifier
            if time_in_force:
                data['time_in_force'] = time_in_force
            
            self.logger.order_event(
                "place_order_request",
                {
                    "market": market,
                    "side": side,
                    "ord_type": ord_type,
                    "volume": volume,
                    "price": price,
                    "time_in_force": time_in_force
                }
            )
            
            result = await self._make_request('POST', '/v1/orders', data=data, require_auth=True)
            
            self.logger.order_event(
                "place_order_response",
                {
                    "uuid": result.get('uuid'),
                    "state": result.get('state'),
                    "market": result.get('market'),
                    "side": result.get('side')
                }
            )
            
            return result
    
    async def cancel_order(self, uuid: Optional[str] = None, identifier: Optional[str] = None) -> Dict[str, Any]:
        """Cancel an existing order.
        
        Args:
            uuid: Order UUID
            identifier: Order identifier
            
        Returns:
            Cancellation result
        """
        with correlation_context():
            if not uuid and not identifier:
                raise ValueError("Either uuid or identifier must be provided")
            
            data = {}
            if uuid:
                data['uuid'] = uuid
            if identifier:
                data['identifier'] = identifier
            
            self.logger.order_event(
                "cancel_order_request",
                {"uuid": uuid, "identifier": identifier}
            )
            
            result = await self._make_request('DELETE', '/v1/order', data=data, require_auth=True)
            
            self.logger.order_event(
                "cancel_order_response",
                {
                    "uuid": result.get('uuid'),
                    "state": result.get('state')
                }
            )
            
            return result
    
    async def cancel_orders(self, uuids: Optional[List[str]] = None, identifiers: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Cancel multiple orders.
        
        Args:
            uuids: List of order UUIDs
            identifiers: List of order identifiers
            
        Returns:
            List of cancellation results
        """
        with correlation_context():
            if not uuids and not identifiers:
                raise ValueError("Either uuids or identifiers must be provided")
            
            data = {}
            if uuids:
                data['uuids[]'] = uuids
            if identifiers:
                data['identifiers[]'] = identifiers
            
            self.logger.order_event(
                "cancel_orders_request",
                {"uuids": uuids, "identifiers": identifiers}
            )
            
            result = await self._make_request('DELETE', '/v1/orders', data=data, require_auth=True)
            
            self.logger.order_event(
                "cancel_orders_response",
                {"cancelled_count": len(result) if isinstance(result, list) else 0}
            )
            
            return result
    
    # Utility methods
    
    async def health_check(self) -> bool:
        """Check API health by fetching market list.
        
        Returns:
            True if API is healthy
        """
        try:
            markets = await self.get_markets(is_details=False)
            return len(markets) > 0
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
            return False
    
    async def get_server_time(self) -> Dict[str, Any]:
        """Get server time (if endpoint exists).
        
        Returns:
            Server time information
        """
        with correlation_context():
            # Note: Upbit doesn't have a dedicated server time endpoint
            # This is a placeholder that could be implemented if available
            return {
                "server_time": get_kst_now().isoformat(),
                "timezone": "Asia/Seoul"
            }
