# M1 Data Report — 8.7 years, 2018–2026
### Notun data diye ki peyechi (ar ekta khub important abishkar)

---

## 1. Data

Tumi je M1 data diyecho seta **onek boro upgrade**:

| | Purano (tick) | **Notun (M1)** |
|---|---|---|
| Bars | 12.8M ticks | 3,022,190 M1 bars |
| Trading days | 83 | **2,692** (32x) |
| Period | 2024 Q1 + 2026-08 | **2018-01 → 2026-09** |
| Continuous? | Na (856-din gap) | **Ha, 9 bochor** |
| Price range | $2,045–$4,084 | $1,160–$5,597 |

`src/m1_loader.py` — timestamps EST theke UTC convert kora. M1 file e bid/ask nai, tai spread ta **real tick data theke mapa hour-by-hour profile** use korechi (flat guess na).

---

## 2. Multi-session ARB — frequency peyechi

3 ta session e ARB apply korechi:

| Session | Range window | Entry window |
|---|---|---|
| ASIA | 00:00–06:00 | 07:00–12:00 |
| LON | 07:00–12:00 | 13:00–16:00 |
| NY | 13:00–17:00 | 17:00–20:00 |

**Frequency target hit:** 4,931 trades, **1.83 trade/day, ~462 trade/year**. Purano 76 er tulonay **65x beshi**.

Kintu result:

| Session | n | Net | PF | Win% |
|---|---|---|---|---|
| ASIA | 1,907 | +$684 | 1.09 | 55.3% |
| LON | 2,003 | −$734 | 0.91 | 51.3% |
| NY | 1,021 | +$17 | 1.01 | 40.1% |
| **COMBINED** | **4,931** | **−$33** | **1.00** | **50.5%** |

**PF 1.00. Kono edge nai.**

---

## 3. Sob theke important abishkar — ARB er 1.57 ta bhua chilo

Year by year dekho:

| Year | n | Net | PF | Win% |
|---|---|---|---|---|
| 2018 | 602 | −$336 | **0.68** | 46.7% |
| 2019 | 593 | −$424 | **0.67** | 45.4% |
| 2020 | 559 | +$39 | 1.02 | 50.6% |
| 2021 | 559 | −$268 | 0.85 | 51.0% |
| 2022 | 594 | +$2 | 1.00 | 54.0% |
| 2023 | 578 | −$407 | **0.76** | 48.1% |
| 2024 | 576 | −$26 | 0.99 | 52.4% |
| 2025 | 541 | +$610 | 1.18 | 54.0% |
| 2026 | 329 | +$778 | 1.22 | 55.0% |

Walk-forward:

| Era | n | Net | PF |
|---|---|---|---|
| TRAIN 2018–2022 | 2,907 | −$987 | **0.87** |
| VALID 2023–2024 | 1,154 | −$433 | **0.89** |
| HOLDOUT 2025–2026 | 870 | +$1,387 | 1.20 |

ARB **6 bochor e loss kore, shudhu 2025–2026 e lav kore**.

Amar age deoa **PF 1.57** result ta 2024 Q1 + 2026-08 er 83 din theke chilo. Ei notun data proman korlo oi window ta **lucky window** chilo — durable edge na. **Ami tomake bhul information diyechilam, ar notun data ta seta dhora dilo.** Eta valo hoyeche — 83 din diye kokhonoi certain howa jeto na.

---

## 4. Ar 40 ta strategy test korechi — sob fail

`src/m1_battery.py` — 40 variant, 9 bochor er upor. Rule: **tinta era teii (train/valid/holdout) positive hote hobe**.

| Strategy | n | PF | train | valid | hold |
|---|---|---|---|---|---|
| LongTrend 480m → 480m | 1,833,269 | 1.01 | 0.93 | 0.99 | 1.07 |
| LongTrend 2880m → 480m | 1,832,037 | 1.00 | 0.88 | 0.91 | 1.14 |
| Momentum 240m → 480m | 1,832,977 | 0.98 | 0.92 | 0.94 | 1.04 |
| Z2.5 momentum 240m | 134,492 | 0.97 | 0.89 | 0.99 | 1.06 |
| Hour 07 momentum | 133,775 | 0.97 | 0.82 | 0.88 | 1.18 |
| Gap fade → 240m | 2,655 | 0.95 | 0.71 | 0.78 | 1.19 |
| Channel breakout 240m | 6,319 | 0.91 | 0.82 | 0.81 | 1.16 |

