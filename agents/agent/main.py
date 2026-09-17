"""MT5 Web Console - Bridge Agent (run this on the Windows machine).

Why this exists
---------------
The ``MetaTrader5`` python package is Windows-only (MetaQuotes publish no Linux
wheel), so a service hosted on Render (Ubuntu) cannot import it. This agent runs
next to your MetaTrader 5 terminal, executes the whitelisted MT5 calls the web
app asks for, and streams the answers back over one outbound WebSocket - no
inbound ports, no firewall changes.

Usage
-----
    python -m pip install -r requirements.txt
    python main.py --url https://your-app.onrender.com/ws/agent --key <bridge key>

or drop a ``agent.json`` next to this file:

    {"url": "wss://your-app.onrender.com/ws/agent", "key": "abcd", "name": "home-pc"}

Environment variables ``MT5WEB_URL`` / ``MT5WEB_KEY`` / ``MT5WEB_NAME`` win over
the file. Add ``--install-mt5`` to download and silently install MetaTrader 5
first (useful on a fresh Windows VPS).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

AGENT_VERSION = "1.0.0"
MT5_DEFAULT_DOWNLOAD = "https://download.mql5.com/cdn/web/metaquotes.ltd/mt5/metaquotes5setup.exe"

try:
    import MetaTrader5 as mt5  # type: ignore
except Exception:  # noqa: BLE001 - the whole point: the package may be missing
    mt5 = None

log = logging.getLogger("mt5.agent")
HERE = Path(__file__).resolve().parent


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #


class Config:
    def __init__(self) -> None:
        file_cfg = {}
        cfg_path = HERE / "agent.json"
        if cfg_path.exists():
            try:
                file_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                print(f"[agent] ignoring malformed agent.json: {exc}")
        self.url = os.getenv("MT5WEB_URL") or file_cfg.get("url") or ""
        self.key = os.getenv("MT5WEB_KEY") or file_cfg.get("key") or ""
        self.name = os.getenv("MT5WEB_NAME") or file_cfg.get("name") or os.getenv("COMPUTERNAME", "mt5-agent")
        self.terminal_path = file_cfg.get("terminal_path") or os.getenv("MT5_TERMINAL_PATH") or None
        self.install_mt5 = bool(file_cfg.get("install_mt5")) or "--install-mt5" in sys.argv
        self.mt5_download_url = file_cfg.get("mt5_download_url") or MT5_DEFAULT_DOWNLOAD
        self.auto_start_terminal = bool(file_cfg.get("auto_start_terminal", True))
        self.log_tail_seconds = float(file_cfg.get("log_tail_seconds", 5))
        self.insecure_tls = bool(file_cfg.get("insecure_tls", False))
        self.max_rpc_concurrency = int(file_cfg.get("max_rpc_concurrency", 4))

    def apply_args(self, args: argparse.Namespace) -> None:
        self.url = args.url or self.url
        self.key = args.key or self.key
        self.name = args.name or self.name
        self.terminal_path = args.terminal_path or self.terminal_path
        self.install_mt5 = args.install_mt5 or self.install_mt5


# --------------------------------------------------------------------------- #
# MT5 wrapper
# --------------------------------------------------------------------------- #

MT_OK_RE = re.compile(r"(\d+)\s*error", re.I)


class MT5Bridge:
    """Thin, whitelist-only wrapper around the MetaTrader5 package."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.initialized: dict[str, Any] | None = None
        self._sem = asyncio.Semaphore(cfg.max_rpc_concurrency)

    # ---- helpers ------------------------------------------------------ #
    def _require(self) -> Any:
        if mt5 is None:
            raise RuntimeError(
                "The MetaTrader5 python package is not installed in this environment. "
                "Run: python -m pip install MetaTrader5 (Windows, 64-bit Python 3.7+)"
            )
        return mt5

    def find_terminal(self) -> str | None:
        candidates = [self.cfg.terminal_path] if self.cfg.terminal_path else []
        candidates += [
            r"C:\Program Files\MetaTrader 5\terminal64.exe",
            r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe",
        ]
        root = Path(os.getenv("ProgramFiles", r"C:\Program Files"))
        if root.exists():
            candidates += [str(p / "terminal64.exe") for p in root.glob("MetaTrader*") if p.is_dir()]
        for cand in candidates:
            if cand and Path(cand).exists():
                return str(cand)
        return None

    def data_folder(self) -> str:
        try:
            self._require()
            path = mt5.terminal_path()  # type: ignore[union-attr]
            if path:
                return str(Path(path).parent)
        except Exception:  # noqa: BLE001
            pass
        term = self.find_terminal()
        if term:
            return str(Path(term).parent)
        appdata = os.getenv("APPDATA", "")
        if appdata:
            found = sorted(Path(appdata).glob("MetaQuotes/Terminal/*"))
            if found:
                return str(found[-1])
        raise RuntimeError("MetaTrader 5 installation not found on this machine")

    # ---- RPC dispatch -------------------------------------------------- #
    async def handle(self, method: str, params: dict) -> Any:
        async with self._sem:
            return await asyncio.to_thread(self._sync_handle, method, params)

    def _sync_handle(self, method: str, params: dict) -> Any:  # noqa: C901 - flat RPC table
        if method == "ping":
            return {"pong": time.time()}
        if method == "mt5_status":
            return {
                "package_installed": mt5 is not None,
                "terminal_path": self.find_terminal(),
                "data_folder": None,
                "initialized": self.initialized,
                "version": getattr(mt5, "__version__", None) if mt5 else None,
            }
        if method == "initialize":
            return self._initialize(params)
        if method == "shutdown":
            if mt5 is not None:
                mt5.shutdown()  # type: ignore[union-attr]
            self.initialized = None
            return {"ok": True}
        if method in ("fs_write", "fs_read", "fs_list", "fs_delete", "file_exists", "terminal_compile", "prepare_ini", "tail_logs"):
            return getattr(self, "_" + method)(params)

        fn = getattr(mt5, method, None) if mt5 is not None else None
        if fn is None:
            raise RuntimeError(f"MetaTrader5.{method}() is not callable here (package missing or renamed)")
        kwargs = {k: v for k, v in params.items() if k not in ("account_id",)}
        result = fn(**kwargs)
        return unwrap(result)

    # ---- terminal / login ---------------------------------------------- #
    def _initialize(self, params: dict) -> dict:
        if mt5 is None:
            raise RuntimeError(
                "MetaTrader5 package missing - install it with: python -m pip install MetaTrader5"
            )
        kwargs: dict[str, Any] = {}
        path = params.get("path") or self.find_terminal()
        if path:
            kwargs["path"] = path
        if params.get("login"):
            kwargs["login"] = int(params["login"])
        if params.get("password"):
            kwargs["password"] = str(params["password"])
        if params.get("server"):
            kwargs["server"] = str(params["server"])
        kwargs["timeout"] = int(params.get("timeout_ms") or 60000)
        if params.get("portable"):
            kwargs["portable"] = True
        try:
            ok = bool(mt5.initialize(**kwargs))  # type: ignore[union-attr]
        except TypeError as exc:  # older builds: no 'path' kwarg? retry without
            kwargs.pop("path", None)
            ok = bool(mt5.initialize(**kwargs))  # type: ignore[union-attr]
            if not ok:
                raise RuntimeError(f"initialize() failed: {exc}") from exc
        if not ok:
            code, text = mt5.last_error()  # type: ignore[union-attr]
            return {"ok": False, "code": code, "error": f"{text} (code {code})", "terminal_path": path}
        self.initialized = {
            "login": kwargs.get("login"),
            "server": kwargs.get("server"),
            "at": time.time(),
            "terminal_path": path,
        }
        info = unwrap(mt5.terminal_info()) or {}  # type: ignore[union-attr]
        return {
            "ok": True,
            "terminal": info,
            "data_folder": Path(info.get("data_path", ".")).name if info else None,
            "build": info.get("build"),
        }

    # ---- files ---------------------------------------------------------- #
    def _resolve(self, params: dict) -> Path:
        """Resolve a path inside the terminal folders.

        ``mode`` picks the base folder:
          data        -> terminal install/data folder (MQL5/, Logs/, ...)
          filesandbox -> <data>/MQL5/Files (the MQL5 sandbox an EA can read/write)
        Absolute paths are accepted as-is: the agent intentionally trusts the
        holder of the bridge key (that key already grants order execution).
        """
        raw = str(params.get("path") or "").strip()
        if not raw:
            raise RuntimeError("path is required")
        base = Path(self.data_folder())
        if params.get("mode") == "filesandbox":
            base = base / "MQL5" / "Files"
        target = (Path(raw) if Path(raw).is_absolute() else base / raw.lstrip("\\/")).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def _fs_write(self, params: dict) -> dict:
        target = self._resolve(params)
        target.parent.mkdir(parents=True, exist_ok=True)
        content = params.get("content", "")
        if params.get("b64"):
            data = base64.b64decode(content)
        else:
            data = str(content).encode("utf-8")
        if len(data) > 8 * 1024 * 1024:
            raise RuntimeError("refusing to write more than 8 MB")
        target.write_bytes(data)
        return {"ok": True, "absolute": str(target), "bytes": len(data), "mtime": target.stat().st_mtime}

    def _fs_read(self, params: dict) -> dict:
        target = self._resolve(params)
        if not target.exists():
            return {"exists": False, "text": ""}
        if params.get("b64"):
            return {"exists": True, "b64": base64.b64encode(target.read_bytes()).decode()}
        raw = target.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:  # MT5 logs are UTF-16
                text = raw.decode("utf-16-le", errors="replace")
            except Exception:  # noqa: BLE001
                text = raw.decode("latin-1", errors="replace")
        return {"exists": True, "text": text[-400000:], "mtime": target.stat().st_mtime}

    def _file_exists(self, params: dict) -> dict:
        target = self._resolve(params)
        return {"exists": target.exists(), "absolute": str(target), "size": target.stat().st_size if target.exists() else 0}

    def _fs_list(self, params: dict) -> list[dict]:
        target = self._resolve(params)
        if not target.exists():
            return []
        rows = []
        for item in sorted(target.iterdir()):
            rows.append({"name": item.name, "size": item.stat().st_size, "mtime": item.stat().st_mtime, "dir": item.is_dir()})
        return rows[:500]

    def _fs_delete(self, params: dict) -> dict:
        target = self._resolve(params)
        existed = target.exists()
        if existed:
            target.unlink(missing_ok=True)
        return {"ok": True, "deleted": existed}

    # ---- MQL5 compiler --------------------------------------------------- #
    def _metaeditor(self) -> Path | None:
        base = Path(self.data_folder())
        for cand in (base / "metaeditor64.exe", base / "MetaEditor64.exe"):
            if cand.exists():
                return cand
        install = Path(getattr(self, "_install_dir", None) or self.data_folder())
        for name in ("metaeditor64.exe", "MetaEditor64.exe"):
            for parent in (install, install / "..", Path(self.find_terminal() or ".")):
                cand = Path(parent) / name
                if cand.exists():
                    return cand.resolve()
        return None

    def _terminal_compile(self, params: dict) -> dict:
        src = Path(params.get("path") or "")
        if not src.exists():
            src = self._resolve({"path": str(src), "mode": params.get("mode", "data")})
        editor = self._metaeditor()
        if editor is None:
            raise RuntimeError("metaeditor64.exe not found next to the terminal - is MetaTrader 5 fully installed?")
        log_path = src.with_suffix(".log")
        if log_path.exists():
            log_path.unlink()
        cmd = [str(editor), f"/compile:{src}", f"/log:{log_path}"]
        if params.get("inc"):
            cmd.append(f"/inc:{params['inc']}")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=int(params.get("timeout") or 120))  # noqa: S603
        text = ""
        if log_path.exists():
            raw = log_path.read_bytes()
            for enc in ("utf-16-le", "utf-8", "latin-1"):
                try:
                    text = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
        errors = int(MT_OK_RE.search(text or "").group(1)) if MT_OK_RE.search(text or "") else text.lower().count(": error")
        return {
            "ok": proc.returncode == 0 and errors == 0 and text != "",
            "returncode": proc.returncode,
            "log": str(log_path),
            "output": text[-4000:],
            "errors": errors,
            "source": str(src),
            "ex5": str(src.with_suffix(".ex5")),
            "ex5_exists": src.with_suffix(".ex5").exists(),
        }

    def _prepare_ini(self, params: dict) -> dict:
        """Write a terminal config .ini so the terminal can start already logged in."""
        ini = [
            "[Common]",
            f"Login={params.get('login', '')}",
            f"Password={params.get('password', '')}",
            f"Server={params.get('server', '')}",
            "AutoConfiguration=0",
            "ProxyEnable=0",
            "",
            "[Experts]",
            "AllowLiveTrading=1",
            "AllowDllImport=0",
            "Enabled=1",
            "Account=1",
            "Profile=1",
            "",
            "[Charts]",
            "MaxBars=2000000",
        ]
        if params.get("profile"):
            ini.insert(len(ini) - 1, f"ProfileLast={params['profile']}")
        target = Path(self.data_folder()) / f"mt5web_{params.get('name', 'agent')}.ini"
        target.write_text("\r\n".join(ini) + "\r\n", encoding="utf-8")
        term = self.find_terminal()
        return {
            "ok": True,
            "ini": str(target),
            "start_command": f'"{term}" /config:"{target}"' if term else None,
            "note": "starts the terminal already logged in with algo trading enabled",
        }

    # ---- log tailing ------------------------------------------------------ #
    _log_state: dict[str, int] = {}

    def _tail_logs(self, params: dict) -> dict:
        base = Path(self.data_folder())
        candidates = [base / "MQL5" / "Logs", base / "Logs"]
        want = str(params.get("filter") or "").lower()
        lines: list[dict] = []
        for folder in candidates:
            if not folder.exists():
                continue
            for log_file in sorted(folder.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:2]:
                try:
                    raw = log_file.read_bytes()
                except OSError:
                    continue
                for enc in ("utf-16-le", "utf-8", "latin-1"):
                    try:
                        text = raw.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    continue
                rows = [ln for ln in text.splitlines() if ln.strip()]
                if want:
                    rows = [ln for ln in rows if want in ln.lower()]
                for line in rows[-int(params.get("lines") or 100):]:
                    lines.append({"file": log_file.name, "line": line[:400]})
        return {"lines": lines[-1000:], "at": time.time()}


