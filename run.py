#!/usr/bin/env python3
"""Dev launcher: python run.py [--port 8000] [--reload]

On Windows this same command gives you the app *and* direct MetaTrader5 access
(install with: pip install -r requirements-win.txt).
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1" if os.name == "nt" else "0.0.0.0")
    ap.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    ap.add_argument("--reload", action="store_true")
    ap.add_argument("--agents", default="1")
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT))
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        print("missing deps -> python -m pip install -r requirements.txt")
        return 1

    mt5 = importlib.util.find_spec("MetaTrader5") is not None
    print(f"MT5 Web Console  http://{'127.0.0.1' if args.host.startswith('0.0.0.0') else args.host}:{args.port}")
    print(f"  os={os.name}  MetaTrader5 package: {'importable (direct terminal access)' if mt5 else 'not available -> use the Bridge agent'}")
    if os.name != "nt" and not mt5:
        print("  tip: start the mock agent for development:\n"
              f"       python agents/mock_agent.py --url ws://127.0.0.1:{args.port}/ws/agent --key <key from the Bridge tab>")
    uvicorn.run(
        "app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=1 if args.reload else max(1, int(args.agents)),
        log_level=os.getenv("MT5WEB_LOG", "info"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
