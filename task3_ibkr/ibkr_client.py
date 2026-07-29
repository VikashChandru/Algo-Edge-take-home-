"""
Thin wrapper around ib_async (the actively-maintained, API-compatible fork
of the now-archived ib_insync) covering the four things Task 3 asks for:

  1. contract fetching       -> fetch_contract_details()
  2. data feed subscription  -> stream_market_data()
  3. tick storage to Redis   -> (delegated to redis_store.TickStore, called
                                  from the tick callback here)
  4. order placement         -> place_order()

Requires a running TWS or IB Gateway instance with the API enabled
(see config.py for the checklist). Without one, connect() will raise a
ConnectionRefusedError / TimeoutError.

NOTE ON THE LIBRARY: this file imports `ib_async`. If you're on an
environment that only has the older `ib_insync` installed, the two are a
drop-in replacement for each other for everything used here - just change
the import line (`from ib_insync import ...`) and nothing else needs to
change.

NOTE ON MARKET DATA (error 10089): demo / non-subscribed accounts almost
always get "Error 10089: Requested market data requires additional
subscription for API" on live data. connect() below requests delayed data
(reqMarketDataType) as a fallback so reqMktData() still works without a
live-data subscription. See config.MARKET_DATA_TYPE / README.md.
"""

import logging
import time
from typing import Callable, Optional

from ib_async import IB, Stock, LimitOrder, MarketOrder, Contract, Trade

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ibkr_client")


