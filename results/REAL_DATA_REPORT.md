# REAL TICK DATA BACKTEST — XAUUSD 0.01 lot @ 800x

### Data: your uploaded HistData archives · 12,799,655 real ticks

---

## THE HEADLINE — read this first

The strategy **loses money on your real tick data.**

| | Synthetic data (earlier) | **YOUR REAL DATA** |
|---|---|---|
| Net profit | +$218.96 | **−$979.93** |
| Return | +21.90% | **−97.99%** |
| Profit factor | 2.49 | **0.086** |
| Win rate | 68.63% | **11.33%** |
| Profitable days | 19 / 20 | **0 / 83** |

An account of $1,000 ends at **$20.07**. Not a single profitable day in 83.

I am reporting this rather than tuning the parameters until the curve looks
good, because the underlying analysis below shows the problem is **not**
fixable by tuning.

---

## 1. Data actually used

| Item | Value |
|---|---|
| Source | `HISTDATA_COM_ASCII_XAUUSD_T{202401,202402,202403,202608}.zip` |
| Total ticks | **12,799,655** |
| Period | 2024-01-01 → 2026-08-28 |
| Trading days | 83 |
| Gold price range | ~$2,045 → ~$4,084 |
| Ticks per day | ~125,487 |
| Median tick gap | 0.102 s |

Note the months are non-contiguous (Jan/Feb/Mar 2024, then Aug 2026), so
month-to-month continuity is broken — but that does not affect the conclusion.

---

## 2. Overall results

| Metric | Value |
|---|---|
| Initial balance | $1,000.00 |
| **Final balance** | **$20.07** |
| **Net profit** | **−$979.93** |
| **Return** | **−97.99%** |
| Total trades | 2,445 |
| **Winning trades** | **277 (11.33%)** |
| **Losing trades** | **2,168 (88.67%)** |
| Gross profit | $92.39 |
| Gross loss | −$1,072.32 |
| **Profit factor** | **0.086** |
| Expectancy | **−$0.4008 / trade** |
| Avg win / avg loss | $0.3335 / −$0.4946 |
| Payoff ratio | 0.674 |
| Max drawdown | **−97.99%** |

### Month by month

| Month | Trades | Net P&L | Win rate |
|---|---|---|---|
| 2024-01 | 1,527 | **−$591.72** | 12.97% |
| 2024-02 | 601 | **−$237.91** | 5.66% |
| 2024-03 | 241 | **−$98.29** | 8.30% |
| 2026-08 | 76 | **−$52.01** | 32.89% |

Every month negative.

### Daily

| Metric | Value |
|---|---|
| Trading days | 83 |
| **Profitable days** | **0** |
| **Losing days** | **83** |
| Max trades in one day | 106 (2024-01-03) |
| Min trades in one day | 1 (2026-08-14) |
| Avg trades / day | 29.46 |
| Best day | −$1.61 |
| Worst day | −$39.82 |

### Exit reasons

| Exit | Trades | Net P&L |
|---|---|---|
| stop_loss | 948 | −$588.70 |
| flow_flip | 1,212 | −$459.67 |
| take_profit | 49 | +$39.92 |
| trail | 130 | +$34.95 |
| time_stop | 106 | −$6.44 |

Only 49 trades out of 2,445 (2%) ever reached target.

---

## 3. WHY — the diagnosis

### 3.1 Costs alone exceed the entire edge

| | |
|---|---|
| Gross P&L **before costs** | **−$7.84** |
| Spread paid | −$788.72 |
| Commission | −$171.15 |
| Slippage | −$12.22 |
| **Total costs** | **−$972.09** |
| Net | −$979.93 |

The raw signal produced **−$7.84** — statistically indistinguishable from
zero on 2,445 trades. The entire −$980 loss **is** transaction costs.

### 3.2 The spread is far bigger than a tick move

| Measure | Real data | Synthetic (assumed) |
|---|---|---|
| Mean spread | **$0.451** | $0.30 |
| Median spread | $0.350 | $0.24 |
| Mean absolute tick move | **$0.051** | — |
| **Spread ÷ tick move** | **8.9x** | — |

