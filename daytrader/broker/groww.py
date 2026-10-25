"""Groww Trade API connector (https://groww.in/trade-api/docs/curl).

Two pieces:

* GrowwClient: a small REST client (standard library only) for auth, live
  prices, historical candles, orders and positions.
* GrowwBroker: the live Broker implementation. It is only used when the
  config says "live" AND the server is started with --live. Paper mode uses
  Groww for prices and the PaperBroker for fills.

Authentication (Groww tokens expire every day at 6:00 AM):

    GROWW_ACCESS_TOKEN                 a token generated on Groww's Trading APIs page, or
    GROWW_API_KEY + GROWW_API_SECRET   key and secret; the key must be approved daily on Groww Cloud
    GROWW_API_KEY + a TOTP code        `daytrader groww login --totp 123456`

Keys come from environment variables only. They are never written to the
config file, the logs or the repo.

SEBI rules for live API orders: send them from your registered static IP,
stay under 10 orders per second, and use market protection on market orders.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from ..market_calendar import to_ist
from ..models import Bar
from ..risk import OrderThrottle
from .base import Broker, Order, OrderResult

BASE_URL = "https://api.groww.in"
TOKEN_CACHE = Path("state/groww_token.json")

# Order states that mean the order is finished one way or another.
FILLED_STATES = {"EXECUTED", "COMPLETED"}
DEAD_STATES = {"REJECTED", "FAILED", "CANCELLED"}


class GrowwError(RuntimeError):
    def __init__(self, message: str, code: str = "", status: int = 0):
        super().__init__(f"{code} {message}".strip())
        self.code = code
        self.status = status


def checksum(secret: str, timestamp: str) -> str:
    """Groww's key+secret auth: SHA-256 hex of secret followed by the timestamp."""
    return hashlib.sha256((secret + timestamp).encode()).hexdigest()


def new_reference_id() -> str:
    """8 to 20 alphanumeric characters, at most two hyphens (Groww's rule)."""
    return "DT-" + secrets.token_hex(6).upper()  # 15 characters, one hyphen


class GrowwClient:
    def __init__(self, access_token: str | None = None, base_url: str = BASE_URL,
                 opener: Callable | None = None, timeout: float = 10.0):
        self.access_token = access_token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen

    # ---- plumbing ------------------------------------------------------
    def _request(self, method: str, path: str, params: dict | None = None,
                 body: dict | None = None, auth: str | None = None) -> dict:
        token = auth or self.access_token
        if not token:
            raise GrowwError("no Groww access token; run `daytrader groww login` or set GROWW_ACCESS_TOKEN")
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "X-API-VERSION": "1.0",
            **({"Content-Type": "application/json"} if data else {}),
        })
        try:
            with self._open(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode() or "{}")
                status = getattr(resp, "status", 200)
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read().decode() or "{}")
            except ValueError:
                payload = {}
            err = payload.get("error") or {}
            raise GrowwError(err.get("message") or e.reason, err.get("code", ""), e.code) from None
        except urllib.error.URLError as e:
            raise GrowwError(f"cannot reach Groww: {e.reason}") from None
        if payload.get("status") != "SUCCESS":
            err = payload.get("error") or {}
            raise GrowwError(err.get("message", "request failed"), err.get("code", ""), status)
        return payload.get("payload") or {}

    # ---- auth ----------------------------------------------------------
    def login_with_secret(self, api_key: str, api_secret: str) -> dict:
        ts = str(int(time.time()))
        p = self._request("POST", "/v1/token/api/access", auth=api_key,
                          body={"key_type": "approval", "checksum": checksum(api_secret, ts), "timestamp": ts})
        self.access_token = p["token"]
        return p

    def login_with_totp(self, api_key: str, totp: str) -> dict:
        p = self._request("POST", "/v1/token/api/access", auth=api_key,
                          body={"key_type": "totp", "totp": totp})
        self.access_token = p["token"]
        return p

    # ---- market data ---------------------------------------------------
    def ltp(self, symbols: list[str], exchange: str = "NSE") -> dict[str, float]:
        """Last traded prices, keyed by plain symbol (RELIANCE, not NSE_RELIANCE)."""
        out: dict[str, float] = {}
        for i in range(0, len(symbols), 50):  # 50 instruments per call
            chunk = symbols[i:i + 50]
            p = self._request("GET", "/v1/live-data/ltp", params={
                "segment": "CASH", "exchange_symbols": ",".join(f"{exchange}_{s}" for s in chunk)})
            for key, price in p.items():
                out[key.split("_", 1)[1] if "_" in key else key] = float(price)
        return out

    def candles(self, symbol: str, start: datetime, end: datetime, interval: str = "1minute",
                exchange: str = "NSE") -> list[Bar]:
        """Historical candles (up to 30 days per call for 1 to 5 minute bars)."""
        p = self._request("GET", "/v1/historical/candles", params={
            "exchange": exchange, "segment": "CASH", "groww_symbol": f"{exchange}-{symbol}",
            "start_time": start.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": end.strftime("%Y-%m-%d %H:%M:%S"),
            "candle_interval": interval,
        })
        bars = []
        for c in p.get("candles") or []:
            ts = c[0]
            dt = datetime.fromtimestamp(ts) if isinstance(ts, (int, float)) else datetime.fromisoformat(str(ts))
            bars.append(Bar(to_ist(dt), symbol, float(c[1]), float(c[2]), float(c[3]), float(c[4]),
                            float(c[5] or 0)))
        return bars

    # ---- orders and positions ------------------------------------------
    def place_order(self, body: dict) -> dict:
        return self._request("POST", "/v1/order/create", body=body)

    def cancel_order(self, groww_order_id: str) -> dict:
        return self._request("POST", "/v1/order/cancel", body={"segment": "CASH", "groww_order_id": groww_order_id})

    def order_detail(self, groww_order_id: str) -> dict:
        return self._request("GET", f"/v1/order/detail/{groww_order_id}", params={"segment": "CASH"})

    def positions(self) -> list[dict]:
        return self._request("GET", "/v1/positions/user", params={"segment": "CASH"}).get("positions", [])


