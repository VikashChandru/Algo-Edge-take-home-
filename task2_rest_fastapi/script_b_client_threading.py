"""
Script B (threading version) - REST client
=============================================
Calls the FastAPI server in script_a_server.py using the synchronous
`requests` library, with concurrency provided by a `ThreadPoolExecutor`
(each request runs on its own OS thread).

Run the server first:
    python3 script_a_server.py
then in another terminal:
    python3 script_b_client_threading.py
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

BASE_URL = "http://127.0.0.1:8000"

# same 5 demo orders as Task 1, for an easy side-by-side comparison
DEMO_ORDERS = [
    {"symbol": "AAPL", "side": "BUY",  "qty": 100, "price": 150.00},
    {"symbol": "AAPL", "side": "BUY",  "qty": 50,  "price": 151.00},
    {"symbol": "AAPL", "side": "SELL", "qty": 80,  "price": 155.00},
    {"symbol": "MSFT", "side": "BUY",  "qty": 40,  "price": 300.00},
    {"symbol": "AAPL", "side": "SELL", "qty": 40,  "price": 156.00},
]


def wait_for_server(timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{BASE_URL}/health", timeout=1)
            if r.status_code == 200:
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(0.3)
    return False


def place_order(order: dict) -> dict:
    resp = requests.post(f"{BASE_URL}/orders", json=order, timeout=5)
    resp.raise_for_status()
    return resp.json()


def main():
    print("[B-threading] waiting for server...")
    if not wait_for_server():
        print("[B-threading] server not reachable at", BASE_URL)
        return

    print(f"[B-threading] submitting {len(DEMO_ORDERS)} orders concurrently "
          f"via ThreadPoolExecutor ...")
    start = time.perf_counter()

    results = []
    with ThreadPoolExecutor(max_workers=len(DEMO_ORDERS)) as pool:
        futures = {pool.submit(place_order, o): o for o in DEMO_ORDERS}
        for fut in as_completed(futures):
            order_req = futures[fut]
            result = fut.result()
            results.append(result)
            print(f"[B-threading] filled {result['order_id']}  "
                  f"{result['side']} {result['qty']} {result['symbol']} @ {result['price']}")

    elapsed = time.perf_counter() - start
    print(f"[B-threading] all {len(DEMO_ORDERS)} orders placed in {elapsed:.3f}s")

    report(elapsed)


def report(elapsed: float):
    orders = requests.get(f"{BASE_URL}/orders", timeout=5).json()
    positions = requests.get(f"{BASE_URL}/positions", timeout=5).json()
    pnl = requests.get(f"{BASE_URL}/pnl", timeout=5).json()

    print("\n" + "=" * 72)
    print(f"ORDER BOOK (via GET /orders)   [client=threading, {elapsed:.3f}s]")
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
    main()
