"""
Central configuration for the IBKR demo.

IBKR default API ports:
    7497  TWS      - paper trading   (use this one for the demo)
    7496  TWS      - live trading
    4002  IB Gateway - paper trading
    4001  IB Gateway - live trading

Make sure, in TWS/Gateway: File -> Global Configuration -> API -> Settings:
    * "Enable ActiveX and Socket Clients" is checked
    * "Read-Only API" is UNCHECKED if you want order placement to work
    * 127.0.0.1 is in "Trusted IP Addresses" (usually fine by default for localhost)
"""

import os

# --- IBKR connection ---
IB_HOST = os.environ.get("IB_HOST", "127.0.0.1")
IB_PORT = int(os.environ.get("IB_PORT", 7497))     # 7497 = TWS paper trading
IB_CLIENT_ID = int(os.environ.get("IB_CLIENT_ID", 101))

# Market data type requested right after connecting (see ibkr_client.connect()).
# 1 = Live, 2 = Frozen, 3 = Delayed, 4 = Delayed Frozen.
# Demo/paper accounts without a live-data subscription will get
# "Error 10089: Requested market data requires additional subscription for
# API" on type 1 - default to 3 (Delayed) so the demo works out of the box.
# If your account *does* have a real-time data subscription, set this to 1.
MARKET_DATA_TYPE = int(os.environ.get("IB_MARKET_DATA_TYPE", 3))

# --- Redis ---
# Defaults assume Redis is running in Docker with -p 6379:6379 published to
# localhost (see README.md). If your script itself is also running inside a
# Docker container on the same custom network as Redis, set REDIS_HOST to
# the Redis container's name instead (e.g. `redis`) via the env var below.
REDIS_HOST = os.environ.get("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
REDIS_DB = int(os.environ.get("REDIS_DB", 0))
TICK_STREAM_MAXLEN = 10_000   # cap each symbol's tick stream so redis memory stays bounded

# --- Demo parameters ---
CONTRACT_SYMBOLS = ["AAPL", "MSFT"]     # symbols to fetch contract details for
DATAFEED_SYMBOL = "AAPL"                # symbol to stream live ticks for
DATAFEED_DURATION_SEC = 20              # how long to stream market data before stopping

# Demo order: a BUY LIMIT order priced well below the market so it rests
# unfilled in your paper account rather than executing accidentally.
# ALWAYS double check this is pointed at a PAPER account before running.
DEMO_ORDER_SYMBOL = "AAPL"
DEMO_ORDER_ACTION = "BUY"
DEMO_ORDER_QTY = 1
DEMO_ORDER_LIMIT_PRICE = 1.00