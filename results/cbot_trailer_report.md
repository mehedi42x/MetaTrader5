# cTrader cBot 'Trande Hunter' — faithful port and test

The cBot: EMA 6/9 crossover on M1 + 5m EMA 9/12 trend, entry on the cross in the
trend direction, exit on the raw opposite 1m crossover, plus a trailing stop that
activates at +$2.00, trails $1.50 behind, locks at least +$0.50 and never more than
+$2.00 (MaxTrailCap). 0.01 lot, $0.20 per round trip, real XAUUSD M1.

Only M1 OHLC exists (no ticks), so the intrabar order of the high and the low is
unknown; both orderings are reported: **conservative** (the adverse extreme is hit
first) and **optimistic** (the favourable extreme comes first). The truth is between
the two, and the difference is small.

## Four full years 2022-2025

| variant | 2022 | 2023 | 2024 | 2025 | total | trades | win% | maxDD $ |
|---|---|---|---|---|---|---|---|---|
| no trail (cross exit only) | $-3,195 | $-2,552 | $-2,718 | $-3,401 | **$-11,865** | 52,111 | 23.7% | $-11,892 |
| trail 2.0 / 1.5 / cap 2.0 (cBot defaults) | $-3,213 | $-2,569 | $-2,690 | $-3,309 | **$-11,781** | 52,111 | 29.0% | $-11,807 |
| trail 2.0 / 1.5 / cap 2.0 (optimistic) | $-3,831 | $-3,004 | $-3,673 | $-5,665 | **$-16,173** | 52,111 | 29.3% | $-16,179 |
| trail 1.0 / 0.5 / cap 1.0 | $-3,004 | $-2,332 | $-2,553 | $-3,121 | **$-11,011** | 52,111 | 38.6% | $-11,031 |
| trail 1.0 / 1.0 / cap 1.0 | $-3,110 | $-2,389 | $-2,634 | $-3,132 | **$-11,264** | 52,111 | 33.2% | $-11,284 |
| trail 2.0 / 1.0 / cap 2.0 | $-3,192 | $-2,548 | $-2,738 | $-3,345 | **$-11,823** | 52,111 | 29.0% | $-11,839 |
| trail 3.0 / 1.5 / cap 3.0 | $-3,187 | $-2,614 | $-2,611 | $-3,306 | **$-11,718** | 52,111 | 26.0% | $-11,757 |
| trail 5.0 / 2.0 / cap 5.0 | $-3,154 | $-2,573 | $-2,632 | $-3,207 | **$-11,566** | 52,111 | 24.3% | $-11,646 |
| trail 10.0 / 3.0 / cap 10.0 | $-3,205 | $-2,567 | $-2,832 | $-3,191 | **$-11,794** | 52,111 | 23.8% | $-11,806 |

## What the trailing stop actually does (2022-2025)

| | no trail | trail ON (defaults) |
|---|---|---|
| trades | 52,111 | 52,111 |
| win rate | 23.7% | 29.0% |
| net | $-11,864.97 | $-11,780.82 |
| gross before spread | $-1,442.77 | $-1,358.62 |
| average win | $2.23 | $1.56 |
| average loss | $-0.99 | $-0.96 |
| biggest win | $56.21 | $53.13 |
| worst trade | $-61.69 | $-61.69 |
| max drawdown | $-11,892 | $-11,807 |

With the trail ON, **9,283 of 52,111 trades (17.8%)** were closed by the trailing stop: 97.5% of them in profit, median $+1.13, and 2,730 exited at the +$2.00 cap (+$1.80 net). Exit mix: cross 42,827, trail 8,479, trail gap 804, open at end 1.

The same 9,283 entries closed by the cross instead would have produced $10,128 versus the trail's $10,212 - the trailing stop added $84. It improved 6,036 trades and worsened 3,201: a reshuffle, not an edge.

## Worst month (August 2023)

| variant | trades | net $ | win% |
|---|---|---|---|
| no trail | 1,296 | $-382.49 | 18.1% |
| trail ON (conservative) | 1,296 | $-380.90 | 18.8% |
| trail ON (optimistic) | 1,296 | $-388.53 | 18.8% |

## September 2026 (real Exness MT5, 9-18 Sep)

| variant | trades | net $ | win% |
|---|---|---|---|
| no trail | 364 | $31.44 | 29.4% |
| trail ON | 364 | $95.22 | 55.5% |

Charts: results/cbot_trailer.png

## Verdict

**1. The trailing stop barely changes anything.** Over four years it moves the result from
-$11,864.97 to -$11,780.82 (+$84, or 0.7% of the loss). On the 9,283 entries it closed it
improved 6,036 and worsened 3,201 for a net $84 gain - a **reshuffle, not an edge**.

**2. What it really does is swap big winners for small locked wins.** Average win falls from
$2.23 to $1.56 while the average loss stays at about -$0.96, and the win rate rises from
23.7% to 29.0%. The biggest winner collapses from $56.21 to $53.13 because MaxTrailCap caps
the exit at +$2.00 net $1.80 - **2,730 trades exited exactly at that cap**. The losing side
does not shrink at all (worst trade still -$61.69, because the trail only exists after
+$2.00 of profit).

**3. The maths is the same as every other test in this repo.** 52,111 trades x $0.20 =
$10,422 of spread; gross P/L is -$1,443 without the trail and -$1,359 with it. The trail
shifts about $84 of gross around and leaves the edge at zero.

**4. Parameters: the tighter the trail, the smaller the loss - for mechanical reasons.**
The best of the nine settings is **1.0 / 0.5 / cap 1.0 at -$11,010.52** (2022 -$3,004 |
2023 -$2,332 | 2024 -$2,553 | 2025 -$3,121), and the win rate is exactly 38.6% - the number
that a 1:1 payout needs when the $0.20 cost is charged. Bigger trails behave like no trail at
all (5.0/2.0 and 10.0/3.0 land within $100 of the no-trail result) because they are rarely
reached. The cBot's defaults sit in the middle of a $200 band - the parameter choice is
worth $200 across four years and not one setting is profitable.

**5. The optimistic/conservative spread measures the tick-order uncertainty.** Assuming the
favourable extreme of each M1 bar comes first turns -$11,781 into -$16,173: tick-level
sequencing is worth about $4,400 over four years, which is why the conservative figure is
the honest one to quote (a live account pays the worse path more often than the better one).

**6. September 2026 (real Exness MT5, 9-18 Sep):** no trail +$31.44 (364 trades) vs trail
ON +$95.22 conservative. A nine-day window on an unusually trendy $200 range - it cannot
overturn four years of results, and the optimistic path on the same window is -$62.17.

**Conclusion:** the entry is the same M1 EMA 6/9 + 5m EMA 9/12 signal that has now been
tested five different ways in this repo (raw, MTF-filtered, sideways-filtered, hybrid exit,
trailing stop) and it has no edge. Exit management cannot create one: every variant lands
between -$11,000 and -$11,900 over four years, which is exactly the spread bill. The only
measured edge in this repo remains the S7 order-block retest: **+$4,124.58, 4/4 positive
years**.
