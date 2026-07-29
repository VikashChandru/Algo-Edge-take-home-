"""
Script B - Broker Adapter
==========================
Sits between the strategy (A) and the broker (C). Binds all four sockets
(it is the hub of the star topology described in config.py) and performs
the job a real broker adapter would do:

  * Assigns its own broker_order_id to every inbound order (ID translation)
    and remembers the client_order_id <-> broker_order_id mapping.
  * Performs a trivial pre-trade risk check (qty > 0, price > 0) and would
    REJECT the order back to A without ever forwarding it to C if it failed.
  * Relays valid orders on to Script C.
  * Relays execution reports from Script C back to Script A, translating
    broker_order_id back to the client_order_id A originally used.

Strict flow enforced by the socket wiring itself:
    orders   : A -> B -> C
    updates  : C -> B -> A
"""

import threading

import zmq

import config
import protocol


def log(msg: str):
    print(f"[B-BrokerAdapter] {msg}", flush=True)


class BrokerAdapter:
    def __init__(self):
        ctx = zmq.Context.instance()

        # From A
        self.orders_in = ctx.socket(zmq.PULL)
        self.orders_in.bind(config.BIND_B_ORDERS_IN)

        # To A
        self.updates_out = ctx.socket(zmq.PUSH)
        self.updates_out.bind(config.BIND_B_UPDATES_OUT)

        # To C
        self.orders_out = ctx.socket(zmq.PUSH)
        self.orders_out.bind(config.BIND_B_ORDERS_OUT)

        # From C
        self.updates_in = ctx.socket(zmq.PULL)
        self.updates_in.bind(config.BIND_B_UPDATES_IN)

        self.ctx = ctx
        self.lock = threading.Lock()

        # client_order_id <-> broker_order_id translation table
        self.client_to_broker = {}
        self.broker_to_client = {}

    # ---------------------------------------------------------------- A->C
    def _handle_order_from_a(self, raw: bytes):
        order = protocol.decode(raw)
        if order.get("type") != "NEW_ORDER":
            return

        client_order_id = order["client_order_id"]

        # --- trivial pre-trade risk check ---
        if order["qty"] <= 0 or order["price"] <= 0:
            log(f"REJECT {client_order_id}: invalid qty/price")
            reject = protocol.make_exec_report(
                broker_order_id="N/A", symbol=order["symbol"], side=order["side"],
                status="REJECTED", filled_qty=0, remaining_qty=order["qty"],
                reason="invalid qty/price", client_order_id=client_order_id,
            )
            self.updates_out.send(protocol.encode(reject))
            return

        broker_order_id = protocol.new_broker_order_id()
        with self.lock:
            self.client_to_broker[client_order_id] = broker_order_id
            self.broker_to_client[broker_order_id] = client_order_id

        order["broker_order_id"] = broker_order_id
        log(f"A->B->C  {client_order_id} mapped to {broker_order_id}  "
            f"({order['side']} {order['qty']} {order['symbol']} @ {order['price']})")
        self.orders_out.send(protocol.encode(order))

    # ---------------------------------------------------------------- C->A
    def _handle_report_from_c(self, raw: bytes):
        report = protocol.decode(raw)
        if report.get("type") != "EXEC_REPORT":
            return

        broker_order_id = report["broker_order_id"]
        with self.lock:
            client_order_id = self.broker_to_client.get(broker_order_id)

        report["client_order_id"] = client_order_id
        log(f"C->B->A  {broker_order_id} ({client_order_id})  status={report['status']}")
        self.updates_out.send(protocol.encode(report))

    def run(self):
        log(f"bound: orders_in={config.BIND_B_ORDERS_IN} "
            f"updates_out={config.BIND_B_UPDATES_OUT} "
            f"orders_out={config.BIND_B_ORDERS_OUT} "
            f"updates_in={config.BIND_B_UPDATES_IN}")
        log("ready. relaying A<->C ... (Ctrl+C to stop)")

        poller = zmq.Poller()
        poller.register(self.orders_in, zmq.POLLIN)
        poller.register(self.updates_in, zmq.POLLIN)

        try:
            while True:
                events = dict(poller.poll(timeout=1000))
                if self.orders_in in events:
                    self._handle_order_from_a(self.orders_in.recv())
                if self.updates_in in events:
                    self._handle_report_from_c(self.updates_in.recv())
        except KeyboardInterrupt:
            log("shutting down.")
        finally:
            for s in (self.orders_in, self.updates_out, self.orders_out, self.updates_in):
                s.close(0)
            self.ctx.term()


if __name__ == "__main__":
    BrokerAdapter().run()
