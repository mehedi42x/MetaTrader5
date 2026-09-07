# ZCB — Zone Compression Breakout
### Tomar specified logic · implement kora hoise · real tick e test

---

## 1. Ki banano hoise

Tomar rule ta exactly jemon bolecho:

```
ZONE     Price ke fixed-width zone-e bhag kora (floor(price / zone_w))
TOUCH    Price jokhon notun zone-e DHOKE tokhon 1 touch. Ek zone-e
         boshe thakle count bare na
CHARGE   1 minute rolling window-e ek zone-e 4 bar er beshi touch
         hole zone ta "armed"
ENTRY    Armed zone theke price ber hoye gele sei direction e entry
EXIT     Same logic ulto kore — trade-er moddhe notun ekta zone-e
         price bar bar obosthan korle (reverse er chesta) → close
SIZE     0.01 lot, 800x
```

`src/zone_strategy.py` — full implementation. `src/run_zone.py` — backtest.

---

## 2. Result: 18 configuration, sob-tai loss

Real ticks, 2024-01, 3,000,000 tick:

| zone | touch | break | exit_tch | stop | Trades | Net | PF | Win% |
|---|---|---|---|---|---|---|---|---|
| $0.10 | 5 | 2 | 5 | 1.5 | 15,971 | **−$6,339** | 0.056 | 8.4% |
| $0.10 | 8 | 3 | 5 | 1.5 | 9,286 | −$3,736 | 0.058 | 8.4% |
| $0.25 | 5 | 2 | 5 | 1.5 | 5,581 | −$2,228 | 0.119 | 16.2% |
| $0.25 | 5 | 2 | 8 | 1.5 | 3,902 | −$1,487 | 0.263 | 24.7% |
| $0.50 | 5 | 2 | 5 | 1.5 | 2,082 | −$781 | 0.243 | 28.7% |
| **$0.50** | **8** | **3** | **5** | **1.5** | **888** | **−$341** | **0.251** | **28.2%** |

Zone width, touch count, break distance, exit touches, stop ($0.5/$1.5/$3.0), hold (300s/900s/3600s) — sob variation korechi. **Best config-eo PF 0.25.**

Trade count tumi jemon chaichile temon — **15,971 trades** (ARB-er 76 er tulonay 210x beshi). Kintu prottek ta trade harai.

---

### Full dataset run (all 12,799,655 ticks, default config)

| Metric | Value |
|---|---|
| Trades | **81,703** |
| Net | **−$41,364.61** |
| Return | **−4,136%** (account 41x blown) |
| PF | 0.079 |
| Win rate | 10.15% |
| Expectancy | −$0.51 / trade |
| Gross before costs | **−$34,011** |
| Costs | −$7,353 |
| Avg duration | 25.5 s |

Trade frequency tumi jeta chaichile tar cheyeo beshi — **81,703 trades**. Kintu gross-i −$34,011, mane **cost baad diyeo** system ta harai.

---

## 3. Keno fail korlo — duita alada karon

### Karon A: Exit rule ta trade-ke gola tipe mere fele

Exit statistics:

| Exit reason | n | Mean gross | Mean duration |
|---|---|---|---|
| `zone_reverse` | 5,403 (97%) | **−$0.27** | 55.6 s |
| `stop` | 166 (3%) | −$1.58 | 81.8 s |
| `time` | 12 | −$0.33 | 905 s |

**Median trade duration matro 29 second.**

Problem ta structural: entry er por-e price **obosshoi** ekta notun zone-e thake ar sekhane tick kore. Tai "zone-e bar bar obosthan" condition ta prai shathe shathe true hoye jay — signal hisebe na, definition hisebe. Result:

- Prottek winner **29 second-e** kaita jay (~$0.27 loss e)
- Prottek loser **$1.50 hard stop** porjonto chole

Choto win kete deoa + boro loss chalte deoa = guaranteed loss, signal jai hok na keno.

