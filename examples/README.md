# Example strategies

These are the same three starters the app attaches to a new **python** / **hybrid** algo, so you
can diff them against what Algo Studio shows. Contract:

```python
def init(ctx):            # optional: once before the first bar
    ...

def on_bar(ctx, bars, i): # called on every newly closed bar (and per second with run_on_timer)
    return None                     # no action
    return "buy"                    # shorthand
    return {"action": "sell", "reason": "...", "volume": 0.02}
    return {"action": "close"}      # flatten the algo's position
```

| file | idea | honest weakness |
| --- | --- | --- |
| `ema_cross.py` | EMA 12/26 cross with an RSI 68/32 filter | chops itself to pieces in a flat market |
| `donchian_breakout.py` | 20-bar breakout entry, 10-bar exit, ATR-sized stops | late entries, big slippage on news bars |
| `mean_reversion_grid.py` | z-score vs a 50-bar mean, 2σ bands | a trend turns it into an unfunded martingale — small lots only |

```bash
cp examples/ema_cross.py  # paste into Algo Studio -> source
pytest tests/test_algo_logic.py   # the starter maths is unit-tested, including a hand-computed EMA
```

Nothing here is a trading signal. Volumes are deliberately tiny (`ctx.volume` comes from the
algo's `volume` field), SL/TP come from `stop_loss_points` / `take_profit_points` in the UI, and
`ctx.compute_volume()` sizes the lot from `risk_percent` if you tick *size from risk*.
