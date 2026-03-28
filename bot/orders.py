"""Order placement logic — sits between the CLI and the raw API client."""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .client import BinanceFuturesClient, BinanceAPIError
from .logging_config import get_logger
from .validators import (
    ValidationError,
    validate_symbol,
    validate_side,
    validate_order_type,
    validate_quantity,
    validate_price,
    validate_stop_price,
)

logger = get_logger("orders")


def _fmt(value: Optional[Decimal]) -> Optional[str]:
    """Format a Decimal as a plain string without scientific notation."""
    if value is None:
        return None
    return f"{value:f}"


class OrderManager:
    """High-level order operations with built-in validation."""

    def __init__(self, client: BinanceFuturesClient):
        self._client = client

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_params(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Optional[Decimal],
        stop_price: Optional[Decimal],
        time_in_force: str = "GTC",
    ) -> dict:
        params: dict = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": _fmt(quantity),
        }

        if order_type == "LIMIT":
            params["price"] = _fmt(price)
            params["timeInForce"] = time_in_force

        elif order_type == "STOP_MARKET":
            params["stopPrice"] = _fmt(stop_price)

        return params

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def place(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: str | float,
        price: Optional[str | float] = None,
        stop_price: Optional[str | float] = None,
    ) -> dict:
        """
        Validate inputs, build request params, submit order, return response.

        Returns a dict with keys:
            orderId, symbol, side, type, status,
            origQty, executedQty, avgPrice, price (for LIMIT)
        """
        # --- Validate ---
        symbol = validate_symbol(symbol)
        side = validate_side(side)
        order_type = validate_order_type(order_type)
        qty = validate_quantity(quantity)
        p = validate_price(price, order_type)
        sp = validate_stop_price(stop_price, order_type)

        # --- Build params ---
        params = self._build_params(symbol, side, order_type, qty, p, sp)

        logger.info(
            "Submitting %s %s order | symbol=%s qty=%s price=%s stop=%s",
            side, order_type, symbol, qty, p, sp,
        )

        # --- Submit ---
        try:
            response = self._client.place_order(params)
        except BinanceAPIError as exc:
            logger.error("Order placement failed: %s", exc)
            raise
        except Exception as exc:
            logger.error("Unexpected error during order placement: %s", exc, exc_info=True)
            raise

        return response
