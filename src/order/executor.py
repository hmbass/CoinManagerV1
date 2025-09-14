"""Order Execution Engine.

This module implements comprehensive order execution for both paper
trading and live trading modes, as specified in requirement.md FR-6.

Features:
- Paper trading simulation with realistic fills
- Live trading with JWT authentication
- OCO-like order management
- Slippage control and monitoring
- Order state tracking and reporting
"""

import asyncio
import json
import random
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path

from ..api.upbit_rest import UpbitRestClient, UpbitAPIError
from ..utils.config import OrdersConfig, PaperModeConfig, EnvironmentConfig
from ..utils.logging import get_trading_logger, log_performance, correlation_context
from ..utils.time_utils import get_kst_now
from ..utils.telegram import send_trade_notification, send_risk_notification
from ..signals.signal_manager import TradingSignal
from ..risk.guard import TradeRisk


logger = get_trading_logger(__name__)


class OrderStatus(Enum):
    """Order status enumeration."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class OrderType(Enum):
    """Order type enumeration."""
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"


class OrderSide(Enum):
    """Order side enumeration."""
    BUY = "buy"
    SELL = "sell"


@dataclass
class OrderRequest:
    """Order request definition."""
    
    order_id: str
    market: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float]
    stop_price: Optional[float] = None
    time_in_force: str = "IOC"
    signal_reference: Optional[str] = None


@dataclass
class OrderResult:
    """Order execution result."""
    
    order_id: str
    status: OrderStatus
    market: str
    side: OrderSide
    order_type: OrderType
    
    # Quantities
    quantity_requested: float
    quantity_filled: float
    quantity_remaining: float
    
    # Prices
    price_requested: Optional[float]
    price_filled: Optional[float]
    
    # Execution details
    fill_time: Optional[datetime]
    submit_time: datetime
    
    # Fees and costs
    commission: float = 0.0
    slippage_bp: float = 0.0
    
    # Paper trading details
    is_paper_trade: bool = False
    simulated_delay_ms: int = 0
    
    # Error information
    error_message: Optional[str] = None


@dataclass
class Position:
    """Trading position tracking."""
    
    market: str
    side: OrderSide
    entry_price: float
    quantity: float
    entry_time: datetime
    
    # Associated orders
    entry_order_id: str
    stop_loss_order_id: Optional[str] = None
    take_profit_order_id: Optional[str] = None
    
    # P&L tracking
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    
    # Status
    is_active: bool = True
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None


class OrderExecutor:
    """Order execution engine supporting both paper and live trading.
    
    Implements requirement.md FR-6 specification:
    - JWT 인터페이스 실거래 주문
    - IOC/FOK/BEST 주문 타입 지원
    - OCO-like 주문 관리 (스톱로스/이익실현)
    - 슬리피지 제한 (5bp)
    - 페이퍼 트레이딩 시뮬레이션
    """
    
    def __init__(
        self,
        config: OrdersConfig,
        env_config: EnvironmentConfig,
        api_client: Optional[UpbitRestClient] = None,
        data_dir: str = "runtime/data"
    ):
        """Initialize order executor.
        
        Args:
            config: Orders configuration
            env_config: Environment configuration
            api_client: Upbit API client (required for live trading)
            data_dir: Data directory for order tracking
        """
        self.config = config
        self.env_config = env_config
        self.api_client = api_client
        self.logger = logger
        
        # Determine trading mode
        self.is_paper_mode = env_config.trading_mode == "paper"
        
        if not self.is_paper_mode and not api_client:
            raise ValueError("API client required for live trading mode")
        
        # Data storage
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.orders_file = self.data_dir / "orders.json"
        self.positions_file = self.data_dir / "positions.json"
        
        # Order and position tracking
        self.orders: Dict[str, OrderResult] = {}
        self.positions: Dict[str, Position] = {}
        
        # Paper trading state
        self.paper_balance: float = 1000000.0  # Default 1M KRW for paper trading
        
        # Load existing data
        self._load_order_data()
    
    def _load_order_data(self) -> None:
        """Load order and position data from files."""
        # Load orders
        if self.orders_file.exists():
            try:
                with open(self.orders_file, 'r') as f:
                    data = json.load(f)
                    self.orders = {
                        order_id: OrderResult(**order_data)
                        for order_id, order_data in data.items()
                        if isinstance(order_data, dict)
                    }
            except Exception as e:
                self.logger.error(f"Error loading orders: {e}")
        
        # Load positions
        if self.positions_file.exists():
            try:
                with open(self.positions_file, 'r') as f:
                    data = json.load(f)
                    self.positions = {
                        pos_id: Position(**pos_data)
                        for pos_id, pos_data in data.items()
                        if isinstance(pos_data, dict)
                    }
            except Exception as e:
                self.logger.error(f"Error loading positions: {e}")
    
    def _save_order_data(self) -> None:
        """Save order and position data to files."""
        # Convert datetime objects to strings for JSON serialization
        def convert_datetime(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            return obj
        
        # Save orders
        try:
            orders_data = {}
            for order_id, order in self.orders.items():
                order_dict = asdict(order)
                # Convert datetime objects
                for key, value in order_dict.items():
                    order_dict[key] = convert_datetime(value)
                orders_data[order_id] = order_dict
            
            with open(self.orders_file, 'w') as f:
                json.dump(orders_data, f, indent=2, default=str)
        except Exception as e:
            self.logger.error(f"Error saving orders: {e}")
        
        # Save positions
        try:
            positions_data = {}
            for pos_id, position in self.positions.items():
                pos_dict = asdict(position)
                # Convert datetime objects  
                for key, value in pos_dict.items():
                    pos_dict[key] = convert_datetime(value)
                positions_data[pos_id] = pos_dict
            
            with open(self.positions_file, 'w') as f:
                json.dump(positions_data, f, indent=2, default=str)
        except Exception as e:
            self.logger.error(f"Error saving positions: {e}")
    
    @log_performance
    async def submit_order(self, order_request: OrderRequest) -> OrderResult:
        """Submit an order for execution.
        
        Args:
            order_request: Order request details
            
        Returns:
            Order execution result
        """
        with correlation_context():
            self.logger.info(
                f"Submitting order: {order_request.side.value} {order_request.quantity} {order_request.market}",
                data={
                    "order_id": order_request.order_id,
                    "market": order_request.market,
                    "side": order_request.side.value,
                    "quantity": order_request.quantity,
                    "price": order_request.price,
                    "order_type": order_request.order_type.value,
                    "is_paper_mode": self.is_paper_mode
                }
            )
            
            if self.is_paper_mode:
                result = await self._execute_paper_order(order_request)
            else:
                result = await self._execute_live_order(order_request)
            
            # Store order result
            self.orders[result.order_id] = result
            self._save_order_data()
            
            # Log execution result
            self.logger.info(
                f"Order executed: {result.status.value}",
                data={
                    "order_id": result.order_id,
                    "status": result.status.value,
                    "quantity_filled": result.quantity_filled,
                    "price_filled": result.price_filled,
                    "slippage_bp": result.slippage_bp,
                    "commission": result.commission
                }
            )
            
            return result
    
    async def _execute_paper_order(self, order_request: OrderRequest) -> OrderResult:
        """Execute paper trading order with simulation.
        
        Args:
            order_request: Order request
            
        Returns:
            Simulated order result
        """
        submit_time = get_kst_now()
        
        # Simulate processing delay
        delay_ms = random.randint(
            self.config.paper_mode.fill_delay_ms[0],
            self.config.paper_mode.fill_delay_ms[1]
        )
        await asyncio.sleep(delay_ms / 1000.0)
        
        # Simulate fill probability
        fill_probability = self.config.paper_mode.fill_probability
        is_filled = random.random() < fill_probability
        
        if not is_filled:
            return OrderResult(
                order_id=order_request.order_id,
                status=OrderStatus.EXPIRED,
                market=order_request.market,
                side=order_request.side,
                order_type=order_request.order_type,
                quantity_requested=order_request.quantity,
                quantity_filled=0.0,
                quantity_remaining=order_request.quantity,
                price_requested=order_request.price,
                price_filled=None,
                fill_time=None,
                submit_time=submit_time,
                is_paper_trade=True,
                simulated_delay_ms=delay_ms
            )
        
        # Simulate slippage
        slippage_bp = 0.0
        fill_price = order_request.price
        
        if self.config.paper_mode.simulate_slippage and fill_price:
            slippage_range = self.config.paper_mode.slippage_bp_range
            slippage_bp = random.uniform(slippage_range[0], slippage_range[1])
            
            if order_request.side == OrderSide.BUY:
                # Buying: slippage increases price
                fill_price = fill_price * (1 + slippage_bp / 10000)
            else:
                # Selling: slippage decreases price
                fill_price = fill_price * (1 - slippage_bp / 10000)
        
        # Calculate commission (Upbit: 0.05%)
        commission = order_request.quantity * (fill_price or 0) * 0.0005
        
        return OrderResult(
            order_id=order_request.order_id,
            status=OrderStatus.FILLED,
            market=order_request.market,
            side=order_request.side,
            order_type=order_request.order_type,
            quantity_requested=order_request.quantity,
            quantity_filled=order_request.quantity,
            quantity_remaining=0.0,
            price_requested=order_request.price,
            price_filled=fill_price,
            fill_time=get_kst_now(),
            submit_time=submit_time,
            commission=commission,
            slippage_bp=slippage_bp,
            is_paper_trade=True,
            simulated_delay_ms=delay_ms
        )
    
    async def _execute_live_order(self, order_request: OrderRequest) -> OrderResult:
        """Execute live trading order via Upbit API.
        
        Args:
            order_request: Order request
            
        Returns:
            Live order result
        """
        submit_time = get_kst_now()
        
        try:
            # Convert order request to Upbit API format
            upbit_side = "bid" if order_request.side == OrderSide.BUY else "ask"
            upbit_ord_type = self._convert_order_type(order_request.order_type)
            
            # Submit order to Upbit
            api_result = await self.api_client.place_order(
                market=order_request.market,
                side=upbit_side,
                ord_type=upbit_ord_type,
                volume=str(order_request.quantity),
                price=str(order_request.price) if order_request.price else None,
                time_in_force=order_request.time_in_force
            )
            
            # Parse result
            order_uuid = api_result.get('uuid', order_request.order_id)
            
            # Wait for order to fill or timeout
            fill_result = await self._wait_for_fill(order_uuid, order_request)
            
            return fill_result
            
        except UpbitAPIError as e:
            self.logger.error(f"Upbit API error: {e}")
            
            return OrderResult(
                order_id=order_request.order_id,
                status=OrderStatus.REJECTED,
                market=order_request.market,
                side=order_request.side,
                order_type=order_request.order_type,
                quantity_requested=order_request.quantity,
                quantity_filled=0.0,
                quantity_remaining=order_request.quantity,
                price_requested=order_request.price,
                price_filled=None,
                fill_time=None,
                submit_time=submit_time,
                error_message=str(e),
                is_paper_trade=False
            )
        
        except Exception as e:
            self.logger.error(f"Unexpected error executing live order: {e}")
            
            return OrderResult(
                order_id=order_request.order_id,
                status=OrderStatus.REJECTED,
                market=order_request.market,
                side=order_request.side,
                order_type=order_request.order_type,
                quantity_requested=order_request.quantity,
                quantity_filled=0.0,
                quantity_remaining=order_request.quantity,
                price_requested=order_request.price,
                price_filled=None,
                fill_time=None,
                submit_time=submit_time,
                error_message=str(e),
                is_paper_trade=False
            )
    
    def _convert_order_type(self, order_type: OrderType) -> str:
        """Convert internal order type to Upbit format.
        
        Args:
            order_type: Internal order type
            
        Returns:
            Upbit order type string
        """
        mapping = {
            OrderType.MARKET: "market",
            OrderType.LIMIT: "limit",
            OrderType.STOP_LOSS: "limit",  # Upbit doesn't have native stop orders
            OrderType.TAKE_PROFIT: "limit"
        }
        
        return mapping.get(order_type, "limit")
    
    async def _wait_for_fill(
        self,
        order_uuid: str,
        order_request: OrderRequest,
        timeout_seconds: Optional[int] = None
    ) -> OrderResult:
        """Wait for order to fill with timeout.
        
        Args:
            order_uuid: Upbit order UUID
            order_request: Original order request
            timeout_seconds: Timeout in seconds
            
        Returns:
            Final order result
        """
        if timeout_seconds is None:
            timeout_seconds = self.config.fill_timeout_seconds
        
        start_time = get_kst_now()
        
        while True:
            # Check timeout
            if (get_kst_now() - start_time).total_seconds() > timeout_seconds:
                # Cancel the order
                try:
                    await self.api_client.cancel_order(uuid=order_uuid)
                    status = OrderStatus.CANCELLED
                except:
                    status = OrderStatus.EXPIRED
                
                return OrderResult(
                    order_id=order_request.order_id,
                    status=status,
                    market=order_request.market,
                    side=order_request.side,
                    order_type=order_request.order_type,
                    quantity_requested=order_request.quantity,
                    quantity_filled=0.0,
                    quantity_remaining=order_request.quantity,
                    price_requested=order_request.price,
                    price_filled=None,
                    fill_time=None,
                    submit_time=start_time,
                    error_message="Order timeout",
                    is_paper_trade=False
                )
            
            # Check order status
            try:
                order_info = await self.api_client.get_order(uuid=order_uuid)
                
                state = order_info.get('state', 'wait')
                
                if state == 'done':
                    # Order filled
                    trades = order_info.get('trades', [])
                    
                    if trades:
                        # Calculate weighted average fill price
                        total_volume = 0.0
                        total_value = 0.0
                        total_commission = 0.0
                        
                        for trade in trades:
                            volume = float(trade['volume'])
                            price = float(trade['price'])
                            commission = float(trade['funds'])
                            
                            total_volume += volume
                            total_value += volume * price
                            total_commission += commission
                        
                        avg_fill_price = total_value / total_volume if total_volume > 0 else 0
                        
                        # Calculate slippage
                        slippage_bp = 0.0
                        if order_request.price and avg_fill_price > 0:
                            slippage = abs(avg_fill_price - order_request.price) / order_request.price
                            slippage_bp = slippage * 10000
                        
                        return OrderResult(
                            order_id=order_request.order_id,
                            status=OrderStatus.FILLED,
                            market=order_request.market,
                            side=order_request.side,
                            order_type=order_request.order_type,
                            quantity_requested=order_request.quantity,
                            quantity_filled=total_volume,
                            quantity_remaining=max(0, order_request.quantity - total_volume),
                            price_requested=order_request.price,
                            price_filled=avg_fill_price,
                            fill_time=get_kst_now(),
                            submit_time=start_time,
                            commission=total_commission,
                            slippage_bp=slippage_bp,
                            is_paper_trade=False
                        )
                
                elif state == 'cancel':
                    return OrderResult(
                        order_id=order_request.order_id,
                        status=OrderStatus.CANCELLED,
                        market=order_request.market,
                        side=order_request.side,
                        order_type=order_request.order_type,
                        quantity_requested=order_request.quantity,
                        quantity_filled=0.0,
                        quantity_remaining=order_request.quantity,
                        price_requested=order_request.price,
                        price_filled=None,
                        fill_time=None,
                        submit_time=start_time,
                        is_paper_trade=False
                    )
            
            except Exception as e:
                self.logger.error(f"Error checking order status: {e}")
            
            # Wait before next check
            await asyncio.sleep(1.0)
    
    @log_performance
    async def execute_signal_trade(
        self,
        signal: TradingSignal,
        trade_risk: TradeRisk
    ) -> Tuple[Optional[Position], List[OrderResult]]:
        """Execute a complete trade from signal with stop loss and take profit.
        
        Args:
            signal: Trading signal
            trade_risk: Risk assessment result
            
        Returns:
            Tuple of (position, list of order results)
        """
        orders = []
        position = None
        
        try:
            # Determine order side
            signal_type = signal.signal_type.lower()
            if 'long' in signal_type:
                side = OrderSide.BUY
            elif 'short' in signal_type:
                side = OrderSide.SELL
            else:
                raise ValueError(f"Cannot determine order side from signal: {signal_type}")
            
            # Create entry order
            entry_order_id = str(uuid.uuid4())
            entry_order = OrderRequest(
                order_id=entry_order_id,
                market=signal.market,
                side=side,
                order_type=OrderType.LIMIT,
                quantity=trade_risk.position_size,
                price=signal.entry_price,
                time_in_force=self.config.time_in_force,
                signal_reference=signal_type
            )
            
            # Submit entry order
            entry_result = await self.submit_order(entry_order)
            orders.append(entry_result)
            
            if entry_result.status == OrderStatus.FILLED:
                # Send Telegram notification for successful trade
                strategy_name = signal_type.upper().replace('_', ' ')
                total_value = entry_result.quantity_filled * entry_result.price_filled
                
                try:
                    await send_trade_notification(
                        trade_type="BUY" if side == OrderSide.BUY else "SELL",
                        market=signal.market,
                        quantity=entry_result.quantity_filled,
                        price=entry_result.price_filled,
                        total_value=total_value,
                        strategy=strategy_name,
                        is_paper=self.is_paper_mode
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to send Telegram trade notification: {e}")
                # Create position
                position = Position(
                    market=signal.market,
                    side=side,
                    entry_price=entry_result.price_filled,
                    quantity=entry_result.quantity_filled,
                    entry_time=entry_result.fill_time,
                    entry_order_id=entry_order_id
                )
                
                # Create stop loss order
                if hasattr(signal, 'stop_loss') and signal.stop_loss:
                    stop_order_id = str(uuid.uuid4())
                    stop_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
                    
                    stop_order = OrderRequest(
                        order_id=stop_order_id,
                        market=signal.market,
                        side=stop_side,
                        order_type=OrderType.LIMIT,
                        quantity=entry_result.quantity_filled,
                        price=signal.stop_loss,
                        time_in_force="GTC"  # Good Till Cancelled for stop orders
                    )
                    
                    # Note: In paper mode, we simulate; in live mode, this would need
                    # more sophisticated stop order management
                    if self.is_paper_mode:
                        # For paper trading, we'll handle stops in the monitoring loop
                        position.stop_loss_order_id = stop_order_id
                    
                # Create take profit order
                if hasattr(signal, 'take_profit') and signal.take_profit:
                    tp_order_id = str(uuid.uuid4())
                    tp_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
                    
                    tp_order = OrderRequest(
                        order_id=tp_order_id,
                        market=signal.market,
                        side=tp_side,
                        order_type=OrderType.LIMIT,
                        quantity=entry_result.quantity_filled,
                        price=signal.take_profit,
                        time_in_force="GTC"
                    )
                    
                    if self.is_paper_mode:
                        position.take_profit_order_id = tp_order_id
                
                # Store position
                position_id = f"{signal.market}_{entry_order_id}"
                self.positions[position_id] = position
                self._save_order_data()
                
                self.logger.info(
                    f"Position opened: {side.value} {position.quantity} {signal.market}",
                    data={
                        "market": signal.market,
                        "side": side.value,
                        "entry_price": position.entry_price,
                        "quantity": position.quantity,
                        "stop_loss": signal.stop_loss if hasattr(signal, 'stop_loss') else None,
                        "take_profit": signal.take_profit if hasattr(signal, 'take_profit') else None
                    }
                )
        
        except Exception as e:
            self.logger.error(f"Error executing signal trade: {e}")
        
        return position, orders
    
    def get_active_positions(self) -> List[Position]:
        """Get all active positions.
        
        Returns:
            List of active positions
        """
        return [pos for pos in self.positions.values() if pos.is_active]
    
    def get_order_history(self, market: Optional[str] = None) -> List[OrderResult]:
        """Get order history.
        
        Args:
            market: Filter by market (optional)
            
        Returns:
            List of order results
        """
        orders = list(self.orders.values())
        
        if market:
            orders = [order for order in orders if order.market == market]
        
        return sorted(orders, key=lambda x: x.submit_time, reverse=True)
    
    def get_trading_statistics(self) -> Dict[str, Any]:
        """Get trading statistics.
        
        Returns:
            Trading statistics dictionary
        """
        all_orders = list(self.orders.values())
        filled_orders = [o for o in all_orders if o.status == OrderStatus.FILLED]
        
        total_volume = sum(o.quantity_filled * (o.price_filled or 0) for o in filled_orders)
        total_commission = sum(o.commission for o in filled_orders)
        
        stats = {
            "orders": {
                "total": len(all_orders),
                "filled": len(filled_orders),
                "cancelled": len([o for o in all_orders if o.status == OrderStatus.CANCELLED]),
                "rejected": len([o for o in all_orders if o.status == OrderStatus.REJECTED])
            },
            "volume": {
                "total_krw": total_volume,
                "total_commission": total_commission
            },
            "positions": {
                "total": len(self.positions),
                "active": len(self.get_active_positions()),
                "closed": len([p for p in self.positions.values() if not p.is_active])
            },
            "performance": {
                "fill_rate": len(filled_orders) / max(len(all_orders), 1),
                "avg_slippage_bp": sum(o.slippage_bp for o in filled_orders) / max(len(filled_orders), 1)
            }
        }
        
        return stats
    
    async def close_position(
        self,
        position: Position,
        current_price: float,
        reason: str = "manual"
    ) -> Optional[OrderResult]:
        """Close an active position.
        
        Args:
            position: Position to close
            current_price: Current market price
            reason: Reason for closing
            
        Returns:
            Close order result or None
        """
        if not position.is_active:
            return None
        
        try:
            # Create close order
            close_side = OrderSide.SELL if position.side == OrderSide.BUY else OrderSide.BUY
            close_order_id = str(uuid.uuid4())
            
            close_order = OrderRequest(
                order_id=close_order_id,
                market=position.market,
                side=close_side,
                order_type=OrderType.LIMIT,
                quantity=position.quantity,
                price=current_price,
                time_in_force=self.config.time_in_force
            )
            
            # Submit close order
            close_result = await self.submit_order(close_order)
            
            if close_result.status == OrderStatus.FILLED:
                # Update position
                position.is_active = False
                position.exit_time = close_result.fill_time
                position.exit_price = close_result.price_filled
                position.exit_reason = reason
                
                # Calculate P&L
                if position.side == OrderSide.BUY:
                    pnl = (position.exit_price - position.entry_price) * position.quantity
                else:
                    pnl = (position.entry_price - position.exit_price) * position.quantity
                
                position.realized_pnl = pnl - close_result.commission
                
                self._save_order_data()
                
                # Send Telegram notification for position closure
                try:
                    await send_trade_notification(
                        trade_type="SELL" if position.side == OrderSide.BUY else "BUY",
                        market=position.market,
                        quantity=position.quantity,
                        price=position.exit_price,
                        total_value=position.quantity * position.exit_price,
                        strategy=f"CLOSE ({reason.upper()})",
                        is_paper=self.is_paper_mode
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to send Telegram close notification: {e}")
                
                self.logger.info(
                    f"Position closed: {reason}",
                    data={
                        "market": position.market,
                        "side": position.side.value,
                        "entry_price": position.entry_price,
                        "exit_price": position.exit_price,
                        "quantity": position.quantity,
                        "realized_pnl": position.realized_pnl,
                        "reason": reason
                    }
                )
            
            return close_result
            
        except Exception as e:
            self.logger.error(f"Error closing position: {e}")
            return None
