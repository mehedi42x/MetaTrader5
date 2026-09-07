# 30 Strategy Battery — full market study
### "Beshi trade, beshi win rate, choto profit" — eta possible kina, real data diye

---

## 1. Ki korechi

Tumi bolecho market dekhte ar nijer moto kore 20-30 ta strategy try korte. **30 ta strategy** test korechi, 7,160,048 one-second bar er upor (12.8M real tick theke banano).

Tarpor je 5 ta positive ashlo — segulo **realistic fill simulation** diye jachai korechi. Setai asol golpo.

---

## 2. Part 1 — Aggressive strategies (spread cross kore, cost ~$0.42)

20 ta test. **Sob 20 tai negative.** Ranking:

| # | Strategy | n | Gross | **Net** | Win% | PF |
|---|---|---|---|---|---|---|
| 10 | Channel breakout 30m → 1h | 108,646 | +$0.169 | −$0.283 | 43.3% | 0.86 |
| 9 | Channel breakout 15m → 1h | 168,025 | +$0.115 | −$0.335 | 43.3% | 0.83 |
| 14 | Exhaustion fade 5m → 30m | 615,123 | +$0.054 | −$0.414 | 42.9% | 0.75 |
| 17 | Low-vol momentum 5m → 1h | 553,699 | −$0.021 | −$0.419 | 40.0% | 0.59 |
| 11 | Channel fade 15m → 15m | 171,746 | +$0.029 | −$0.422 | 38.6% | 0.63 |
| 12 | Vol-scaled breakout 5m → 1h | 418,086 | +$0.003 | −$0.436 | 42.3% | 0.76 |
| 7 | Z-score>2 revert 5m | 613,423 | +$0.022 | −$0.447 | 33.0% | 0.49 |
| 19 | NY-open momentum → 1h | 597,057 | +$0.027 | −$0.452 | 46.7% | 0.87 |
| 13 | Acceleration 5m → 30m | 1,032,669 | −$0.012 | −$0.479 | 41.2% | 0.72 |
| 16 | High-vol momentum 5m → 1h | 1,507,176 | +$0.078 | −$0.504 | 47.5% | 0.87 |
| 18 | London-open momentum → 1h | 596,671 | −$0.055 | −$0.509 | 44.2% | 0.73 |
| 8 | Z-score>2 momentum → 15m | 613,423 | −$0.045 | −$0.515 | 37.7% | 0.61 |
| 20 | Tick imbalance 5m → 15m | 3,526,647 | −$0.094 | −$0.542 | 36.9% | 0.51 |
| 15 | Tight-spread momentum → 30m | 22,654 | −$0.450 | −$0.868 | 46.9% | 0.74 |

Momentum, mean reversion, z-score, channel, acceleration, exhaustion, volatility regime, session timing, tick imbalance — **sob dhoroner idea**. Best gross matro **+$0.169**, cost **$0.42**.

---

## 3. Part 2 — Passive strategies (limit order, spread *kamai* kore)

Ekhane ami tomar brief er jonno asol upay ta khujechi. Logic ta shundor:

- **Aggressive**: market order → spread **dao** → cost −$0.42
- **Passive**: limit order → spread **pao** → cost **+$0.33**

Bid e buy limit boshale keu tomar kache bech le tumi spread ta *kamao*. Ei jonnoi real high-frequency market maker ra beshi trade + beshi win rate + choto profit e bache.

Result **darun** dekhalo:

| # | Strategy | n | **Net** | Win% | PF |
|---|---|---|---|---|---|
| 27 | PASSIVE tight-spread revert | 22,654 | **+$0.424** | 57.0% | 1.43 |
| 25 | PASSIVE z>1.5 revert → 5m | 1,339,575 | **+$0.341** | 63.1% | 1.75 |
| 29 | PASSIVE channel fade → 5m | 172,346 | **+$0.325** | 64.4% | 1.82 |
| 28 | PASSIVE low-vol revert → 30s | 554,299 | **+$0.246** | **94.1%** | **38.32** |
| 26 | PASSIVE low-vol revert → 5m | 554,299 | +$0.233 | 70.7% | 3.25 |

**#28: 554,299 trades, 94.1% win rate, PF 38.32.** Tomar brief er ekdom perfect — beshi trade, beshi win rate, choto profit.

Ekhane thamle ami tomake bolte partam "peye gechi". **Kintu eta bhul hoto.**

---

## 4. Asol test — limit order ki really fill hoy?

Upor er hisheb ekta jinis dhore niyechilo: **limit order shob shomoy fill hoy**. Hoy na. Ar jevabe fail kore seta random na.

Bid e ekta buy limit **tokhon-i** fill hoy jokhon keu tomar kache bech che — mane **price niche ashche**. Manে tumi je fill gulo pao, segulo thik oi khetre jekhane market already tomar biruddhe. Ar je order gulo lav dito, segulo **fill-i hoy na**.

Eta ke bole **adverse selection**. Ei ek karone retail "market making" backtest gulo mittha hoy.

`src/fill_test.py` — real fill simulate korechi: limit boshai, 60 second wait kori, market sotti oi price e ashle tobei fill.

