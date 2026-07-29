# Task 2 — REST API (FastAPI server + threading / asyncio clients)

| Script | Role | File |
|---|---|---|
| A | FastAPI server hosting the order-management REST API | `script_a_server.py` |
| B (v1) | Client using `requests` + `ThreadPoolExecutor` (threading) | `script_b_client_threading.py` |
| B (v2) | Client using `httpx.AsyncClient` + `asyncio.gather` (asyncio) | `script_b_client_asyncio.py` |

## API (Script A)

| Method | Path | Description |
|---|---|---|
| GET | `/health` | liveness check |
| POST | `/orders` | place an order — `{symbol, side, qty, price}`, filled immediately at the requested price (mock) |
| GET | `/orders` | list all orders placed so far |
| GET | `/orders/{order_id}` | fetch a single order |
| GET | `/positions` | current open positions (FIFO cost basis) |
| GET | `/pnl` | realised PnL, total + per symbol |

State is in-memory and resets when the server restarts.

## How to run

### Requirements
```bash
pip install -r requirements.txt
```

### 1. Start the server
```bash
python3 script_a_server.py
```
(equivalently: `uvicorn script_a_server:app --reload`). Leave it running.
Docs are auto-available at `http://127.0.0.1:8000/docs`.

### 2. Run either client (or both) in another terminal
```bash
python3 script_b_client_threading.py
# or
python3 script_b_client_asyncio.py
```

Each client submits the same 5 demo orders (mix of BUY/SELL, two symbols —
identical to Task 1) **concurrently**, times how long that took, then reads
back `/orders`, `/positions`, and `/pnl` and prints an order book / open
positions / realised PnL report, same shape as Task 1's.

> **Restart the server between client runs** if you want a clean, comparable
> report — otherwise orders accumulate across runs (which is realistic
> server behaviour, just noisier for a demo).

### Note on concurrency and realised PnL
Both clients fire all 5 requests concurrently (via a thread pool or an
asyncio event loop) rather than one-at-a-time, which is the whole point of
this task. That means the server can receive them in a different order than
they were submitted in, and because realised PnL depends on FIFO lot order,
**the exact PnL number can vary slightly run to run** — this is expected,
real behaviour of concurrent dispatch, unlike Task 1 where the ZMQ pipeline
is strictly sequential per order. If you need deterministic ordering, send
requests sequentially (`for o in DEMO_ORDERS: place_order(o)`), which
trades away the concurrency benefit these clients are meant to demonstrate.

## Files

```
script_a_server.py              Script A - FastAPI server
script_b_client_threading.py    Script B - threading client
script_b_client_asyncio.py      Script B - asyncio client
requirements.txt
```
