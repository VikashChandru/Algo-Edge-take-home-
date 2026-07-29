"""
Script B (asyncio version) - REST client
============================================
Calls the FastAPI server in script_a_server.py using `httpx.AsyncClient`,
with concurrency provided by `asyncio.gather` (single thread, cooperative
concurrency via the event loop, no OS threads involved).

Run the server first:
    python3 script_a_server.py
then in another terminal:
    python3 script_b_client_asyncio.py
"""

import asyncio
import time

import httpx

BASE_URL = "http://127.0.0.1:8000"

# same 5 demo orders as Task 1 / the threading client
DEMO_ORDERS = [
    {"symbol": "AAPL", "side": "BUY",  "qty": 100, "price": 150.00},
    {"symbol": "AAPL", "side": "BUY",  "qty": 50,  "price": 151.00},
    {"symbol": "AAPL", "side": "SELL", "qty": 80,  "price": 155.00},
    {"symbol": "MSFT", "side": "BUY",  "qty": 40,  "price": 300.00},
    {"symbol": "AAPL", "side": "SELL", "qty": 40,  "price": 156.00},
]


async def wait_for_server(client: httpx.AsyncClient, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = await client.get(f"{BASE_URL}/health", timeout=1)
            if r.status_code == 200:
                return True
        except httpx.RequestError:
            pass
        await asyncio.sleep(0.3)
    return False


async def place_order(client: httpx.AsyncClient, order: dict) -> dict:
    resp = await client.post(f"{BASE_URL}/orders", json=order, timeout=5)
    resp.raise_for_status()
    return resp.json()


async def main():
    async with httpx.AsyncClient() as client:
        print("[B-asyncio] waiting for server...")
        if not await wait_for_server(client):
            print("[B-asyncio] server not reachable at", BASE_URL)
            return

        print(f"[B-asyncio] submitting {len(DEMO_ORDERS)} orders concurrently "
              f"via asyncio.gather ...")
        start = time.perf_counter()

        results = await asyncio.gather(*(place_order(client, o) for o in DEMO_ORDERS))

        elapsed = time.perf_counter() - start
        for result in results:
            print(f"[B-asyncio] filled {result['order_id']}  "
                  f"{result['side']} {result['qty']} {result['symbol']} @ {result['price']}")
        print(f"[B-asyncio] all {len(DEMO_ORDERS)} orders placed in {elapsed:.3f}s")

        await report(client, elapsed)


async def report(client: httpx.AsyncClient, elapsed: float):
    orders = (await client.get(f"{BASE_URL}/orders", timeout=5)).json()
    positions = (await client.get(f"{BASE_URL}/positions", timeout=5)).json()
    pnl = (await client.get(f"{BASE_URL}/pnl", timeout=5)).json()

    print("\n" + "=" * 72)
    print(f"ORDER BOOK (via GET /orders)   [client=asyncio, {elapsed:.3f}s]")
    print("=" * 72)
    print(f"{'ORDER ID':14} {'SYM':6} {'SIDE':5} {'QTY':>6} {'PRICE':>9} {'STATUS':>10}")
    for o in orders:
        print(f"{o['order_id']:14} {o['symbol']:6} {o['side']:5} {o['qty']:>6} "
              f"{o['price']:>9.2f} {o['status']:>10}")

    print("\n" + "=" * 72)
    print("OPEN POSITIONS (via GET /positions)")
    print("=" * 72)
    for p in positions:
        print(f"{p['symbol']:6} qty={p['qty']:>6} avg_price={p['avg_price']:.2f}")
    if not positions:
        print("(flat)")

    print("\n" + "=" * 72)
    print("REALISED PNL (via GET /pnl)")
    print("=" * 72)
    for symbol, val in pnl["by_symbol"].items():
        print(f"{symbol:6} {val:>10.2f}")
    print(f"{'TOTAL':6} {pnl['total_realized_pnl']:>10.2f}")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
