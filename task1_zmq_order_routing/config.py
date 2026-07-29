"""
Shared configuration for the ZMQ order-routing demo.

Topology (Script B is the hub and binds all four sockets;
Script A and Script C only connect):

    Script A (Strategy)                Script B (Broker Adapter)              Script C (Mock Broker)
    --------------------                -------------------------              -----------------------
    PUSH  -> connect 5555   orders  ->   PULL bind 5555 (orders_in)
                                         PUSH bind 5557 (orders_out)   orders -> PULL connect 5557
    PULL  <- connect 5556   updates <-   PUSH bind 5556 (updates_out)
                                         PULL bind 5558 (updates_in) <- updates  PUSH connect 5558

Order flow  : A --PUSH/PULL--> B --PUSH/PULL--> C   (strictly A -> B -> C)
Update flow : C --PUSH/PULL--> B --PUSH/PULL--> A   (strictly C -> B -> A)

PUSH/PULL is used (instead of PUB/SUB) on purpose: it is a 1:1 relay, not a
broadcast, and PUSH sockets queue outbound messages internally until the peer
connects, so we don't suffer from the ZMQ PUB/SUB "slow joiner" problem where
early messages get silently dropped.
"""

HOST = "127.0.0.1"

# B's bind ports
B_ORDERS_IN_PORT = 5555     # A  -> B   (orders)
B_UPDATES_OUT_PORT = 5556   # B  -> A   (execution reports)
B_ORDERS_OUT_PORT = 5557    # B  -> C   (orders)
B_UPDATES_IN_PORT = 5558    # C  -> B   (execution reports)

ADDR_B_ORDERS_IN = f"tcp://{HOST}:{B_ORDERS_IN_PORT}"
ADDR_B_UPDATES_OUT = f"tcp://{HOST}:{B_UPDATES_OUT_PORT}"
ADDR_B_ORDERS_OUT = f"tcp://{HOST}:{B_ORDERS_OUT_PORT}"
ADDR_B_UPDATES_IN = f"tcp://{HOST}:{B_UPDATES_IN_PORT}"

BIND_B_ORDERS_IN = f"tcp://*:{B_ORDERS_IN_PORT}"
BIND_B_UPDATES_OUT = f"tcp://*:{B_UPDATES_OUT_PORT}"
BIND_B_ORDERS_OUT = f"tcp://*:{B_ORDERS_OUT_PORT}"
BIND_B_UPDATES_IN = f"tcp://*:{B_UPDATES_IN_PORT}"
