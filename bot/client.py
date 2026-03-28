"""Low-level Binance Futures Testnet REST client.

Handles:
- HMAC-SHA256 request signing
- Timestamping
- HTTP request execution with retries
- Structured error parsing
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .logging_config import get_logger

logger = get_logger("client")

TESTNET_BASE_URL = "https://testnet.binancefuture.com"
API_V1 = "/fapi/v1"

# Retry on transient network errors, not on 4xx (user errors)
_RETRY_STRATEGY = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[500, 502, 503, 504],
    allowed_methods=["GET", "POST", "DELETE"],
)


class BinanceAPIError(Exception):
    """Raised when the Binance API returns an error response."""

    def __init__(self, code: int, message: str, raw: dict):
        self.code = code
        self.message = message
        self.raw = raw
        super().__init__(f"[Binance API {code}] {message}")


class BinanceFuturesClient:
    """Thin wrapper around the Binance USDT-M Futures REST API (Testnet)."""

    def __init__(self, api_key: str, api_secret: str, base_url: str = TESTNET_BASE_URL):
        if not api_key or not api_secret:
            raise ValueError("api_key and api_secret must not be empty.")
        self._api_key = api_key
        self._api_secret = api_secret.encode()
        self._base_url = base_url.rstrip("/")

        self._session = requests.Session()
        adapter = HTTPAdapter(max_retries=_RETRY_STRATEGY)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        self._session.headers.update(
            {
                "X-MBX-APIKEY": self._api_key,
                "Content-Type": "application/x-www-form-urlencoded",
            }
        )
        logger.debug("BinanceFuturesClient initialised. base_url=%s", self._base_url)

    # ------------------------------------------------------------------
    # Signing helpers
    # ------------------------------------------------------------------

    def _timestamp(self) -> int:
        return int(time.time() * 1000)

    def _sign(self, params: dict) -> str:
        query_string = urlencode(params)
        signature = hmac.new(
            self._api_secret, query_string.encode(), hashlib.sha256
        ).hexdigest()
        return signature

    def _signed_params(self, params: Optional[dict] = None) -> dict:
        p = params.copy() if params else {}
        p["timestamp"] = self._timestamp()
        p["recvWindow"] = 5000
        p["signature"] = self._sign(p)
        return p

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self._base_url}{API_V1}{path}"

    def _handle_response(self, response: requests.Response) -> dict:
        logger.debug(
            "HTTP %s %s → %s", response.request.method, response.url, response.status_code
        )
        try:
            data: dict = response.json()
        except Exception:
            response.raise_for_status()
            raise

        if response.status_code != 200 or (isinstance(data, dict) and "code" in data and data["code"] != 200):
            code = data.get("code", response.status_code)
            msg = data.get("msg", response.text)
            logger.error("API error — code=%s msg=%s", code, msg)
            raise BinanceAPIError(code=code, message=msg, raw=data)

        return data

    def _get(self, path: str, params: Optional[dict] = None, signed: bool = False) -> dict:
        p = self._signed_params(params) if signed else (params or {})
        logger.debug("GET %s params=%s", path, {k: v for k, v in p.items() if k != "signature"})
        resp = self._session.get(self._url(path), params=p, timeout=10)
        return self._handle_response(resp)

    def _post(self, path: str, params: Optional[dict] = None, signed: bool = True) -> dict:
        p = self._signed_params(params) if signed else (params or {})
        logger.debug("POST %s params=%s", path, {k: v for k, v in p.items() if k != "signature"})
        resp = self._session.post(self._url(path), data=p, timeout=10)
        return self._handle_response(resp)

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        """Check server connectivity."""
        try:
            self._get("/ping")
            logger.info("Ping successful — testnet is reachable.")
            return True
        except Exception as exc:
            logger.error("Ping failed: %s", exc)
            return False

    def get_server_time(self) -> int:
        data = self._get("/time")
        return data["serverTime"]

    def get_account(self) -> dict:
        return self._get("/account", signed=True)

    def place_order(self, params: Dict[str, Any]) -> dict:
        """Place a futures order. `params` should be a fully-formed order dict."""
        logger.info("Placing order — %s", {k: v for k, v in params.items()})
        result = self._post("/order", params=params, signed=True)
        logger.info("Order response — %s", result)
        return result
