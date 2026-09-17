"""Strategy sandbox + indicator maths (no terminal needed)."""

from __future__ import annotations

import math

import pytest


def make_rows(prices, spread=0.0002):
    rows = []
    t = 1_700_000_000
    for p in prices:
        rows.append(
            {
                "time": t,
                "open": p,
                "high": p + spread,
                "low": p - spread,
                "close": p,
                "tick_volume": 10,
            }
        )
        t += 300
    return rows


def test_bars_indicators_match_hand_computation(isolated_env):
    from mt5web.algo import Bars

    rows = make_rows([1.0, 2.0, 3.0, 4.0, 5.0])
    bars = Bars(rows, {"point": 1e-5, "digits": 5})
    assert len(bars) == 5
    assert bars.sma(3, 4) == pytest.approx(4.0)
    assert bars.sma(2, 1) == pytest.approx(1.5)
    # ema: seeded with the first close, k = 2/(2+1)
    k = 2 / 3
    e = 1.0
    for v in [1.0, 2.0, 3.0]:
        e = v * k + e * (1 - k)
    assert bars.ema(2, 2) == pytest.approx(e)
    hi, lo = bars.donchian(3, 4)
    assert hi == pytest.approx(5.0 + 0.0002) and lo == pytest.approx(3.0 - 0.0002)
    # rsi over a strictly rising series is 100
    assert bars.rsi(3, 4) == pytest.approx(100.0)
    assert bars.atr_points(4, 3) > 0
    assert bars.stdev(3, 4) == pytest.approx(statistics_stdev([3.0, 4.0, 5.0]))
    line, sig, hist = bars.macd(2, 3, 2, 4)
    assert math.isfinite(line) and math.isfinite(sig)


def statistics_stdev(values):
    n = len(values)
    mean = sum(values) / n
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))


def test_normalise_signal_shorthands(isolated_env):
    from mt5web.algo import _normalise_signal

    assert _normalise_signal(None) is None
    assert _normalise_signal(1) == {"action": "buy"}
    assert _normalise_signal(-1) == {"action": "sell"}
    assert _normalise_signal(0) == {"action": "close"}
    assert _normalise_signal("long") is None  # strings are the short forms only
    assert _normalise_signal("buy") == {"action": "buy"}
    assert _normalise_signal({"action": "short", "volume": 0.5})["action"] == "sell"
    assert _normalise_signal({"action": "exit"})["action"] == "close"
    assert _normalise_signal({"action": "frobnicate"}) is None
    assert _normalise_signal("nonsense") is None


def test_compile_strategy_errors_are_actionable(isolated_env):
    from mt5web.algo import StrategyError, compile_strategy

    with pytest.raises(StrategyError, match="empty"):
        compile_strategy("   ")
    with pytest.raises(StrategyError, match="syntax error on line"):
        compile_strategy("def broken(:\n  pass\n")
    with pytest.raises(StrategyError, match="on_bar"):
        compile_strategy("x = 1\n")
    init_fn, bar_fn = compile_strategy("def on_bar(ctx, bars, i):\n    return 1\n")
    assert init_fn is None and callable(bar_fn)


def test_sandbox_blocks_import_and_open(isolated_env):
    from mt5web.algo import StrategyError, compile_strategy

    _, bar_fn = compile_strategy("def on_bar(ctx, bars, i):\n    import os\n    return None\n")
    with pytest.raises(StrategyError, match="sandbox"):
        bar_fn(None, None, 0)

    _, bar_fn = compile_strategy("def on_bar(ctx, bars, i):\n    return open('/etc/passwd').read()\n")
    with pytest.raises(StrategyError, match="sandbox"):
        bar_fn(None, None, 0)

    with pytest.raises(StrategyError):
        compile_strategy("import os\n\ndef on_bar(c, b, i):\n    return None\n")  # module-level import runs at load


def test_starter_templates_compile_and_produce_signals(isolated_env):
    from mt5web.algo import Bars, Ctx, compile_strategy, starter_source

    # Choppy drift + impulses: the EMA starter deliberately refuses signals when
    # RSI is overextended, so a perfectly linear series would (correctly) produce
    # none. This shape triggers each of the three starters at least once.
    prices = [1.10]
    for i in range(30):
        prices.append(prices[-1] + 0.0004 * (1 if i % 5 else -4))
    for _ in range(14):
        prices.append(prices[-1] + 0.0018)
    for _ in range(10):
        prices.append(prices[-1] - 0.0001)
    for i in range(30):
        prices.append(prices[-1] - 0.0006 * (1 if i % 4 else -2))
    for _ in range(14):
        prices.append(prices[-1] - 0.0018)
    for _ in range(10):
        prices.append(prices[-1] + 0.0001)
    for _ in range(20):
        prices.append(prices[-1] + 0.0004)
    rows = make_rows(prices)

    for kind in ("ema", "donchian", "grid"):
        source = starter_source(kind)
        init_fn, bar_fn = compile_strategy(source)
        ctx = Ctx({"symbol": "EURUSD", "timeframe": "M5", "volume": 0.01, "engine": kind})
        logs = []
        ctx.log = lambda *a, **k: logs.append(a)
        if init_fn:
            init_fn(ctx)
        bars = Bars(rows, {"point": 1e-5, "digits": 5})
        signals = [bar_fn(ctx, bars, i) for i in range(len(rows))]
        assert any(s is not None for s in signals), f"{kind} produced no signal on the wavy series"
        assert logs if kind == "ema" else True


def test_ctx_compute_volume_uses_risk(isolated_env):
    from mt5web.algo import Ctx

    ctx = Ctx(
        {
            "symbol": "EURUSD", "timeframe": "M5", "volume": 0.01, "volume_from_risk": True,
            "risk_percent": 2.0, "stop_loss_points": 500,
            "params": {},
        }
    )
    ctx.meta = {"point": 1e-5, "contract_size": 100000, "volume_step": 0.01, "volume_min": 0.01, "volume_max": 100}
    lots = ctx.compute_volume(10_000)
    # 2% of 10k = 200 USD ; 500 pts * 1e-5 * 100000 = 500 USD per lot -> 0.4 lots
    assert lots == pytest.approx(0.4)
    ctx.volume_from_risk = False
    assert ctx.compute_volume(10_000) == 0.01
