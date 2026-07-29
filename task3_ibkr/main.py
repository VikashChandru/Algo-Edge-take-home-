"""
Task 3 - IBKR demo: contract fetching, data feed subscription,
tick storage to Redis, and order placement.

Requires:
  * TWS or IB Gateway running locally with the API enabled, logged into a
    PAPER TRADING account (see config.py for the exact settings + ports).
  * A reachable Redis server (see README for how to start one).

Run:
    python main.py

What it does, in order:
  1. Connects to IBKR.
  2. Fetches + prints contract details for a couple of symbols
     (config.CONTRACT_SYMBOLS).
  3. Subscribes to the live data feed for one symbol
     (config.DATAFEED_SYMBOL), streaming for config.DATAFEED_DURATION_SEC
     seconds, storing every tick into Redis as it arrives.
  4. Reads back what landed in Redis and prints it, proving the storage
     step actually worked.
  5. Places one demo LIMIT order, priced well below market so it rests
     unfilled in your paper account, and prints the resulting order status.
  6. Disconnects cleanly.
"""

import sys

import config
from ibkr_client import IBKRClient
from redis_store import TickStore


def main():
    store = TickStore()
    if not store.ping():
        print("ERROR: could not reach Redis at "
              f"{config.REDIS_HOST}:{config.REDIS_PORT}. Start it first "
              "(see README.md) and re-run.")
        sys.exit(1)

    client = IBKRClient()
    try:
        client.connect()
    except Exception as e:
        print(f"ERROR: could not connect to IBKR at {config.IB_HOST}:{config.IB_PORT} - {e}")
        print("Make sure TWS or IB Gateway is running, logged into a paper "
              "account, with the API enabled (see config.py / README.md).")
        sys.exit(1)

    try:
        # ---------------------------------------------------- 1) contracts
        print("\n" + "=" * 72)
        print("STEP 1: CONTRACT FETCHING")
        print("=" * 72)
        qualified_contracts = {}
        for symbol in config.CONTRACT_SYMBOLS:
            contract, details = client.fetch_contract_details(symbol)
            qualified_contracts[symbol] = contract
            cd = details[0] if details else None
            print(f"{symbol:6} conId={contract.conId:<10} "
                  f"exchange={contract.exchange:<8} "
                  f"primaryExchange={contract.primaryExchange:<8} "
                  f"longName={getattr(cd, 'longName', '')}")

        # ------------------------------------------------- 2+3) data + redis
        print("\n" + "=" * 72)
        print(f"STEP 2/3: DATA FEED SUBSCRIPTION + TICK STORAGE "
              f"({config.DATAFEED_SYMBOL}, {config.DATAFEED_DURATION_SEC}s)")
        print("=" * 72)

        tick_count = 0

        def on_tick(tick: dict):
            nonlocal tick_count
            tick_count += 1
            store.store_tick(tick["symbol"], tick)
            print(f"  tick #{tick_count}: {tick}")

        feed_contract = qualified_contracts[config.DATAFEED_SYMBOL]
        client.stream_market_data(feed_contract, on_tick, duration_sec=config.DATAFEED_DURATION_SEC)

        print(f"\nstored {tick_count} ticks to Redis stream "
              f"'ticks:{config.DATAFEED_SYMBOL}' "
              f"(stream length now {store.stream_length(config.DATAFEED_SYMBOL)})")
        print("most recent tick from Redis:", store.latest_tick(config.DATAFEED_SYMBOL))

        if tick_count == 0:
            print(
                "\nWARNING: zero ticks received from IBKR during the "
                f"{config.DATAFEED_DURATION_SEC}s window. Redis and the "
                "storage code are not the issue here (see redis_store.py's "
                "own standalone test) - this means IBKR itself isn't "
                "sending data. Common causes:\n"
                "  * market is closed for this symbol right now\n"
                "  * this account has no data subscription at all, even "
                "delayed, for this exchange (watch the console above for "
                "an 'IBKR errorEvent ... code=10089' or similar line)\n"
                "  * wrong exchange for this symbol\n"
                "Check the errorEvent log lines printed above for the "
                "specific IBKR error code."
            )

        # -------------------------------------------------------- 4) orders
        print("\n" + "=" * 72)
        print("STEP 4: ORDER PLACEMENT")
        print("=" * 72)
        order_contract = qualified_contracts[config.DEMO_ORDER_SYMBOL]
        trade = client.place_order(
            order_contract,
            action=config.DEMO_ORDER_ACTION,
            qty=config.DEMO_ORDER_QTY,
            order_type="LMT",
            limit_price=config.DEMO_ORDER_LIMIT_PRICE,
        )
        print(f"order id={trade.order.orderId} status={trade.orderStatus.status} "
              f"filled={trade.orderStatus.filled} remaining={trade.orderStatus.remaining}")
        print("(this order is priced well below market on purpose, so it "
              "should sit as 'PreSubmitted'/'Submitted' rather than fill. "
              "Cancel it in TWS, or call client.cancel_order(trade), when done.)")

    finally:
        client.disconnect()


if __name__ == "__main__":
    main()