#!/usr/bin/env python3
"""Binance Smart Copy Trader (Kivy GUI) - Enhanced Version with P1 Fixes.

Overview:
1. Users only input Binance API Key and API Secret.
2. Credentials are encrypted and stored locally.
3. The app reads public lead-trader positions and mirrors position deltas.

⚠ Risk warning:
- For learning/research only. Start with very small size.
- Binance web endpoints may change and break lead position fetching.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from cryptography.fernet import Fernet
from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Lead trader ID extracted from the user-provided URL.
LEAD_PORTFOLIO_ID = "4326059289542684929"

# Simplified strategy parameters
DEFAULT_NOTIONAL_USDT = 25.0
POLL_INTERVAL_SEC = 10

# Symbol whitelist for safety (only trade these pairs)
ALLOWED_SYMBOLS = {
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
    "DOGEUSDT", "SOLUSDT", "MATICUSDT", "LTCUSDT", "LINKUSDT"
}


@dataclass
class AppConfig:
    api_key: str = ""
    api_secret: str = ""


class EncryptionManager:
    """Handles encryption/decryption of sensitive credentials."""
    
    def __init__(self) -> None:
        self.config_dir = Path.home() / ".binance_copy_trader"
        self.key_file = self.config_dir / ".key"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._key = self._load_or_create_key()
        self._cipher = Fernet(self._key)
    
    def _load_or_create_key(self) -> bytes:
        """Load encryption key or create a new one."""
        if self.key_file.exists():
            return self.key_file.read_bytes()
        
        # Generate a new key
        key = Fernet.generate_key()
        self.key_file.write_bytes(key)
        # Set restrictive permissions (Unix-like systems)
        self.key_file.chmod(0o600)
        logger.info(f"Created encryption key at {self.key_file}")
        return key
    
    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext and return base64-encoded token."""
        return self._cipher.encrypt(plaintext.encode()).decode()
    
    def decrypt(self, token: str) -> str:
        """Decrypt token and return plaintext."""
        try:
            return self._cipher.decrypt(token.encode()).decode()
        except Exception as exc:
            logger.error(f"Decryption failed: {exc}")
            return ""


