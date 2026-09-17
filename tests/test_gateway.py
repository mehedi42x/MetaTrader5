"""Conversions from MT5 payloads to the JSON the frontend consumes."""

from __future__ import annotations

import pytest


def test_normalize_symbol_info_defaults_and_explicit():
    from mt5web.gateway import normalize_symbol_info

    fallback = normalize_symbol_info("XAUUSD", None)
    assert fallback["name"] == "XAUUSD"
    assert fallback["digits"] == 5 and fallback["point"] == 1e-5
    assert fallback["volume_min"] is None

    real = normalize_symbol_info(
        "XAUUSD",
        {"digits": 2, "point": 0.01, "bid": 2465.1, "ask": 2465.4, "spread": 30, "volume_min": 0.01,
         "volume_max": 100, "volume_step": 0.01, "trade_contract_size": 100, "tradeable": True},
    )
    assert real["digits"] == 2 and real["point"] == 0.01
    assert real["bid"] == 2465.1 and real["contract_size"] == 100


def test_round_to_step_clamps_volume():
    from mt5web.gateway import round_to_step

    assert round_to_step(0.017, 0.01, 0.01, 100) == 0.02
    assert round_to_step(0.001, 0.01, 0.01, 100) == 0.01
    assert round_to_step(500, 0.1, None, 10) == 10
    assert round_to_step(0.12345678, None) == 0.12345678


def test_position_order_deal_conversion():
    from mt5web.gateway import deal_to_dict, order_to_dict, position_to_dict

    pos = position_to_dict(
        {"ticket": 7, "type": 1, "symbol": "EURUSD", "volume": 0.5, "price_open": 1.1,
         "price_current": 1.09, "sl": 0, "tp": 0, "profit": 500.0, "_internal": 1},
        {"EURUSD": 5},
    )
    assert pos["type"] == "sell" and pos["digits"] == 5 and "_internal" not in pos
    assert pos["profit"] == 500.0

    order = order_to_dict({"ticket": 8, "symbol": "GBPUSD", "type": 4, "price_open": 1.3})
    assert order["type_text"] == "buy_stop"

    deal = deal_to_dict({"ticket": 9, "type": 0, "entry": 1, "profit": -3.5, "symbol": "GBPUSD"})
    assert deal["type"] == "buy" and deal["entry"] == "out" and deal["profit"] == -3.5


def test_account_info_handles_infinite_margin_level():
    from mt5web.gateway import account_info_to_dict

    info = account_info_to_dict({"login": 1, "balance": 10.0, "margin": 0.0, "margin_level": float("inf")})
    assert info["margin_level"] is None and info["balance"] == 10.0 and info["login"] == 1


def test_rates_to_rows_accepts_dicts_tuples_and_none():
    from mt5web.gateway import rates_to_rows

    assert rates_to_rows(None) == []
    rows = rates_to_rows([{"time": 1, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5}])
    assert rows == [{"time": 1, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "tick_volume": 0}]
    tuple_rows = rates_to_rows([(1, 1.0, 2.0, 0.5, 1.5, 42)])
    assert tuple_rows[0]["tick_volume"] == 42


def test_unwrap_namedtuple_and_structured_array():
    from collections import namedtuple
    from types import SimpleNamespace

    from mt5web.gateway import unwrap

    Row = namedtuple("Row", "ticket hidden volume")
    assert unwrap(Row(5, 9, 0.2)) == {"ticket": 5, "hidden": 9, "volume": 0.2}
    # leading-underscore keys are dropped (MT5 structs expose them as internals)
    assert unwrap({"ticket": 1, "_ignore": 0}) == {"ticket": 1}

    class FakeArr:  # mimics a numpy structured array: not a list, but len-able
        dtype = object()

        def __init__(self, items):
            self.items = items

        def __len__(self):
            return len(self.items)

        def __iter__(self):
            return iter(self.items)

    assert unwrap(FakeArr([{"a": 1}, (2, 3)])) == [{"a": 1}, [2, 3]]
    assert unwrap(3.5) == 3.5
    assert unwrap(None) is None


def test_place_raises_gateway_error_with_hint(monkeypatch):
    from mt5web.gateway import BaseGateway, GatewayError, err_text

    async def fake_call(self, method, **kwargs):
        if method == "order_send":
            return {"retcode": 10016, "order": 0}
        return (0, "some terminal error")

    monkeypatch.setattr(BaseGateway, "call", fake_call)
    gw = BaseGateway()
    with pytest.raises(GatewayError) as exc:
        import asyncio

        asyncio.run(gw.place({"action": 1}))
    assert "distance" in str(exc.value).lower()
    assert exc.value.retryable is False
    assert "Market is closed" in err_text(10004)


def test_estimate_lots_is_risk_linear(isolated_env):
    from mt5web import broker

    meta = {"point": 1e-5, "contract_size": 100000, "volume_step": 0.01, "volume_min": 0.01, "volume_max": 100}
    # risk 100 USD; 250 points * 1e-5 * 100000 contract = 250 USD per lot -> 0.4 lots
    small = broker.estimate_lots(10000, 1.0, 250, meta)
    double = broker.estimate_lots(20000, 1.0, 250, meta)
    assert small == 0.4 and double == 0.8  # risk / (contract * point * sl_points) per lot
    assert broker.estimate_lots(100, 1.0, 250, meta) == 0.01      # tiny account -> floored at volume_min
    assert broker.estimate_lots(10_000_000, 1.0, 250, meta) == 100.0  # capped at volume_max
    assert broker.estimate_lots(10000, 1.0, None, meta) == 0.01  # no SL -> minimum lot