def unwrap(value: Any) -> Any:
    """numpy / namedtuple -> JSON-friendly structures."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {k: unwrap(v) for k, v in value.items() if not str(k).startswith("_")}
    if hasattr(value, "_asdict") and callable(getattr(value, "_asdict")):  # namedtuple (checked before the tuple branch)
        return {k: unwrap(v) for k, v in value._asdict().items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [unwrap(v) for v in value]
    if hasattr(value, "dtype") and hasattr(value, "__len__"):  # numpy structured array
        out = []
        names = list(getattr(value.dtype, "names", []) or [])
        for rec in value:
            if names:
                out.append({name: unwrap(rec[name]) for name in names if not name.startswith("_")})
            else:
                out.append(unwrap(list(rec)))
        return out
    if hasattr(value, "__dict__"):
        return {k: unwrap(v) for k, v in vars(value).items() if not k.startswith("_")}
    return value


# --------------------------------------------------------------------------- #
# MT5 installer (optional, for a bare Windows VPS)
# --------------------------------------------------------------------------- #


def install_mt5(url: str = MT5_DEFAULT_DOWNLOAD) -> bool:
    if shutil.which("curl") is None and sys.platform == "win32":
        pass
    dest = Path(os.getenv("TEMP", ".")) / "metaquotes5setup.exe"
    print(f"[agent] downloading MetaTrader 5 setup -> {dest}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (mt5-web-console)"})  # noqa: S310
        with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as fh:  # noqa: S310
            shutil.copyfileobj(resp, fh)
    except Exception as exc:  # noqa: BLE001
        print(f"[agent] download failed: {exc}")
        return False
    print("[agent] running silent install ...")
    proc = subprocess.run([str(dest), "/auto"], check=False, timeout=900)  # noqa: S603
    return proc.returncode in (0, 1, 3010)


# --------------------------------------------------------------------------- #
# connection loop
# --------------------------------------------------------------------------- #


async def connect_once(cfg: Config, bridge: MT5Bridge, stop: asyncio.Event) -> None:
    import websockets

    if not cfg.url or not cfg.key:
        raise SystemExit(
            "[agent] missing --url/--key (or MT5WEB_URL / MT5WEB_KEY). "
            "Copy both from the web app: Bridge tab -> 'Connection settings'."
        )
    print(f"[agent] connecting to {cfg.url} as '{cfg.name}' (MT5 package: {'yes' if mt5 else 'MISSING'})")
    ssl = None
    if cfg.url.startswith("wss://") and cfg.insecure_tls:
        import ssl as _ssl

        ssl = _ssl.create_default_context()
        ssl.check_hostname = False
        ssl.verify_mode = _ssl.CERT_NONE
    async with websockets.connect(cfg.url, ping_interval=20, ping_timeout=30, max_size=32_000_000, ssl=ssl) as ws:
        data_folder = None
        try:
            data_folder = bridge.data_folder()
        except Exception as exc:  # noqa: BLE001
            log.warning("data folder lookup failed: %s", exc)
        await ws.send(
            json.dumps(
                {
                    "t": "hello",
                    "name": cfg.name,
                    "agent_version": AGENT_VERSION,
                    "os": platform.system(),
                    "os_release": platform.release(),
                    "machine": platform.node(),
                    "python": platform.python_version(),
                    "mt5_available": mt5 is not None,
                    "mt5_version": getattr(mt5, "__version__", None) if mt5 else None,
                    "terminal_path": bridge.find_terminal(),
                    "data_folder": data_folder,
                    "initialized": bridge.initialized,
                }
            )
        )
        welcome = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
        print(f"[agent] handshake ok: {welcome.get('t')} agent_id={welcome.get('agent_id')}")

        async def worker() -> None:
            async for raw in ws:
                msg = json.loads(raw)
                kind = msg.get("t")
                if kind == "rpc":
                    rid = msg.get("id")
                    try:
                        result = await bridge.handle(msg.get("method", ""), msg.get("params") or {})
                        await ws.send(json.dumps({"t": "rpc_result", "id": rid, "result": unwrap(result)}, default=str))
                    except Exception as exc:  # noqa: BLE001
                        await ws.send(json.dumps({"t": "rpc_error", "id": rid, "error": f"{exc.__class__.__name__}: {exc}"}))
                elif kind == "cmd":
                    action = msg.get("action")
                    if action == "tail":
                        payload = bridge._tail_logs(msg.get("params") or {})  # noqa: SLF001
                        await ws.send(json.dumps({"t": "event", "event": "log", "payload": payload}, default=str))
                    elif action == "reinit":
                        res = bridge._initialize(msg.get("params") or {})  # noqa: SLF001
                        await ws.send(json.dumps({"t": "event", "event": "reinit", "payload": res}, default=str))

        async def log_pump() -> None:
            if cfg.log_tail_seconds <= 0:
                return
            while not stop.is_set():
                try:
                    payload = await asyncio.to_thread(bridge._tail_logs, {"lines": 40, "filter": ""})  # noqa: SLF001
                    if payload.get("lines"):
                        await ws.send(json.dumps({"t": "event", "event": "log", "payload": payload}, default=str))
                except Exception as exc:  # noqa: BLE001
                    log.debug("log pump: %s", exc)
                await asyncio.sleep(cfg.log_tail_seconds)

        tasks = [asyncio.create_task(worker()), asyncio.create_task(log_pump())]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()


async def run(cfg: Config) -> None:
    bridge = MT5Bridge(cfg)
    if cfg.install_mt5 and bridge.find_terminal() is None:
        ok = await asyncio.to_thread(install_mt5, cfg.mt5_download_url)
        print(f"[agent] MT5 install {'done' if ok else 'FAILED'}")
    stop = asyncio.Event()
    backoff = 2
    while not stop.is_set():
        try:
            await connect_once(cfg, bridge, stop)
            backoff = 2
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"[agent] connection lost: {exc.__class__.__name__}: {exc} (retry in {backoff}s)")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MT5 Web Console bridge agent")
    parser.add_argument("--url", default="", help="websocket url of the web app, e.g. wss://host/ws/agent")
    parser.add_argument("--key", default="", help="bridge key from the app's Bridge tab")
    parser.add_argument("--name", default="", help="label shown in the dashboard")
    parser.add_argument("--terminal-path", default="", help="full path to terminal64.exe (optional)")
    parser.add_argument("--install-mt5", action="store_true", help="download + silently install MetaTrader 5 if missing")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.DEBUG if "--verbose" in sys.argv else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config()
    cfg.apply_args(parse_args())
    try:
        asyncio.run(run(cfg))
    except KeyboardInterrupt:
        print("[agent] stopped")


if __name__ == "__main__":
    main()