Momentum, reversion, z-score, channel, vol-regime, range expansion, gap, day-of-week, hour-of-day, long trend — 40 ta.

### **Tinta era teii positive: SHUNNO (0 / 40).**

---

## 5. Ekta trap ja ami dhorechi

Khyal koro: **prottek strategy er `hold` column `train` er cheye beshi.** Prottekta. Eta suspicious — ar karon ta alpha na:

| Year | Gold price | Mean 1-min move | Cost | **move/cost** |
|---|---|---|---|---|
| 2018 | $1,269 | $0.144 | $0.462 | **0.31x** |
| 2019 | $1,394 | $0.173 | $0.463 | 0.37x |
| 2021 | $1,799 | $0.279 | $0.463 | 0.60x |
| 2023 | $1,942 | $0.267 | $0.460 | 0.58x |
| 2025 | $3,441 | $0.730 | $0.463 | **1.58x** |
| 2026 | $4,575 | $1.508 | $0.463 | **3.26x** |

Gold **$1,269 → $4,575** (3.6x). Kintu spread dollar e mota-muti **fixed**. Tai cost, move-er tulonay, **10x choto hoye gache**.

Erman **2025–2026 e je kono strategy bhalo dekhabe** — edge er jonno na, cost ratio er jonno. Ei jonnoi holdout er number gulo bhalo. Jodi shudhu 2025–2026 dekhtam, ami abar tomake bhul bolttam.

Ar ei table tai bole keno **1-minute frequency gold e kaj kore na**: 2018–2024 e mean 1-min move **cost er cheye choto** (ratio 0.31–0.82). 2026 e ratio 3.26 — kintu seta *ekhon*, ar gold pore ba porleo ratio abar niche nambe.

---

## 6. Sob mile ekhon porjonto

| System | Trades | PF | Verdict |
|---|---|---|---|
| Old TFAM scalper | 2,445 | 0.086 | Dead |
| ZCB (tomar zone logic) | 81,703 | 0.079 | Dead |
| 20 aggressive (tick) | — | 0.49–0.87 | Dead |
| 5 passive, real fills | — | 0.01–0.41 | Dead |
| **ARB 76-trade (tick)** | **76** | **1.57** | **Small-sample luck** |
| **ARB multi-session (M1)** | **4,931** | **1.00** | **Dead** |
| **40 M1 strategies** | — | **0.67–1.01** | **Sob dead** |

**~80 ta configuration test hoyeche. Ekhon porjonto kichui 9 bochor tikeni.**

---

## 7. Sotti kotha

Tumi frequency chaichile — **peyechi** (462 trade/year, 1.83/day). Kintu frequency er sathe edge ashe ni.

Ar tomar diye deoa data-i amar age er best result ta bhul proman korlo. Seta **bhalo** — 83 din er data diye ami PF 1.57 bolechilam, 2,692 din boleche PF 1.00. Boro data ei jonnoi dorkar.

Ekhon obdi gold-er M1/tick e ja test korechi, tar kono tateo **cost barrier** para jay ni. Mean 1-min move gor-e **$0.425**, cost **$0.463** — ratio **0.92x**. 9 bochor er gor e, ekta typical 1-minute move **cost-o cover kore na**.

Eta amar bakti-mot na — 3 million bar er mapa number.

---

## 8. Ekhon ki korte pari

Duito realistic option:

**a) Daily / swing horizon.** Cost fixed $0.46, tai horizon jotoi boro, cost totoi tuccho. Daily bar e mean move ~$20-30, cost $0.46 = **2% matro**. Frequency kom (week e 1-2 trade) kintu cost barrier ta thake na. Ei data diye ekhoni test kora jay.

**b) Cost-ta niye sotti kotha.** Tomar broker er real spread ki? Ami $0.33-0.90 dhorechi (HistData tick theke mapa). Tomar jodi ECN account thake ar spread $0.10-0.15 hoy, tahole puro arithmetic bodle jay — onek strategy tokhon viable hoye jay. **Eta jana amar kache shob theke joruri.**

Tumi ki (a) daily strategy test korte chao, na (b) tomar real spread bolbe?

---

## 9. Files

| Path | Ki ase |
|---|---|
| `src/m1_loader.py` | M1 loader, EST→UTC, measured spread profile |
| `src/arb_m1.py` | Multi-session ARB + walk-forward |
| `src/m1_battery.py` | 40-strategy scan, 3-era gate |
| `/tmp/arb_m1_trades.csv` | 4,931 trade audit trail |
