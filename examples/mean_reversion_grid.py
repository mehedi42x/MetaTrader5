# Bollinger z-score mean reversion. Careful with real money: averaging into a
# losing position is how accounts die - keep the stop loss set in the algo config.

def init(ctx):
    ctx.p.setdefault("period", 50)
    ctx.p.setdefault("entry_z", 2.0)
    ctx.p.setdefault("exit_z", 0.4)


def on_bar(ctx, bars, i):
    if i < ctx.p["period"] + 1:
        return None
    mean = bars.sma(ctx.p["period"], i)
    sigma = bars.stdev(ctx.p["period"], i) or 1e-9
    z = (bars.close[i] - mean) / sigma
    if z <= -ctx.p["entry_z"]:
        return {"action": "buy", "reason": f"z={z:.2f} oversold"}
    if z >= ctx.p["entry_z"]:
        return {"action": "sell", "reason": f"z={z:.2f} overbought"}
    if ctx.has_position() and abs(z) < ctx.p["exit_z"]:
        return {"action": "close", "reason": f"z={z:.2f} reverted"}
    return None
