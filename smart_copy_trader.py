#!/usr/bin/env python3
"""Binance Smart Copy Trader (Kivy GUI).

Overview:
1. Users only input Binance API Key and API Secret.
2. Credentials are stored locally and auto-loaded on next launch.
3. The app reads public lead-trader positions from the provided link and
   mirrors position deltas to the user's futures account.

⚠ Risk warning:
- For learning/research only. Start with very small size.
- Binance web endpoints may change and break lead position fetching.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput

# Lead trader ID extracted from the user-provided URL.
LEAD_PORTFOLIO_ID = "4326059289542684929"

# Simplified strategy parameters (no extra user input required).
DEFAULT_NOTIONAL_USDT = 25.0  # target notional per mirrored change
POLL_INTERVAL_SEC = 10


@dataclass
class AppConfig:
    api_key: str = ""
    api_secret: str = ""


class ConfigStore:
    def __init__(self) -> None:
        self.config_dir = Path.home() / ".binance_copy_trader"
        self.config_file = self.config_dir / "config.json"

    def load(self) -> AppConfig:
        if not self.config_file.exists():
            return AppConfig()
        try:
            raw = json.loads(self.config_file.read_text(encoding="utf-8"))
            return AppConfig(
                api_key=raw.get("api_key", ""),
                api_secret=raw.get("api_secret", ""),
            )
        except (json.JSONDecodeError, OSError):
            return AppConfig()

    def save(self, cfg: AppConfig) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(
            json.dumps(
                {"api_key": cfg.api_key.strip(), "api_secret": cfg.api_secret.strip()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


class BinanceClient:
    def __init__(self, api_key: str, api_secret: str) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.session = requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": api_key, "User-Agent": "Mozilla/5.0"})

    def _sign(self, params: dict[str, Any]) -> str:
        query = urlencode(params, doseq=True)
        return hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()

    def place_futures_market_order(self, symbol: str, side: str, quantity: float) -> dict[str, Any]:
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": f"{quantity:.3f}",
            "timestamp": int(time.time() * 1000),
            "recvWindow": 5000,
        }
        params["signature"] = self._sign(params)
        resp = self.session.post("https://fapi.binance.com/fapi/v1/order", params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_symbol_price(self, symbol: str) -> float:
        resp = self.session.get("https://fapi.binance.com/fapi/v1/ticker/price", params={"symbol": symbol}, timeout=10)
        resp.raise_for_status()
        return float(resp.json()["price"])


class LeadTraderFeed:
    """Fetches public lead-trader positions with endpoint fallback."""

    ENDPOINT_CANDIDATES = [
        "https://www.binance.com/bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/positions",
        "https://www.binance.com/bapi/futures/v1/friendly/future/copy-trade/lead-data/positions",
    ]

    def __init__(self, portfolio_id: str) -> None:
        self.portfolio_id = portfolio_id
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})

    def fetch_positions(self) -> dict[str, float]:
        last_error: Exception | None = None
        for endpoint in self.ENDPOINT_CANDIDATES:
            try:
                resp = self.session.get(endpoint, params={"portfolioId": self.portfolio_id}, timeout=12)
                resp.raise_for_status()
                payload = resp.json()
                parsed = self._parse_payload(payload)
                if parsed:
                    return parsed
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue

        if last_error:
            raise RuntimeError(f"Unable to read lead trader positions: {last_error}")
        raise RuntimeError("Unable to read lead trader positions: empty/invalid payload")

    @staticmethod
    def _parse_payload(payload: dict[str, Any]) -> dict[str, float]:
        # Supports structures like {data:[...]} and {data:{positions:[...]}}.
        data = payload.get("data", payload)
        candidates: list[dict[str, Any]] = []

        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            if isinstance(data.get("positions"), list):
                candidates = data["positions"]
            elif isinstance(data.get("list"), list):
                candidates = data["list"]

        result: dict[str, float] = {}
        for pos in candidates:
            symbol = pos.get("symbol") or pos.get("pair")
            amt_raw = pos.get("positionAmt") or pos.get("amount") or pos.get("positionAmount")
            if not symbol or amt_raw is None:
                continue
            try:
                result[str(symbol).upper()] = float(amt_raw)
            except (TypeError, ValueError):
                continue
        return result


class SmartCopyTrader:
    def __init__(self, client: BinanceClient, feed: LeadTraderFeed, status_cb) -> None:
        self.client = client
        self.feed = feed
        self.status_cb = status_cb
        self.running = False
        self._thread: threading.Thread | None = None
        self._prev_positions: dict[str, float] = {}

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _run(self) -> None:
        self.status_cb("Copy trading started. Listening for lead position changes...")
        while self.running:
            try:
                positions = self.feed.fetch_positions()
                self._sync_positions(positions)
                self._prev_positions = positions
                self.status_cb(f"Sync success: {len(positions)} active symbols.")
            except Exception as exc:  # noqa: BLE001
                self.status_cb(f"Sync error: {exc}")
            time.sleep(POLL_INTERVAL_SEC)

    def _sync_positions(self, current: dict[str, float]) -> None:
        symbols = set(self._prev_positions) | set(current)
        for symbol in symbols:
            prev_amt = self._prev_positions.get(symbol, 0.0)
            cur_amt = current.get(symbol, 0.0)
            delta = cur_amt - prev_amt
            if abs(delta) < 1e-8:
                continue

            side = "BUY" if delta > 0 else "SELL"
            qty = self._calc_quantity(symbol, abs(delta))
            if qty <= 0:
                continue

            result = self.client.place_futures_market_order(symbol=symbol, side=side, quantity=qty)
            order_id = result.get("orderId", "N/A")
            self.status_cb(f"Order placed: {symbol} {side} {qty:.3f}, orderId={order_id}")

    def _calc_quantity(self, symbol: str, leader_delta: float) -> float:
        # Simplified sizing rule: fixed notional scaled by leader delta magnitude.
        price = self.client.get_symbol_price(symbol)
        base_qty = DEFAULT_NOTIONAL_USDT / max(price, 1e-8)
        factor = min(max(leader_delta, 0.2), 5.0)
        return round(base_qty * factor, 3)


class RootWidget(BoxLayout):
    def __init__(self, **kwargs) -> None:
        super().__init__(orientation="vertical", spacing=dp(10), padding=dp(12), **kwargs)
        self.config_store = ConfigStore()
        cfg = self.config_store.load()

        self.add_widget(Label(text="Binance Smart Copy Trader", font_size="20sp", size_hint=(1, None), height=dp(40)))
        self.add_widget(Label(text=f"Lead Portfolio ID: {LEAD_PORTFOLIO_ID}", size_hint=(1, None), height=dp(24)))

        self.api_key_input = TextInput(text=cfg.api_key, hint_text="Enter Binance API Key", multiline=False)
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
        Clock.schedule_once(lambda dt: setattr(self.status_label, "text", f"Status: {text}"))

    def on_save(self, *_args) -> None:
        cfg = AppConfig(api_key=self.api_key_input.text, api_secret=self.api_secret_input.text)
        self.config_store.save(cfg)
        self._status("Credentials saved. They will auto-load next launch.")

    def on_start(self, *_args) -> None:
        cfg = AppConfig(api_key=self.api_key_input.text.strip(), api_secret=self.api_secret_input.text.strip())
        if not cfg.api_key or not cfg.api_secret:
            self._status("Please enter and save API Key/Secret first.")
            return

        # Auto-save so user only needs to enter once.
        self.config_store.save(cfg)

        client = BinanceClient(api_key=cfg.api_key, api_secret=cfg.api_secret)
        feed = LeadTraderFeed(portfolio_id=LEAD_PORTFOLIO_ID)
        self.trader = SmartCopyTrader(client=client, feed=feed, status_cb=self._status)
        self.trader.start()
        self._status("Smart copy trading started.")

    def on_stop(self, *_args) -> None:
        if self.trader:
            self.trader.stop()
        self._status("Copy trading stopped.")


class SmartCopyTraderApp(App):
    def build(self):  # type: ignore[override]
        return RootWidget()


if __name__ == "__main__":
    SmartCopyTraderApp().run()
