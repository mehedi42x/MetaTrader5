# Bridge agent (`agents/`)

Everything in this folder runs **next to MetaTrader 5** — never inside the web service.
The web app is only a control plane: it sends RPC requests over one outbound WebSocket and the
agent executes them with the `MetaTrader5` python package.

| file | what it is |
| --- | --- |
| `agent/main.py` | the agent itself (python 3.9–3.12, needs 64-bit) |
| `agent/requirements.txt` | `MetaTrader5` (win32 only) + `websockets` |
| `agent/agent.json` | optional config file (created by the app, or write your own) |
| `start-agent.bat` | Windows launcher: creates a venv, installs deps, keeps the agent running |
| `install-mt5.ps1` | silently downloads + installs MetaTrader 5 on Windows |
| `setup-mt5-wine.sh` | Linux helper: Wine 11.x + MT5 + Xvfb + Windows python inside Wine |
| `mock_agent.py` | deterministic simulator speaking the same protocol (no broker needed) |

## Windows (recommended)

```bat
cd mt5-bridge-agent
py -3.11 -m venv .venv && .venv\Scripts\activate
pip install -r agent\requirements.txt
python agent\main.py --url wss://YOUR-APP.onrender.com/ws/agent --key YOUR-BRIDGE-KEY --name my-pc
```

or just edit the two `set` lines in `start-agent.bat` and double-click it (put a shortcut in
`shell:startup` to survive reboots).

Flags / config keys (CLI wins over env, env wins over `agent.json`):

```
--url                wss://host/ws/agent          (MT5WEB_URL)
--key                bridge key from the app      (MT5WEB_BRIDGE_KEY / MT5WEB_KEY)
--name               label shown in the Bridge tab(MT5WEB_NAME)
--terminal-path      C:\...\terminal64.exe        (MT5_TERMINAL_PATH, empty = auto-detect)
--install-mt5        download + install MT5 if missing
--verbose            log every RPC
agent.json: {"portable": true, "auto_start_terminal": true, "log_tail_seconds": 5,
             "insecure_tls": false, "max_rpc_concurrency": 4, "mt5_download_url": "..."}
```

Before trading: in MetaTrader 5 enable **Tools → Options → Expert Advisors → Allow
algorithmic trading** (and keep "req... mode for market executions" aligned with your broker —
the app asks the terminal for the symbol's filling mode and picks FOK/IOC/RETURN).

## Linux (MT5 under Wine)

Verified from MetaQuotes' own material: their `mt5linux.sh` only bootstraps Wine
(`winehq-staging`, `~/.mt5` prefix, WebView2, the Windows `mt5setup.exe` wizard, then a reboot).
`setup-mt5-wine.sh` wraps that and adds the headless bits:

```bash
bash agents/setup-mt5-wine.sh --status        # what is present/missing
bash agents/setup-mt5-wine.sh                 # Wine 11.x + MT5 (interactive wizard part)
bash agents/setup-mt5-wine.sh --run --wine-python --portable   # + python-in-Wine, headless starter
```

It writes `~/start-mt5-headless.sh`, which runs

```bash
xvfb-run -a wine ~/.mt5/drive_c/Program Files/MetaTrader 5/terminal64.exe /config:mt5web.ini
```

Then the agent must run with **Wine's Windows python** (the `MetaTrader5` package has no Linux
build):

```bash
wine "C:\\python312\\python.exe" "C:\\agent\\main.py" --url wss://YOUR-APP/ws/agent --key YOUR-KEY
```

Use Wine **11.x** (MetaQuotes report 10.0 and 11.0 are broken), pass `--no-sudo` when running
as root inside a container, and expect the first run to need a desktop for the installer wizard
(`--no-official` skips MetaQuotes' bootstrap if Wine is already set up).

## `mock_agent.py` (demo / CI)

Same protocol, same RPC names, but backed by a deterministic random-walk simulator: it opens
positions, honours SL/TP, keeps deals, and emulates `MQL5\Files` + MetaEditor compilation on disk
(under `agents/.mock_mt5_data/`). It also exposes a `MetaTrader5` façade, so `InProcessGateway`
can be pointed at it.

```bash
python agents/mock_agent.py --url ws://127.0.0.1:8000/ws/agent --key <bridge key> --name mock
```

`tests/e2e_smoke.py` starts a real uvicorn + this mock and walks the whole flow (login, agent
register, candles, market order with SL/TP, modify, close, pending+cancel, backtest, live
engine, EA compile/deploy, signal file, hybrid engine, kill switch, audit, reconnect).

## Protocol (v1)

```
connect        GET /ws/agent?key=<bridge key>          (401/1008 on a bad key)
agent → app    {"t":"hello","name":..,"os":..,"python":..,"mt5_available":true,
                "mt5_version":..,"data_folder":..,"initialized":bool,"agent_version":1}
app → agent    {"t":"rpc","id":123,"method":"order_send","params":{...}}
agent → app    {"t":"rpc_result","id":123,"ok":true,"result":...}
                {"t":"rpc_result","id":123,"ok":false,"error":"...","code":10004}
agent → app    {"t":"event","kind":"mt5log","lines":[...]}
app → agent    {"t":"cmd","action":"subscribe"|"resync"|"ping"}
```

`method` is checked against a whitelist (`MAX_RPC` in `mt5web/hub.py`): MT5 reads
(`account_info`, `symbol_*`, `ticks_*`, `copy_rates_*`, `copy_ticks_*`, `positions_get`,
`orders_get`, `history_*`, `market_book_*`), trading (`order_send`, `initialize`, `shutdown`,
`last_error`), terminal (`terminal_info`, `terminal_*`), file/EA helpers (`fs_write`, `fs_read`,
`fs_list`, `fs_delete`, `file_exists`, `terminal_compile`, `prepare_ini`, `tail_logs`) and
`mt5_status`. Anything else is refused before it reaches your machine.

## Troubleshooting

| symptom | fix |
| --- | --- |
| `401` / socket closes instantly | wrong `--key`; rotate it in the Bridge tab and restart the agent |
| `MT5 package: MISSING` in the Bridge panel | you installed deps in the wrong interpreter — `python -m pip install MetaTrader5` inside `.venv`, 64-bit python |
| `initialize() failed (code -2 / 5200)` | wrong login/password/server, or the terminal is not allowed to reach that broker server |
| EA deploys but never trades | "Allow algorithmic trading" off; or the `.ex5` was compiled outside `MQL5\Experts` (the agent always writes there) |
| `metaeditor64.exe not found` | install MT5 fully (the web installer also installs MetaEditor), or set `--terminal-path` |
| Wine: black screen / installer aborts | needs a display — run the setup script on a desktop session, only the *start* can be headless (Xvfb) |
| agent dies when you log out | use `start-agent.bat` + `shell:startup`, or a scheduled task / `systemd --user` service |
