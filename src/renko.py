"""Classic fixed-brick Renko construction from M15 bars.

Uses intrabar high/low. One direction per bar (if a bar spans both brick
levels, direction is decided by close vs last brick close) — this avoids
whipsaw oscillation and matches common renko implementations.
"""
import pandas as pd

MAX_BRICKS_PER_BAR = 500  # safety cap


def build_renko(df: pd.DataFrame, brick: float) -> pd.DataFrame:
    """Build renko bricks. Returns DataFrame(time, open, high, low, close, direction).

    - Brick size fixed at `brick` price units (e.g. 0.50 USD = 50 points on gold).
    - Brick time = M15 bar time when it completed; open = prev brick close.
    """
    df = df.sort_values("time").reset_index(drop=True)
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    c = df["close"].to_numpy()
    t = pd.to_datetime(df["time"]).to_numpy()

    bricks = []
    last = float(c[0])  # anchor at first close
    for i in range(len(df)):
        hi, lo, cl = float(h[i]), float(l[i]), float(c[i])
        up_possible = hi >= last + brick
        dn_possible = lo <= last - brick
        if not up_possible and not dn_possible:
            continue
        # one direction per bar
        if up_possible and dn_possible:
            going_up = cl >= last
        else:
            going_up = up_possible
        n = 0
        while n < MAX_BRICKS_PER_BAR:
            if going_up:
                lvl = last + brick
                if hi < lvl:
                    break
            else:
                lvl = last - brick
                if lo > lvl:
                    break
            bricks.append(dict(
                time=t[i], open=last, close=lvl,
                high=max(last, lvl), low=min(last, lvl),
                direction=1 if going_up else -1,
            ))
            last = lvl
            n += 1
    out = pd.DataFrame(bricks)
    out["time"] = pd.to_datetime(out["time"])
    return out