| Strategy | Fill rate | **Filled net** | **Filled win%** | PF | Battery bolechilo |
|---|---|---|---|---|---|
| 25. z>1.5 revert | 33.7% | **−$0.407** | 34.8% | 0.41 | +$0.341 / 63% |
| 26. low-vol revert 5m | 15.3% | **−$0.473** | 21.6% | 0.13 | +$0.233 / 71% |
| **28. low-vol revert 30s** | **15.3%** | **−$0.423** | **2.9%** | **0.01** | **+$0.246 / 94%** |

**94.1% win rate → 2.9%.** PF 38.32 → 0.01.

Ar unfilled counterfactual ta dekho:

| Strategy | Unfilled gulo koto dito | Adverse selection cost |
|---|---|---|
| 25 | +$0.202 | **$0.609/signal** |
| 26 | +$0.014 | $0.487/signal |
| 28 | +$0.037 | $0.459/signal |

Je trade gulo **fill hoyni segulo profitable chilo**. Je gulo fill holo segulo loss. Eta proman je edge ta signal er chilo na — **fill selection er artefact chilo**.

---

## 5. Win rate niye ekta guruttopurno kotha

Tumi beshi win rate chao. Ekta jinis jana dorkar: **win rate ta free parameter, edge na.** Choto target + boro stop dile win rate mechanically bere jay.

`src/winrate_test.py` — **random entry** te shudhu tp/sl geometry:

| TP | SL | Win% | Mean net | PF |
|---|---|---|---|---|
| $0.50 | $20.00 | **80.0%** | −$0.467 | 0.142 |
| $0.50 | $10.00 | **79.9%** | −$0.480 | 0.139 |
| $0.50 | $5.00 | **79.2%** | −$0.469 | 0.141 |
| $0.50 | $2.00 | 73.2% | −$0.448 | 0.137 |
| $1.00 | $5.00 | 70.1% | −$0.455 | 0.473 |
| $2.00 | $2.00 | 46.5% | −$0.418 | 0.614 |
| $5.00 | $5.00 | 43.9% | −$0.403 | **0.731** |

Dekho: **80% win rate** ekdom random entry theke banano jay — shudhu $0.50 target ar $20 stop diye. Kintu PF **0.142**.

Ar ulta dike: **win rate jotoi kome (80% → 44%), PF totoi bare (0.14 → 0.73).**

Ei jonnoi ARB er 63% win rate PF 1.57 dey, ar ei 80% win rate PF 0.14 dey. **Win rate ta target size er choice, market er edge na.**

---

## 6. Keno 81,000 trade + gold = impossible

Simple arithmetic:

| | |
|---|---|
| Round-trip cost | **$0.42** |
| 81,000 trades | **$34,020 cost** |
| Tomar account | $1,000 |

81,000 trade korte hole **account er 34 gun** shudhu cost e dite hobe. Edge ta hote hobe **$0.42/trade er beshi** — 30 ta strategy er kono ekta tar dhare kacheo ashe ni (best aggressive gross +$0.169).

Ar **passive** kore cost komano jeto — kintu fill test dekhalo oita fill selection er bhul hishab.

Ei jonnoi **ZCB 81,703 trade kore −$41,364** hoyechilo. Trade count ta problem na — trade count ta **cost multiplier**.

---

## 7. Tahole ki kora jay

Frequency baranor **valid** upay ase — edge nosto na kore:

**a) Multi-session ARB** — Asian range + London range + NY range → din e 3 trade, ~750/year. Ekhoni kora jay, ei data diyei.

**b) Multi-pair ARB** — XAUUSD + EURUSD + GBPUSD + USDJPY → din e 4-12 trade. Oi pair er tick data lagbe.

**c) Duita eksathe** — 3 session × 4 pair = din e ~12 trade, **~3,000 trade/year**, PF 1.5 thik rekhe.

Eta 81,000 na, kintu **3,000 profitable trade** vs **81,000 losing trade** — ami prothom ta recommend korchi.

---

## 8. Summary

| System | Trades | PF | Verdict |
|---|---|---|---|
| Old TFAM scalper | 2,445 | 0.086 | Dead |
| ZCB (zone logic) | 81,703 | 0.079 | Dead |
| 20 aggressive strategies | — | 0.49–0.87 | **Sob dead** |
| 5 passive (assumed fills) | — | 1.43–38.3 | **Illusion** |
| 5 passive (real fills) | — | 0.01–0.41 | Dead |
| Random 80% win-rate geometry | — | 0.142 | Dead |
| **ARB (session breakout)** | **76** | **1.57** | **Works** |

**35+ configuration test korechi. Ekta matro kaj kore.**

---

## 9. Files

| Path | Ki ase |
|---|---|
| `src/battery.py` | 30 strategy scan, aggressive + passive |
| `src/fill_test.py` | Realistic limit-order fill simulation (decisive test) |
| `src/winrate_test.py` | Win rate vs PF geometry study |
| `/tmp/bat.log`, `/tmp/ft.log`, `/tmp/wt.log` | Raw output |
