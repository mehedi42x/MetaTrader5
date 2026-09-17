"""Runtime settings for the MT5 Web Console.

Everything is driven by environment variables so the same code runs on
Render (Linux, public URL) and on a local Windows machine next to the
MetaTrader 5 terminal.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings:
    """Lazy settings object (env vars can be set by the platform after import)."""

    APP_NAME = "MT5 Web Console"
    VERSION = "1.0.0"

    # --- storage ---------------------------------------------------------
    DATA_DIR = Path(os.getenv("MT5WEB_DATA", str(ROOT_DIR / "data")))
    RUNTIME_DIR = Path(os.getenv("MT5WEB_RUNTIME", str(DATA_DIR / "runtime")))
    STATIC_DIR = Path(__file__).resolve().parent / "static"
    TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

    # --- security --------------------------------------------------------
    SECRET_ENV = "MT5WEB_SECRET"
    PASSCODE_ENV = "MT5WEB_PASSCODE"
    BRIDGE_KEY_ENV = "MT5WEB_BRIDGE_KEY"

    # --- market ----------------------------------------------------------
    DEFAULT_SYMBOLS = _env_list(
        "MT5WEB_SYMBOLS",
        [
            "EURUSD",
            "GBPUSD",
            "USDJPY",
            "AUDUSD",
            "USDCAD",
            "XAUUSD",
            "BTCUSD",
        ],
    )
    TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"]

    # --- trading guards --------------------------------------------------
    MAX_LOT = float(os.getenv("MT5WEB_MAX_LOT", "5.0"))
    RPC_TIMEOUT = float(os.getenv("MT5WEB_RPC_TIMEOUT", "30"))
    TICK_INTERVAL = float(os.getenv("MT5WEB_TICK_INTERVAL", "1.5"))
    HISTORY_BARS = int(os.getenv("MT5WEB_HISTORY_BARS", "400"))

    # --- agent install ---------------------------------------------------
    MT5_DOWNLOAD_URL = os.getenv(
        "MT5_DOWNLOAD_URL",
        "https://download.mql5.com/cdn/web/metaquotes.ltd/mt5/metaquotes5setup.exe",
    )

    @classmethod
    def secret_key(cls) -> bytes:
        """Stable 32-byte key. Uses MT5WEB_SECRET when set, else a file in DATA_DIR."""
        env_secret = os.getenv(cls.SECRET_ENV, "").strip()
        if env_secret:
            return _sha256(env_secret.encode())
        key_file = cls.RUNTIME_DIR / "secret.key"
        key_file.parent.mkdir(parents=True, exist_ok=True)
        if key_file.exists():
            return bytes.fromhex(key_file.read_text().strip())
        material = secrets.token_hex(32)
        key_file.write_text(material)
        try:
            os.chmod(key_file, 0o600)
        except OSError:  # pragma: no cover - platform dependent
            pass
        return _sha256(material.encode())

    @classmethod
    def expected_passcode(cls) -> str:
        return os.getenv(cls.PASSCODE_ENV, "").strip()

    @classmethod
    def expected_bridge_key(cls) -> str:
        return os.getenv(cls.BRIDGE_KEY_ENV, "").strip()

    @classmethod
    def public_origin(cls) -> str:
        """Best-effort public origin, used to build EA callback URLs."""
        env_origin = os.getenv("MT5WEB_PUBLIC_URL", "").strip()
        if env_origin:
            return env_origin.rstrip("/")
        host = os.getenv("RENDER_EXTERNAL_URL", "").strip()
        if host:
            return host.rstrip("/")
        return ""


def _sha256(data: bytes) -> bytes:
    import hashlib

    return hashlib.sha256(data).digest()


settings = Settings()