### Karon B: Entry signal-tao khali (eta beshi guruttopurno)

Exit-take shore rekhe, shudhu entry-r por fixed horizon-e ki hoy:

| Horizon | n | Mean gross | Win% |
|---|---|---|---|
| 10 s | 5,578 | +$0.0134 | 51.1% |
| 30 s | 5,580 | +$0.0160 | 49.7% |
| 60 s | 5,579 | +$0.0148 | 50.1% |
| 120 s | 5,577 | +$0.0204 | 50.3% |
| 300 s | 5,573 | −$0.0025 | 49.5% |
| 1800 s | 5,520 | −$0.0052 | 48.6% |

**Random entry control** (same time-e coin flip):

| | Mean gross | Win% |
|---|---|---|
| Zone entry, 60 s | +$0.0148 | 50.1% |
| **Random, 60 s** | **+$0.0055** | 49.4% |

Zone signal random er thekay **$0.009** bhalo. Cost **$0.41**. Signal ta cost er **1/45 ভাগ**.

Best horizon-eo (+$0.0204) net = **−$0.39**.

Erman: exit rule thik kore dileo lav nai. Signal-ei kichu nai.

---

## 4. Keno ei logic ta gold-e kaj korte pare na

Ekta zone-e price bar bar fire asha mane market **balanced** — buyer ar seller equal. Sekhan theke ber howa mane onek somoy just noise, kono order flow na.

Ar mool arithmetic problem ta age-o peyechilam:

| | |
|---|---|
| Mean tick move | $0.051 |
| Mean spread | $0.334–0.451 |
| **Ratio** | **cost 8.9x boro** |

1-minute window-e price gor-e $0.46 nore. Cost $0.41. Manে tomake **89% accuracy** lagbe just break-even korte. Zone signal dicche **50.1%**.

Ei jonnoi 1-minute analysis diye gold-e trade kora jay na — timeframe ta chhoto na, **cost ta boro**.

---

## 5. Tomar ARB niye apotti

> "matro olpo ei koyta trade"

Thik bolecho — 76 trade kom. Kintu karon ta hoccche **83 din-er data** (2024 Jan/Feb/Mar + 2026 Aug matro). ARB din-e 1 trade kore, tai:

- 83 trading days → 76 trades = **prai protidin trade hoyeche**
- Puro 1 bochor data thakle → **~250 trades/year**
- Frequency kom na — **amader kache data-i kom**

Tumi jodi beshi frequency chao, ARB-ke multi-instrument (XAUUSD + EURUSD + GBPUSD) ba multi-session (Asian range + London range + NY range) korle din-e 3-6 trade hote pare, PF thik rekhe. Setar jonno oi pair-gulor tick data lagbe.

---

## 6. Sotti kotha

Ami tomar strategy fail korate chai nai — **18 ta config test korechi**, exit rule alada kore diagnose korechi, random control rekhechi. Rule ta bhul kore implement korini; rule ta gold-er cost structure-e kaj kore na.

Amar chai tumi eta jano: PF 0.25 wala system live-e cholale **account 1-2 mash-e shesh** hobe. Purano scalper ta ei karonei **−97.99%** hoyechilo.

| System | PF | Trades | Verdict |
|---|---|---|---|
| Old TFAM scalper | 0.086 | 2,445 | Dead |
| **ZCB (zone logic)** | **0.25** | **15,971** | **Dead** |
| **ARB (session breakout)** | **1.57** | **76** | **Works** |

---

## 7. Files

| Path | Ki ase |
|---|---|
| `src/zone_strategy.py` | Tomar zone logic, full implementation |
| `src/run_zone.py` | Backtest + 18-config sweep |
| `src/diagnose_zone.py` | Exit vs entry failure separation + random control |
| `src/research_zone.py` | Zone width × touch × window grid on 1-second bars |
| `results/zone_results.json` | Metrics |
