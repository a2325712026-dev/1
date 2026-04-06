# Binance Smart Copy Trader (Python + Kivy)

A desktop copy-trading example for this lead trader URL:

- https://www.binance.com/en/copy-trading/lead-details/4326059289542684929?timeRange=7D

## Features

- Kivy GUI for entering `Binance API Key` and `API Secret`.
- Auto-persisted credentials: saved locally and auto-loaded on next start.
- Smart copy logic: polls lead-trader public positions and mirrors deltas with a simplified risk rule.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python smart_copy_trader.py
```

## Local config path

- Linux/macOS: `~/.binance_copy_trader/config.json`

## Notes

- Ensure your API key has futures trading permission.
- Start with small capital first.
- Binance public web endpoints may change; update `LeadTraderFeed.ENDPOINT_CANDIDATES` if needed.
