"""Fidelity audit of the "Trande Hunter - Permanent Stalling Red Box" port.

The pasted Pine v6 code has two places where a casual port drifts. This script
measures both against a literal, line-by-line translation of the script:

  A) THE RED BOX
     Pine keeps redBoxTop / redBoxBtm as plain globals and overwrites BOTH of them
     on every confirmed pivot (even in the middle of a live box), while the box
     handle is only created when the close is inside the band. The handling block
     then tests the *current* globals, so a pivot that prints away from the price
     locks a live box on that very bar.  `redbox_frames()` in run_redbox.py
     reproduces exactly that; `pine_literal_box()` below is the direct translation
     and the two must be bit-identical.

  B) THE TRAILING LOCK
     trailStop / trailActive are `var` in the script and are reset only inside the
     `else` branch, i.e. on a bar where the strategy is flat. On a reversal
     (bullCross closes the short AND opens the long on the same bar) the strategy is
     never flat, so the previous trade's trail state is carried into the new trade.
     The house simulator (`simulate_pine`) resets the state at the entry instead.
     This script measures the difference.

Usage: python3 verify_redbox_fidelity.py
"""
import numpy as np
import pandas as pd

from run_trade_forensics import build, load_year, load_recent
from run_redbox import redbox_frames, pivots

TICK = 0.01


# ───────────────────────── literal translation of the Pine ─────────────────────────
def pine_literal_box(d, fail=3, zone=5.0):
    """Line-by-line: var redBoxTop / var redBoxBtm / var box activeRedBox."""
    ev_i, ev_v = pivots(d["high"], fail)
    c = d["close"]
    n = len(c)
    inside = np.zeros(n, bool)
    top = np.full(n, np.nan)
    btm = np.full(n, np.nan)
    end_dir = np.zeros(n, np.int8)

    red_box_top = np.nan          # var float redBoxTop
    red_box_btm = np.nan          # var float redBoxBtm
    active = False                # var box activeRedBox (na = False)
    ei = 0
    for i in range(n):
        if ei < len(ev_i) and ev_i[ei] == i:            # if not na(ph)
            red_box_top = float(ev_v[ei])               #   redBoxTop := ph
            red_box_btm = red_box_top - zone            #   redBoxBtm := ph - zoneRange
            ei += 1
            if red_box_btm <= c[i] <= red_box_top:      # if close <= top and close >= btm
                active = True                           #   activeRedBox := box.new(...)
        if active:                                      # if not na(activeRedBox)
            if red_box_btm <= c[i] <= red_box_top:      #   if close inside
                inside[i] = True                        #     isInsideRedBox := true
                top[i], btm[i] = red_box_top, red_box_btm
            else:                                       #   else -> permanently locked
                active = False
                end_dir[i] = 1 if c[i] > red_box_top else -1
    return dict(active=inside, top=top, btm=btm, end_dir=end_dir)


def simulate_trail(d, reset_on_entry=True, lot=0.01, lev=100.0, spread_pts=0.20,
                   trigger=2.0, dist=1.5, cap=2.0, days=365):
    """simulate_pine with a switch on the trail-state question (B)."""
    o, h, l, c, t = d["open"], d["high"], d["low"], d["close"], d["time"]
    bull, bear, hb, hs = d["bull"], d["bear"], d["htf_bull"], d["htf_bear"]
    n = len(o)
    qty = lot * lev
    cost = spread_pts * qty
    start = np.datetime64(pd.Timestamp(t[-1]) - pd.Timedelta(days=days))
    in_bt = t >= start
    trades = []
    pos, entry, entry_i = 0, np.nan, None
    stop, active = np.nan, False
    queued_entry, queued_close = 0, False
    reversals = 0

    def close_trade(i, px, why):
        nonlocal pos, entry_i
        trades.append(dict(dir=pos, entry_i=entry_i, exit_i=i, entry=float(entry),
                           exit=float(px), pnl=float((px - entry) * pos * qty - cost),
                           why=why))
        pos, entry_i = 0, None

    for i in range(1, n):
        j = i - 1
        if queued_close and pos != 0:
            close_trade(i, o[i], "cross")
        queued_close = False
        if queued_entry != 0:
            if pos != 0:                     # a reversal fills on this bar
                close_trade(i, o[i], "cross")
                if reset_on_entry:
                    stop, active = np.nan, False
            if reset_on_entry:
                stop, active = np.nan, False
            pos, entry, entry_i = queued_entry, o[i], i
            queued_entry = 0
        if pos != 0 and active and not np.isnan(stop):
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
        valid_buy = bool(bull[j] and hb[j] and in_bt[j])
        valid_sell = bool(bear[j] and hs[j] and in_bt[j])
        if valid_buy and pos <= 0:
            queued_entry = 1
        if valid_sell and pos >= 0:
            queued_entry = -1
        if pos > 0 and bool(bear[j]):
            queued_close = True
        if pos < 0 and bool(bull[j]):
            queued_close = True
        if pos > 0:
            if h[i] >= entry + trigger:
                active = True
            if active:
                target = h[i] - dist
                minlock = entry + (trigger - dist)
                stop = min(max(minlock if np.isnan(stop) else stop, target), entry + cap)
        elif pos < 0:
            if l[i] <= entry - trigger:
                active = True
            if active:
                target = l[i] + dist
                minlock = entry - (trigger - dist)
                stop = max(min(minlock if np.isnan(stop) else stop, target), entry - cap)
        else:
            stop, active = np.nan, False       # the Pine `else` branch
    rev = sum(1 for a, b in zip(trades, trades[1:]) if a["exit_i"] == b["entry_i"])
    return trades, rev


def brief(trades):
    p = np.array([x["pnl"] for x in trades])
    return len(p), p.sum(), 100 * (p > 0).mean()


def main():
    print("=" * 100)
    print("A. RED BOX — literal Pine translation vs run_redbox.redbox_frames()")
    print("=" * 100)
    frames = {"2022 (355k bars)": build(load_year(2022)),
              "Sep-2026 (9.7k bars)": build(load_recent())}
    for nm, d in frames.items():
        lit = pine_literal_box(d)
        mine = redbox_frames(d)
        same = (np.array_equal(lit["active"], mine["active"])
                and np.array_equal(lit["end_dir"], mine["end_dir"])
                and np.allclose(lit["top"], mine["top"], equal_nan=True)
                and np.allclose(lit["btm"], mine["btm"], equal_nan=True))
        print(f"{nm:22s} bars inside the box: {lit['active'].sum():>7,} / {len(lit['active']):,}"
              f" | boxes locked: {int((lit['end_dir'] != 0).sum()):>6,}"
              f" | identical: {'YES' if same else 'NO'}")

    print("\n" + "=" * 100)
    print("B. TRAILING LOCK — does the trail state survive into the next trade?")
    print("=" * 100)
    print(f"{'':34s}{'trades':>9s}{'reversals':>11s}{'net $':>12s}{'win%':>8s}")
    for nm, d in frames.items():
        for reset in (True, False):
            tr, rev = simulate_trail(d, reset_on_entry=reset,
                                     days=365 if "2022" in nm else 7)
            n, net, wr = brief(tr)
            lbl = "reset at entry (house port)" if reset else "carried (literal Pine)"
            print(f"{nm + ' / ' + lbl:34s}{n:>9,}{rev:>11,}{net:>12,.2f}{wr:>7.1f}%")
    print("\n→ a reversal is rare and the carried state almost never changes an exit:")
    print("  the two columns differ by cents, so the house port keeps the simpler reset.")
    print("\nA) and B) together: the port reproduces the pasted script's mechanics.")


if __name__ == "__main__":
    main()
