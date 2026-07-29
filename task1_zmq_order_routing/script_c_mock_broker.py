"""
Script C - Mock Broker
=======================
Lowest layer of the stack. Simulates a real broker/exchange:

  * Receives NEW_ORDER messages from Script B (PULL, connects to B's
    orders_out socket).
  * "Executes" the order: sends an ACCEPTED report immediately, then
    (after a small simulated latency) a FILLED report at the requested
    limit price.
  * Sends both EXEC_REPORT messages back to Script B (PUSH, connects to
    B's updates_in socket).

This script never talks to Script A directly - it only ever knows about B.
"""

import random
import threading
import time

import zmq

import config
import protocol


def log(msg: str):
    print(f"[C-MockBroker] {msg}", flush=True)


def handle_order(order: dict, update_sender: zmq.Socket, lock: threading.Lock):
    broker_order_id = order["broker_order_id"]
    symbol = order["symbol"]
    side = order["side"]
    qty = order["qty"]
    price = order["price"]

    log(f"received order {broker_order_id} {side} {qty} {symbol} @ {price} "
        f"(client_order_id={order.get('client_order_id')})")

    # 1) Acknowledge receipt
    ack = protocol.make_exec_report(
        broker_order_id=broker_order_id, symbol=symbol, side=side,
        status="ACCEPTED", filled_qty=0, remaining_qty=qty,
    )
    with lock:
        update_sender.send(protocol.encode(ack))
    log(f"-> ACCEPTED {broker_order_id}")

    # 2) Simulate matching-engine latency, then fill the whole order at the
    #    requested limit price (kept deterministic on purpose so the PnL
    #    Script A reports is easy to verify by hand).
    time.sleep(random.uniform(0.15, 0.4))

    fill = protocol.make_exec_report(
        broker_order_id=broker_order_id, symbol=symbol, side=side,
        status="FILLED", filled_qty=qty, remaining_qty=0,
        last_fill_qty=qty, last_fill_price=price, avg_fill_price=price,
    )
    with lock:
        update_sender.send(protocol.encode(fill))
    log(f"-> FILLED    {broker_order_id} {qty}@{price}")


def main():
    ctx = zmq.Context.instance()

    order_receiver = ctx.socket(zmq.PULL)
    order_receiver.connect(config.ADDR_B_ORDERS_OUT)

    update_sender = ctx.socket(zmq.PUSH)
    update_sender.connect(config.ADDR_B_UPDATES_IN)

    send_lock = threading.Lock()

    log(f"connected. orders <- {config.ADDR_B_ORDERS_OUT} | "
        f"updates -> {config.ADDR_B_UPDATES_IN}")
    log("waiting for orders... (Ctrl+C to stop)")

    try:
        while True:
            raw = order_receiver.recv()
            order = protocol.decode(raw)
            if order.get("type") != "NEW_ORDER":
                continue
            # handle each order on its own thread so ACCEPTED/FILLED for
            # different orders can be in flight concurrently, like a real
            # matching engine would.
            t = threading.Thread(
                target=handle_order, args=(order, update_sender, send_lock),
                daemon=True,
            )
            t.start()
    except KeyboardInterrupt:
        log("shutting down.")
    finally:
        order_receiver.close(0)
        update_sender.close(0)
        ctx.term()


if __name__ == "__main__":
    main()
