"""Bridge hub: agent registry, request/response RPC and fan-out event streams."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Any

from .config import settings
from .gateway import BaseGateway, GatewayError

log = logging.getLogger("mt5web.hub")

MAX_RPC = {
    "account_info": "info",
    "terminal_info": "info",
    "terminal_path": "path",
    "terminal_datafolder": "path",
    "initialize": "init",
    "login": "login",
    "shutdown": "simple",
    "last_error": "err",
    "symbols_total": "list",
    "symbol_select": "bool",
    "symbol_info": "dict",
    "symbol_properties": "dict",
    "symbols_get": "list",
    "ticks_stock": "list",
    "ticks_last": "ticks",
    "ticks_history": "rates",
    "copy_rates_from_pos": "rates",
    "copy_rates_from": "rates",
    "copy_rates_range": "rates",
    "copy_ticks_from": "ticks",
    "copy_ticks_range": "ticks",
    "positions_get": "rows",
    "orders_get": "rows",
    "history_orders_get": "rows",
    "history_deals_get": "rows",
    "order_send": "dict",
    "market_book_add": "bool",
    "market_book_get": "rows",
    "terminal_info_full": "dict",
    "fs_write": "dict",
    "fs_read": "dict",
    "fs_list": "list",
    "fs_delete": "dict",
    "file_exists": "dict",
    "terminal_compile": "dict",
    "attach_ea": "dict",
    "detach_ea": "dict",
    "mt5_status": "dict",
    "tail_logs": "dict",
}


class HubError(RuntimeError):
    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class AgentConnection:
    """One live WebSocket connection from a Bridge agent."""

    def __init__(self, agent_id: str, name: str, ws) -> None:
        self.agent_id = agent_id
        self.name = name
        self.ws = ws
        self.hello: dict = {}
        self.connected_at = time.time()
        self.last_seen = time.time()
        self.rpc_count = 0
        self.rpc_errors = 0
        self.pending: dict[str, asyncio.Future] = {}
        self.events: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._seq = 0
        self._write_lock = asyncio.Lock()

    # ---- outbound ----------------------------------------------------- #
    async def _raw_send(self, payload: dict) -> None:
        async with self._write_lock:
            await self.ws.send_text(json.dumps(payload, default=str))

    async def request(self, method: str, params: dict | None = None, timeout: float | None = None) -> Any:
        self._seq += 1
        self.rpc_count += 1
        rid = f"{self.agent_id}-{self._seq}"
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self.pending[rid] = fut
        timeout = timeout or settings.RPC_TIMEOUT
        try:
            await self._raw_send({"t": "rpc", "id": rid, "method": method, "params": params or {}})
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError as exc:
            self.rpc_errors += 1
            raise HubError(f"Agent '{self.name}' timed out on {method}() after {timeout:.0f}s") from exc
        except HubError:
            self.rpc_errors += 1
            raise
        finally:
            self.pending.pop(rid, None)

    async def notify(self, payload: dict) -> None:
        await self._raw_send({"t": "cmd", **payload})

    # ---- inbound ------------------------------------------------------ #
    def resolve(self, msg: dict) -> None:
        fut = self.pending.get(str(msg.get("id")))
        if fut is None or fut.done():
            return
        if msg.get("ok"):
            fut.set_result(msg.get("result"))
        else:
            fut.set_exception(
                HubError(str(msg.get("error") or "agent error"), code=msg.get("code"))
            )

    def push_event(self, event: dict) -> None:
        with contextlib.suppress(asyncio.QueueFull):
            self.events.put_nowait(event)

    # ---- status ------------------------------------------------------- #
    def as_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "connected": True,
            "connected_at": self.connected_at,
            "last_seen": self.last_seen,
            "os": self.hello.get("os"),
            "os_release": self.hello.get("os_release"),
            "python": self.hello.get("python"),
            "mt5_available": bool(self.hello.get("mt5_available")),
            "mt5_version": self.hello.get("mt5_version"),
            "data_folder": self.hello.get("data_folder"),
            "initialized": bool(self.hello.get("initialized")),
            "agent_version": self.hello.get("agent_version"),
            "rpc_count": self.rpc_count,
            "rpc_errors": self.rpc_errors,
        }


class EventFan:
    """Multi-subscriber pub/sub used for tick / log / trade-event streams."""

    def __init__(self, maxlen: int = 400) -> None:
        self.subs: set[asyncio.Queue] = set()
        self.buffer: list[dict] = []
        self.maxlen = maxlen

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self.subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subs.discard(q)

    def publish(self, item: dict) -> None:
        self.buffer.append(item)
        if len(self.buffer) > self.maxlen:
            del self.buffer[: len(self.buffer) - self.maxlen]
        for q in list(self.subs):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(item)

    def recent(self, minutes: float = 60) -> list[dict]:
        cutoff = time.time() - minutes * 60
        return [row for row in self.buffer if row.get("ts", 0) >= cutoff]

    @property
    def subscriber_count(self) -> int:
        return len(self.subs)


class Hub:
    def __init__(self) -> None:
        self.agents: dict[str, AgentConnection] = {}
        self.ticks = EventFan()
        self.trade_events = EventFan()
        self.agent_logs = EventFan()
        self._lock = asyncio.Lock()

    # ---- registry ----------------------------------------------------- #
    async def register(self, name: str, ws, hello: dict) -> AgentConnection:
        agent_id = f"agent_{abs(hash((name, hello.get('machine', '')))) % 10**8:08d}"
        conn = AgentConnection(agent_id, name or "agent", ws)
        conn.hello = hello or {}
        async with self._lock:
            old = self.agents.get(agent_id)
            if old is not None:
                with contextlib.suppress(Exception):
                    await old.ws.close(code=4000, reason="replaced by a newer agent with the same name")
            self.agents[agent_id] = conn
        log.info("agent '%s' connected (%s, MT5 %s)", name, hello.get("os"), hello.get("mt5_version"))
        return conn

    async def unregister(self, conn: AgentConnection) -> None:
        async with self._lock:
            if self.agents.get(conn.agent_id) is conn:
                self.agents.pop(conn.agent_id, None)
        for fut in list(conn.pending.values()):
            if not fut.done():
                fut.set_exception(HubError("agent disconnected while the call was in flight"))
        log.info("agent '%s' disconnected", conn.name)

    def default_agent(self) -> AgentConnection:
        if not self.agents:
            raise HubError("no Bridge agent is connected")
        preferred = str(data_preferred_agent() or "")
        if preferred and preferred in self.agents:
            return self.agents[preferred]
        return sorted(self.agents.values(), key=lambda c: -c.last_seen)[0]

    def list_agents(self) -> list[dict]:
        preferred = str(data_preferred_agent() or "")
        rows = [conn.as_dict() for conn in self.agents.values()]
        for row in rows:
            row["preferred"] = row["agent_id"] == preferred or (not preferred and row is rows[0])
        return rows

    async def rpc(self, method: str, params: dict | None = None, agent_id: str | None = None, timeout: float | None = None) -> Any:
        conn = self.agents[agent_id] if agent_id and agent_id in self.agents else self.default_agent()
        if method not in MAX_RPC:
            raise HubError(f"method '{method}' is not exposed by the bridge")
        return await conn.request(method, params or {}, timeout=timeout)

    async def broadcast(self, payload: dict) -> None:
        for conn in list(self.agents.values()):
            with contextlib.suppress(Exception):
                await conn.notify(payload)


# The preferred agent is stored in the config collection (see mt5web.store),
# but importing ``data`` here would be circular, so we look it up lazily.
def data_preferred_agent():
    from .store import data

    return data.config.read().get("preferred_agent_id")


hub = Hub()


class AgentGateway(BaseGateway):
    """Gateway transport that talks to a Bridge agent over the hub socket.

    All the high level behaviour (retcode handling, position/order shaping,
    close & modify flows) is inherited from ``BaseGateway``; this class only
    supplies the transport.
    """

    supports_terminal_files = True

    def __init__(self, account_id: str | None, agent_id: str | None = None) -> None:
        self.account_id = account_id
        self.agent_id = agent_id

    source = "agent"
    live = True

    async def call(self, method: str, params: dict | None = None, **kwargs) -> Any:
        """Either ``call("x", {"a": 1})`` or ``call("x", a=1)`` - both are used."""
        merged = dict(params or {})
        merged.update(kwargs)
        params = merged
        if self.account_id:
            params.setdefault("account_id", self.account_id)
        try:
            return await hub.rpc(method, params, agent_id=self.agent_id)
        except HubError as exc:
            raise GatewayError(str(exc), exc.code) from exc

    async def push_subscription(self, symbols: list[str], interval: float) -> None:
        with contextlib.suppress(Exception):
            await hub.default_agent().notify(
                {"action": "subscribe", "symbols": symbols, "interval": interval, "account_id": self.account_id}
            )
