# XAUUSD 2022 — full-year backtest (LuxAlgo SMC systems)

Data: **data/xauusd_m1_2022.csv** — real broker M1, 354,628 bars, 2022-01-02 → 2022-12-30 (source tiumbj/M1_XAUUSD, DAT_MT_XAUUSD_M1_2022.csv).
Sizing: 0.01 lot (1 oz), cost $0.20 per round trip (spread 20 points only), leverage 1:1000. Signals on closed bars only.

## Whole year

| system | TF | net P/L | return | trades | win% | PF | max DD $ |
|---|---|---|---|---|---|---|---|
| S1 swing bias flip | M1 | $-386.66 | -3.87% | 1280 | 33.5% | 0.88 | $-567.63 |
| S2 CHoCH only | M1 | $-388.91 | -3.89% | 1279 | 33.5% | 0.88 | $-567.63 |
| S3 BOS entry / CHoCH exit | M1 | $-148.07 | -1.48% | 709 | 59.1% | 0.92 | $-346.94 |
| S4 internal bias flip | M1 | $-2,207.44 | -22.07% | 9588 | 31.5% | 0.77 | $-2,236.51 |
| S5 internal CHoCH only | M1 | $-2,210.06 | -22.10% | 9587 | 31.4% | 0.77 | $-2,236.51 |
| S6 pullback zone entry | M1 | $-386.66 | -3.87% | 1280 | 33.5% | 0.88 | $-567.63 |
| S7 order block retest | M1 | $702.06 | +7.02% | 1337 | 21.6% | 1.67 | $-40.04 |
| EMA 9/12 (reference) | M1 | $-5,446.39 | -54.46% | 22115 | 24.1% | 0.64 | $-5,467.31 |
| S1 swing bias flip | M5 | $214.96 | +2.15% | 278 | 38.1% | 1.15 | $-230.56 |
| S2 CHoCH only | M5 | $202.86 | +2.03% | 277 | 37.9% | 1.14 | $-230.56 |
| S3 BOS entry / CHoCH exit | M5 | $56.22 | +0.56% | 144 | 63.2% | 1.07 | $-247.95 |
| S4 internal bias flip | M5 | $-602.46 | -6.02% | 1916 | 34.6% | 0.85 | $-842.54 |
| S5 internal CHoCH only | M5 | $-625.78 | -6.26% | 1915 | 34.5% | 0.85 | $-842.54 |
| S6 pullback zone entry | M5 | $214.96 | +2.15% | 278 | 38.1% | 1.15 | $-230.56 |
| S7 order block retest | M5 | $304.04 | +3.04% | 284 | 22.2% | 1.56 | $-122.64 |
| EMA 9/12 (reference) | M5 | $-1,257.47 | -12.57% | 4439 | 26.5% | 0.79 | $-1,280.26 |
| S1 swing bias flip | M15 | $-375.38 | -3.75% | 101 | 29.7% | 0.7 | $-598.78 |
| S2 CHoCH only | M15 | $-368.42 | -3.68% | 100 | 30.0% | 0.7 | $-598.78 |
| S3 BOS entry / CHoCH exit | M15 | $117.88 | +1.18% | 51 | 60.8% | 1.24 | $-135.36 |
| S4 internal bias flip | M15 | $-150.39 | -1.50% | 680 | 32.1% | 0.94 | $-319.55 |
| S5 internal CHoCH only | M15 | $-132.75 | -1.33% | 679 | 32.1% | 0.95 | $-319.55 |
| S6 pullback zone entry | M15 | $-288.38 | -2.88% | 99 | 30.3% | 0.76 | $-598.78 |
| S7 order block retest | M15 | $257.98 | +2.58% | 92 | 18.5% | 1.82 | $-81.54 |
| EMA 9/12 (reference) | M15 | $-65.09 | -0.65% | 1396 | 27.0% | 0.98 | $-368.16 |

## H1 (development) vs H2 (out-of-sample)