def client_from_env(env: dict | None = None, cache: Path = TOKEN_CACHE) -> GrowwClient:
    """Build a client from environment variables or today's cached token."""
    env = env if env is not None else os.environ
    if env.get("GROWW_ACCESS_TOKEN"):
        return GrowwClient(env["GROWW_ACCESS_TOKEN"])
    cached = load_cached_token(cache)
    if cached:
        return GrowwClient(cached)
    if env.get("GROWW_API_KEY") and env.get("GROWW_API_SECRET"):
        c = GrowwClient()
        info = c.login_with_secret(env["GROWW_API_KEY"], env["GROWW_API_SECRET"])
        save_cached_token(info, cache)
        return c
    raise GrowwError("set GROWW_ACCESS_TOKEN, or GROWW_API_KEY and GROWW_API_SECRET, "
                     "or run `daytrader groww login --totp CODE`")


def save_cached_token(info: dict, cache: Path = TOKEN_CACHE) -> None:
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"token": info["token"], "expiry": info.get("expiry", "")}))
    os.chmod(cache, 0o600)


def load_cached_token(cache: Path = TOKEN_CACHE) -> Optional[str]:
    if not cache.exists():
        return None
    try:
        data = json.loads(cache.read_text())
        expiry = data.get("expiry")
        if expiry and datetime.fromisoformat(expiry.replace("Z", "+00:00")).timestamp() <= time.time():
            return None
        return data.get("token")
    except (ValueError, KeyError):
        return None


class GrowwBroker(Broker):
    """Sends REAL orders to Groww. Built only by the server in live mode."""

    is_live = True

    def __init__(self, client: GrowwClient, max_orders_per_second: int = 5,
                 fill_timeout: float = 10.0, sleep=time.sleep):
        self.client = client
        self.throttle = OrderThrottle(max_orders_per_second)
        self.fill_timeout = fill_timeout
        self.sleep = sleep

    @staticmethod
    def order_body(order: Order, ltp: Optional[float] = None) -> dict:
        order.validate()
        body = {
            "trading_symbol": order.symbol,
            "quantity": order.qty,
            "validity": "DAY",
            "exchange": order.exchange,
            "segment": "CASH",
            "product": order.product,
            "order_type": order.order_type.replace("-", "_"),
            "transaction_type": order.side,
            "order_reference_id": new_reference_id(),
        }
        if order.order_type == "MARKET" and ltp:
            # Market protection: send a marketable LIMIT capped at protection % from LTP,
            # so a thin order book cannot fill us at any price.
            band = ltp * order.market_protection_pct / 100
            limit = ltp + band if order.side == "BUY" else ltp - band
            body["order_type"] = "LIMIT"
            body["price"] = round(round(limit / 0.05) * 0.05, 2)  # NSE tick size 0.05
        if order.price is not None and order.order_type == "LIMIT":
            body["price"] = order.price
        if order.trigger is not None:
            body["trigger_price"] = order.trigger
        return body

    def place_order(self, order: Order, ltp: Optional[float] = None) -> OrderResult:
        if order.order_type == "MARKET" and not ltp:
            return OrderResult(False, status="REJECTED", message="need a last price for market protection")
        body = self.order_body(order, ltp)
        self.throttle.wait()
        try:
            p = self.client.place_order(body)
        except GrowwError as e:
            return OrderResult(False, status="REJECTED", message=str(e))
        oid = p.get("groww_order_id", "")
        if order.order_type in ("SL", "SL-M"):
            return OrderResult(True, oid, p.get("order_status", "OPEN"))
        return self._await_fill(oid)

    def _await_fill(self, oid: str) -> OrderResult:
        deadline = time.monotonic() + self.fill_timeout
        last = {}
        while time.monotonic() < deadline:
            try:
                last = self.client.order_detail(oid)
            except GrowwError:
                last = {}
            st = last.get("order_status", "")
            if st in FILLED_STATES:
                return OrderResult(True, oid, st, float(last.get("average_fill_price") or 0) or None)
            if st in DEAD_STATES:
                return OrderResult(False, oid, st, message=last.get("remark", ""))
            self.sleep(0.5)
        return OrderResult(False, oid, last.get("order_status", "UNKNOWN"),
                           message="not filled in time; check the Groww app")

    def cancel_order(self, order_id: str) -> OrderResult:
        try:
            p = self.client.cancel_order(order_id)
            return OrderResult(True, order_id, p.get("order_status", "CANCELLED"))
        except GrowwError as e:
            return OrderResult(False, order_id, "REJECTED", message=str(e))

    def positions(self) -> dict[str, dict]:
        out = {}
        for p in self.client.positions():
            if p.get("product") != "MIS":
                continue
            out[p["trading_symbol"]] = {"qty": int(p.get("quantity", 0)),
                                        "avg": float(p.get("net_price") or 0),
                                        "realized": float(p.get("realised_pnl") or 0)}
        return out
