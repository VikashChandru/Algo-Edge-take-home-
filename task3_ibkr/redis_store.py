"""
Redis-backed tick storage.

Each symbol gets its own Redis Stream (`ticks:<SYMBOL>`), which is the right
Redis data structure for an append-only, time-ordered feed like market
ticks: entries are automatically timestamp-ordered by Redis, consumers can
read from any offset, and old entries can be trimmed with `maxlen` so memory
stays bounded (a plain list or capped-length structure would work too, but
Streams also give you consumer groups for free if you ever want multiple
downstream readers).

We additionally keep a `latest:<SYMBOL>` hash with just the most recent
snapshot, for O(1) "what's the current price" reads without scanning the
stream.
"""

import time
from typing import Optional

import redis

import config


class TickStore:
    def __init__(self, host=config.REDIS_HOST, port=config.REDIS_PORT,
                 db=config.REDIS_DB, maxlen=config.TICK_STREAM_MAXLEN):
        self.client = redis.Redis(host=host, port=port, db=db, decode_responses=True)
        self.maxlen = maxlen

    def ping(self) -> bool:
        return self.client.ping()

    def store_tick(self, symbol: str, tick: dict):
        """Append one tick to the symbol's stream and refresh its 'latest' hash.

        `tick` values are coerced to strings since Redis stream/hash fields
        are text; None values are dropped (Redis rejects None as a value).
        """
        stream_key = f"ticks:{symbol}"
        fields = {k: str(v) for k, v in tick.items() if v is not None}
        self.client.xadd(stream_key, fields, maxlen=self.maxlen, approximate=True)
        self.client.hset(f"latest:{symbol}", mapping=fields)

    def recent_ticks(self, symbol: str, count: int = 10):
        """Most recent `count` ticks, newest first: list of (entry_id, fields)."""
        return self.client.xrevrange(f"ticks:{symbol}", count=count)

    def latest_tick(self, symbol: str) -> Optional[dict]:
        data = self.client.hgetall(f"latest:{symbol}")
        return data or None

    def stream_length(self, symbol: str) -> int:
        return self.client.xlen(f"ticks:{symbol}")


if __name__ == "__main__":
    # Quick standalone smoke test: `python3 redis_store.py`
    # Verifies the storage layer works independently of any IBKR connection.
    store = TickStore()
    assert store.ping(), "Redis not reachable - is redis-server running?"

    print("Writing 5 synthetic ticks for TEST ...")
    for i in range(5):
        store.store_tick("TEST", {
            "symbol": "TEST",
            "last": 100 + i * 0.5,
            "bid": 100 + i * 0.5 - 0.01,
            "ask": 100 + i * 0.5 + 0.01,
            "volume": 1000 + i,
            "ts": time.time(),
        })
        time.sleep(0.05)

    print("stream length:", store.stream_length("TEST"))
    print("latest tick  :", store.latest_tick("TEST"))
    print("last 3 ticks :")
    for entry_id, fields in store.recent_ticks("TEST", count=3):
        print(" ", entry_id, fields)
