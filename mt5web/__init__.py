"""MT5 Web Console - control a MetaTrader 5 terminal from the browser.

Layout:
  config.py  environment driven settings
  auth.py    passcode sessions + bridge agent keys
  crypto.py  stdlib AES-CTR + HMAC for the stored MT5 password
  store.py   tiny JSON persistence
  gateway.py MT5 transports (in-process Windows package / remote agent)
  hub.py     agent registry + RPC + event fan-out
  broker.py  account connection manager, orders, risk guards
  market.py  quotes, candles, polling loop
  backtest.py bar-based backtester for Algo Studio previews
  algo.py    strategy sandbox, live engines, EA engines
  MQL5.py    Expert Advisor generation / compilation / deployment
  main.py    FastAPI routes and WebSockets
"""

__version__ = "1.0.0"
