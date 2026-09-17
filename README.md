# MT5 Web Console

Control a **live** MetaTrader 5 account from a browser: pick the symbol, log in with your
MT5 account number / password / server, write or paste an algo, then **start** and **stop**
it while watching positions, equity and the terminal's own log.

> ⚠️ **This tool places real orders on a real account.** There is no demo/simulation mode —
> that was a deliberate design choice, so nothing hides behind "it's only a test". Use a
> small `max_lot`, keep the **Kill Switch** one click away, and read
> [Risk notes](#risk-notes) before the first run.

---

## 1. Why the app is split in two (the important part)

You asked: *"can MetaTrader 5 be installed inside Render and driven from a web app?"*
The honest answer, after checking MetaQuotes' docs, PyPI and the official installer:

| Fact | Consequence |
| --- | --- |
| The `MetaTrader5` python package ships **Windows-only** wheels (`win_amd64` `.pyd`) | a Render Ubuntu service can never `import MetaTrader5` |
| MetaTrader's "Linux installer" (`mt5linux.sh`) is a **Wine bootstrap**: it installs `winehq-staging`, builds a `~/.mt5` prefix, then runs the Windows `mt5setup.exe` wizard (sudo + desktop + reboot) | no native Linux MT5 exists; MT5 cannot live inside a Render *web* service |
| Render web services get **no persistent disk** by default | even with Wine, the terminal data folder would vanish on redeploy |

So the architecture is:

```
┌─────────────────────────────┐   HTTPS (token auth)   ┌──────────────────────────────┐
│  Browser UI                 │ ─────────────────────► │  FastAPI control plane       │
│  /#/trade  /#/algo  /#/bridge│                        │  (Render / any Linux host)   │
└─────────────────────────────┘ ◄──── WS /ws/stream ── │  mt5web/                     │
                                                        │   · passcode + tokens        │
   one OUTBOUND WebSocket, no ports opened              │   · algo engine + backtester │
   on the machine that owns MT5                         │   · EA generator             │
                                                        │   · audit log, kill switch   │
                                                        └───────────────┬──────────────┘
                                                                        │  WSS /ws/agent
                                                        ┌───────────────▼──────────────┐
                                                        │  Bridge agent  agents/agent/ │
                                                        │  Windows PC, Wine box or VPS │
                                                        │  import MetaTrader5  ← the    │
                                                        │  only place MT5 can run       │
                                                        └──────────────────────────────┘
```

The agent is a ~600 line python script. It holds the terminal session, executes the
`MetaTrader5` calls, writes/compiles MQL5 Experts and tails the terminal logs. The web app
never needs a public port on your trading machine.

**Everything else you asked for is in the app**: currency/symbol selection, MT5 login +
password + server, an in-browser algo editor with a sandboxed python engine, backtest,
start/stop, positions, history, audit trail, and an Expert Advisor generator for people who
want execution inside the terminal itself.

---

## 2. Quick start

### 2a. Everything on one Windows machine (simplest)

```bat
git clone https://github.com/mehedi42x/MetaTrader5.git
cd MetaTrader5
py -3.11 -m venv .venv && .venv\Scripts\activate
pip install -r requirements-win.txt
python run.py
```

`run.py` prints whether `MetaTrader5` imports; if it does, open http://127.0.0.1:8000 and
use **Settings → In-process terminal** (no agent needed).

### 2b. Web app on Render + agent on your PC (recommended)

1. Push this repo to GitHub → **Render → New → Blueprint** (it reads `render.yaml`).
   The blueprint sets `MT5WEB_PASSCODE`, `MT5WEB_BRIDGE_KEY` (fill in real secrets) and
   `MT5WEB_DATA=/var/tmp/mt5web-data`. **Attach a Disk** if you want accounts/algs to
   survive redeploys (otherwise re-add them after each deploy).
2. Open the Render URL, set your passcode, then go to **Bridge** and press
   *⬇ agent bundle (.zip)*.
3. On the Windows machine that runs MetaTrader 5:

   ```bat
   cd mt5-bridge-agent
   py -3.11 -m venv .venv && .venv\Scripts\activate
   pip install -r agent\requirements.txt
   start-agent.bat  --url wss://YOUR-RENDER-APP.onrender.com/ws/agent --key YOUR-BRIDGE-KEY --name my-vps
   ```

   (`agents/install-mt5.ps1` installs the terminal if you do not have it yet.)
4. Back in the browser: **Settings → MT5 account** → login / password / server → *Connect*.
   The Bridge panel should now show the agent, the terminal build and a live RPC counter.

### 2c. Linux box running MT5 under Wine (your `mt5linux.sh` question)

Verified: `wget https://download.terminal.free/cdn/web/metaquotes.software.corp/mt5/mt5linux.sh`
is served by MetaQuotes (`download.terminal.free` resolves to the same CDN as
`download.mql5.com`), and the script only prepares Wine + runs the Windows installer.

`agents/setup-mt5-wine.sh` does the whole job in one shot (Ubuntu/Debian/Mint/Fedora), including
the parts the official script leaves to you — headless Xvfb startup and a `--portable` install:

```bash
sudo apt-get update && sudo apt-get install -y xvfb cabextract winetricks
bash agents/setup-mt5-wine.sh --run          # installs wine 11.x, MT5, then starts it
bash agents/setup-mt5-wine.sh --status       # what is installed / missing right now
```

Notes that actually matter (from MetaQuotes' own docs/forum):

* use Wine **11.x** — Wine 10.0 and 11.0 are reported broken;
* the prefix is `~/.mt5`, the terminal is `~/.mt5/drive_c/Program Files/MetaTrader 5/terminal64.exe`;
* after the GUI installer finishes you must **reboot** once;
* for headless use, start under Xvfb and pass an INI: `terminal64.exe /config:mt5web.ini`
  (`[Common] Login/Password/Server`, `[Experts] AllowLiveTrading=1`);
* the **python API is still Windows-only**: on Linux run the agent with Wine's own python, e.g.
  `wine "C:\python312\python.exe" "C:\agent\main.py" --url wss://… --key …`.

### 2d. Docker (self-hosted, opt-in Wine layer)

```bash
docker build -t mt5web .                                  # control plane only
docker run -p 8000:8000 -e MT5WEB_PASSCODE=… -e MT5WEB_BRIDGE_KEY=… mt5web

docker build --build-arg WITH_MT5=1 -t mt5web:mt5 .        # adds xvfb + agents/setup-mt5-wine.sh
docker run -p 8000:8000 -v mt5data:/var/lib/mt5web-data -v mt5prefix:/root/.mt5 --ipc=host mt5web:mt5
```

---

## 3. What you can do in the UI

| Page | What happens |
| --- | --- |
| **Overview** | account snapshot, equity, spread/quote ticker, agent + kill-switch state, live event feed |
| **Markets** | symbol list (add/remove), candles chart per timeframe, one-click quote refresh |
| **Trade** | currency + direction + volume, SL/TP in *points* or absolute price, market and 4 pending types, risk-based lot calculator, one-click close/modify |
| **Positions** | open positions/orders with live P&L, partial close, cancel pending, deal history + summary |
| **Algo Studio** | create/rename algos, edit the python strategy in-browser, syntax + preview backtest, run/stop with live log, EA (MQL5) tab, hybrid mode, per-algo limits |
| **Bridge** | agent install steps, `.zip` download, key rotation, connected-agent details, MT5 terminal log tail, host/platform verdict |
| **Settings** | MT5 account (login/password/server/terminal path), symbols, `max_lot`, tick interval, **Kill Switch**, change passcode |

Everything is one small vanilla-JS bundle (`mt5web/static/`) — no build step, no framework.

---

## 4. Algo scripts

`Algo Studio → python engine` runs your code in a restricted namespace (imports, `open`,
`eval`, `exec`, `compile`, double underscores are refused at compile time). Contract:

```python
def init(ctx):
    ctx.p.setdefault("fast", 12)          # user-editable params live in ctx.p
    ctx.log("ready", ctx.symbol, ctx.timeframe)

def on_bar(ctx, bars, i):
    if i < 30:
        return None
    if bars.ema(12, i) > bars.ema(26, i) and bars.rsi(14, i) < 68 and not ctx.has_position():
        return {"action": "buy", "reason": "ema cross up"}   # -> order via the gateway
    if ctx.position and bars.close[i] < bars.sma(20, i):
        return {"action": "close", "reason": "flat"}
    return None
```

* `bars` helpers: `close/open/high/low/volume`, `sma`, `ema`, `rsi`, `atr_points`, `stdev`,
  `donchian`, `spread_points`, `time`, and `bars.meta` (point/digits/contract size).
* `ctx`: `ctx.position`, `ctx.position_count`, `ctx.balance/equity`, `ctx.volume`,
  `ctx.compute_volume()` (risk-% sizing), `ctx.points_to_price(n)`, `ctx.log(...)`.
* Signals: `"buy" | "sell" | "close"`, or `1 / -1 / 0`, or a dict with
  `action, volume, reason, comment, deviation`.
* Three engines: **python** (this app places the orders), **MQL5** (we generate an EA, the
  agent compiles + deploys it, MT5 executes), **hybrid** (python decides, EA executes through
  a signal file in `MQL5\Files` — no WebRequest, no ports, works with the terminal's own
  stop-out logic).
* `run_on_timer` on an algo also evaluates inside the bar (faster feedback, noisier); the
  *warm-up pass over history does **not** trade* unless you tick `trade_on_replay`.

Three starters are pre-loaded (`examples/`: ema cross, donchian breakout, mean-reversion grid)
and the same source is attached automatically when you create a python/hybrid algo.

---

## 5. Safety model (what the code actually does)

* **Kill Switch** (`/api/settings`) — blocks every new order *and* refuses to start algos;
  also pushes `kill=1` into the signal file so a deployed EA stops opening positions.
* **Per-algo limits** — `max_open_positions`, `one_position_per_symbol`, `allow_reverse`,
  `max_daily_loss_percent` (engine halts itself), server-side trailing stop.
* **App-level `max_lot`** — every request is clamped to it and to the symbol's volume
  step/min/max; `round_to_step` never rounds *up* past the limit.
* **Stop validation** — for a BUY the SL must sit below entry and TP above it (mirrored for
  a SELL); impossible SL/TP pairs are rejected before they reach your broker.
* **Credentials** — MT5 passwords are encrypted with AES-128-CTR+HMAC (stdlib only, key
  derived from `MT5WEB_SECRET`) and are never returned by any API; fingerprints only.
  They are forwarded to the agent only while connecting.
* **Auth** — single passcode (`PBKDF2-HMAC-SHA256`, 240k iters) → HMAC-signed bearer token
  (`exp`, role). The agent uses a separate `MT5WEB_BRIDGE_KEY` (rotate it in the Bridge page)
  and only *outbound* connections are needed.
* **Audit log** — `data.audit`: who saved what, order/position/algo events with results, kept
  last 500 lines, exposed at `/api/bridge/audit`.
* **Docs endpoints are off** in production (`MT5WEB_SECRET` set), `/api/openapi.json` only.

---

## 6. HTTP API

Everything under `/api`, bearer-token authenticated (`?token=` works too, used for downloads).

```
GET  /api/health                       POST /api/auth/login                 GET  /api/auth/status
POST /api/auth/change-passcode         GET  /api/state                      GET  /api/status
GET  /api/platform                     POST /api/settings
GET/POST /api/symbols                   DELETE /api/symbols/{symbol}
GET  /api/market/rates  /api/market/quote
GET  /api/trade/state   /api/trade/history   GET /api/trade/risk
POST /api/trade/order /trade/close /trade/modify /trade/cancel-order
GET/POST /api/accounts                  PATCH/DELETE /api/accounts/{id}
POST /api/accounts/connect /accounts/disconnect
GET/POST /api/algos                      PATCH/DELETE /api/algos/{id}
GET/PUT /api/algos/{id}/source           POST /api/algos/{id}/backtest|/run|/stop|/deploy|/signal
GET  /api/algos/{id}/log|/mt5-log|/ea|/signal-file      POST /api/algos/preview
GET  /api/bridge                         POST /api/bridge/rotate-key
GET  /api/bridge/audit /api/bridge/download /api/bridge/agent-config
WS   /ws/stream   WS  /ws/agent?key=<bridge key>
```

`GET /api/docs` renders a small in-app reference for the same routes.

---

## 7. Configuration

| env | default | meaning |
| --- | --- | --- |
| `MT5WEB_DATA` | `./data` | where `*.json` state lives (use `/var/tmp/mt5web-data` on Render) |
| `MT5WEB_SECRET` | random per start | encrypts credentials + signs tokens — **set it**, or state cannot be decrypted after a restart |
| `MT5WEB_PASSCODE` | — | if set, it is the login passcode; otherwise the first visit creates it |
| `MT5WEB_BRIDGE_KEY` | random per install | agents authenticate with it |
| `MT5WEB_SYMBOLS` | `EURUSD,GBPUSD,USDJPY,AUDUSD,USDCAD,XAUUSD,BTCUSD` | default watchlist |
| `MT5WEB_MAX_LOT` | `5` | hard lot ceiling for every order |
| `MT5WEB_RPC_TIMEOUT` | `25` | seconds to wait for the agent |
| `MT5WEB_TICK_INTERVAL` | `2` | quote poll cadence (seconds) |
| `MT5WEB_HISTORY_BARS` | `400` | candles cached per refresh |
| `MT5WEB_PUBLIC_URL` / `RENDER_EXTERNAL_URL` | — | used to print the agent's WS URL |

---

## 8. Tests

```bash
pip install -r requirements-dev.txt
pytest tests/            # 50 unit/integration tests (crypto, gateway, algo maths, MQL5, API)
python tests/e2e_smoke.py  # boots the real server + a mock bridge agent and walks the whole
                           # flow: login → agent → candles → orders → SL/TP → modify/close →
                           # pending+cancel → backtest → live engine → EA compile/deploy →
                           # signal file → hybrid → kill switch → audit → reconnect
```

The e2e script uses `agents/mock_agent.py`, a deterministic simulator that speaks the same
agent protocol — it is also how you can demo the UI without a broker account. It is **not** a
trading mode: nothing in the app routes to it unless you start it yourself.

---

## 9. Risk notes

* Real money: an algo bug or a broker requote can cost you. Test with `max_lot: 0.01` and
  `risk_percent` small, and watch `Algo Studio → log` for the first bars.
* Reconnection is automatic, but an in-flight order can be lost between retries — that is why
  every order is logged with its retcode and why positions are re-synced on every tick.
* `data/*.json` contains encrypted credentials and the bridge key: never commit it
  (`.gitignore` already excludes it), and keep `MT5WEB_SECRET` out of git too.
* Render's free tier sleeps: the web app can sleep, but a **running EA on the terminal will keep
  trading**. That is exactly why the EA enforces `kill=1` from the signal file and the agent
  reconnects on its own.

---

## 10. বাংলা সংক্ষেপে

**আপনার প্রশ্ন:** MetaTrader 5 কি Render-এর ভেতরে ইনস্টল করে ব্রাউজার থেকে চালা যাবে?

**উত্তর (যাচাই করা):** না — `MetaTrader5` python প্যাকেজটি শুধুই Windows-এর জন্য (`win_amd64`
wheels), আর MetaQuotes-এর "Linux installer" আসলে একটা Wine bootstrap: ওই স্ক্রিপ্ট
`winehq-staging` ইনস্টল করে, `~/.mt5` prefix বানায়, তারপর উইন্ডোজের `mt5setup.exe` উইজার্ড
চালায় (sudo, ডেস্কটপ, রিবুট লাগে)। Linux-এ MT5-এর নেটিভ বিল্ড নেই, তাই Render-এর সাধারণ
web service-এ টার্মিনাল চালানো যাবে না।

**তাই তৈরি করা হয়েছে এই আর্কিটেকচার:** Render-এ (বা যেকোনো Linux-এ) FastAPI web console, আর
আপনার Windows PC / VPS-এ একটা ছোট **Bridge agent** যে MT5 কলগুলো চালায়। দুটোর মাঝে একটাই
আউটবাউন্ড WebSocket, আপনার মেশিনে কোনো পোর্ট খোলা লাগে না। ব্রিজে কী কী আছে:

* কারেন্সি/সিম্বল সিলেক্ট, MT5 **login + password + server** দিয়ে লগইন (পাসওয়ার্ড এনক্রিপ্ট করে রাখা হয়, কারও কাছে ফেরত দেওয়া হয় না);
* অ্যালগোর স্ক্রিপ্ট ব্রাউজারেই লেখা/সম্পাদনা করা — স্যান্ডবক্সড python ইঞ্জিন (`init`/`on_bar`), ইন্ডিকেটর হেল্পার, রিয়েল ক্যান্ডেলসে ব্যাকটেস্ট;
* **Start / Stop** বাটন, প্রতিটি অ্যালগোর জন্য আলাদা `max_open_positions`, ডেইলি-লস লিমিট, ট্রেইলিং স্টপ;
* বাজার অর্ডার + ৪ ধরনের পেন্ডিং অর্ডার, SL/TP পয়েন্টে বা প্রাইসে, লট ক্যালকুলেটর, পজিশন ক্লোজ/মডিফাই, ডিল হিস্ট্রি;
* চাইলে **MQL5 Expert Advisor জেনারেট** — agent ফাইল লিখে MetaEditor দিয়ে কম্পাইল করে, অথবা **hybrid** মোড (python সিগন্যাল দেয়, EA টার্মিনালের ভেতরে এক্সিকিউট করে);
* **Kill Switch** (এক ক্লিকে সব অর্ডার বন্ধ), অডিট লগ, টার্মিনালের লাইভ লগ।

**নিজস্ব Linux মেশিনে চালাতে:** `bash agents/setup-mt5-wine.sh --run` (Wine 11.x + MT5 +
headless Xvfb স্ক্রিপ্ট), তারপর agent-টি Wine-এর উইন্ডোজ python দিয়ে চালান
(`wine "C:\python312\python.exe" "C:\agent\main.py" --url wss://… --key …`)। Docker-এ
`--build-arg WITH_MT5=1` দিলে এই স্তরটা ইমেজেই বেসে যায়।

**সতর্কতা:** এটি সরাসরি **লাইভ অ্যাকাউন্টে** অর্ডার পাঠায় (আপনিই ডেমো মোড বাদ দিয়েছেন)। প্রথমে
`max_lot` 0.01 রাখুন, Kill Switch হাতের কাছে রাখুন, আর RSI/EMA ক্রসের মতো সহজ স্ট্র্যাটেজি
দিয়ে ১ দিন পর্যবেক্ষণ করুন। বিস্তারিত ইংরেজি ডকুমেন্টেশন উপরের সেকশন ১–৯-এ।

---

## 11. Repo map

```
app.py                  # uvicorn entry: from mt5web.main import app
run.py                  # dev launcher (prints whether MetaTrader5 imports)
render.yaml             # Render blueprint (health check, envs, docker variant commented)
Dockerfile              # slim control plane (+ opt-in Wine/MT5 layer)
requirements*.txt        # base / windows (+MetaTrader5) / dev
mt5web/
  main.py               # all routes, WS endpoints, static mount
  config.py store.py auth.py crypto.py    # env, atomic JSON store, passcode+tokens, AES+HMAC
  gateway.py hub.py broker.py market.py   # MT5 transport, agent hub, trading layer, quotes loop
  algo.py backtest.py MQL5.py             # sandboxed engine, backtester, EA generator
  static/               # the whole UI (index.html + app.css + 5 js files)
agents/
  agent/main.py         # the bridge agent (Windows or Wine)
  mock_agent.py         # deterministic simulator speaking the same protocol
  setup-mt5-wine.sh     # Linux: Wine 11.x + MT5 + Xvfb + optional python-in-Wine
  install-mt5.ps1 start-agent.bat requirements.txt README.md
examples/*.py           # three ready-to-paste strategies
tests/                  # 50 pytest tests + e2e_smoke.py (real server + mock agent)
```