class IBKRClient:
    def __init__(self, host=config.IB_HOST, port=config.IB_PORT,
                 client_id=config.IB_CLIENT_ID):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = IB()
        # Surface every IBKR error/warning (e.g. 10089 "requires additional
        # subscription") to the console immediately instead of it only
        # showing up as "no ticks arrived" further down the line.
        self.ib.errorEvent += self._on_error

    def _on_error(self, reqId, errorCode, errorString, contract=None):
        log.warning(f"IBKR errorEvent  reqId={reqId} code={errorCode} "
                    f"msg={errorString}" + (f" contract={contract.symbol}" if contract else ""))

    # ------------------------------------------------------------------ conn
    def connect(self, timeout: float = 10.0):
        log.info(f"connecting to IBKR at {self.host}:{self.port} "
                 f"(clientId={self.client_id}) ...")

        self.ib.connect(
            self.host,
            self.port,
            clientId=self.client_id,
            timeout=timeout,
        )

        # ---------------------------------------------------------
        # Force a market data type so reqMktData() still works on
        # accounts without a live-data subscription (this is what
        # fixes "Error 10089: Requested market data requires
        # additional subscription for API").
        #
        # 1 = Live
        # 2 = Frozen
        # 3 = Delayed
        # 4 = Delayed Frozen
        #
        # config.MARKET_DATA_TYPE defaults to 3 (Delayed). If you do
        # have a real-time data subscription on this account, set it
        # to 1 in config.py to get live ticks instead.
        # ---------------------------------------------------------
        self.ib.reqMarketDataType(config.MARKET_DATA_TYPE)
        log.info(f"requested market data type = {config.MARKET_DATA_TYPE} "
                 f"(1=Live 2=Frozen 3=Delayed 4=DelayedFrozen)")

        log.info(f"connected. server version={self.ib.client.serverVersion()}")

    def disconnect(self):
        if self.ib.isConnected():
            self.ib.disconnect()
            log.info("disconnected.")

    # ------------------------------------------------------------- contracts
    def fetch_contract_details(self, symbol: str, exchange="SMART", currency="USD"):
        """Qualify a stock contract and return (qualified_contract, details_list).

        Qualifying fills in fields IBKR needs (conId, primary exchange, etc.)
        that you don't have to know up front - you just supply symbol/
        exchange/currency and IB resolves the rest.
        """
        contract = Stock(symbol, exchange, currency)
        qualified = self.ib.qualifyContracts(contract)
        if not qualified:
            raise ValueError(f"could not qualify contract for symbol={symbol}")
        details = self.ib.reqContractDetails(qualified[0])
        log.info(f"qualified {symbol}: conId={qualified[0].conId} "
                 f"primaryExchange={qualified[0].primaryExchange}")
        return qualified[0], details

    # ------------------------------------------------------------- data feed
    def stream_market_data(self, contract: Contract, on_tick: Callable[[dict], None],
                            duration_sec: float = 20.0):
        """Subscribe to streaming top-of-book market data for `contract` and
        invoke `on_tick(tick_dict)` for every update received over
        `duration_sec` seconds, then unsubscribe.

        Uses ib.reqMktData (continuous top-of-book snapshot updates) rather
        than tick-by-tick trade prints, since it's the more commonly needed
        feed for a strategy (bid/ask/last/volume). connect() already forced
        delayed data via reqMarketDataType() so this works on demo/paper
        accounts without a live-data subscription.
        """
        log.info(f"requesting market data for {contract.symbol} ...")

        ticker = self.ib.reqMktData(contract, "", False, False)

        # Confirms IBKR actually created a subscription object on our side -
        # useful to eyeball while debugging "why am I getting no ticks".
        print("Ticker object:", ticker)

        log.info(f"subscribed to {contract.symbol}. waiting {duration_sec}s ...")

        def _on_update(tickers):
            print("\n==============================")
            print("pendingTickersEvent fired")
            print("==============================")

            for t in tickers:
                if t.contract.conId != contract.conId:
                    continue

                print(f"Bid={t.bid} Ask={t.ask} Last={t.last} Volume={t.volume}")

                tick = {
                    "symbol": contract.symbol,
                    "bid": t.bid if t.bid == t.bid else None,      # NaN-safe (NaN != NaN)
                    "ask": t.ask if t.ask == t.ask else None,
                    "last": t.last if t.last == t.last else None,
                    "bid_size": t.bidSize if t.bidSize == t.bidSize else None,
                    "ask_size": t.askSize if t.askSize == t.askSize else None,
                    "volume": t.volume if t.volume == t.volume else None,
                    "ts": time.time(),
                }

                print("Tick dictionary:", tick)
                on_tick(tick)

        self.ib.pendingTickersEvent += _on_update
        try:
            self.ib.sleep(duration_sec)   # pumps the ib_async event loop for this long
        finally:
            self.ib.pendingTickersEvent -= _on_update
            self.ib.cancelMktData(contract)
            log.info(f"unsubscribed from market data for {contract.symbol}")

    # --------------------------------------------------------------- orders
    def place_order(self, contract: Contract, action: str, qty: int,
                     order_type: str = "LMT", limit_price: Optional[float] = None,
                     wait_sec: float = 5.0) -> Trade:
        """Place an order and wait briefly for status/fill events to arrive."""
        if order_type == "LMT":
            if limit_price is None:
                raise ValueError("limit_price is required for LMT orders")
            order = LimitOrder(action, qty, limit_price)
        elif order_type == "MKT":
            order = MarketOrder(action, qty)
        else:
            raise ValueError(f"unsupported order_type: {order_type}")

        trade = self.ib.placeOrder(contract, order)
        log.info(f"placed order: {action} {qty} {contract.symbol} "
                 f"{order_type} {limit_price if limit_price else ''}")

        def _on_status(trade_: Trade):
            log.info(f"order status update: {trade_.orderStatus.status} "
                     f"filled={trade_.orderStatus.filled} "
                     f"remaining={trade_.orderStatus.remaining}")

        trade.statusEvent += _on_status
        try:
            self.ib.sleep(wait_sec)   # give IB time to send back status/fill events
        finally:
            trade.statusEvent -= _on_status

        return trade

    def cancel_order(self, trade: Trade):
        self.ib.cancelOrder(trade.order)
        log.info(f"cancel requested for order {trade.order.orderId}")