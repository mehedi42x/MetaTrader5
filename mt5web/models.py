"""Pydantic request/response models for the MT5 Web Console API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    passcode: str = ""
    bridge_key: str | None = None


class LoginResponse(BaseModel):
    token: str
    role: str
    expires_in: int


class SettingsPatch(BaseModel):
    symbols: list[str] | None = None
    max_lot: float | None = Field(default=None, gt=0, le=100)
    kill_switch: bool | None = None
    allow_live_trading: bool | None = None
    tick_interval: float | None = Field(default=None, ge=0.2, le=60)


class AccountIn(BaseModel):
    name: str = "MT5"
    server: str = Field(min_length=2, examples=["ICMarkets-Demo01"])
    login: int = Field(gt=0, examples=[1234567])
    password: str = Field(min_length=1)
    terminal_path: str | None = None
    timeout_ms: int = Field(default=60_000, ge=5_000, le=600_000)
    make_default: bool = True


class AccountOut(BaseModel):
    id: str
    name: str
    server: str
    login: int
    terminal_path: str | None = None
    has_password: bool = True
    status: str = "disconnected"
    last_error: str | None = None
    connected_at: float | None = None
    is_default: bool = False


class AccountInfo(BaseModel):
    login: int | None = None
    server: str | None = None
    currency: str | None = None
    balance: float | None = None
    equity: float | None = None
    margin: float | None = None
    margin_free: float | None = None
    margin_level: float | None = None
    profit: float | None = None
    leverage: int | None = None
    company: str | None = None


class SymbolOut(BaseModel):
    name: str
    description: str | None = None
    currency_profit: str | None = None
    digits: int = 5
    point: float = 1e-05
    spread: int | None = None
    bid: float | None = None
    ask: float | None = None
    volume_min: float | None = None
    volume_max: float | None = None
    volume_step: float | None = None
    tradeable: bool = True
    source: str = "app"
    selected: bool = True


class Rate(BaseModel):
    time: int
    open: float
    high: float
    low: float
    close: float
    tick_volume: int = 0


class OrderRequest(BaseModel):
    symbol: str = Field(min_length=1)
    direction: str = Field(pattern="^(buy|sell)$")
    volume: float = Field(gt=0, le=100)
    order_type: str = Field(default="market", pattern="^(market|buy_limit|sell_limit|buy_stop|sell_stop)$")
    price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    sl_points: float | None = Field(default=None, gt=0)
    tp_points: float | None = Field(default=None, gt=0)
    deviation: int = Field(default=20, ge=0, le=1000)
    comment: str = Field(default="web", max_length=64)
    magic: int = Field(default=0, ge=0)
    account_id: str | None = None


class AlgoCreate(BaseModel):
    name: str = Field(min_length=2, max_length=48, pattern=r"^[\w .()-]+$")
    description: str = ""
    engine: str = Field(default="python", pattern="^(python|mql5|hybrid)$")
    symbol: str
    timeframe: str = "M5"
    volume: float = Field(default=0.01, gt=0, le=100)
    volume_from_risk: bool = False
    risk_percent: float = Field(default=1.0, gt=0, le=100)
    stop_loss_points: float | None = Field(default=None, gt=0)
    take_profit_points: float | None = Field(default=None, gt=0)
    trailing_points: float | None = Field(default=None, gt=0)
    one_position_per_symbol: bool = True
    allow_reverse: bool = True
    run_on_timer: bool = Field(default=False, description="Evaluate inside a bar too (faster feedback, noisier)")
    max_daily_loss_percent: float = Field(default=0.0, ge=0, le=100)
    max_open_positions: int = Field(default=1, ge=1, le=50)
    magic: int = Field(default=20260917, ge=1)
    comment: str = Field(default="algo", max_length=32)
    source: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    account_id: str | None = None


class AlgoUpdate(BaseModel):
    description: str | None = None
    symbol: str | None = None
    timeframe: str | None = None
    volume: float | None = Field(default=None, gt=0, le=100)
    volume_from_risk: bool | None = None
    risk_percent: float | None = Field(default=None, gt=0, le=100)
    stop_loss_points: float | None = None
    take_profit_points: float | None = None
    trailing_points: float | None = None
    one_position_per_symbol: bool | None = None
    allow_reverse: bool | None = None
    run_on_timer: bool | None = None
    max_daily_loss_percent: float | None = Field(default=None, ge=0, le=100)
    max_open_positions: int | None = Field(default=None, ge=1, le=50)
    magic: int | None = Field(default=None, ge=1)
    comment: str | None = None
    source: str | None = None
    params: dict[str, Any] | None = None
    account_id: str | None = None


class AlgoRunRequest(BaseModel):
    lookback_bars: int = Field(default=600, ge=50, le=5000)
    replay: bool = True
    trade_on_replay: bool = False


class AlgoOut(BaseModel):
    id: str
    name: str
    description: str = ""
    engine: str
    symbol: str
    timeframe: str
    volume: float
    volume_from_risk: bool = False
    risk_percent: float = 1.0
    stop_loss_points: float | None = None
    take_profit_points: float | None = None
    trailing_points: float | None = None
    one_position_per_symbol: bool = True
    allow_reverse: bool = True
    max_daily_loss_percent: float = 0.0
    max_open_positions: int = 1
    magic: int
    comment: str = "algo"
    params: dict[str, Any] = Field(default_factory=dict)
    account_id: str | None = None
    status: str = "stopped"
    has_source: bool = False
    source_bytes: int = 0
    error: str | None = None
    stats: dict[str, Any] = Field(default_factory=dict)
    deploy: dict[str, Any] = Field(default_factory=dict)
    updated_at: float = 0.0


class PositionClose(BaseModel):
    ticket: int
    volume: float | None = Field(default=None, gt=0)
    account_id: str | None = None


class PositionModify(BaseModel):
    ticket: int
    stop_loss: float | None = None
    take_profit: float | None = None
    account_id: str | None = None


class SymbolAdd(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=50)


class PreviewRequest(BaseModel):
    source: str
    symbol: str
    timeframe: str = "M5"
    bars: int = Field(default=300, ge=50, le=2000)
    volume: float = Field(default=0.01, gt=0, le=10)
    stop_loss_points: float | None = None
    take_profit_points: float | None = None
    params: dict[str, Any] = Field(default_factory=dict)