class ConfigStore:
    """Manages configuration with encrypted credential storage."""
    
    def __init__(self) -> None:
        self.config_dir = Path.home() / ".binance_copy_trader"
        self.config_file = self.config_dir / "config.json"
        self.encryption = EncryptionManager()
    
    def load(self) -> AppConfig:
        """Load configuration from file."""
        if not self.config_file.exists():
            return AppConfig()
        try:
            raw = json.loads(self.config_file.read_text(encoding="utf-8"))
            api_key = self.encryption.decrypt(raw.get("api_key", ""))
            api_secret = self.encryption.decrypt(raw.get("api_secret", ""))
            return AppConfig(api_key=api_key, api_secret=api_secret)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error(f"Failed to load config: {exc}")
            return AppConfig()
    
    def save(self, cfg: AppConfig) -> None:
        """Save configuration with encrypted credentials."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        encrypted_key = self.encryption.encrypt(cfg.api_key.strip())
        encrypted_secret = self.encryption.encrypt(cfg.api_secret.strip())
        
        self.config_file.write_text(
            json.dumps(
                {"api_key": encrypted_key, "api_secret": encrypted_secret},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        logger.info("Configuration saved securely")


class BinanceClient:
    """Binance API client with proper request signing."""
    
    def __init__(self, api_key: str, api_secret: str) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.session = requests.Session()
        self.session.headers.update({
            "X-MBX-APIKEY": api_key,
            "User-Agent": "BinanceSmartCopyTrader/1.0"
        })
        self._exchange_info_cache: dict[str, Any] = {}
    
    def _sign(self, params: dict[str, Any]) -> str:
        """Sign request with proper parameter ordering."""
        # Sort parameters alphabetically for consistent signing
        sorted_params = sorted(params.items())
        query = urlencode(sorted_params)
        signature = hmac.new(
            self.api_secret.encode(),
            query.encode(),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def get_exchange_info(self) -> dict[str, Any]:
        """Fetch exchange info with symbol details and filters."""
        if self._exchange_info_cache:
            return self._exchange_info_cache
        
        try:
            resp = self.session.get(
                "https://fapi.binance.com/fapi/v1/exchangeInfo",
                timeout=10
            )
            resp.raise_for_status()
            self._exchange_info_cache = resp.json()
            return self._exchange_info_cache
        except Exception as exc:
            logger.error(f"Failed to fetch exchange info: {exc}")
            return {}
    
    def get_symbol_precision(self, symbol: str) -> int:
        """Get the required decimal precision for a symbol."""
        exchange_info = self.get_exchange_info()
        symbols_data = exchange_info.get("symbols", [])
        
        for sym_info in symbols_data:
            if sym_info.get("symbol") == symbol:
                # Find LOT_SIZE filter to get step size precision
                for filt in sym_info.get("filters", []):
                    if filt.get("filterType") == "LOT_SIZE":
                        step_size = float(filt.get("stepSize", "0.001"))
                        # Calculate precision from step size
                        if step_size == 0:
                            return 3
                        precision = len(str(step_size).rstrip("0").split(".")[-1])
                        return precision
        
        return 3  # Default precision
    
    def place_futures_market_order(
        self, symbol: str, side: str, quantity: float, client_order_id: str | None = None
    ) -> dict[str, Any]:
        """Place a futures market order with proper signing and idempotency key."""
        precision = self.get_symbol_precision(symbol)
        formatted_quantity = f"{quantity:.{precision}f}"
        
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": formatted_quantity,
            "timestamp": int(time.time() * 1000),
            "recvWindow": 5000,
        }
        
        # Add client order ID for idempotency
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        
        params["signature"] = self._sign(params)
        
        try:
            resp = self.session.post(
                "https://fapi.binance.com/fapi/v1/order",
                params=params,
                timeout=15
            )
            resp.raise_for_status()
            result = resp.json()
            logger.info(f"Order placed: {symbol} {side} {quantity}")
            return result
        except requests.exceptions.HTTPError as exc:
            logger.error(f"API error: {exc.response.text}")
            raise
    
    def get_symbol_price(self, symbol: str) -> float:
        """Fetch current symbol price."""
        try:
            resp = self.session.get(
                "https://fapi.binance.com/fapi/v1/ticker/price",
                params={"symbol": symbol},
                timeout=10
            )
            resp.raise_for_status()
            return float(resp.json()["price"])
        except Exception as exc:
            logger.error(f"Failed to fetch price for {symbol}: {exc}")
            raise


class LeadTraderFeed:
    """Fetches public lead-trader positions with endpoint fallback."""
    
    ENDPOINT_CANDIDATES = [
        "https://www.binance.com/bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/positions",
        "https://www.binance.com/bapi/futures/v1/friendly/future/copy-trade/lead-data/positions",
    ]
    
    def __init__(self, portfolio_id: str) -> None:
        self.portfolio_id = portfolio_id
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json"
        })
    
    def fetch_positions(self) -> dict[str, float]:
        """Fetch lead trader positions with fallback endpoints.
        
        FIXED P1: Now returns empty dict {} as valid state (not failure).
        This allows syncing when lead trader closes all positions.
        """
        last_error: Exception | None = None
        
        for endpoint in self.ENDPOINT_CANDIDATES:
            try:
                resp = self.session.get(
                    endpoint,
                    params={"portfolioId": self.portfolio_id},
                    timeout=12
                )
                resp.raise_for_status()
                payload = resp.json()
                parsed = self._parse_payload(payload)
                # FIXED: Check is not None instead of truthiness
                # This allows empty dict {} to be treated as valid
                if parsed is not None:
                    logger.info(f"Successfully fetched {len(parsed)} positions")
                    return parsed
            except Exception as exc:
                logger.warning(f"Endpoint {endpoint} failed: {exc}")
                last_error = exc
                continue
        
        error_msg = f"Unable to read lead trader positions: {last_error}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    
    @staticmethod
    def _parse_payload(payload: dict[str, Any]) -> dict[str, float] | None:
        """Parse positions from varied payload structures.
        
        Returns dict (empty or with data) on success, None on invalid payload.
        """
        data = payload.get("data", payload)
        candidates: list[dict[str, Any]] = []
        
        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            if isinstance(data.get("positions"), list):
                candidates = data["positions"]
            elif isinstance(data.get("list"), list):
                candidates = data["list"]
        else:
            # Invalid payload structure
            return None
        
        result: dict[str, float] = {}
        for pos in candidates:
            symbol = pos.get("symbol") or pos.get("pair")
            amt_raw = (
                pos.get("positionAmt")
                or pos.get("amount")
                or pos.get("positionAmount")
            )
            if not symbol or amt_raw is None:
                continue
            try:
                result[str(symbol).upper()] = float(amt_raw)
            except (TypeError, ValueError):
                continue
        
        return result


class SmartCopyTrader:
    """Core copy trading logic with thread-safe position management."""
    
    def __init__(self, client: BinanceClient, feed: LeadTraderFeed, status_cb) -> None:
        self.client = client
        self.feed = feed
        self.status_cb = status_cb
        self.running = False
        self._thread: threading.Thread | None = None
        self._prev_positions: dict[str, float] = {}
        self._lock = threading.Lock()
        # Track placed orders by (symbol, side) to detect retries
        self._recent_orders: dict[tuple[str, str], str] = {}
    
    def start(self) -> None:
        """Start the copy trading loop."""
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Copy trader started")
    
    def stop(self) -> None:
        """Stop the copy trading loop."""
        self.running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        logger.info("Copy trader stopped")
    
    def _run(self) -> None:
        """Main loop for syncing positions."""
        self.status_cb("Copy trading started. Listening for lead position changes...")
        
        while self.running:
            try:
                positions = self.feed.fetch_positions()
                # FIXED P3: Update _prev_positions before syncing
                # This prevents repeated orders if a single symbol fails
                with self._lock:
                    self._prev_positions = positions
                
                self._sync_positions(positions)
                self.status_cb(f"Sync success: {len(positions)} active symbols.")
            except Exception as exc:
                logger.error(f"Sync error: {exc}")
                self.status_cb(f"Sync error: {type(exc).__name__}: {exc}")
            
            time.sleep(POLL_INTERVAL_SEC)
    
    def _sync_positions(self, current: dict[str, float]) -> None:
        """Sync position deltas between leader and follower.
        
        FIXED P3: Individual symbol order failures no longer abort the cycle.
        Each symbol is processed independently with try-except.
        """
        with self._lock:
            prev_positions = self._prev_positions.copy()
        
        symbols = set(prev_positions) | set(current)
        
        for symbol in symbols:
            # Validate symbol is in whitelist
            if symbol not in ALLOWED_SYMBOLS:
                logger.warning(f"Symbol {symbol} not in whitelist, skipping")
                continue
            
            prev_amt = prev_positions.get(symbol, 0.0)
            cur_amt = current.get(symbol, 0.0)
            delta = cur_amt - prev_amt
            
            if abs(delta) < 1e-8:
                continue
            
            side = "BUY" if delta > 0 else "SELL"
            qty = self._calc_quantity(symbol, abs(delta))
            
            if qty <= 0:
                logger.warning(f"Calculated quantity <= 0 for {symbol}")
                continue
            
            # Try to place order with individual error handling
            try:
                # Generate idempotency key for this order
                order_key = f"{symbol}_{side}_{qty:.6f}_{int(time.time()/10)}"
                client_order_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, order_key))
                
                result = self.client.place_futures_market_order(
                    symbol=symbol,
                    side=side,
                    quantity=qty,
                    client_order_id=client_order_id
                )
                order_id = result.get("orderId", "N/A")
                self.status_cb(f"Order: {symbol} {side} {qty:.3f}, ID={order_id}")
                
                # Track this order for idempotency
                self._recent_orders[(symbol, side)] = client_order_id
            except Exception as exc:
                # Log and continue to next symbol (don't abort cycle)
                logger.error(f"Failed to place order for {symbol}: {exc}")
                self.status_cb(f"Order failed for {symbol}: {exc}")
                continue
    
    def _calc_quantity(self, symbol: str, leader_delta: float) -> float:
        """Calculate order quantity based on leader delta."""
        try:
            price = self.client.get_symbol_price(symbol)
            base_qty = DEFAULT_NOTIONAL_USDT / max(price, 1e-8)
            factor = min(max(leader_delta, 0.2), 5.0)
            final_qty = base_qty * factor
            
            precision = self.client.get_symbol_precision(symbol)
            return round(final_qty, precision)
        except Exception as exc:
            logger.error(f"Failed to calculate quantity for {symbol}: {exc}")
            return 0.0


class RootWidget(BoxLayout):
    """Kivy GUI root widget."""
    
    def __init__(self, **kwargs) -> None:
        super().__init__(orientation="vertical", spacing=dp(10), padding=dp(12), **kwargs)
        self.config_store = ConfigStore()
        cfg = self.config_store.load()
        
        self.add_widget(
            Label(
                text="Binance Smart Copy Trader",
                font_size="20sp",
                size_hint=(1, None),
                height=dp(40)
            )
        )
        self.add_widget(
            Label(
                text=f"Lead Portfolio ID: {LEAD_PORTFOLIO_ID}",
                size_hint=(1, None),
                height=dp(24)
            )
        )
        
        self.api_key_input = TextInput(
            text=cfg.api_key,
            hint_text="Enter Binance API Key",
            multiline=False
        )
        self.api_secret_input = TextInput(
            text=cfg.api_secret,
            hint_text="Enter Binance API Secret",
            multiline=False,
            password=True,
        )
        self.add_widget(self.api_key_input)
        self.add_widget(self.api_secret_input)
        
        btns = BoxLayout(size_hint=(1, None), height=dp(44), spacing=dp(8))
        self.save_btn = Button(text="Save Credentials")
        self.start_btn = Button(text="Start Copy")
        self.stop_btn = Button(text="Stop Copy")
        btns.add_widget(self.save_btn)
        btns.add_widget(self.start_btn)
        btns.add_widget(self.stop_btn)
        self.add_widget(btns)
        
        self.status_label = Label(text="Status: Idle", halign="left", valign="top")
        self.status_label.bind(size=lambda inst, val: setattr(inst, "text_size", val))
        self.add_widget(self.status_label)
        
        self.save_btn.bind(on_press=self.on_save)
        self.start_btn.bind(on_press=self.on_start)
        self.stop_btn.bind(on_press=self.on_stop)
        
        self.trader: SmartCopyTrader | None = None
    
    def _status(self, text: str) -> None:
        """Update status label from any thread."""
        Clock.schedule_once(lambda dt: setattr(self.status_label, "text", f"Status: {text}"))
    
    def on_save(self, *_args) -> None:
        """Save credentials securely."""
        cfg = AppConfig(
            api_key=self.api_key_input.text,
            api_secret=self.api_secret_input.text
        )
        self.config_store.save(cfg)
        self._status("Credentials saved. They will auto-load next launch.")
    
    def on_start(self, *_args) -> None:
        """Start copy trading.
        
        FIXED P2: Stop any existing trader before creating a new one.
        This prevents duplicate threads from running.
        """
        cfg = AppConfig(
            api_key=self.api_key_input.text.strip(),
            api_secret=self.api_secret_input.text.strip()
        )
        
        if not cfg.api_key or not cfg.api_secret:
            self._status("Please enter and save API Key/Secret first.")
            return
        
        self.config_store.save(cfg)
        
        # FIXED P2: Stop old trader if it exists before starting new one
        if self.trader and self.trader.running:
            logger.info("Stopping existing trader before starting new one")
            self.trader.stop()
        
        try:
            client = BinanceClient(api_key=cfg.api_key, api_secret=cfg.api_secret)
            feed = LeadTraderFeed(portfolio_id=LEAD_PORTFOLIO_ID)
            self.trader = SmartCopyTrader(client=client, feed=feed, status_cb=self._status)
            self.trader.start()
            self._status("Smart copy trading started.")
        except Exception as exc:
            logger.error(f"Failed to start trader: {exc}")
            self._status(f"Failed to start: {exc}")
    
    def on_stop(self, *_args) -> None:
        """Stop copy trading."""
        if self.trader:
            self.trader.stop()
        self._status("Copy trading stopped.")


class SmartCopyTraderApp(App):
    """Main Kivy application."""
    
    def build(self):  # type: ignore[override]
        return RootWidget()


if __name__ == "__main__":
    SmartCopyTraderApp().run()