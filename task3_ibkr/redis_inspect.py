"""
Small standalone utility to inspect what main.py stored in Redis, without
needing to touch IBKR at all.

Usage:
    python3 redis_inspect.py AAPL
    python3 redis_inspect.py AAPL --count 20
"""

import argparse

from redis_store import TickStore


def main():
    parser = argparse.ArgumentParser(description="Inspect stored ticks for a symbol")
    parser.add_argument("symbol")
    parser.add_argument("--count", type=int, default=10, help="how many recent ticks to show")
    args = parser.parse_args()

    store = TickStore()
    if not store.ping():
        print("ERROR: Redis not reachable.")
        return

    print(f"stream length for {args.symbol}: {store.stream_length(args.symbol)}")
    print(f"latest tick: {store.latest_tick(args.symbol)}")
    print(f"\nlast {args.count} ticks (newest first):")
    for entry_id, fields in store.recent_ticks(args.symbol, count=args.count):
        print(f"  [{entry_id}] {fields}")


if __name__ == "__main__":
    main()
