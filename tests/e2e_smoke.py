"""End-to-end smoke test: real uvicorn server + the mock MT5 agent over WebSocket.

Everything the dashboard does is exercised for real here:
  bridge handshake -> account login -> quotes/candles -> market data ->
  order submission -> positions/SL-TP -> risk sizing -> algo engine running live ->
  MQL5 EA generation, compile (against the mock compiler) and signal-file push.

Run:  python tests/e2e_smoke.py      (exit 0 = pass)
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
PASSCODE = "e2e-pass-123"
BRIDGE_KEY = "e2e-bridge-key-0001"
HDR: dict[str, str] = {}


def logs_tail(client, algo_id: str, lines: int = 40) -> list[dict]:
    try:
        return client.get(f"/api/algos/{algo_id}/log?lines={lines}", headers=HDR).json().get("lines", [])
    except Exception:  # noqa: BLE001
        return []


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url: str, timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=2.0).status_code == 200:
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.4)
    return False


class Step:
    def __init__(self, name: str) -> None:
        self.name = name

    def __enter__(self):
        print(f"  -> {self.name} ... ", end="", flush=True)
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            print("ok")
            return False
        print(f"FAIL\n     {exc_type.__name__}: {exc}")
        return False  # propagate


def main() -> int:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "MT5WEB_DATA": str(ROOT / "data" / "e2e"),
        "MT5WEB_PASSCODE": PASSCODE,
        "MT5WEB_BRIDGE_KEY": BRIDGE_KEY,
        "MT5WEB_SECRET": "e2e-secret-0123456789abcdef",
        "MT5WEB_TICK_INTERVAL": "1",
        "PYTHONPATH": str(ROOT),
    }
    import shutil

    shutil.rmtree(ROOT / "data" / "e2e", ignore_errors=True)
    shutil.rmtree(ROOT / "agents" / ".mock_mt5_data", ignore_errors=True)
    (ROOT / "data" / "e2e" / "runtime").mkdir(parents=True, exist_ok=True)
    (ROOT / "agents" / ".mock_mt5_data" / "terminal" / "MQL5" / "Experts").mkdir(parents=True, exist_ok=True)

    print(f"[e2e] starting server on {base}")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT,
        env=env,
        stdout=open(ROOT / "data" / "e2e-server.log", "wb"),
        stderr=subprocess.STDOUT,
    )
    agent = None
    failures: list[str] = []

    def check(label: str, fn):
        try:
            with Step(label):
                fn()
        except AssertionError as exc:
            failures.append(f"{label}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{label}: {exc.__class__.__name__}: {exc}")

    try:
        assert wait_for(f"{base}/api/health"), "server never became healthy"

        # ---------------------------------------------------------------- agent
        print("[e2e] connecting the mock bridge agent")
        agent = subprocess.Popen(
            [sys.executable, "agents/mock_agent.py", "--url", f"ws://127.0.0.1:{port}/ws/agent",
             "--key", BRIDGE_KEY, "--name", "e2e-mock"],
            cwd=ROOT, env=env, stdout=open(ROOT / "data" / "e2e-agent.log", "wb"), stderr=subprocess.STDOUT,
        )

        def agent_connected():
            deadline = time.time() + 30
            while time.time() < deadline:
                r = httpx.get(f"{base}/api/state", headers=HDR, timeout=5)
                if r.status_code == 200 and r.json()["agents"]:
                    return
                time.sleep(0.5)
            raise AssertionError("no agent registered within 30s")

        # ---------------------------------------------------------------- login
        c = httpx.Client(base_url=base, timeout=30)

        def login():
            r = c.post("/api/auth/login", json={"passcode": PASSCODE})
            assert r.status_code == 200, r.text
            HDR["Authorization"] = "Bearer " + r.json()["token"]
            # also let the server authenticate our raw httpx calls by query token
            c.headers.update({"Authorization": HDR["Authorization"]})

        check("login with the configured passcode", login)
        check("mock agent connects over the bridge websocket", agent_connected)

        def bind_account():
            r = c.post(
                "/api/accounts",
                json={"name": "E2E demo", "server": "Mock-Demo01", "login": 7788990, "password": "demo-pass", "make_default": True},
                headers=HDR,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["connected"], body.get("error")
            assert body["info"]["login"] == 7788990
            assert body["info"]["balance"] == 10000.0

        check("bind MT5 account (login/password/server) via the agent", bind_account)

        def symbols():
            r = c.post("/api/symbols", json={"symbols": ["EURUSD", "XAUUSD", "BTCUSD"]}, headers=HDR)
            assert r.status_code == 200, r.text
            assert "EURUSD" in r.json()["symbols"]
            r2 = c.get("/api/symbols", headers=HDR)
            items = {s["name"]: s for s in r2.json()["items"]}
            assert items["EURUSD"]["source"] == "terminal", items["EURUSD"]
            assert items["XAUUSD"]["digits"] == 2, items["XAUUSD"]
            assert items["EURUSD"]["volume_min"] == 0.01

        check("read symbol metadata from the terminal", symbols)

        def rates_and_quotes():
            r = c.get("/api/market/rates?symbol=EURUSD&timeframe=M5&bars=120", headers=HDR)
            assert r.status_code == 200, r.text
            bars = r.json()["bars"]
            assert len(bars) >= 100, f"only {len(bars)} bars"
            assert bars == sorted(bars, key=lambda b: b["time"]), "bars are not time-ordered"
            for b in bars[-5:]:
                assert b["high"] >= max(b["open"], b["close"]) - 1e-9, b
                assert b["low"] <= min(b["open"], b["close"]) + 1e-9, b
            r2 = c.get("/api/market/quote?symbols=EURUSD,XAUUSD", headers=HDR)
            prices = r2.json()["prices"]
            assert "EURUSD" in prices and prices["EURUSD"]["ask"] > prices["EURUSD"]["bid"], prices

        check("fetch candles + live quotes", rates_and_quotes)

        def market_loop_is_live():
            deadline = time.time() + 25
            while time.time() < deadline:
                s = c.get("/api/state", headers=HDR).json()
                if s["market"]["price_symbols"] >= 1:
                    return
                time.sleep(1)
            raise AssertionError("the background market loop never produced any quote")

        check("background market loop streams quotes", market_loop_is_live)

        def risk_endpoint():
            r = c.get("/api/trade/risk?balance=10000&risk_percent=1&sl_points=250&symbol=EURUSD", headers=HDR)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["risk_money"] == 100.0
            assert 0 < body["suggested_lots"] < 100, body

        check("risk-based lot sizing", risk_endpoint)

        def manual_order():
            r = c.post(
                "/api/trade/order",
                json={"symbol": "EURUSD", "direction": "buy", "volume": 0.2, "sl_points": 300, "tp_points": 600, "comment": "e2e"},
                headers=HDR,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["ok"] and body["retcode"] == 10009, body
            assert body["sl"] and body["tp"], body
            assert body["sl"] < body["price"] < body["tp"], body  # buy: SL below, TP above
            state = c.get("/api/trade/state", headers=HDR).json()
            assert state["positions"], "order accepted but no position"
            pos = state["positions"][0]
            assert pos["volume"] == 0.2 and pos["type"] == "buy" and pos["comment"] == "e2e", pos
            globals()["POSITION_TICKET"] = pos["ticket"]

        check("place a market order with SL/TP", manual_order)

        def modify_and_close():
            ticket = globals().get("POSITION_TICKET")
            assert ticket, "no ticket from the previous step"
            # SL below and TP above the (long) entry price - both must be accepted
            r = c.post("/api/trade/modify", json={"ticket": ticket, "stop_loss": 1.05, "take_profit": 1.15}, headers=HDR)
            assert r.status_code == 200, r.text
            state = c.get("/api/trade/state", headers=HDR).json()
            pos = state["positions"][0]
            assert (pos["sl"], pos["tp"]) == (1.05, 1.15), pos
            r2 = c.post("/api/trade/close", json={"ticket": ticket}, headers=HDR)
            assert r2.status_code == 200, r2.text
            after = c.get("/api/trade/state", headers=HDR).json()
            assert not any(p["ticket"] == ticket for p in after["positions"]), after["positions"]

        check("modify SL/TP then close the position", modify_and_close)

        def buy_limit_flow():
            quote = c.get("/api/market/quote?symbols=XAUUSD", headers=HDR).json()["prices"]["XAUUSD"]
            far = round(quote["bid"] - 25.0, 2)
            r = c.post(
                "/api/trade/order",
                json={"symbol": "XAUUSD", "direction": "buy", "volume": 0.05, "order_type": "buy_limit", "price": far},
                headers=HDR,
            )
            assert r.status_code == 200, r.text
            state = c.get("/api/trade/state", headers=HDR).json()
            assert state["orders"], "pending order not visible in orders_get"
            assert state["orders"][0]["price_open"] == far, state["orders"][0]
            r2 = c.post("/api/trade/cancel-order", json={"ticket": state["orders"][0]["ticket"]}, headers=HDR)
            assert r2.status_code == 200, r2.text
            assert not c.get("/api/trade/state", headers=HDR).json()["orders"], "pending order survived cancel"

        check("pending order + cancellation", buy_limit_flow)

        def validation_errors():
            r = c.post("/api/trade/order", json={"symbol": "NOSUCH", "direction": "buy", "volume": 0.1}, headers=HDR)
            assert r.status_code == 400, r.text
            assert "unknown symbol" in r.json()["detail"].lower(), r.json()

            # an SL on the wrong side of the market is refused before it reaches the broker:
            # for a SELL the stop must sit *above* entry, so 1.00 is nonsensical
            wrong = c.post(
                "/api/trade/order",
                json={"symbol": "EURUSD", "direction": "sell", "volume": 0.01,
                      "stop_loss": 1.0, "take_profit": 0.95},
                headers=HDR,
            )
            assert wrong.status_code == 400, wrong.text
            assert "stop" in wrong.json()["detail"].lower(), wrong.json()
            # ...while the same levels computed as "100 points away" are valid
            ok_side = c.post(
                "/api/trade/order",
                json={"symbol": "EURUSD", "direction": "sell", "volume": 0.01,
                      "sl_points": 100, "tp_points": 200},
                headers=HDR,
            )
            assert ok_side.status_code == 200, ok_side.text

            flat = c.get("/api/trade/state", headers=HDR).json()["positions"]
            for p in flat:
                c.post("/api/trade/close", json={"ticket": p["ticket"]}, headers=HDR)

            c.post("/api/settings", json={"max_lot": 0.5}, headers=HDR)
            big = c.post("/api/trade/order", json={"symbol": "EURUSD", "direction": "buy", "volume": 25}, headers=HDR)
            assert big.status_code == 200, big.text
            assert abs(big.json()["volume"] - 0.5) < 1e-9, big.json()["volume"]  # clamped, never rejected
            held = c.get("/api/trade/state", headers=HDR).json()["positions"]
            assert [p["volume"] for p in held] == [0.5], held
            for p in held:
                c.post("/api/trade/close", json={"ticket": p["ticket"]}, headers=HDR)
            c.post("/api/settings", json={"max_lot": 5}, headers=HDR)

        check("bad symbols and oversized lots are rejected", validation_errors)

        def history():
            r = c.get("/api/trade/history?days=7", headers=HDR)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["deals"], "expected at least one deal"
            assert body["summary"]["deals"] >= 1

        check("deal history + summary", history)

        # ---------------------------------------------------------------- algo
        def create_algo():
            src = (
                "def init(ctx):\n"
                "    ctx.log('e2e strategy ready')\n"
                "    ctx.p['once'] = True\n"
                "def on_bar(ctx, bars, i):\n"
                "    if ctx.position is None and ctx.p.get('once'):\n"
                "        ctx.p['once'] = False\n"
                "        return {'action': 'buy', 'reason': 'one-shot e2e signal'}\n"
                "    return None\n"
            )
            r = c.post(
                "/api/algos",
                json={
                    "name": "E2E Runner", "engine": "python", "symbol": "EURUSD", "timeframe": "M5",
                    "volume": 0.03, "stop_loss_points": 200, "take_profit_points": 400, "magic": 777, "source": src,
                },
                headers=HDR,
            )
            assert r.status_code == 200, r.text
            globals()["ALGO_ID"] = r.json()["id"]
            assert r.json()["has_source"]

        check("create a python algo", create_algo)

        def backtest():
            r = c.post(f"/api/algos/{globals()['ALGO_ID']}/backtest?bars=300", headers=HDR)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["bars"] >= 200, body["bars"]
            assert body["trade_count"] >= 1, f"expected the one-shot strategy to trade once, got {body}"
            assert body["trade_count"] == 1, f"one-shot strategy traded {body['trade_count']} times"
            assert body["equity_curve"], body
            assert body["errors"] == 0, body.get("first_error")

        check("backtest the strategy on real candles", backtest)

        def live_algo():
            r = c.post(
                f"/api/algos/{globals()['ALGO_ID']}/run",
                json={"lookback_bars": 250, "replay": True, "trade_on_replay": True},
                headers=HDR,
            )
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "running", r.json()
            deadline = time.time() + 40
            seen_order = False
            while time.time() < deadline:
                state = c.get("/api/trade/state", headers=HDR).json()
                mine = [p for p in state["positions"] if p["magic"] == 777]
                a = c.get(f"/api/algos/{globals()['ALGO_ID']}", headers=HDR).json()
                if mine or (a.get("stats") or {}).get("orders"):
                    seen_order = True
                    break
                time.sleep(1.5)
            if not seen_order:
                a = c.get(f"/api/algos/{globals()['ALGO_ID']}", headers=HDR).json()
                lg = logs_tail(c, globals()["ALGO_ID"])
                raise AssertionError(
                    f"no live order; status={a.get('status')} error={a.get('error')} "
                    f"stats={a.get('stats')} logs={[l['text'] for l in lg][-6:]}"
                )
            logs = c.get(f"/api/algos/{globals()['ALGO_ID']}/log", headers=HDR).json()["lines"]
            assert any("e2e strategy ready" in l["text"] for l in logs), logs[:3]
            assert any("BUY" in l["text"] for l in logs if l["level"] == "trade"), [l["text"] for l in logs][-5:]
            pos = [p for p in c.get("/api/trade/state", headers=HDR).json()["positions"] if p["magic"] == 777]
            assert pos and pos[0]["sl"] and pos[0]["tp"], pos
            globals()["ALGO_TICKET"] = pos[0]["ticket"]

        check("run the engine live (bar signal -> real order -> position)", live_algo)

        def stop_algo():
            r = c.post(f"/api/algos/{globals()['ALGO_ID']}/stop", headers=HDR)
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "stopped"
            # clean up the algo position so later assertions start from flat
            c.post("/api/trade/close", json={"ticket": globals()["ALGO_TICKET"]}, headers=HDR)

        check("stop the engine and clean up", stop_algo)

        # ------------------------------------------------------------------ EA
        def deploy_ea():
            r = c.post(
                "/api/algos",
                json={"name": "E2E Hybrid", "engine": "hybrid", "symbol": "GBPUSD", "timeframe": "M15",
                      "volume": 0.02, "stop_loss_points": 250, "magic": 9911},
                headers=HDR,
            )
            assert r.status_code == 200, r.text
            aid = r.json()["id"]
            globals()["HYBRID_ID"] = aid
            d = c.post(f"/api/algos/{aid}/deploy", headers=HDR)
            assert d.status_code == 200, d.text
            body = d.json()
            assert body["compiled"] is True, body
            assert body["errors"] == 0, body
            assert "MQL5/Experts/MT5Web_E2E_Hybrid.mq5" in body["mq5_path"], body["mq5_path"]
            assert body["ex5_exists"] is True, body  # mock compiler really wrote a .ex5
            # the file really landed on the (mock) terminal data folder
            local = ROOT / "agents" / ".mock_mt5_data" / "terminal" / "MQL5" / "Experts" / "MT5Web_E2E_Hybrid.mq5"
            assert local.exists(), f"{local} was never written"
            assert "OnTick" in local.read_text()

        check("generate + compile + deploy an Expert Advisor through the agent", deploy_ea)

        def ea_signal_file():
            r = c.post(f"/api/algos/{globals()['HYBRID_ID']}/signal", json={"action": "buy"}, headers=HDR)
            assert r.status_code == 200, r.text
            target = ROOT / "agents" / ".mock_mt5_data" / "terminal" / "MQL5" / "Files" / "MT5Web_E2E_Hybrid.txt"
            deadline = time.time() + 10
            while time.time() < deadline and not target.exists():
                time.sleep(0.3)
            assert target.exists(), "signal file was not written into the MQL5 Files sandbox"
            text = target.read_text()
            assert "signal=" in text and "sl_points=250" in text, text

        check("push the signal file the EA reads", ea_signal_file)

        def run_hybrid():
            r = c.post(f"/api/algos/{globals()['HYBRID_ID']}/run", json={"lookback_bars": 200, "replay": False}, headers=HDR)
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "running", r.json()
            logs = c.get(f"/api/algos/{globals()['HYBRID_ID']}/log", headers=HDR).json()["lines"]
            assert any("deploying Expert Advisor" in l["text"] for l in logs), logs
            c.post(f"/api/algos/{globals()['HYBRID_ID']}/stop", headers=HDR)

        check("start/stop the hybrid (python -> EA) engine", run_hybrid)

        def mt5_log_tail():
            r = c.get(f"/api/algos/{globals()['HYBRID_ID']}/mt5-log?lines=10", headers=HDR)
            assert r.status_code == 200, r.text
            assert isinstance(r.json()["lines"], list)

        check("tail terminal logs from the agent", mt5_log_tail)

        # ------------------------------------------------------------ guards
        def kill_switch_blocks_everything():
            c.post("/api/settings", json={"kill_switch": True}, headers=HDR)
            r = c.post("/api/trade/order", json={"symbol": "EURUSD", "direction": "buy", "volume": 0.01}, headers=HDR)
            assert r.status_code == 400 and "kill" in r.json()["detail"].lower(), r.json()
            r2 = c.post(f"/api/algos/{globals()['ALGO_ID']}/run", json={}, headers=HDR)
            assert r2.status_code == 409, r2.json()
            c.post("/api/settings", json={"kill_switch": False}, headers=HDR)
            assert c.post("/api/trade/order", json={"symbol": "EURUSD", "direction": "buy", "volume": 0.01}, headers=HDR).status_code == 200

        check("kill switch blocks orders and algo starts", kill_switch_blocks_everything)

        def bridge_panel_data():
            b = c.get("/api/bridge", headers=HDR).json()
            assert b["agents"] and b["agents"][0]["name"] == "e2e-mock", b["agents"]
            assert b["agents"][0]["rpc_count"] > 5
            assert "onrender" in b["install_snippets"]["run"] or "/ws/agent" in b["install_snippets"]["run"]
            a = c.get("/api/bridge/audit", headers=HDR).json()["items"]
            known = {
                "order.send", "order.remove", "account.save", "account.connect", "account.disconnect",
                "algo.create", "algo.update", "algo.delete", "algo.start", "algo.stop", "algo.ea",
                "settings.kill_switch", "settings.update", "position.close", "position.modify", "auth.passcode",
            }
            assert a and {row["action"] for row in a} <= known, [r["action"] for r in a[:8]]

        check("bridge status + audit trail", bridge_panel_data)

        def disconnect_flows():
            r = c.post("/api/accounts/disconnect", headers=HDR)
            assert r.status_code == 200, r.text
            assert c.get("/api/state", headers=HDR).json()["accounts"][0]["status"] == "disconnected"
            r2 = c.post("/api/accounts/connect", headers=HDR)
            assert r2.status_code == 200, r2.text
            assert r2.json()["ok"]

        check("disconnect / reconnect the terminal session", disconnect_flows)
    finally:
        for proc in (server, agent):
            if proc and proc.poll() is None:
                proc.terminate()
        for proc in (server, agent):
            if proc:
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()

    print()
    if failures:
        print(f"[e2e] FAILED {len(failures)} step(s):")
        for f in failures:
            print("   -", f)
        for name in ("e2e-server.log", "e2e-agent.log"):
            log = ROOT / "data" / name
            if log.exists():
                print(f"----- tail {name} -----")
                print("\n".join(log.read_text(errors="replace").splitlines()[-25:]))
        return 1
    print("[e2e] ALL STEPS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
