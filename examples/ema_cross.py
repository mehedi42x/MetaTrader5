# EMA cross with an RSI filter - default starter strategy.
# The web app runs this on every closed bar and sends real orders (SL/TP in points).

def init(ctx):
    ctx.p.setdefault("fast", 12)
    ctx.p.setdefault("slow", 26)
    ctx.p.setdefault("rsi_period", 14)
    ctx.p.setdefault("rsi_buy_max", 68.0)
    ctx.p.setdefault("rsi_sell_min", 32.0)
    ctx.log(f"{ctx.symbol} {ctx.timeframe}: fast={ctx.p['fast']} slow={ctx.p['slow']}")


def on_bar(ctx, bars, i):
    if i < ctx.p["slow"] + 2:
        return None
    fast, slow = bars.ema(ctx.p["fast"], i), bars.ema(ctx.p["slow"], i)
    fp, sp = bars.ema(ctx.p["fast"], i - 1), bars.ema(ctx.p["slow"], i - 1)
    rsi = bars.rsi(ctx.p["rsi_period"], i)
    if fp <= sp and fast > slow and rsi < ctx.p["rsi_buy_max"]:
        return {"action": "buy", "reason": f"ema up / rsi {rsi:.0f}"}
    if fp >= sp and fast < slow and rsi > ctx.p["rsi_sell_min"]:
        return {"action": "sell", "reason": f"ema down / rsi {rsi:.0f}"}
    return None
