"""
Script A - Strategy
=====================
Top of the stack. Generates orders, sends them into the pipeline
(A -> B -> C), and consumes execution reports flowing back
(C -> B -> A) on a background thread.

Maintains, purely from the execution reports it receives:
  * an order book (every order this strategy has sent + its live status)
  * open positions (FIFO cost basis, per symbol)
  * realised PnL (booked every time a SELL closes out an existing long lot)

At the end of the demo it prints all three.
"""

import threading
import time
from collections import deque

import zmq

import config
import protocol


def log(msg: str):
    print(f"[A-Strategy] {msg}", flush=True)


# --------------------------------------------------------------------------- 
# Position / PnL tracking (FIFO cost basis)
# ---------------------------------------------------------------------------
class PositionBook:
    """Tracks open positions and realised PnL using FIFO lot matching.

    Only supports going long -> flat here (no short selling), which is all
    the demo needs, but the lot-matching logic generalises easily.
    """

    def __init__(self):
        self.lots = {}          # symbol -> deque[[qty, price], ...]  (open BUY lots, FIFO)
        self.realized_pnl = 0.0
        self.realized_pnl_by_symbol = {}
        self.lock = threading.Lock()

    def apply_fill(self, symbol, side, qty, price):
        with self.lock:
            book = self.lots.setdefault(symbol, deque())
            if side == "BUY":
                book.append([qty, price])
            else:  # SELL -> close out oldest lots first
                remaining = qty
                while remaining > 0 and book:
                    lot_qty, lot_price = book[0]
                    matched = min(lot_qty, remaining)
                    pnl = matched * (price - lot_price)
                    self.realized_pnl += pnl
                    self.realized_pnl_by_symbol[symbol] = (
                        self.realized_pnl_by_symbol.get(symbol, 0.0) + pnl
                    )
                    lot_qty -= matched
                    remaining -= matched
                    if lot_qty == 0:
                        book.popleft()
                    else:
                        book[0][0] = lot_qty
                if remaining > 0:
                    # selling more than currently held - not expected in this
                    # demo, but track it as a negative ("short") lot so
                    # nothing silently disappears.
                    book.appendleft([-remaining, price])

    def open_positions(self):
        with self.lock:
            out = {}
            for symbol, book in self.lots.items():
                total_qty = sum(q for q, _ in book)
                if total_qty == 0:
                    continue
                cost = sum(q * p for q, p in book if q > 0)
                qty_long = sum(q for q, _ in book if q > 0)
                avg_price = (cost / qty_long) if qty_long else 0.0
                out[symbol] = (total_qty, avg_price)
            return out


