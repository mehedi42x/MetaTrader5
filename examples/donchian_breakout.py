# Donchian channel breakout, ATR-scaled exits.

def init(ctx):
    ctx.p.setdefault("entry_channel", 20)
    ctx.p.setdefault("exit_channel", 10)
    ctx.p.setdefault("atr_period", 14)


def on_bar(ctx, bars, i):
    if i < ctx.p["entry_channel"] + 2:
        return None
    hi, _ = bars.donchian(ctx.p["entry_channel"], i - 1)
    _, lo = bars.donchian(ctx.p["exit_channel"], i - 1)
    price = bars.close[i]
    atr = bars.atr_points(i - 1, ctx.p["atr_period"])
    if atr <= 0:
        return None
    if not ctx.has_position():
        if price > hi:
            return {"action": "buy", "reason": f"breakout {hi:.5f}, atr {atr:.0f}"}
        if price < lo:
            return {"action": "sell", "reason": f"breakdown {lo:.5f}, atr {atr:.0f}"}
    elif ctx.position["type"] == "buy" and price < lo:
        return {"action": "close", "reason": "channel exit"}
    elif ctx.position["type"] == "sell" and price > hi:
        return {"action": "close", "reason": "channel exit"}
    return None
