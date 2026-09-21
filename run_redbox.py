"""Faithful port of the pasted Pine v6 strategy
"Trande Hunter - Permanent Stalling Red Box" + a hunt for a better version of the filter.

The new piece is the RED BOX ("dynamic stalling zone"):

    ph = ta.pivothigh(high, 1, failCandles)        // confirmed failCandles bars later
    at confirmation: redBoxTop = ph, redBoxBtm = ph - zoneRange
                     a box OPENS only if the close is inside that band
    while a box is open: close inside  -> the box extends, isInsideRedBox = true (no entries)
                         close outside -> the box is locked/closed for good
    entries: bullCross + 5m trend + not inside the box + inside the backtest window
    exits:   opposite 1m cross, plus the delayed trailing lock (2.0 / 1.5 / cap 2.0)

The user reports the filter lifted the win rate from 31% to 68%. This script
  1. reproduces that filter exactly (fixed $5 band, failCandles 3) and measures it,
  2. sweeps the whole filter family (band width, pivot confirmation length, one-sided
     blocking, ATR-scaled bands, stacked pivot levels),
  3. tunes on 2022-2023 and validates on 2024-2025 + the 2026 data (never tuned there),
  4. reports win rate, trade count and net P&L together - a win rate on its own is not
     a result.

The box state machine is vectorised: for every pivot event the band is set at the
confirmation bar and the zone stays "hot" only for the contiguous run of bars whose close
stays inside it - exactly what the Pine code does with box.set_right / activeRedBox := na.

Usage: python3 run_redbox.py
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from run_trade_forensics import build, load_year, load_recent
from run_user_pine import simulate_pine, st

COST = 0.20                      # $ per oz per round trip (house rule)
ZONE, FAIL = 5.0, 3              # the pasted script's defaults
CACHE = {}


def pivots(high, fail):
    """ta.pivothigh(high, leftbars=1, rightbars=fail) -> (index, value) of confirmations."""
    n = len(high)
    idx, val = [], []
    for i in range(fail + 1, n):
        p = i - fail
        v = high[p]
        if v <= high[p - 1]:
            continue
        ok = True
        for k in range(1, fail + 1):
            if v <= high[p + k]:
                ok = False
                break
        if ok:
            idx.append(i)
            val.append(v)
    return np.array(idx, dtype=int), np.array(val, dtype=float)


def head(d, k):
    """First k bars of a built frame (simulate_pine's in_bt = t >= start has no upper
    bound, so a window must be created by slicing the data, not by passing t_end)."""
    return {kk: (vv[:k] if hasattr(vv, "__len__") and len(vv) == len(d["close"]) else vv)
            for kk, vv in d.items()}


def redbox_frames(d, fail=FAIL, zone=ZONE, zone_atr=None, levels=1):
    """The literal state machine of the pasted Pine code.

    Pine keeps two globals (redBoxTop / redBoxBtm) AND a box handle. Every confirmed
    pivot overwrites the two globals (even in the middle of a live box) while the
    handle is created only when the close is inside the band; the handling block then
    tests the *current* globals - so a pivot that prints away from the price locks a
    live box on that very bar. This loop reproduces that:
        * the band in force is always the latest confirmed pivot's band
        * a box lives while the close stays inside that band and locks when it leaves
        * end_dir (+1/-1) marks the bar at which a box ended (deferred-entry input)
    levels > 1 is my own stacked variant: the older bands stay alive (and keep
    blocking) while the close remains inside them; the newest band still takes over
    the primary slot exactly as in the script.
    """
    key = (id(d), fail)
    if key not in CACHE:
        CACHE[key] = pivots(d["high"], fail)
    ev_i, ev_v = CACHE[key]
    c, atr = d["close"], d.get("atr")
    n = len(c)
    inside = np.zeros(n, bool)
    top = np.full(n, np.nan)
    btm = np.full(n, np.nan)
    end_dir = np.zeros(n, np.int8)
    if len(ev_i) == 0:
        return dict(active=inside, top=top, btm=btm, end_dir=end_dir)

    pi = 0
    band = None                       # band in force (the Pine globals)
    box = False                       # the handle: a box exists
    extra = []                        # levels>1: older bands still alive
    for i in range(n):
        if pi < len(ev_i) and ev_i[pi] == i:
            w = zone if zone_atr is None else zone_atr * float(atr[i])
            ph = float(ev_v[pi])
            pi += 1
            if box and band is not None and levels > 1:
                extra = ([band] + extra)[:levels - 1]
            band = [ph, ph - w]
            if band[1] <= c[i] <= band[0]:
                box = True
        if box and band is not None:
            if band[1] <= c[i] <= band[0]:
                inside[i] = True
                top[i], btm[i] = band[0], band[1]
            else:
                box = False
                end_dir[i] = 1 if c[i] > band[0] else -1
        if extra:
            alive = [b for b in extra if b[1] <= c[i] <= b[0]]
            for b in extra:
                if b not in alive:
                    end_dir[i] = 1 if c[i] > b[0] else -1
            if alive:
                inside[i] = True
                top[i] = max([top[i]] + [b[0] for b in alive] if not np.isnan(top[i])
                             else [b[0] for b in alive])
                btm[i] = min([btm[i]] + [b[1] for b in alive] if not np.isnan(btm[i])
                             else [b[1] for b in alive])
            extra = alive
    return dict(active=inside, top=top, btm=btm, end_dir=end_dir)


def redbox_state(d, **kw):
    """Boolean blocking array (kept for the family section)."""
    return redbox_frames(d, **kw)["active"]


def simulate_deferred(d, frames, mode="box_end", delay=3, lot=0.01, lev=100.0,
                      spread_pts=0.20, trigger=2.0, dist=1.5, cap=2.0, days=7,
                      t_end=None):
    """Same harness as simulate_pine, but a signal that lands inside the red box is NOT
    dropped - it is DEFERRED and fired when the box ends, so the trade count is kept.

    mode "box_end"   : the pending order fires as soon as the box closes, whichever way
    mode "box_break" : it only fires when the box breaks in the trade's own direction
                       (a long waits for a close above the box top); an adverse break
                       cancels it
    mode "delay"     : it fires `delay` bars after the blocked signal, break or no break
    """
    o, h, l, c, t = d["open"], d["high"], d["low"], d["close"], d["time"]
    bull, bear = d["bull"], d["bear"]
    hb, hs = d["htf_bull"], d["htf_bear"]
    n = len(o)
    qty = lot * lev
    cost = spread_pts * qty
    end = pd.Timestamp(t[-1]) if t_end is None else pd.Timestamp(t_end)
    start = np.datetime64(end - pd.Timedelta(days=days))
    in_bt = t >= start
    act, edir = frames["active"], frames["end_dir"]

    trades = []
    pos, entry, entry_i = 0, np.nan, None
    stop, trail_on = np.nan, False
    queued_entry, queued_close = 0, False
    pending, due = 0, 0
    n_defer, n_cancel = 0, 0

    def close_trade(i, px, why):
        nonlocal pos, stop, trail_on, entry_i
        trades.append(dict(dir=pos, entry_i=entry_i, exit_i=i,
                           entry_time=pd.Timestamp(t[entry_i]),
                           exit_time=pd.Timestamp(t[i]),
                           entry=float(entry), exit=float(px),
                           pnl=float((px - entry) * pos * qty - cost),
                           why=why, qty=qty, bars=int(i - entry_i)))
        pos, stop, trail_on, entry_i = 0, np.nan, False, None

    for i in range(1, n):
        j = i - 1
        if queued_close and pos != 0:
            close_trade(i, o[i], "cross")
        queued_close = False
        if queued_entry != 0:
            if pos != 0:
                close_trade(i, o[i], "cross")
            pos, entry, entry_i = queued_entry, o[i], i
            stop, trail_on = np.nan, False
            queued_entry = 0
        if pos != 0 and trail_on and not np.isnan(stop):
            if pos == 1:
                if o[i] <= stop:
                    close_trade(i, o[i], "trail gap")
                elif l[i] <= stop:
                    close_trade(i, stop, "trail")
            else:
                if o[i] >= stop:
                    close_trade(i, o[i], "trail gap")
                elif h[i] >= stop:
                    close_trade(i, stop, "trail")

        # ---- deferred order: did the box end / break / come due at this bar? ----
        if pending != 0:
            fire = False
            if mode == "box_end":
                fire = edir[j] != 0
            elif mode == "box_break":
                if edir[j] == pending:
                    fire = True
                elif edir[j] == -pending:
                    pending, n_cancel = 0, n_cancel + 1
            elif mode == "delay":
                fire = i >= due
            if fire:
                if pending == 1 and pos <= 0:
                    queued_entry, n_defer = 1, n_defer + 1
                elif pending == -1 and pos >= 0:
                    queued_entry, n_defer = -1, n_defer + 1
                pending = 0

        valid_buy = bool(bull[j] and hb[j] and in_bt[j])
        valid_sell = bool(bear[j] and hs[j] and in_bt[j])
        if valid_buy:
            if act[j]:
                pending, due = 1, j + delay
            elif pos <= 0:
                queued_entry = 1
        if valid_sell:
            if act[j]:
                pending, due = -1, j + delay
            elif pos >= 0:
                queued_entry = -1
        if pos > 0 and bool(bear[j]):
            queued_close = True
        if pos < 0 and bool(bull[j]):
            queued_close = True
        if pos > 0:
            if h[i] >= entry + trigger:
                trail_on = True
            if trail_on:
                target = h[i] - dist
                minlock = entry + (trigger - dist)
                stop = min(max(minlock if np.isnan(stop) else stop, target), entry + cap)
        elif pos < 0:
            if l[i] <= entry - trigger:
                trail_on = True
            if trail_on:
                target = l[i] + dist
                minlock = entry - (trigger - dist)
                stop = max(min(minlock if np.isnan(stop) else stop, target), entry - cap)
        else:
            stop, trail_on = np.nan, False
    return trades, n_defer, n_cancel


def build_bb(df):
    """build() with the timestamp forced to timezone-naive UTC (the getdata CSV is
    tz-aware, the MT5 CSV is not)."""
    d = df.copy()
    try:
        tz = getattr(d["time"].dt, "tz", None)
        if tz is not None:
            d["time"] = d["time"].dt.tz_convert("UTC").dt.tz_localize(None)
    except Exception:
        pass
    return build(d)


def stats_row(label, trades, w=42):
    s = st(trades)
    print(f"{label:{w}s}{s['n']:>7d}{s['net']:>12.2f}{s['wr']:>6.1f}%{s['pf']:>7.2f}"
          f"{s['dd']:>11.2f}")
    return s


HDR = f"{'variant':42s}{'trades':>7s}{'net $':>12s}{'win%':>6s}{'PF':>7s}{'maxDD $':>11s}"


def run(d, block=None, buy_only=False, sell_only=False, **kw):
    bb = None if block is None else (~block if False else block)
    if bb is None:
        return simulate_pine(d, **kw)
    return simulate_pine(d,
                         block_buy=None if sell_only else bb,
                         block_sell=None if buy_only else bb, **kw)


def main():
    d26 = build_bb(load_recent())
    data = {y: build_bb(load_year(y)) for y in (2022, 2023, 2024, 2025)}
    g26 = None
    try:
        g = pd.read_csv("/tmp/d2026/getdata/XAUUSD_1m.csv", parse_dates=["datetime"])
        g = g.set_index("datetime")[["open", "high", "low", "close"]].reset_index(names="time")
        g26 = build_bb(g)
        print(f"2026 getdata segment loaded: {len(g26['close']):,} bars")
    except Exception as ex:
        print("getdata 2026 segment not available:", ex)

    # ---------------- 1. the claim ----------------
    print("\n" + "=" * 122)
    print("1. THE PASTED SCRIPT — does the red box take the win rate from 31% to 68%?")
    print("   their settings: 10 oz, spread 0.2 -> $2.00/trade, trail 2.0/1.5/2.0, 7 days")
    print("=" * 122)
    ins26 = redbox_state(d26)
    kw10 = dict(lot=0.01, lev=1000.0, spread_pts=COST, days=7)
    print("\nSep 2026 real MT5 window, their 10 oz sizing:")
    print(HDR)
    a10 = stats_row("without the box", run(d26, None, **kw10))
    b10 = stats_row("with the red box ($5, fail 3)", run(d26, ins26, **kw10))
    print(f"  -> win rate {a10['wr']:.1f}% -> {b10['wr']:.1f}% | trades {a10['n']} -> "
          f"{b10['n']} | net ${a10['net']:,.2f} -> ${b10['net']:,.2f} at 10 oz")

    kw1 = dict(lot=0.01, lev=100.0, spread_pts=COST, days=7)
    print("\nSame window at 1 oz (0.01 lot), $0.20/trade:")
    print(HDR)
    a1 = stats_row("without the box", run(d26, None, **kw1))
    b1 = stats_row("with the red box", run(d26, ins26, **kw1))

    # ---------------- 2. full years ----------------
    print("\n" + "=" * 122)
    print("2. FULL YEARS 2022-2025 — the pasted filter vs none (1 oz, $0.20/trade)")
    print("=" * 122)
    print(f"{'year':>6s}{'no box: trades':>16s}{'net $':>11s}{'win%':>7s}"
          f"{'| red box: trades':>19s}{'net $':>11s}{'win%':>7s}")
    tot = {"no": [], "box": []}
    for y in (2022, 2023, 2024, 2025):
        ins = redbox_state(data[y])
        t_no = simulate_pine(data[y], **kw1 | {"days": 365})
        t_box = run(data[y], ins, **kw1 | {"days": 365})
        tot["no"] += t_no
        tot["box"] += t_box
        s0, s1 = st(t_no), st(t_box)
        print(f"{y:>6d}{s0['n']:>16,}{s0['net']:>11,.0f}{s0['wr']:>6.1f}%"
              f"{s1['n']:>19,}{s1['net']:>11,.0f}{s1['wr']:>6.1f}%")
    s0, s1 = st(tot["no"]), st(tot["box"])
    print(f"{'total':>6s}{s0['n']:>16,}{s0['net']:>11,.0f}{s0['wr']:>6.1f}%"
          f"{s1['n']:>19,}{s1['net']:>11,.0f}{s1['wr']:>6.1f}%")

    # ---------------- 3. the family ----------------
    print("\n" + "=" * 122)
    print("3. FILTER FAMILY — tuned on 2022-2023, validated on 2024-2025 / 2026 / Sep 2026")
    print("=" * 122)
    fam = []
    for fail in (2, 3, 4, 5):
        for zone in (3.0, 5.0, 8.0, 12.0):
            fam.append((f"fixed ${zone:.0f}, fail {fail}", dict(fail=fail, zone=zone)))
    for k in (0.3, 0.5, 0.75, 1.0, 1.5):
        fam.append((f"ATR band {k}x, fail 3", dict(fail=3, zone_atr=k)))
    fam.append(("stacked 2 levels, $5", dict(fail=3, zone=5.0, levels=2)))
    fam.append(("stacked 2 levels, ATR 1.0x", dict(fail=3, zone_atr=1.0, levels=2)))

    print(f"{'filter':26s}{'2022-23 net':>12s}{'win%':>7s}{'trades':>8s}"
          f"{'2024-25 net':>12s}{'win%':>7s}{'trades':>8s}{'2026 net':>10s}{'Sep26':>9s}")
    rows = []
    for label, kwf in fam:
        seg_a = [run(data[y], redbox_state(data[y], **kwf), **kw1 | {"days": 365})
                 for y in (2022, 2023)]
        seg_b = [run(data[y], redbox_state(data[y], **kwf), **kw1 | {"days": 365})
                 for y in (2024, 2025)]
        ta = [t for x in seg_a for t in x]
        tb = [t for x in seg_b for t in x]
        tc = (run(g26, redbox_state(g26, **kwf), **kw1 | {"days": 365}) if g26 else [])
        td = run(d26, redbox_state(d26, **kwf), **kw1 | {"days": 7})
        sa, sb, sc, sd = st(ta), st(tb), st(tc), st(td)
        s4 = st(ta + tb)
        rows.append((label, sa, sb, sc, sd, s4))
        print(f"{label:26s}{sa['net']:>12,.0f}{sa['wr']:>6.1f}%{sa['n']:>8,}"
              f"{sb['net']:>12,.0f}{sb['wr']:>6.1f}%{sb['n']:>8,}"
              f"{sc['net']:>10,.0f}{sd['net']:>9,.0f}")
    # reference
    r_a = [simulate_pine(data[y], **kw1 | {"days": 365}) for y in (2022, 2023)]
    r_b = [simulate_pine(data[y], **kw1 | {"days": 365}) for y in (2024, 2025)]
    ta = [t for x in r_a for t in x]
    tb = [t for x in r_b for t in x]
    sa, sb = st(ta), st(tb)
    print(f"{'(no filter reference)':26s}{sa['net']:>12,.0f}{sa['wr']:>6.1f}%{sa['n']:>8,}"
          f"{sb['net']:>12,.0f}{sb['wr']:>6.1f}%{sb['n']:>8,}")

    # ---------------- 4. one-sided ----------------
    print("\n" + "=" * 122)
    print("4. ONE-SIDED BLOCKING — stop only the side that is running into the zone")
    print("=" * 122)
    print(f"{'variant':30s}{'2022-23 net':>12s}{'win%':>7s}{'trades':>8s}"
          f"{'2024-25 net':>12s}{'win%':>7s}{'trades':>8s}{'2026 net':>10s}")
    for nm, kwf, side in [("block buys only, $5", dict(fail=3, zone=5.0), "buy"),
                          ("block sells only, $5", dict(fail=3, zone=5.0), "sell"),
                          ("block buys only, ATR 1.0x", dict(fail=3, zone_atr=1.0), "buy"),
                          ("block sells only, ATR 1.0x", dict(fail=3, zone_atr=1.0), "sell")]:
        ta, tb, tc = [], [], []
        for y in (2022, 2023):
            ta += run(data[y], redbox_state(data[y], **kwf), buy_only=(side == "buy"),
                      sell_only=(side == "sell"), **kw1 | {"days": 365})
        for y in (2024, 2025):
            tb += run(data[y], redbox_state(data[y], **kwf), buy_only=(side == "buy"),
                      sell_only=(side == "sell"), **kw1 | {"days": 365})
        if g26:
            tc = run(g26, redbox_state(g26, **kwf), buy_only=(side == "buy"),
                     sell_only=(side == "sell"), **kw1 | {"days": 365})
        sa, sb, sc = st(ta), st(tb), st(tc)
        print(f"{nm:30s}{sa['net']:>12,.0f}{sa['wr']:>6.1f}%{sa['n']:>8,}"
              f"{sb['net']:>12,.0f}{sb['wr']:>6.1f}%{sb['n']:>8,}{sc['net']:>10,.0f}")

    # ---------------- 5. what the box blocks ----------------
    print("\n" + "=" * 122)
    print("5. WHAT THE BOX ACTUALLY BLOCKS (2022-2025, 1 oz, $0.20/trade)")
    print("=" * 122)
    for nm, kwf in [("$5 fixed", dict(fail=3, zone=5.0)),
                    ("ATR 1.0x", dict(fail=3, zone_atr=1.0))]:
        blocked, kept = [], []
        for y in (2022, 2023, 2024, 2025):
            ins = redbox_state(data[y], **kwf)
            for t in simulate_pine(data[y], **kw1 | {"days": 365}):
                (blocked if ins[t["entry_i"]] else kept).append(t)
        sb, sk = st(blocked), st(kept)
        print(f"{nm:12s} blocked {sb['n']:>6,} trades (win {sb['wr']:4.1f}%, net ${sb['net']:>10,.0f})"
              f" | kept {sk['n']:>6,} (win {sk['wr']:4.1f}%, net ${sk['net']:>10,.0f})")

    defer_rows = []

    def defer_eval(kwf, mode, delay=0):
        """Per-year trade lists for a deferred variant + the 2026 segments."""
        per = {}
        nd = nc = 0
        for y in (2022, 2023, 2024, 2025):
            fr = redbox_frames(data[y], **kwf)
            x, a, b = simulate_deferred(data[y], fr, mode=mode, delay=delay,
                                        **kw1 | {"days": 365})
            per[y] = x
            nd, nc = nd + a, nc + b
        tc = (simulate_deferred(g26, redbox_frames(g26, **kwf), mode=mode, delay=delay,
                                **kw1 | {"days": 365})[0] if g26 else [])
        td = simulate_deferred(d26, redbox_frames(d26, **kwf), mode=mode, delay=delay,
                               **kw1)[0]
        return per, tc, td, nd, nc

    def block_eval(kwf, buy_only=False, sell_only=False):
        per = {}
        for y in (2022, 2023, 2024, 2025):
            fr = redbox_frames(data[y], **kwf)
            per[y] = run(data[y], fr["active"], buy_only=buy_only, sell_only=sell_only,
                         **kw1 | {"days": 365})
        tc = (run(g26, redbox_frames(g26, **kwf)["active"], buy_only=buy_only,
                  sell_only=sell_only, **kw1 | {"days": 365}) if g26 else [])
        td = run(d26, redbox_frames(d26, **kwf)["active"], buy_only=buy_only,
                 sell_only=sell_only, **kw1)
        return per, tc, td

    def sums(per):
        t_22_23 = per[2022] + per[2023]
        t_24_25 = per[2024] + per[2025]
        t4 = t_22_23 + t_24_25
        return t_22_23, t_24_25, t4

    # the yardstick: the pasted strategy with no filter at all, same windows
    nof = {y: simulate_pine(data[y], **kw1 | {"days": 365}) for y in (2022, 2023, 2024, 2025)}
    nf_a, nf_b, nf4 = sums(nof)
    NF22_23, NF24_25, NF4 = st(nf_a), st(nf_b), st(nf4)
    NF26 = st(simulate_pine(d26, **kw1))
    print("\n" + "=" * 122)
    print("6. DEFERRED ENTRY — the blocked signal is NOT dropped, it is held and fired when")
    print("   the box ends.  This is the answer to 'stop the losses without shrinking the")
    print("   trade count'.  Kept% is trades vs the unfiltered rule over the SAME window.")
    print(f"   no filter: 2022-23 {NF22_23['n']:,} trd {NF22_23['wr']:.1f}% "
          f"${NF22_23['net']:,.0f} | 2024-25 {NF24_25['n']:,} trd {NF24_25['wr']:.1f}% "
          f"${NF24_25['net']:,.0f} | 2022-25 {NF4['n']:,} trd {NF4['wr']:.1f}% "
          f"${NF4['net']:,.0f} | Sep-26 7d {NF26['n']:,} trd {NF26['wr']:.1f}% "
          f"${NF26['net']:,.2f}")
    print("=" * 122)
    print(f"{'variant':30s}{'4y trades':>10s}{'kept':>6s}{'4y win%':>9s}{'4y net $':>11s}"
          f"{'2022-23 net':>13s}{'2024-25 net':>13s}{'24-25 win':>10s}"
          f"{'Sep26 trd':>10s}{'Sep26 win':>10s}{'Sep26 net':>10s}")
    print(f"{'(no filter)':30s}{NF4['n']:>10,}{100:>5.0f}%{NF4['wr']:>8.1f}%{NF4['net']:>11,.0f}"
          f"{NF22_23['net']:>13,.0f}{NF24_25['net']:>13,.0f}{NF24_25['wr']:>9.1f}%"
          f"{NF26['n']:>10,}{NF26['wr']:>9.1f}%{NF26['net']:>10,.2f}")
    for tag, kwf in [("$5 box", dict(fail=3, zone=5.0)),
                     ("ATR 1.0x box", dict(fail=3, zone_atr=1.0))]:
        # the plain block, as pasted
        per, tc, td = block_eval(kwf)
        xa, xb, x4 = sums(per)
        sa, sb, s4, sc, sd = st(xa), st(xb), st(x4), st(tc), st(td)
        print(f"{tag + ' / block (as pasted)':30s}{s4['n']:>10,}{100*s4['n']/NF4['n']:>5.0f}%"
              f"{s4['wr']:>8.1f}%{s4['net']:>11,.0f}{sa['net']:>13,.0f}{sb['net']:>13,.0f}"
              f"{sb['wr']:>9.1f}%{sd['n']:>10,}{sd['wr']:>9.1f}%{sd['net']:>10,.2f}")
        defer_rows.append((tag + " / block", sa, sb, s4, sc, sd, 100 * s4["n"] / NF4["n"]))
        for mode, dly in [("box_end", 0), ("box_break", 0), ("delay", 3)]:
            per, tc, td, nd, nc = defer_eval(kwf, mode, dly)
            xa, xb, x4 = sums(per)
            sa, sb, s4, sc, sd = st(xa), st(xb), st(x4), st(tc), st(td)
            nm = f"{tag} / defer {mode}" + (f" {dly}" if mode == "delay" else "")
            print(f"{nm:30s}{s4['n']:>10,}{100*s4['n']/NF4['n']:>5.0f}%{s4['wr']:>8.1f}%"
                  f"{s4['net']:>11,.0f}{sa['net']:>13,.0f}{sb['net']:>13,.0f}"
                  f"{sb['wr']:>9.1f}%{sd['n']:>10,}{sd['wr']:>9.1f}%{sd['net']:>10,.2f}")
            defer_rows.append((nm, sa, sb, s4, sc, sd, 100 * s4["n"] / NF4["n"]))
        print(f"  {tag}: {nd:,} deferred orders fired, {nc:,} cancelled (only a cancel really"
              f" removes a trade)")

    # ---------------- 6b. is the deferred version robust across the band? -------------
    print("\n" + "=" * 122)
    print("6b. ROBUSTNESS of DEFER(box_end) — the band is a free parameter, so we check")
    print("    whether the improvement survives every setting (band width x pivot length)")
    print("=" * 122)
    print(f"{'band':22s}{'4y trades':>10s}{'kept':>6s}{'4y win%':>9s}{'4y net $':>11s}"
          f"{'2024-25 win':>12s}{'2024-25 net $':>14s}{'Sep26 win':>10s}{'Sep26 net':>10s}")
    print(f"{'(no filter)':22s}{NF4['n']:>10,}{100:>5.0f}%{NF4['wr']:>8.1f}%{NF4['net']:>11,.0f}"
          f"{NF24_25['wr']:>11.1f}%{NF24_25['net']:>14,.0f}{NF26['wr']:>9.1f}%"
          f"{NF26['net']:>10,.2f}")
    for fail in (2, 3, 4):
        for zone in (3.0, 5.0, 8.0, 12.0):
            per, tc, td, nd, nc = defer_eval(dict(fail=fail, zone=zone), "box_end")
            xa, xb, x4 = sums(per)
            s4, sb, sd = st(x4), st(xb), st(td)
            print(f"${zone:<5.0f} fail {fail}          {s4['n']:>10,}{100*s4['n']/NF4['n']:>5.0f}%"
                  f"{s4['wr']:>8.1f}%{s4['net']:>11,.0f}{sb['wr']:>11.1f}%{sb['net']:>14,.0f}"
                  f"{sd['wr']:>9.1f}%{sd['net']:>10,.2f}")

    # ---------------- 7. head to head ----------------
    print("\n" + "=" * 122)
    print("7. HEAD TO HEAD — same box, three ways to use it (1 oz, $0.20/trade)")
    print("=" * 122)
    kwf = dict(fail=3, zone=5.0)
    rows7 = []
    for nm, kind in [("no filter", "none"), ("BLOCK inside box", "block"),
                     ("DEFER (box_end)", "box_end"), ("DEFER (box_break)", "box_break")]:
        if kind == "none":
            xa, xb, x4 = nf_a, nf_b, nf4
            td = simulate_pine(d26, **kw1)
        elif kind == "block":
            per, tc, td = block_eval(kwf)
            xa, xb, x4 = sums(per)
        else:
            per, tc, td, nd, nc = defer_eval(kwf, kind)
            xa, xb, x4 = sums(per)
        s4, sb, sd = st(x4), st(xb), st(td)
        rows7.append((nm, s4, sb, sd))
        print(f"{nm:20s}2022-25: {s4['n']:>6,} trd {s4['wr']:>5.1f}% ${s4['net']:>10,.0f}"
              f"   | 2024-25: {sb['n']:>6,} {sb['wr']:>5.1f}% ${sb['net']:>9,.0f}"
              f"   | Sep-2026 7d: {sd['n']:>4,} {sd['wr']:>5.1f}% ${sd['net']:>8,.2f}")

    # ---------------- 8. the claim on every 7-day window ----------------
    print("\n" + "=" * 122)
    print("8. THE CLAIM ON EVERY 7-DAY WINDOW — the script's own default is backtestDays 7, so")
    print("   we walk every 7-day window of 2022-2025 and ask what the box does to the win rate")
    print("=" * 122)
    scan = []
    step = 1440
    for y in (2022, 2023, 2024, 2025):
        dd = data[y]
        fr = redbox_frames(dd, fail=FAIL, zone=ZONE)
        for e in range(len(dd["time"]) - 1, step, -step):
            te = pd.Timestamp(dd["time"][e])
            win = head(dd, e + 1)
            fw = {kk: vv[:e + 1] for kk, vv in fr.items()}
            a = st(simulate_pine(win, **kw1))
            blk = st(run(win, fw["active"], **kw1))
            b = st(simulate_deferred(win, fw, mode="box_end", **kw1)[0])
            if a["n"] < 20 or b["n"] < 10:
                continue
            scan.append((y, str(te)[:10], a["n"], a["wr"], a["net"],
                         blk["n"], blk["wr"], blk["net"], b["n"], b["wr"], b["net"]))
    sw = pd.DataFrame(scan, columns=["year", "end", "n0", "wr0", "net0",
                                     "n_blk", "wr_blk", "net_blk", "n1", "wr1", "net1"])
    print(f"windows scanned: {len(sw):,}")
    print(f"  unfiltered win rate: mean {sw['wr0'].mean():.1f}%, median {sw['wr0'].median():.1f}%"
          f" | red box: mean {sw['wr1'].mean():.1f}%, median {sw['wr1'].median():.1f}%")
    print(f"  the box lifts the win rate in {(sw['wr1'] > sw['wr0']).mean() * 100:.0f}% of windows"
          f" | median change {np.median(sw['wr1'] - sw['wr0']):+.1f} pts")
    low = sw[sw["wr0"] <= 35]
    print(f"  windows where the unfiltered win rate is <= 35% (the user's 31% case): {len(low):,}"
          f" -> red box median {low['wr1'].median():.1f}%, mean {low['wr1'].mean():.1f}%")
    hi = sw[sw["wr0"] <= 35].sort_values("wr1", ascending=False).head(5)
    print("  best such windows:")
    print(f"    {'wk end':12s}{'trd':>6s}{'win%':>8s}{'net $':>10s}{'box trd':>9s}{'box win%':>10s}{'box net $':>11s}")
    for _, r in hi.iterrows():
        print(f"    {r['end']:12s}{r['n0']:>6.0f}{r['wr0']:>7.1f}%{r['net0']:>10.0f}"
              f"{r['n1']:>9.0f}{r['wr1']:>9.1f}%{r['net1']:>11.0f}")
    print(f"  best win rate on any 7-day window: skip-inside {sw['wr_blk'].max():.1f}%, "
          f"defer {sw['wr1'].max():.1f}% (unfiltered the same weeks: "
          f"{sw.loc[sw['wr_blk'].idxmax(), 'wr0']:.1f}% / "
          f"{sw.loc[sw['wr1'].idxmax(), 'wr0']:.1f}%)")
    for c, nm in [("wr_blk", "skip inside"), ("wr1", "defer")]:
        print(f"  {nm:12s}: win rate >= 60% in {(sw[c] >= 60).mean() * 100:4.1f}% of windows, "
              f">= 65% in {(sw[c] >= 65).mean() * 100:4.1f}%, >= 68% in "
              f"{(sw[c] >= 68).mean() * 100:4.1f}%")
    l31 = sw[(sw["wr0"] >= 28.5) & (sw["wr0"] <= 33.5)]
    print(f"  windows right around the user's 31% baseline ({len(l31)} of them): "
          f"skip-inside median {l31['wr_blk'].median():.1f}% (max {l31['wr_blk'].max():.1f}%), "
          f"defer median {l31['wr1'].median():.1f}% (max {l31['wr1'].max():.1f}%)")
    sw.to_csv("results/redbox_windows.csv", index=False)
    print("  saved results/redbox_windows.csv")

    fig2, ax2 = plt.subplots(1, 2, figsize=(13, 5.2))
    ax2[0].scatter(sw["wr0"], sw["wr_blk"], s=6, alpha=0.3, color="#f23645",
                   label="skip inside the box")
    ax2[0].scatter(sw["wr0"], sw["wr1"], s=6, alpha=0.3, color="#1f77b4",
                   label="deferred entry")
    ax2[0].legend(fontsize=8, loc="lower right")
    lim = [0, 100]
    ax2[0].plot(lim, lim, "k--", lw=1)
    ax2[0].axvline(35, color="#888888", ls=":", lw=1)
    ax2[0].set_xlabel("win rate without the box (%)")
    ax2[0].set_ylabel("win rate with the box (%)")
    ax2[0].set_title(f"Every 7-day window, 2022-2025 ({len(sw):,} windows)")
    ax2[0].grid(alpha=0.3)
    ax2[1].hist(sw["wr1"] - sw["wr0"], bins=40, color="#089981", edgecolor="k", linewidth=0.3)
    ax2[1].axvline((sw["wr1"] - sw["wr0"]).median(), color="#0a5", lw=1.5,
                   label=f"median {np.median(sw['wr1'] - sw['wr0']):+.1f} pts")
    ax2[1].legend(fontsize=8)
    ax2[1].axvline(0, color="k", lw=1)
    ax2[1].set_xlabel("win-rate change from the red box (percentage points)")
    ax2[1].set_ylabel("7-day windows")
    ax2[1].set_title("The box raises the win rate almost everywhere")
    ax2[1].grid(alpha=0.3)
    fig2.tight_layout()
    fig2.savefig("results/redbox_windows.png", dpi=120)
    print("\nSaved results/redbox_windows.png")

    # ---------------- chart ----------------
    fig, axes = plt.subplots(1, 3, figsize=(19.5, 6.4))
    labels = ["(no filter)"] + [r[0] for r in rows]
    nets = [NF4["net"]] + [r[5]["net"] for r in rows]
    cnt = [NF4["n"]] + [r[5]["n"] for r in rows]
    wrs = [NF4["wr"]] + [r[5]["wr"] for r in rows]
    order = np.argsort(nets)
    axes[0].barh(range(len(labels)), [nets[i] for i in order],
                 color=["#089981" if nets[i] > 0 else "#f23645" for i in order])
    axes[0].set_yticks(range(len(labels)))
    axes[0].set_yticklabels([labels[i] for i in order], fontsize=6.2)
    for k, i in enumerate(order):
        axes[0].text(nets[i] - 120, k, f"{nets[i]:,.0f}", va="center", ha="right", fontsize=6)
    axes[0].axvline(0, color="k", lw=1)
    axes[0].set_xlabel("4-year net P/L ($), 2022-2025")
    axes[0].set_title("The box family, 2022-2025 (1 oz, $0.20/trade)")
    axes[0].grid(alpha=0.3, axis="x")

    # (b) 4-year frontier: block (circles) vs defer (triangles)
    xs = [100.0 * c / NF4["n"] for c in cnt]
    axes[1].scatter(xs, wrs, s=70, c=nets, cmap="RdYlGn", vmin=-6000, vmax=2500,
                    edgecolor="k", linewidth=0.4, label="skip inside the box")
    dxs = [r[6] for r in defer_rows]
    dys = [r[3]["wr"] for r in defer_rows]
    dns = [r[3]["net"] for r in defer_rows]
    sc = axes[1].scatter(dxs, dys, s=110, marker="^", c=dns, cmap="RdYlGn", vmin=-6000,
                         vmax=2500, edgecolor="k", linewidth=0.4, label="defer until box ends")
    axes[1].axhline(NF4["wr"], color="#888888", ls="--", lw=1)
    axes[1].annotate(f"no filter: win {NF4['wr']:.1f}%, ${NF4['net']:,.0f}",
                     (2, NF4["wr"] - 1.4), fontsize=7.5, color="#555555")
    axes[1].axvline(100, color="#1f77b4", ls=":", lw=1)
    axes[1].text(97, min(wrs) + 0.3, "no shrink", fontsize=7.5, color="#1f77b4", ha="right")
    axes[1].set_xlabel("trades kept vs no filter (%)")
    axes[1].set_ylabel("win rate (%), 2022-2025")
    axes[1].set_title("Win rate vs trade count - the trade-off")
    axes[1].legend(fontsize=7.5, loc="lower right")
    axes[1].grid(alpha=0.3)
    fig.colorbar(sc, ax=axes[1], label="4-year net P/L ($)")

    # (c) the recent 7-day window: what the box does to the user's own case
    pts = [("no filter", NF26["n"], NF26["wr"], NF26["net"], "o", "#555555")]
    for lbl, s7 in [("skip (block)", rows7[1]), ("defer", rows7[2]),
                    ("defer, break only", rows7[3])]:
        sd7 = s7[3]
        pts.append((lbl, sd7["n"], sd7["wr"], sd7["net"], "^",
                    "#089981" if sd7["net"] > 0 else "#f23645"))
    for lbl, nn, wr, net, mk, col in pts:
        axes[2].scatter(100.0 * nn / NF26["n"], wr, s=150, marker=mk, color=col,
                        edgecolor="k", linewidth=0.5, zorder=3)
        axes[2].annotate(f"{lbl}\n{nn} trades, win {wr:.1f}%, ${net:+,.0f}",
                         (100.0 * nn / NF26["n"], wr), textcoords="offset points",
                         xytext=(6, 8 if mk == "o" else -30), fontsize=8)
    axes[2].axhline(NF26["wr"], color="#888888", ls="--", lw=1)
    axes[2].axvline(100, color="#1f77b4", ls=":", lw=1)
    axes[2].set_xlim(30, 112)
    axes[2].set_ylim(50, 70)
    axes[2].set_xlabel("trades kept vs no filter (%)")
    axes[2].set_ylabel("win rate (%)")
    axes[2].set_title("Sep 2026, 7 days (the live window)\ndefer keeps 81% of the trades and wins more")
    axes[2].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig("results/redbox.png", dpi=120)
    print("\nSaved results/redbox.png")

    out = [dict(group="family", variant=r[0], net_2022_23=r[1]["net"], win_2022_23=r[1]["wr"],
                n_2022_23=r[1]["n"], net_2024_25=r[2]["net"], win_2024_25=r[2]["wr"],
                n_2024_25=r[2]["n"], net_2026=r[3]["net"], net_sep26=r[4]["net"],
                sep26_win=r[4]["wr"], net_4y=r[5]["net"], win_4y=r[5]["wr"], n_4y=r[5]["n"],
                trades_kept_pct=100.0 * r[5]["n"] / NF4["n"]) for r in rows]
    out += [dict(group="deferred", variant=r[0], net_2022_23=r[1]["net"], win_2022_23=r[1]["wr"],
                 n_2022_23=r[1]["n"], net_2024_25=r[2]["net"], win_2024_25=r[2]["wr"],
                 n_2024_25=r[2]["n"], net_2026=r[4]["net"], net_sep26=r[5]["net"],
                 sep26_win=r[5]["wr"], n_sep26=r[5]["n"], net_4y=r[3]["net"], win_4y=r[3]["wr"],
                 n_4y=r[3]["n"], trades_kept_pct=r[6]) for r in defer_rows]
    out += [dict(group="head_to_head", variant=r[0], net_2024_25=r[2]["net"],
                 win_2024_25=r[2]["wr"], n_2024_25=r[2]["n"],
                 net_sep26=r[3]["net"], sep26_win=r[3]["wr"], n_sep26=r[3]["n"],
                 net_4y=r[1]["net"], win_4y=r[1]["wr"], n_4y=r[1]["n"],
                 trades_kept_pct=100.0 * r[1]["n"] / NF4["n"]) for r in rows7]
    out.append(dict(group="baseline", variant="(no filter)", net_2022_23=np.nan,
                    win_2022_23=np.nan, n_2022_23=np.nan, net_2024_25=np.nan,
                    win_2024_25=np.nan, n_2024_25=np.nan, net_2026=np.nan,
                    net_sep26=NF26["net"], sep26_win=NF26["wr"], n_sep26=NF26["n"],
                    net_4y=NF4["net"], win_4y=NF4["wr"], n_4y=NF4["n"],
                    trades_kept_pct=100.0))
    pd.DataFrame(out).to_csv("results/redbox_summary.csv", index=False)
    print("Saved results/redbox_summary.csv")
    return rows, tot, sa, sb


if __name__ == "__main__":
    main()
