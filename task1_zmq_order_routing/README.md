# Task 1 — ZMQ Order Routing Demo (Strategy → Broker Adapter → Mock Broker)

Three independent processes talking over ZeroMQ:

| Script | Role | File |
|---|---|---|
| A | Strategy — places orders, tracks order book / positions / realised PnL | `script_a_strategy.py` |
| B | Broker adapter — relays orders/updates, does ID translation + a basic risk check | `script_b_broker_adapter.py` |
| C | Mock broker — "executes" orders and reports fills | `script_c_mock_broker.py` |

## Topology

Script **B is the hub** and binds all four TCP sockets; A and C only connect
to it. This is what makes the required flow structurally guaranteed (not
just a convention we follow in code):

```
 Script A (Strategy)                Script B (Broker Adapter)              Script C (Mock Broker)
 --------------------                -------------------------              -----------------------
 PUSH → connect :5555 ─ orders ─────▶ PULL bind :5555 (orders_in)
                                      PUSH bind :5557 (orders_out) ─ orders ▶ PULL ← connect :5557
 PULL ← connect :5556 ◀─ updates ──── PUSH bind :5556 (updates_out)
                                      PULL bind :5558 (updates_in) ◀ updates  PUSH → connect :5558
```

* **Order flow:** A → B → C (strict — A has no socket that reaches C directly)
* **Update flow:** C → B → A (strict — C has no socket that reaches A directly)

PUSH/PULL (not PUB/SUB) is used deliberately: it's a 1:1 relay rather than a
broadcast, and PUSH sockets buffer outbound messages until the peer connects,
so we don't hit ZMQ's PUB/SUB "slow joiner" problem.

Script B also does two things a real broker adapter does:
* Assigns its own `broker_order_id` and maps it to A's `client_order_id`
  (and translates back on the way out), demonstrating ID translation between
  the strategy-facing and broker-facing protocols.
* A trivial pre-trade risk check (`qty > 0`, `price > 0`) — a failing order
  is REJECTED by B and never reaches C.

## The demo trade sequence

Script A sends 5 orders (mix of BUY/SELL, two symbols):

| # | Side | Qty | Symbol | Price |
|---|------|-----|--------|-------|
| 1 | BUY  | 100 | AAPL   | 150.00 |
| 2 | BUY  | 50  | AAPL   | 151.00 |
| 3 | SELL | 80  | AAPL   | 155.00 |
| 4 | BUY  | 40  | MSFT   | 300.00 |
| 5 | SELL | 40  | AAPL   | 156.00 |

Positions/PnL are computed with **FIFO cost basis** purely from the
execution reports Script A receives (it does not "cheat" by looking at its
own order list — it replays fills the same way a real position keeper
would). By hand:

* Order 3 sells 80 out of the 100-share lot bought @150 → realises `80 × (155-150) = 400`
* Order 5 sells 40: 20 remaining from lot 1 (`20 × (156-150) = 120`) + 20 from
  the 151 lot (`20 × (156-151) = 100`) → realises `220`
* **Total realised PnL = 620**
* **Open positions at the end:** AAPL 30 @ 151.00, MSFT 40 @ 300.00

Running the demo (below) reproduces exactly this.

## How to run

### Requirements
```bash
pip install -r requirements.txt
```
(only dependency: `pyzmq`)

### Option 1 — one command (recommended)
```bash
python3 run_demo.py
```
This starts B and C as background processes and runs A in the foreground so
you see its live log + final report. It cleans up B/C on exit (Ctrl+C or
normal completion).

### Option 2 — three terminals (closer to how you'd run it in production)
```bash
# terminal 1
python3 script_b_broker_adapter.py

# terminal 2 (after B has started)
python3 script_c_mock_broker.py

# terminal 3 (after B and C have started)
python3 script_a_strategy.py
```

## What you'll see

* Live log lines from all three scripts showing each order/report moving
  through the pipeline (`SENT` → `ACCEPTED` → `FILLED`, with A→B→C and
  C→B→A hops both logged).
* At the end, Script A prints:
  * **Order Book** — every order it sent, with fill quantity and status
  * **Open Positions** — remaining qty and average cost per symbol
  * **Realised PnL** — per symbol and total

## Files

```
config.py                     shared ZMQ addresses / topology
protocol.py                   shared JSON message schema + helpers
script_a_strategy.py           Script A
script_b_broker_adapter.py     Script B
script_c_mock_broker.py        Script C
run_demo.py                   convenience one-command launcher
requirements.txt
```