Price must move **9 consecutive ticks in one direction** just to pay the
spread. Round-trip cost including commission and slippage is **$0.531**.

### 3.3 Short-horizon moves are smaller than the cost

Mean absolute price move by holding time vs the $0.531 breakeven:

| Hold | Mean move | p75 | Verdict |
|---|---|---|---|
| 5 s | $0.219 | $0.264 | **below cost** |
| 15 s | $0.390 | $0.465 | **below cost** |
| 30 s | $0.555 | $0.665 | marginal |
| 60 s | $0.787 | $0.940 | above cost |
| 300 s | $1.794 | $2.115 | above cost |

The strategy's median hold was ~5–10 seconds — a horizon where the average
move **cannot** cover the round trip, no matter how good the entry timing is.

### 3.4 And direction is not predictable anyway

Tick-direction autocorrelation is essentially zero beyond lag 2:

```
lag1 +0.0449   lag2 +0.0338   lag3 +0.0010   lag4 +0.0045   lag5 +0.0016
```

I then tested the raw momentum bet directly across millions of samples —
"price moved >$0.20 over the last N seconds, bet on continuation":

| Lookback | Hold | Samples | Gross mean | Net after cost |
|---|---|---|---|---|
| 10 s | 30 s | 5,812,386 | −$0.0070 | −$0.5380 |
| 10 s | 60 s | 5,812,346 | **+$0.0022** | −$0.5288 |
| 30 s | 60 s | 7,968,248 | **+$0.0008** | −$0.5303 |
| 60 s | 300 s | 9,155,138 | −$0.0152 | −$0.5462 |

And the mean-reversion bet (the exact opposite):

| Lookback | Hold | Gross mean | Net after cost |
|---|---|---|---|
| 10 s | 300 s | +$0.0117 | −$0.5194 |
| 30 s | 300 s | +$0.0233 | −$0.5078 |
| 60 s | 60 s | +$0.0081 | −$0.5229 |

**Both directions produce a gross edge of roughly ±$0.01–0.02** against a
required **$0.531**. The signal is ~25x too small to pay for the trade.
This is what an efficient market looks like at tick scale.

---

## 4. What this means

The earlier +21.9% result was **an artefact of my synthetic tick generator**.
I built that simulator with an AR(1) order-flow process that deliberately
creates persistent short-horizon drift — so a momentum strategy was
guaranteed to find an edge. Real XAUUSD has no such persistence.

This is exactly why I flagged that the synthetic numbers had to be
re-validated before any real use. That validation has now happened, and it
failed.

**Tuning will not fix this.** The problem is not the thresholds, the session
filter, or the exits. Gross P&L before costs is ~$0, and the measured
predictability at every horizon tested is ~25x smaller than the cost of
trading. No parameter set changes those two facts.

---

## 5. Honest options

**1. Abandon sub-minute scalping on this cost structure.**
At $0.45 average spread + $0.07 commission, per-trade cost is $0.531 while
5-second moves average $0.219. The arithmetic cannot work.

**2. Move to a longer horizon.** At 5+ minutes, moves average $1.79 against
the same $0.531 cost — a 3.4:1 ratio. That is a genuinely different (and
plausible) strategy, but it is no longer scalping.

**3. Get a much better cost structure.** The strategy needs roughly a 5x
cost reduction to break even, i.e. ~$0.08 spread on gold. That does not
exist retail.

**4. Verify the data before going further.** HistData is aggregated from
retail feeds and its spreads are wider than a good ECN broker's. Exporting
ticks from your own broker's MT5 would give a more accurate picture — the
loader already supports it. But note the cost gap is 5x, and broker
differences are typically well under 2x.

My recommendation is **option 2**: keep the microstructure signal work, but
target a horizon where the move-to-cost ratio is actually favourable.

---

> Backtest run on 12,799,655 real ticks with costs modelled explicitly:
> full spread crossed on entry and exit, $7/lot round-turn commission,
> 0.5 tick slippage per fill. No look-ahead.
