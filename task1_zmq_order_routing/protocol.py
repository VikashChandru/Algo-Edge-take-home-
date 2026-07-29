"""
Wire protocol for the ZMQ order-routing demo.

Every ZMQ message is a single JSON-encoded frame (utf-8 bytes). Two message
types flow through the system:

  NEW_ORDER    : Script A -> Script B -> Script C
  EXEC_REPORT  : Script C -> Script B -> Script A

Helper functions here just centralise (de)serialisation so all three scripts
speak exactly the same dialect.
"""

import json
import time
import uuid


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def new_client_order_id() -> str:
    return f"CL-{uuid.uuid4().hex[:8].upper()}"


def new_broker_order_id() -> str:
    return f"BRK-{uuid.uuid4().hex[:8].upper()}"


def make_new_order(client_order_id, symbol, side, qty, price, order_type="LIMIT"):
    return {
        "type": "NEW_ORDER",
        "client_order_id": client_order_id,
        "symbol": symbol,
        "side": side,            # "BUY" | "SELL"
        "qty": qty,
        "price": price,
        "order_type": order_type,
        "ts": now_iso(),
    }


def make_exec_report(broker_order_id, symbol, side, status, filled_qty,
                      remaining_qty, last_fill_qty=0, last_fill_price=0.0,
                      avg_fill_price=0.0, reason=None, client_order_id=None):
    return {
        "type": "EXEC_REPORT",
        "broker_order_id": broker_order_id,
        "client_order_id": client_order_id,   # filled in by B before forwarding to A
        "symbol": symbol,
        "side": side,
        "status": status,        # "ACCEPTED" | "PARTIALLY_FILLED" | "FILLED" | "REJECTED"
        "filled_qty": filled_qty,
        "remaining_qty": remaining_qty,
        "last_fill_qty": last_fill_qty,
        "last_fill_price": last_fill_price,
        "avg_fill_price": avg_fill_price,
        "reason": reason,
        "ts": now_iso(),
    }


def encode(msg: dict) -> bytes:
    return json.dumps(msg).encode("utf-8")


def decode(raw: bytes) -> dict:
    return json.loads(raw.decode("utf-8"))
