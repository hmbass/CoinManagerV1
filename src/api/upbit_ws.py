"""Upbit WebSocket client for real-time market data.

This module provides a WebSocket client for receiving real-time market data
from Upbit, including ticker updates, orderbook changes, and trade data.

Features:
- Automatic reconnection with exponential backoff
- Subscription management
- Structured message handling
- Error recovery and logging

Based on requirement.md FR-2 (WebSocket data collection).
"""

import asyncio
import json
import uuid
from typing import Dict, List, Optional, Callable, Any, Set
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from ..utils.config import ExchangeConfig
from ..utils.logging import get_api_logger, correlation_context
from ..utils.time_utils import get_kst_now


class UpbitWebSocketError(Exception):
    """Base exception for WebSocket errors."""
    pass


class UpbitWebSocketClient:
    """Upbit WebSocket client for real-time market data.
    
    Supports:
    - ticker: Real-time price updates
    - orderbook: Real-time orderbook changes
    - trade: Real-time trade data
    - Automatic reconnection with backoff
    - Subscription management
    - Message callbacks
    """
    
    def __init__(
        self,
        exchange_config: ExchangeConfig,
        ping_interval: int = 30,
        max_reconnect_attempts: int = 10,
        initial_reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 60.0
    ):
        """Initialize WebSocket client.
        
        Args:
            exchange_config: Exchange configuration
            ping_interval: Ping interval in seconds
            max_reconnect_attempts: Maximum reconnection attempts
            initial_reconnect_delay: Initial reconnection delay
            max_reconnect_delay: Maximum reconnection delay
        """
        self.config = exchange_config
        self.logger = get_api_logger()
        
        # WebSocket connection
        self.websocket: Optional[websockets.WebSocketServerProtocol] = None
        self.is_connected = False
        self.is_connecting = False
        
        # Connection settings
        self.ping_interval = ping_interval
        self.max_reconnect_attempts = max_reconnect_attempts
        self.initial_reconnect_delay = initial_reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay
        
        # Reconnection state
        self.reconnect_attempts = 0
        self.should_reconnect = True
        
        # Subscription management
        self.subscriptions: Set[str] = set()
        self.subscription_callbacks: Dict[str, List[Callable]] = {}
        
        # Message handling
        self.message_handlers: Dict[str, Callable] = {
            'ticker': self._handle_ticker,
            'orderbook': self._handle_orderbook,
            'trade': self._handle_trade
        }
        
        # Tasks
        self.listen_task: Optional[asyncio.Task] = None
        self.ping_task: Optional[asyncio.Task] = None
        
    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
    
    async def connect(self) -> None:
        """Connect to Upbit WebSocket server."""
        if self.is_connected or self.is_connecting:
            return
        
        self.is_connecting = True
        
        try:
            with correlation_context():
                self.logger.info(
                    "Connecting to Upbit WebSocket",
                    data={"url": self.config.websocket_url}
                )
                
                self.websocket = await websockets.connect(
                    self.config.websocket_url,
                    ping_interval=None,  # Handle ping manually
                    ping_timeout=self.config.timeout,
                    close_timeout=10,
                    max_size=2**20,  # 1MB max message size
                    compression=None
                )
                
                self.is_connected = True
                self.is_connecting = False
                self.reconnect_attempts = 0
                
                self.logger.info("WebSocket connected successfully")
                
                # Start listening and ping tasks
                self.listen_task = asyncio.create_task(self._listen_loop())
                self.ping_task = asyncio.create_task(self._ping_loop())
                
                # Resubscribe to previous subscriptions
                if self.subscriptions:
                    await self._resubscribe()
                
        except Exception as e:
            self.is_connecting = False
            self.logger.error(f"Failed to connect to WebSocket: {e}")
            
            if self.should_reconnect:
                await self._schedule_reconnect()
            else:
                raise UpbitWebSocketError(f"WebSocket connection failed: {e}")
    
    async def disconnect(self) -> None:
        """Disconnect from WebSocket server."""
        self.should_reconnect = False
        
        with correlation_context():
            self.logger.info("Disconnecting from WebSocket")
            
            # Cancel tasks
            if self.listen_task and not self.listen_task.done():
                self.listen_task.cancel()
                try:
                    await self.listen_task
                except asyncio.CancelledError:
                    pass
            
            if self.ping_task and not self.ping_task.done():
                self.ping_task.cancel()
                try:
                    await self.ping_task
                except asyncio.CancelledError:
                    pass
            
            # Close WebSocket connection
            if self.websocket and not self.websocket.closed:
                await self.websocket.close()
            
            self.is_connected = False
            self.websocket = None
            
            self.logger.info("WebSocket disconnected")
    
    async def _listen_loop(self) -> None:
        """Main message listening loop."""
        while self.is_connected and self.websocket:
            try:
                message = await self.websocket.recv()
                await self._handle_message(message)
                
            except ConnectionClosed:
                self.logger.warning("WebSocket connection closed")
                self.is_connected = False
                
                if self.should_reconnect:
                    await self._schedule_reconnect()
                break
                
            except WebSocketException as e:
                self.logger.error(f"WebSocket error: {e}")
                self.is_connected = False
                
                if self.should_reconnect:
                    await self._schedule_reconnect()
                break
                
            except Exception as e:
                self.logger.error(f"Unexpected error in listen loop: {e}")
                await asyncio.sleep(0.1)  # Brief pause before continuing
    
    async def _ping_loop(self) -> None:
        """Send periodic ping messages to keep connection alive."""
        while self.is_connected and self.websocket:
            try:
                await asyncio.sleep(self.ping_interval)
                
                if self.is_connected and self.websocket:
                    pong_waiter = await self.websocket.ping()
                    await asyncio.wait_for(pong_waiter, timeout=10)
                    
                    self.logger.debug("WebSocket ping successful")
                    
            except asyncio.TimeoutError:
                self.logger.warning("WebSocket ping timeout")
                self.is_connected = False
                
                if self.should_reconnect:
                    await self._schedule_reconnect()
                break
                
            except Exception as e:
                self.logger.error(f"Ping error: {e}")
                break
    
    async def _schedule_reconnect(self) -> None:
        """Schedule reconnection with exponential backoff."""
        if not self.should_reconnect or self.reconnect_attempts >= self.max_reconnect_attempts:
            self.logger.error("Max reconnection attempts reached, giving up")
            return
        
        self.reconnect_attempts += 1
        delay = min(
            self.initial_reconnect_delay * (2 ** (self.reconnect_attempts - 1)),
            self.max_reconnect_delay
        )
        
        self.logger.info(
            f"Scheduling reconnection attempt {self.reconnect_attempts} in {delay}s",
            data={"attempt": self.reconnect_attempts, "delay": delay}
        )
        
        await asyncio.sleep(delay)
        
        if self.should_reconnect:
            await self.connect()
    
    async def _resubscribe(self) -> None:
        """Resubscribe to all previous subscriptions."""
        if not self.subscriptions:
            return
        
        self.logger.info(
            f"Resubscribing to {len(self.subscriptions)} channels",
            data={"subscriptions": list(self.subscriptions)}
        )
        
        # Group subscriptions by type
        subscription_groups = {}
        for subscription in self.subscriptions:
            parts = subscription.split(':')
            channel_type = parts[0]
            market = parts[1] if len(parts) > 1 else None
            
            if channel_type not in subscription_groups:
                subscription_groups[channel_type] = []
            
            if market:
                subscription_groups[channel_type].append(market)
        
        # Resubscribe by groups
        for channel_type, markets in subscription_groups.items():
            if markets:
                await self.subscribe(channel_type, markets)
            else:
                await self.subscribe(channel_type)
    
    async def _handle_message(self, message: str) -> None:
        """Handle incoming WebSocket message.
        
        Args:
            message: Raw WebSocket message
        """
        try:
            data = json.loads(message)
            
            # Determine message type
            msg_type = data.get('type')
            if not msg_type:
                self.logger.warning("Received message without type", data={"message": data})
                return
            
            # Handle message based on type
            handler = self.message_handlers.get(msg_type)
            if handler:
                await handler(data)
            else:
                self.logger.debug(f"No handler for message type: {msg_type}", data={"message": data})
            
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to decode WebSocket message: {e}")
        except Exception as e:
            self.logger.error(f"Error handling WebSocket message: {e}")
    
    async def _handle_ticker(self, data: Dict[str, Any]) -> None:
        """Handle ticker message.
        
        Args:
            data: Ticker message data
        """
        market = data.get('code')
        if not market:
            return
        
        subscription_key = f"ticker:{market}"
        callbacks = self.subscription_callbacks.get(subscription_key, [])
        
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(data)
                else:
                    callback(data)
            except Exception as e:
                self.logger.error(f"Error in ticker callback: {e}")
    
    async def _handle_orderbook(self, data: Dict[str, Any]) -> None:
        """Handle orderbook message.
        
        Args:
            data: Orderbook message data
        """
        market = data.get('code')
        if not market:
            return
        
        subscription_key = f"orderbook:{market}"
        callbacks = self.subscription_callbacks.get(subscription_key, [])
        
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(data)
                else:
                    callback(data)
            except Exception as e:
                self.logger.error(f"Error in orderbook callback: {e}")
    
    async def _handle_trade(self, data: Dict[str, Any]) -> None:
        """Handle trade message.
        
        Args:
            data: Trade message data
        """
        market = data.get('code')
        if not market:
            return
        
        subscription_key = f"trade:{market}"
        callbacks = self.subscription_callbacks.get(subscription_key, [])
        
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(data)
                else:
                    callback(data)
            except Exception as e:
                self.logger.error(f"Error in trade callback: {e}")
    
    async def subscribe(
        self,
        channel: str,
        markets: Optional[List[str]] = None,
        callback: Optional[Callable] = None
    ) -> None:
        """Subscribe to a channel.
        
        Args:
            channel: Channel type ('ticker', 'orderbook', 'trade')
            markets: List of markets to subscribe to
            callback: Optional callback function for messages
        """
        if not self.is_connected or not self.websocket:
            raise UpbitWebSocketError("WebSocket not connected")
        
        if channel not in self.message_handlers:
            raise ValueError(f"Unsupported channel: {channel}")
        
        with correlation_context():
            # Prepare subscription message
            subscription_data = [
                {
                    'ticket': str(uuid.uuid4())[:8]
                },
                {
                    'type': channel
                }
            ]
            
            # Add markets if specified
            if markets:
                subscription_data[1]['codes'] = markets
                
                # Track subscriptions
                for market in markets:
                    subscription_key = f"{channel}:{market}"
                    self.subscriptions.add(subscription_key)
                    
                    # Add callback
                    if callback:
                        if subscription_key not in self.subscription_callbacks:
                            self.subscription_callbacks[subscription_key] = []
                        self.subscription_callbacks[subscription_key].append(callback)
                
                self.logger.info(
                    f"Subscribing to {channel} for {len(markets)} markets",
                    data={"channel": channel, "markets": markets}
                )
            else:
                subscription_key = channel
                self.subscriptions.add(subscription_key)
                
                if callback:
                    if subscription_key not in self.subscription_callbacks:
                        self.subscription_callbacks[subscription_key] = []
                    self.subscription_callbacks[subscription_key].append(callback)
                
                self.logger.info(f"Subscribing to {channel} (all markets)")
            
            # Send subscription message
            subscription_message = json.dumps(subscription_data)
            await self.websocket.send(subscription_message)
    
    async def unsubscribe(self, channel: str, markets: Optional[List[str]] = None) -> None:
        """Unsubscribe from a channel.
        
        Note: Upbit WebSocket doesn't support selective unsubscription.
        This method removes subscriptions from internal tracking only.
        
        Args:
            channel: Channel type
            markets: Markets to unsubscribe from
        """
        with correlation_context():
            if markets:
                for market in markets:
                    subscription_key = f"{channel}:{market}"
                    self.subscriptions.discard(subscription_key)
                    self.subscription_callbacks.pop(subscription_key, None)
                
                self.logger.info(
                    f"Unsubscribed from {channel} for {len(markets)} markets",
                    data={"channel": channel, "markets": markets}
                )
            else:
                subscription_key = channel
                self.subscriptions.discard(subscription_key)
                self.subscription_callbacks.pop(subscription_key, None)
                
                self.logger.info(f"Unsubscribed from {channel}")
    
    async def subscribe_ticker(self, markets: List[str], callback: Optional[Callable] = None) -> None:
        """Subscribe to ticker updates.
        
        Args:
            markets: List of market codes
            callback: Optional callback for ticker updates
        """
        await self.subscribe('ticker', markets, callback)
    
    async def subscribe_orderbook(self, markets: List[str], callback: Optional[Callable] = None) -> None:
        """Subscribe to orderbook updates.
        
        Args:
            markets: List of market codes
            callback: Optional callback for orderbook updates
        """
        await self.subscribe('orderbook', markets, callback)
    
    async def subscribe_trade(self, markets: List[str], callback: Optional[Callable] = None) -> None:
        """Subscribe to trade updates.
        
        Args:
            markets: List of market codes
            callback: Optional callback for trade updates
        """
        await self.subscribe('trade', markets, callback)
    
    def add_callback(self, channel: str, market: Optional[str], callback: Callable) -> None:
        """Add callback for specific channel/market combination.
        
        Args:
            channel: Channel type
            market: Market code (None for all markets)
            callback: Callback function
        """
        if market:
            subscription_key = f"{channel}:{market}"
        else:
            subscription_key = channel
        
        if subscription_key not in self.subscription_callbacks:
            self.subscription_callbacks[subscription_key] = []
        
        self.subscription_callbacks[subscription_key].append(callback)
    
    def remove_callback(self, channel: str, market: Optional[str], callback: Callable) -> None:
        """Remove callback for specific channel/market combination.
        
        Args:
            channel: Channel type
            market: Market code (None for all markets)
            callback: Callback function to remove
        """
        if market:
            subscription_key = f"{channel}:{market}"
        else:
            subscription_key = channel
        
        callbacks = self.subscription_callbacks.get(subscription_key, [])
        if callback in callbacks:
            callbacks.remove(callback)
        
        if not callbacks:
            self.subscription_callbacks.pop(subscription_key, None)
    
    @property
    def connection_status(self) -> Dict[str, Any]:
        """Get current connection status.
        
        Returns:
            Connection status information
        """
        return {
            "is_connected": self.is_connected,
            "is_connecting": self.is_connecting,
            "reconnect_attempts": self.reconnect_attempts,
            "subscriptions_count": len(self.subscriptions),
            "active_subscriptions": list(self.subscriptions),
            "last_connected": get_kst_now().isoformat() if self.is_connected else None
        }
    
    async def wait_for_connection(self, timeout: float = 30.0) -> bool:
        """Wait for WebSocket connection to be established.
        
        Args:
            timeout: Maximum time to wait
            
        Returns:
            True if connected within timeout
        """
        start_time = asyncio.get_event_loop().time()
        
        while not self.is_connected:
            if asyncio.get_event_loop().time() - start_time > timeout:
                return False
            
            await asyncio.sleep(0.1)
        
        return True