# ---------------------------------------------------------------------------
# Order book
# ---------------------------------------------------------------------------
class OrderBook:
    def __init__(self):
        self.orders = {}   # client_order_id -> dict
        self.lock = threading.Lock()

    def add_new(self, client_order_id, symbol, side, qty, price):
        with self.lock:
            self.orders[client_order_id] = {
                "client_order_id": client_order_id,
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "price": price,
                "status": "SENT",
                "filled_qty": 0,
            }

    def update_from_report(self, report):
        coid = report.get("client_order_id")
        with self.lock:
            if coid not in self.orders:
                return
            self.orders[coid]["status"] = report["status"]
            self.orders[coid]["filled_qty"] = report["filled_qty"]

    def snapshot(self):
        with self.lock:
            return dict(self.orders)


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------
class Strategy:
    def __init__(self):
        ctx = zmq.Context.instance()
        self.order_sender = ctx.socket(zmq.PUSH)
        self.order_sender.connect(config.ADDR_B_ORDERS_IN)

        self.update_receiver = ctx.socket(zmq.PULL)
        self.update_receiver.connect(config.ADDR_B_UPDATES_OUT)

        self.ctx = ctx
        self.positions = PositionBook()
        self.order_book = OrderBook()
        self.done_event = threading.Event()
        self.expected_terminal = 0
        self.terminal_count = 0
        self.terminal_lock = threading.Lock()

    def _listen(self):
        while not self.done_event.is_set():
            try:
                # short timeout via poller so we can check done_event
                if self.update_receiver.poll(timeout=200):
                    raw = self.update_receiver.recv()
                else:
                    continue
            except zmq.ContextTerminated:
                return
            report = protocol.decode(raw)
            if report.get("type") != "EXEC_REPORT":
                continue

            self.order_book.update_from_report(report)

            if report["status"] == "FILLED":
                self.positions.apply_fill(
                    report["symbol"], report["side"],
                    report["last_fill_qty"], report["last_fill_price"],
                )
                log(f"FILLED  {report['client_order_id']}  "
                    f"{report['side']} {report['last_fill_qty']} {report['symbol']} "
                    f"@ {report['last_fill_price']}")
                with self.terminal_lock:
                    self.terminal_count += 1
                    if self.terminal_count >= self.expected_terminal:
                        self.done_event.set()
            elif report["status"] == "REJECTED":
                log(f"REJECTED {report['client_order_id']}  reason={report.get('reason')}")
                with self.terminal_lock:
                    self.terminal_count += 1
                    if self.terminal_count >= self.expected_terminal:
                        self.done_event.set()
            elif report["status"] == "ACCEPTED":
                log(f"ACCEPTED {report['client_order_id']}")

    def send_order(self, symbol, side, qty, price):
        client_order_id = protocol.new_client_order_id()
        order = protocol.make_new_order(client_order_id, symbol, side, qty, price)
        self.order_book.add_new(client_order_id, symbol, side, qty, price)
        self.order_sender.send(protocol.encode(order))
        log(f"SENT     {client_order_id}  {side} {qty} {symbol} @ {price}")
        return client_order_id

    def run_demo(self):
        listener = threading.Thread(target=self._listen, daemon=True)
        listener.start()

        # 5 demo orders: 3x BUY/SELL AAPL (partial closes) + 1x BUY MSFT
        # Chosen so the realised PnL is easy to verify by hand (see README):
        #   order3 realises 80 * (155-150) = 400
        #   order5 realises 20*(156-150) + 20*(156-151) = 220
        #   total realised PnL = 620
        #   ends flat AAPL 30 @ 151 open, MSFT 40 @ 300 open
        demo_orders = [
            ("AAPL", "BUY",  100, 150.00),
            ("AAPL", "BUY",   50, 151.00),
            ("AAPL", "SELL",  80, 155.00),
            ("MSFT", "BUY",   40, 300.00),
            ("AAPL", "SELL",  40, 156.00),
        ]
        self.expected_terminal = len(demo_orders)

        for symbol, side, qty, price in demo_orders:
            self.send_order(symbol, side, qty, price)
            time.sleep(0.3)   # small pacing so the console log reads clearly

        log("all orders sent, waiting for fills...")
        finished = self.done_event.wait(timeout=15)
        if not finished:
            log("WARNING: timed out waiting for all fills")

        self.print_report()

    def print_report(self):
        print("\n" + "=" * 72)
        print("ORDER BOOK")
        print("=" * 72)
        print(f"{'CLIENT ORDER ID':16} {'SYM':6} {'SIDE':5} {'QTY':>6} "
              f"{'PRICE':>9} {'FILLED':>7} {'STATUS':>12}")
        for o in self.order_book.snapshot().values():
            print(f"{o['client_order_id']:16} {o['symbol']:6} {o['side']:5} "
                  f"{o['qty']:>6} {o['price']:>9.2f} {o['filled_qty']:>7} "
                  f"{o['status']:>12}")

        print("\n" + "=" * 72)
        print("OPEN POSITIONS")
        print("=" * 72)
        print(f"{'SYM':6} {'QTY':>8} {'AVG PRICE':>12}")
        positions = self.positions.open_positions()
        if not positions:
            print("(flat - no open positions)")
        for symbol, (qty, avg_price) in positions.items():
            print(f"{symbol:6} {qty:>8} {avg_price:>12.2f}")

        print("\n" + "=" * 72)
        print("REALISED PNL")
        print("=" * 72)
        for symbol, pnl in self.positions.realized_pnl_by_symbol.items():
            print(f"{symbol:6} {pnl:>12.2f}")
        print(f"{'TOTAL':6} {self.positions.realized_pnl:>12.2f}")
        print("=" * 72 + "\n")

    def close(self):
        self.done_event.set()
        time.sleep(0.3)
        self.order_sender.close(0)
        self.update_receiver.close(0)
        self.ctx.term()


if __name__ == "__main__":
    strategy = Strategy()
    try:
        strategy.run_demo()
    finally:
        strategy.close()
