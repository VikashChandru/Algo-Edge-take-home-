"""
Script A - FastAPI order-management server
=============================================
Hosts a small REST API for placing orders and reading back order book /
positions / realised PnL. Script B (in two flavours: threading and asyncio)
is the client that calls this API.

In-memory state only (no DB) - perfectly fine for a demo server; resets on
restart.

Run with:
    uvicorn script_a_server:app --host 0.0.0.0 --port 8000
or simply:
    python3 script_a_server.py
"""

import threading
import time
import uuid
from collections import deque
from typing import Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Mock Trading REST API", version="1.0")

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class OrderRequest(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    qty: int = Field(gt=0)
    price: float = Field(gt=0)


class OrderResponse(BaseModel):
    order_id: str
    symbol: str
    side: str
    qty: int
    price: float
    status: str
    filled_qty: int
    created_at: float


class Position(BaseModel):
    symbol: str
    qty: int
    avg_price: float


# ---------------------------------------------------------------------------
# In-memory state (thread-safe: uvicorn's default worker is single-process,
# but FastAPI may still interleave sync-endpoint calls across threadpool
# threads, so we guard shared state with a lock regardless)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_orders: Dict[str, dict] = {}
_lots: Dict[str, deque] = {}                 # symbol -> deque[[qty, price]] FIFO
_realized_pnl_by_symbol: Dict[str, float] = {}
_realized_pnl_total = 0.0


def _apply_fill(symbol: str, side: str, qty: int, price: float):
    global _realized_pnl_total
    book = _lots.setdefault(symbol, deque())
    if side == "BUY":
        book.append([qty, price])
    else:
        remaining = qty
        while remaining > 0 and book:
            lot_qty, lot_price = book[0]
            matched = min(lot_qty, remaining)
            pnl = matched * (price - lot_price)
            _realized_pnl_total += pnl
            _realized_pnl_by_symbol[symbol] = _realized_pnl_by_symbol.get(symbol, 0.0) + pnl
            lot_qty -= matched
            remaining -= matched
            if lot_qty == 0:
                book.popleft()
            else:
                book[0][0] = lot_qty
        if remaining > 0:
            book.appendleft([-remaining, price])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "time": time.time()}


@app.post("/orders", response_model=OrderResponse)
def place_order(req: OrderRequest):
    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    with _lock:
        order = {
            "order_id": order_id,
            "symbol": req.symbol,
            "side": req.side,
            "qty": req.qty,
            "price": req.price,
            "status": "FILLED",     # mock server fills immediately at the requested price
            "filled_qty": req.qty,
            "created_at": time.time(),
        }
        _orders[order_id] = order
        _apply_fill(req.symbol, req.side, req.qty, req.price)
    return order


@app.get("/orders", response_model=List[OrderResponse])
def list_orders():
    with _lock:
        return list(_orders.values())


@app.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: str):
    with _lock:
        order = _orders.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return order


@app.get("/positions", response_model=List[Position])
def positions():
    with _lock:
        out = []
        for symbol, book in _lots.items():
            total_qty = sum(q for q, _ in book)
            if total_qty == 0:
                continue
            qty_long = sum(q for q, _ in book if q > 0)
            cost = sum(q * p for q, p in book if q > 0)
            avg_price = (cost / qty_long) if qty_long else 0.0
            out.append({"symbol": symbol, "qty": total_qty, "avg_price": avg_price})
        return out


@app.get("/pnl")
def pnl():
    with _lock:
        return {
            "total_realized_pnl": _realized_pnl_total,
            "by_symbol": dict(_realized_pnl_by_symbol),
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