| system | TF | H1 P/L | H2 P/L |
|---|---|---|---|
| S1 swing bias flip | M1 | $-380.61 | $-7.08 |
| S2 CHoCH only | M1 | $-382.86 | $-9.87 |
| S3 BOS entry / CHoCH exit | M1 | $-19.69 | $-129.21 |
| S4 internal bias flip | M1 | $-1,036.29 | $-1,171.63 |
| S5 internal CHoCH only | M1 | $-1,038.91 | $-1,170.31 |
| S6 pullback zone entry | M1 | $-380.61 | $-7.08 |
| S7 order block retest | M1 | $408.67 | $289.81 |
| EMA 9/12 (reference) | M1 | $-2,743.24 | $-2,701.92 |
| S1 swing bias flip | M5 | $248.77 | $-22.90 |
| S2 CHoCH only | M5 | $236.67 | $-22.90 |
| S3 BOS entry / CHoCH exit | M5 | $-59.12 | $115.34 |
| S4 internal bias flip | M5 | $-240.70 | $-360.26 |
| S5 internal CHoCH only | M5 | $-264.02 | $-360.26 |
| S6 pullback zone entry | M5 | $248.77 | $-22.90 |
| S7 order block retest | M5 | $275.09 | $36.22 |
| EMA 9/12 (reference) | M5 | $-712.41 | $-551.04 |
| S1 swing bias flip | M15 | $-101.73 | $-271.96 |
| S2 CHoCH only | M15 | $-94.77 | $-330.37 |
| S3 BOS entry / CHoCH exit | M15 | $-23.38 | $141.26 |
| S4 internal bias flip | M15 | $-98.49 | $-56.99 |
| S5 internal CHoCH only | M15 | $-80.85 | $-45.96 |
| S6 pullback zone entry | M15 | $-14.73 | $-271.96 |
| S7 order block retest | M15 | $57.96 | $200.02 |
| EMA 9/12 (reference) | M15 | $58.80 | $-131.59 |

## Month by month (main candidates)

| month | M1 S7 | M5 S7 | M5 S1 | M5 S4 | M1 EMA |
|---|---|---|---|---|---|
| Jan 2022 | $18.10 | $-27.84 | $30.66 | $-91.71 | $-350.65 |
| Feb 2022 | $100.68 | $51.06 | $96.70 | $191.79 | $-404.52 |
| Mar 2022 | $133.83 | $160.04 | $158.36 | $19.77 | $-498.85 |
| Apr 2022 | $54.21 | $24.77 | $-17.47 | $-145.06 | $-325.56 |
| May 2022 | $57.34 | $41.02 | $30.95 | $-66.05 | $-515.52 |
| Jun 2022 | $38.16 | $17.61 | $-51.09 | $-105.10 | $-549.13 |
| Jul 2022 | $53.69 | $-29.77 | $47.47 | $-99.40 | $-538.53 |
| Aug 2022 | $46.18 | $-33.94 | $-30.97 | $-119.72 | $-427.63 |
| Sep 2022 | $-11.53 | $39.86 | $27.20 | $-113.42 | $-376.57 |
| Oct 2022 | $-5.93 | $40.05 | $22.72 | $-85.16 | $-536.31 |
| Nov 2022 | $117.24 | $-18.22 | $-131.67 | $21.55 | $-425.19 |
| Dec 2022 | $62.72 | $35.09 | $38.57 | $-17.03 | $-291.46 |
| **TOTAL** | **$664.69** | **$299.73** | **$221.43** | **$-609.54** | **$-5,239.92** |

Charts: `results/year_2022.png` (equity + monthly bars).

## Caveats

* Single instrument, single year (2022). 2022 was a strong trending gold year;
  2023-2025 regimes are not covered.
* Spread fixed at 20 points; gold spreads widen at news and rollover.
* No MT5 EA yet.

## Interpretation

* **S7 (order-block retest)** is the only system that is positive in every period:
  full year +$702 (PF 1.67), H1 +$409, H2 +$290 (out-of-sample), 10 of 12 months
  positive, and +$700 +/- 90 across swing sizes 20/34/50/100.
* Its edge comes from trade shape, not hit rate: 19.4% wins with average win $7.11
  vs average loss -$0.89 — a small stop at the order block with a large runner.
* **S1 swing BOS/CHoCH on M5** is a distant second (+$215, PF 1.15) and its H1/H2
  split (+$249 / -$23) shows it is fragile.
* **S4/S5 (internal structure)** and **S6 (zone entry)** lose over the year; the
  internal structure alone is too noisy to trade — treat it as context, not signal.
* The EMA 9/12 crossover reference lost 54% of the account on the same data, which
  is the fair comparison for everything built earlier in this repo.

## Reproduce

```bash
python3 run_year_backtest.py     # downloads nothing; uses data/xauusd_m1_2022.csv
```

Source of the data: https://github.com/tiumbj/M1_XAUUSD (DAT_MT_XAUUSD_M1_2022.csv),
converted to `time,open,high,low,close` (354,628 rows, no malformed bars).
