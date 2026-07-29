# Task 3 — IBKR: contract fetching, data feed, tick storage to Redis, order placement

## Library choice: `ib_async`, not `ib_insync`

`ib_insync` (the library most people reach for first for this) was
**archived in March 2024** after its creator's passing and is no longer
maintained. The community continued it as **`ib_async`**, which is a
drop-in replacement — same classes, same method names, same event pattern.
This code imports `ib_async`. If your environment only has the older
`ib_insync` installed, the only change needed anywhere is the import line in
`ibkr_client.py`:

```python
# from ib_async import IB, Stock, LimitOrder, MarketOrder, Contract, Trade
from ib_insync import IB, Stock, LimitOrder, MarketOrder, Contract, Trade
```

Nothing else needs to change.

## What's implemented

| Requirement | Where | How |
|---|---|---|
| Contract fetching | `IBKRClient.fetch_contract_details()` | builds a `Stock(symbol, "SMART", "USD")`, calls `ib.qualifyContracts()` then `ib.reqContractDetails()` |
| Data feed subscription | `IBKRClient.stream_market_data()` | `ib.reqMktData()` + `ib.pendingTickersEvent` callback, streamed for a configurable duration, then cleanly cancelled |
| Tick storage to Redis | `redis_store.TickStore` | each tick is appended to a Redis **Stream** `ticks:<SYMBOL>` (correct data structure for an append-only, time-ordered feed; auto-trimmed with `maxlen`), plus a `latest:<SYMBOL>` hash for O(1) latest-price reads |
| Order placement | `IBKRClient.place_order()` | builds a `LimitOrder`/`MarketOrder`, calls `ib.placeOrder()`, listens on `trade.statusEvent` for fill/ack updates |

`main.py` wires all four together into one runnable demo; `redis_inspect.py`
lets you look at what landed in Redis independently of IBKR.

## Delayed market data (fixes "Error 10089")

Demo/paper IBKR accounts almost never have a live-data subscription, so a
plain `reqMktData()` call throws:

```
Error 10089: Requested market data requires additional subscription for API
```

`IBKRClient.connect()` now calls `self.ib.reqMarketDataType(config.MARKET_DATA_TYPE)`
right after connecting, defaulting to **3 (Delayed)**, so `stream_market_data()`
works out of the box on a demo account with no live-data entitlements. If
your account *does* have a real-time subscription, set
`IB_MARKET_DATA_TYPE=1` (env var) or edit `config.MARKET_DATA_TYPE` directly
for live ticks instead.

Two more things were added specifically to make failures easy to diagnose:

* `IBKRClient` now subscribes to `ib.errorEvent` in `__init__` and logs
  every IBKR error/warning (code + message) the moment it happens — so a
  10089, a bad exchange, a closed market, etc. shows up immediately in the
  console instead of you just seeing "no ticks arrived" with no explanation.
* `stream_market_data()` prints the raw `Ticker` object right after
  `reqMktData()`, and prints every tick dict as it's stored, so you can see
  exactly what IBKR is sending (or confirm nothing is).
* `main.py` prints an explicit diagnostic block if zero ticks arrive during
  the streaming window, pointing you at the `errorEvent` log lines above it.

## Setup

### 1. Redis — via Docker

```bash
docker run -d --name redis-demo -p 6379:6379 redis:7
docker exec -it redis-demo redis-cli ping   # should print PONG
```

`config.py` defaults to `REDIS_HOST=127.0.0.1`, `REDIS_PORT=6379`, which
matches the `-p 6379:6379` port mapping above — so as long as this script
itself runs on your host machine (not inside another container), no config
change is needed.

If you instead run `main.py` itself inside a container on the same custom
Docker network as Redis, point it at the Redis container by name instead
of `127.0.0.1`:

```bash
docker network create ibkr-demo-net
docker run -d --name redis-demo --network ibkr-demo-net -p 6379:6379 redis:7
# then, for the script:
export REDIS_HOST=redis-demo
```

To inspect stored ticks directly via the Redis CLI at any point:
```bash
docker exec -it redis-demo redis-cli
> XLEN ticks:AAPL
> XREVRANGE ticks:AAPL + - COUNT 10
> HGETALL latest:AAPL
```

### 2. TWS or IB Gateway

* Launch TWS or IB Gateway and log into your **demo/paper trading** account
  (`config.py` defaults to port `7497`, TWS's paper-trading port; use
  `4002` for IB Gateway paper trading instead).
* File → Global Configuration → API → Settings:
  * ✅ Enable ActiveX and Socket Clients
  * ⬜ Read-Only API (must be **unchecked** for order placement to work)
  * confirm `127.0.0.1` is a trusted IP / the socket port matches `config.py`

### 3. Python deps

```bash
pip install -r requirements.txt
```

## Run

```bash
python3 main.py
```

Console flow:
1. Connects to IBKR, requests delayed market data (type 3), prints server version.
2. **Contract fetching** — prints `conId`, exchange, and long name for
   `AAPL` and `MSFT` (edit `config.CONTRACT_SYMBOLS` to change).
3. **Data feed + Redis storage** — subscribes to delayed top-of-book data for
   `AAPL` for `config.DATAFEED_DURATION_SEC` seconds (default 20s), printing
   the raw `Ticker` object, every tick as it arrives, and storing each one
   into Redis; then reads the stream back from Redis to prove the write
   worked.
4. **Order placement** — places a BUY LIMIT order for 1 share of AAPL at
   `config.DEMO_ORDER_LIMIT_PRICE` (default \$1.00 — deliberately far below
   market so it rests unfilled rather than executing by accident), and
   prints the resulting order status. Cancel it from TWS afterward (or call
   `client.cancel_order(trade)`) if you don't want it lingering.
5. Disconnects.

Inspect stored ticks any time, independent of IBKR:
```bash
python3 redis_inspect.py AAPL --count 20
```

## If you still get zero ticks

Read the `IBKR errorEvent ...` log lines printed right after connecting /
subscribing — the exact error code tells you what's wrong:

* **10089 again, even on delayed (type 3)** — this symbol/exchange has no
  delayed data entitlement either on this account; try a different, more
  liquid US symbol, or confirm the exchange (`Stock(symbol, "SMART", "USD")`
  should be fine for major US names).
* **No errorEvent at all, but also no ticks** — the market may simply be
  closed for that symbol right now (delayed data still generally requires
  the exchange to be open).
* **354 / "Requested market data is not subscribed"** — same root cause as
  10089, just a different IBKR error code for it.

## Files

```
config.py           connection settings + demo parameters
redis_store.py       Redis tick storage (Streams + latest-snapshot hash)
ibkr_client.py        IBKR wrapper: contracts, data feed, orders, error logging
main.py                orchestrates all 4 steps end-to-end
redis_inspect.py       standalone helper to view stored ticks
requirements.txt
```