# --------------------------------------------------------------------------- #
# request shaping + risk guards (unit level, no transport needed)
# --------------------------------------------------------------------------- #

def test_copy_rates_uses_the_real_mt5_signature():
    """copy_rates_from_pos(symbol, timeframe, start_position, count) - positional order matters."""
    import asyncio

    from mt5web.gateway import BaseGateway

    class _T(BaseGateway):
        source = "test"
        live = False
        supports_terminal_files = False

        def __init__(self) -> None:
            self.seen: dict = {}

        async def call(self, method, params=None, **kwargs):  # noqa: ANN001
            self.seen = {"method": method, "params": dict(params or {}, **kwargs)}
            return []

    g = _T()
    asyncio.run(g.rates("EURUSD", "M15", 42))
    assert g.seen["method"] == "copy_rates_from_pos"
    assert g.seen["params"]["symbol"] == "EURUSD"
    assert g.seen["params"]["start_position"] == 0
    assert g.seen["params"]["count"] == 42
    assert g.seen["params"]["timeframe"] == 3  # M15 -> TIMEFRAME_M15


def test_stop_side_validation_rejects_impossible_orders():
    from mt5web.broker import _validate_stops
    from mt5web.gateway import GatewayError

    meta = {"digits": 5, "point": 1e-5}

    # BUY: SL below price, TP above price
    assert _validate_stops(1.0818, 1.0908, True, meta, 1.0848) == (1.0818, 1.0908)
    with pytest.raises(GatewayError, match="stop-loss"):
        _validate_stops(1.0898, 0.0, True, meta, 1.0848)
    with pytest.raises(GatewayError, match="take-profit"):
        _validate_stops(0.0, 1.0808, True, meta, 1.0848)

    # SELL: SL above price, TP below price (and therefore TP < SL)
    assert _validate_stops(1.0878, 1.0808, False, meta, 1.0848) == (1.0878, 1.0808)
    with pytest.raises(GatewayError, match="stop-loss"):
        _validate_stops(1.0838, 0.0, False, meta, 1.0848)
    with pytest.raises(GatewayError, match="take-profit"):
        _validate_stops(0.0, 1.0888, False, meta, 1.0848)
    with pytest.raises(GatewayError, match="must be above the entry price"):
        _validate_stops(1.0838, 0.0, False, meta, 1.0848)  # SL under a short's entry = impossible
    with pytest.raises(GatewayError, match="take-profit must be below stop-loss"):
        _validate_stops(1.0878, 1.0898, False, meta, None)  # no price: only the pair is checked

    # without a reference price only the SL/TP relationship is checked
    with pytest.raises(GatewayError, match="take-profit must be above"):
        _validate_stops(1.09, 1.08, True, meta, None)


def test_pending_and_mutation_requests_carry_symbol():
    import asyncio

    from mt5web.gateway import BaseGateway

    class _T(BaseGateway):
        source = "test"
        live = False
        supports_terminal_files = False

        def __init__(self) -> None:
            self.reqs: list[dict] = []

        async def call(self, method, params=None, **kwargs):  # noqa: ANN001
            if method == "order_send":
                merged = dict(params or {})
                merged.update(kwargs)
                # place() forwards the request as {"request": req}, like the MT5 package
                self.reqs.append(dict(merged.get("request") or merged))
                return {"retcode": 10009, "order": 5, "deal": 6}
            if method == "orders_get":
                return [{"ticket": 5, "symbol": "XAUUSD", "volume_current": 0.05, "volume": 0.05, "type": 2}]
            if method == "positions_get":
                return [{"ticket": 5, "symbol": "XAUUSD", "volume": 0.05, "type": 0, "price_open": 2400.0}]
            return []

    g = _T()
    asyncio.run(g.place({"action": 3, "symbol": "XAUUSD", "type": 2, "volume": 0.05}))
    asyncio.run(g.modify_position(5, 2390.0, 2450.0))
    asyncio.run(g.remove_order(5))
    assert g.reqs[1]["action"] == 2 and g.reqs[1]["symbol"] == "XAUUSD", g.reqs[1]
    assert g.reqs[0]["action"] == 3, g.reqs[0]
    assert g.reqs[1]["volume"] == 0.05, g.reqs[1]
    assert g.reqs[2]["action"] == 4 and g.reqs[2]["order"] == 5, g.reqs[2]
    assert g.reqs[2].get("symbol") == "XAUUSD", g.reqs[2]


def test_submit_order_maps_pending_to_trade_action_pending():
    """Regression: pending orders used to be sent as TRADE_ACTION_DEAL (action 1)."""
    import inspect

    from mt5web import broker

    src = inspect.getsource(broker.submit_order)
    assert '"action": 3 if is_pending else 1' in src
    assert "TRADE_ACTION_PENDING" in src
