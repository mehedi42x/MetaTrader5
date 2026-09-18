# EMA 6/9 + Bollinger (M1) with EMA 9/12 trend (M5) — REAL recent data

Data: `data/xauusd_m1_2026-09.csv` — 9,744 real XAUUSD M1 bars from an Exness MT5 feed (09 Sep 19:08 -> 18 Sep 20:54 UTC), reconstructed from the public mirror github.com/lbronight/xau-live-mirror. Only the daily 1-hour break and the weekend are missing (plus a few stray minutes).

19 September 2026 is a Saturday — no bars exist. Data was downloaded right after the Friday close (sandbox clock: 2026-09-18 21:xx UTC).

| window | trades | net $ | win% | PF | max DD $ | avg/trade |
|---|---|---|---|---|---|---|
| Last 3 sessions (16-18 Sep) | 130 | $110.97 | 29.2% | 1.57 | $-38.49 | $+0.854 |
| Last 5 sessions (14-18 Sep) | 230 | $148.84 | 31.7% | 1.44 | $-48.44 | $+0.647 |
| Last 5 sessions, M5 chart (14-18 Sep) | 16 | $39.41 | 31.2% | 1.83 | $-12.52 | $+2.463 |

| day | trades | net $ | win% |
|---|---|---|---|
| Mon 14 Sep 2026 | 41 | $50.34 | 39.0% |
| Tue 15 Sep 2026 | 59 | $-12.47 | 32.2% |
| Wed 16 Sep 2026 | 50 | $28.49 | 26.0% |
| Thu 17 Sep 2026 | 42 | $43.39 | 26.2% |
| Fri 18 Sep 2026 | 38 | $39.09 | 36.8% |

Chart: results/ema_recent_2026.png
