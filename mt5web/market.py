"""Market data layer: shared price state, rate cache and the tick polling loop."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from .config import settings
from .store import data

log = logging.getLogger("mt5web.market")

PriceCallback = Callable[[dict[str, dict]], Awaitable[None]]

# symbol -> last known quote
prices: dict[str, dict] = {}
_rate_cache: dict[str, tuple[float, list[dict]]] = {}
_listeners: set[PriceCallback] = set()
_loop_tasks: dict[str, tuple[asyncio.Task, asyncio.Event]] = {}


def add_price_listener(cb: PriceCallback) -> None:
    _listeners.add(cb)


def remove_price_listener(cb: PriceCallback) -> None:
    _listeners.discard(cb)


def cached_rates(symbol: str, timeframe: str, bars: int) -> list[dict] | None:
    hit = _rate_cache.get(f"{symbol}:{timeframe}:{bars}")
    if not hit:
        return None
    ts, rows = hit
    if time.time() - ts > max(5.0, settings.TICK_INTERVAL * 3):
        return None
    return rows


def put_rates(symbol: str, timeframe: str, bars: int, rows: list[dict]) -> None:
    _rate_cache[f"{symbol}:{timeframe}:{bars}"] = (time.time(), rows)
    # keep the cache bounded (60 symbols * a handful of timeframes is plenty)
    if len(_rate_cache) > 400:
        for stale in sorted(_rate_cache, key=lambda k: _rate_cache[k][0])[:50]:
            _rate_cache.pop(stale, None)


async def refresh_rates(gateway, symbol: str, timeframe: str, bars: int) -> list[dict]:
    cached = cached_rates(symbol, timeframe, bars)
    if cached is not None:
        return cached
    rows = await gateway.rates(symbol, timeframe, bars)
    put_rates(symbol, timeframe, bars, rows)
    return rows


async def _notify(item: dict[str, dict]) -> None:
    for cb in list(_listeners):
        try:
            await cb(item)
        except Exception:  # noqa: BLE001 - a broken listener must not kill the loop
            log.exception("price listener failed")


def hub_publish(changed: dict[str, dict]) -> None:
    from .hub import hub

    for symbol, tick in changed.items():
        hub.ticks.publish({"type": "tick", "symbol": symbol, **tick})


async def poll_once(gateway, symbols: list[str]) -> dict[str, dict]:
    """Fetch quotes for ``symbols`` and fan them out to listeners + WS clients."""
    if not symbols:
        return {}
    try:
        ticks = await gateway.ticks(symbols)
    except Exception as exc:  # noqa: BLE001
        log.debug("tick poll failed: %s", exc)
        return {}
    changed: dict[str, dict] = {}
    for symbol, tick in ticks.items():
        old = prices.get(symbol)
        tick["ts"] = time.time()
        prices[symbol] = tick
        if not old or abs(float(old.get("bid") or 0) - float(tick.get("bid") or 0)) > 1e-12:
            changed[symbol] = tick
    if changed:
        hub_publish(changed)
        await _notify(changed)
    return changed


def watchlist() -> list[str]:
    return list(data.config.read().get("symbols") or settings.DEFAULT_SYMBOLS)


async def market_loop(account_id: str, gateway, stop: asyncio.Event) -> None:
    """Background loop keeping quotes and candles warm for one account."""
    last_bar_seen: dict[str, int] = {}
    while not stop.is_set():
        symbols = watchlist()
        await poll_once(gateway, symbols)

        timeframe = str(data.config.read().get("chart_timeframe") or "M5")
        for symbol in symbols[:12]:
            try:
                rows = await gateway.rates(symbol, timeframe, settings.HISTORY_BARS)
            except Exception as exc:  # noqa: BLE001
                log.debug("rate refresh failed for %s: %s", symbol, exc)
                continue
            if rows:
                put_rates(symbol, timeframe, settings.HISTORY_BARS, rows)
                last_bar = int(rows[-1]["time"])
                previous = last_bar_seen.get(symbol)
                if previous and last_bar > previous:
                    from .hub import hub

                    hub.trade_events.publish(
                        {
                            "ts": time.time(),
                            "type": "bar",
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "time": last_bar,
                        }
                    )
                last_bar_seen[symbol] = last_bar

        interval = float(data.config.read().get("tick_interval") or settings.TICK_INTERVAL)
        try:
            await asyncio.wait_for(stop.wait(), timeout=max(1.0, interval))
        except asyncio.TimeoutError:
            pass


def start_loop(account_id: str, gateway: Any) -> None:
    stop_loop(account_id)
    stop = asyncio.Event()
    task = asyncio.create_task(market_loop(account_id, gateway, stop), name=f"market-{account_id}")
    _loop_tasks[account_id] = (task, stop)


def stop_loop(account_id: str) -> None:
    entry = _loop_tasks.pop(account_id, None)
    if not entry:
        return
    task, stop = entry
    stop.set()
    task.cancel()


def stop_all() -> None:
    for account_id in list(_loop_tasks):
        stop_loop(account_id)


def is_running(account_id: str | None = None) -> bool:
    if account_id is None:
        return bool(_loop_tasks)
    return account_id in _loop_tasks


def loop_status() -> dict:
    return {
        "running": bool(_loop_tasks),
        "accounts": sorted(_loop_tasks),
        "price_symbols": len(prices),
        "cached_rates": len(_rate_cache),
    }
