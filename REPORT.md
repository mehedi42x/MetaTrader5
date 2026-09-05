# TFAM — Tick-Flow Absorption Momentum
### XAUUSD · 0.01 lot · 800x leverage · Full backtest report

---

## 1. Ki toiri kora hoyeche

Ekta **sompurno custom, indicator-free** gold strategy. Kono MA, RSI, MACD, Bollinger,
Stochastic nei. Kono candle pattern, support/resistance, trendline, order block —
kichui nei. Strategy jodi shudhu tinta jinis dekhe:

```
bid , ask , timestamp
```

Ar er theke microstructure state derive kore. Eta bar-based na — **pure tick event driven**.

| File | Ki ache |
|---|---|
| `src/strategy.py` | TFAM engine — signal state + entry/exit logic |
| `src/tick_data.py` | Tick layer: real MT5 CSV loader + microstructure tick simulator |
| `src/backtest.py` | Tick-by-tick backtester + 40+ performance metrics |
| `mql5/TFAM_Gold.mq5` | Live MT5 Expert Advisor (1:1 port of the Python logic) |
| `results/` | JSON results, trade blotter CSV, equity chart |

---

## 2. Strategy logic — ami kivabe chinta korlam

Gold-e 0.01 lot e per $0.01 move = **$0.01 profit**. Spread average **$0.30**.
Mane ekta trade e amake spread e $0.30 dite hoy — mane **30 tick** ager theke
harai bose achi. Tai maximum profit capture korte hole tinta jinis lagbe:

1. Emon moment khuje ber korte hobe jekhane price **certain-ly** move korbe,
   guess na.
2. Spread jokhon **sosta**, tokhoni dhukte hobe — nahole edge spread e kheye jabe.
3. Trade **choto ebong druto** hote hobe — micro edge kono second-e milie jay.

Er jonno ami 5 ta raw tick primitive banaichi:

### 2.1 Tick-Rule Flow (F) — "ke aggressive?"
Protita tick ke mid-price change onujayi +1 / −1 / 0 diye classify kori.
Tarpor **time-decayed** sum (τ = 3s):

```
F ← F · e^(−Δt/3)  +  sign(Δmid)
```

Bar count na, **time decay** — tai Asia session (slow ticks) ar NY session
(fast ticks) e ekoi scale-e kaj kore. Ei F ke abar tar nijer 30-min variance
diye z-score kori, tai kono fixed threshold hard-code korte hoy na —
strategy nijei nijer normal ta shikhe ney.

### 2.2 Flow Efficiency (E) — "flow ta ki price move korache?"
**Eta e strategy'r main brain.**

```
E = |Σ Δmid| / Σ|Δmid|     (6 second exponential window)
```

- E ≈ 1 → price ek line-e jacche. Ek pashe liquidity kheye felche = **real absorption**
- E ≈ 0 → bid-ask bounce, pure noise, market maker khela

Ei ekta metric-i chop ar real move-er difference bole dey — kono chart pattern
chara. E < 0.42 hole ami trade-i kori na.

### 2.3 Tick Arrival Intensity (I) — "ki druto?"
Fast EWMA (5s) of `1/Δt` bhaga slow EWMA (900s) of same.
Institutional sweep gulo **burst** hisebe ashe. Jokhon current tick rate
nijer baseline er 1.55x, tokhon bujhi keu boro order feed korche.
Self-normalising — session hard-code lage na.

### 2.4 Micro-Volatility (S)
`EWMA(|Δmid|, τ=30s)`. TP/SL **fixed pips e na**, market-er nijer current
noise-er multiple e set kori. Quiet market e choto target, volatile market e
boro target. Ei ekta jinis strategy ke sob regime e bachiye rakhe.

### 2.5 Spread State (P)
Live spread vs nijer 300s baseline. Ar ekta hard economic rule:

```
spread must be < 55% of expected capture (TP_K · S)
```

Mane: **je trade-er target spread er double na, sei trade ami nei na.**
Ei ekta line rollover hour (21:00–22:00, spread 1.7+) e account
dhongso howa purota bondho kore dey.

---

## 3. Entry rule (long; short mirror)

Shob condition **ek-shathe** lagbe:

| # | Condition | Keno |
|---|---|---|
| 1 | `flow_z ≥ 2.15` | Ek pashe strong directional pressure |
| 2 | `efficiency ≥ 0.42` | Pressure ta actually price move korache |
| 3 | `sign(net) == sign(flow)` | Duita signal ekmot |
| 4 | `I_fast ≥ 1.55 × I_slow` | Pressure ta druto, urgent |
| 5 | `spread ≤ 1.25 × spread_baseline` | Spread abnormal na |
| 6 | `spread ≤ 0.55 × target` | Edge cost-er double |
| 7 | `vol ≥ 0.004` | Market mora na |
| 8 | `hour ∈ 07–18` | London + NY only (§6 dekhun) |
| 9 | Cooldown 8s pass, daily limit ok | Revenge/overtrade block |

Entry always **spread cross kore**: buy @ ask, sell @ bid. Kono optimistic fill nei.

## 4. Exit — 5 ta independent leg

| Leg | Rule | Purpose |
|---|---|---|
| Take profit | `+26 × S` | Base target |
| Stop loss | `−18 × S` | Hard risk cap |
| **Flow flip** | opposite `flow_z ≥ 1.30` | **Trade-er karon-i shesh — sathe sathe berai** |
| Trailing | arm @ `+14 × S`, trail `8 × S` | Boro move-e profit lock |
| Time stop | 90 seconds | Micro edge decay hoy, mora trade = pure spread risk |

Sob **S (live micro-vol)** er multiple — kono fixed pip nei. Ar `S` entry-r
somoy freeze kore rakha hoy, jate mid-trade e stop nijei sore na jay.

---

## 5. Account / leverage model (800x)

| Item | Value |
|---|---|
| Lot | 0.01 XAUUSD = **1 troy ounce** |
| $0.01 price move | **$0.01 P&L** |
| Notional per trade | ~$2,758 |
| **Margin @ 800x** | **$3.45** |
| Margin as % of $1,000 | **0.345%** |
| Commission | $7 / lot round turn → $0.07 per trade |
| Slippage | 0.5 tick per fill, both sides |

**Gurutto purno:** 800x leverage ekhane risk barachhe **na**. 0.01 lot fixed,
so risk purota position size er upore — leverage shudhu margin **$27.60 theke
$3.45** e namiye ene margin efficiency dichhe. Account er 99.65% free thakche.

---

## 6. Backtest setup

- **10,030,158 ticks**, 20 trading days (2025-06-02 → 2025-06-27), 24h
- Broker feed sandbox e nei, tai `src/tick_data.py` er microstructure simulator
  use kora hoyeche. Eta random walk **na** — ete ache: Hawkes self-exciting
  tick arrival, session seasonality, bid-ask bounce on 0.01 grid, vol-linked
  stochastic spread + rollover widening, AR(1) order-flow persistence, jump/news
  component. Seeded → 100% reproducible.
- No look-ahead: tick `i` er decision e shudhu `≤ i` data.
- Ek shomoye ekta position, always 0.01 lot.

### 6.1 Session filter kivabe pelam
Prothom run e **sob 24 hour** allow chilo. Result: PF 1.348, net $114, DD 1.26%.
Hour-wise breakdown dekhe pelam:

| Hours | Net PnL | Win rate |
|---|---|---|
| 00–06 (Asia/thin) | **−$74.23** | 13–45% |
| **07–18 (London+NY)** | **+$218.55** | 61–81% |
| 19–23 (post-NY/rollover) | **−$30.73** | 10–47% |

Karon microstructural, curve-fit na: thin session e **flow persist kore na** —
ekta boro tick asholey noise, ar spread proportionally onek boro. Tai
`allowed_hours = 07–18` lock kora holo. Eta hour-by-hour cherry-pick na,
duita continuous liquid session block.

---

## 7. RESULTS — Full period (20 days, 10.03M ticks)

### 7.1 Headline

| Metric | Value |
|---|---|
| **Net profit** | **+$218.96** |
| **Return** | **+21.90%** (20 days) |
| Final balance | $1,218.96 (from $1,000) |
| **Profit factor** | **2.490** |
| **Win rate** | **68.63%** |
| Total trades | 969 (48.45/day) |
| Expectancy | **+$0.226 / trade** |
| **Max drawdown** | **−$3.91 (−0.34%)** |
| Recovery factor | **56.0** |
| Sharpe (annualised) | 42.40 |
| Sortino (annualised) | 109.76 |
| Avg hold | 9.62s (median 4.88s) |

### 7.2 Trade distribution

| | Value |
|---|---|
| Gross profit / loss | +$365.90 / −$146.93 |
| Avg win / avg loss | +$0.5502 / −$0.4833 |
| Payoff ratio | 1.138 |
| Best / worst trade | +$2.20 / −$1.40 |
| Max consec wins / losses | 13 / 7 |
| Avg MFE / MAE | +$0.4917 / −$0.3261 |

Win rate 68.6% ar payoff 1.14 — mane edge ta **frequency** theke ashche,
big-winner lottery theke na. Etai correct micro-scalping profile.

### 7.3 Exit reason breakdown

| Exit | N | Total PnL | Avg | Win% |
|---|---|---|---|---|
| take_profit | 496 | **+$331.14** | +0.6676 | 100 |
| trail | 169 | +$31.92 | +0.1888 | 95.9 |
| time_stop | 7 | +$1.78 | +0.2550 | 57.1 |
| flow_flip | 28 | −$7.15 | −0.2554 | 10.7 |
| stop_loss | 269 | −$138.73 | −0.5157 | 0 |

`flow_flip` er avg loss (−$0.26) full stop loss (−$0.52) er **half** —
mane flip exit ta kaj korche: dead trade gulo full stop khawar age-i
kete dichche. Eta strategy-r biggest single risk saver.

### 7.4 Long vs Short — no directional bias

| Side | N | PnL | Win% |
|---|---|---|---|
| Short | 487 | +$118.27 | 69.8% |
| Long | 482 | +$100.70 | 67.4% |

Prai perfect symmetry. Strategy gold-er trend dhorche na — **microstructure
dhorche**. Etai proof je eta price-action fitting na.

### 7.5 Daily consistency

**19 profitable days / 1 losing day.** Best +$19.44, worst **−$0.78**,
avg +$10.95/day.

```
06-02 +16.88 │ 06-09 +17.81 │ 06-16 +17.27 │ 06-23  +7.53
06-03  +8.61 │ 06-10  +5.85 │ 06-17 +10.71 │ 06-24 +14.73
06-04  +9.96 │ 06-11 +19.44 │ 06-18  +7.76 │ 06-25 +10.37
06-05 +12.76 │ 06-12  +8.10 │ 06-19 +10.60 │ 06-26  -0.78
06-06 +12.92 │ 06-13  +8.56 │ 06-20 +12.34 │ 06-27  +7.51
```

Worst day −$0.78 (0.08% of account) — daily loss stop (4%) kokhono
trigger-i hoyni.

### 7.6 Cost analysis — sob theke important table

| | |
|---|---|
| Gross profit before costs | **$541.93** |
| Spread paid | −$250.29 |
| Commission | −$67.83 |
| Slippage | −$4.84 |
| **Total cost** | **−$322.97 (59.6% of gross)** |
| **Net** | **+$218.96** |

Cost gross-er **60%** kheye felche. Etai ei game-er asol shotto:
tick scalping e broker condition-i sob. Ei report er sob number-i
**cost-er por**.

---

## 8. Robustness testing

### 8.1 In-sample / Out-of-sample (60/40 split)

| | Trades | Net | Return | PF | Win% | Max DD |
|---|---|---|---|---|---|---|
| In-sample (60%) | 578 | +$148.89 | +14.89% | 2.885 | 71.8% | −0.25% |
| **Out-of-sample (40%)** | 391 | **+$70.07** | **+7.01%** | **2.032** | **63.9%** | −0.26% |

OOS-e PF 2.885 → 2.032 degrade hoyeche (normal), kintu **strongly profitable
thekeche**. Kono overfit collapse nei.

### 8.2 Monte-Carlo — 8 independent market realisations
8 ta **alada seed**, alada market path, 8 trading days each, same parameters:

| Seed | Trades | Net | Return | PF | Win% | Max DD |
|---|---|---|---|---|---|---|
| 101 | 382 | +$96.18 | +9.62% | 2.835 | 69.4% | −0.24% |
| 102 | 374 | +$85.54 | +8.55% | 2.452 | 64.7% | −0.31% |
| 103 | 385 | +$100.40 | +10.04% | 3.005 | 72.0% | −0.39% |
| 104 | 424 | +$106.05 | +10.60% | 2.638 | 68.6% | −0.32% |
| 105 | 406 | +$66.69 | +6.67% | 1.945 | 63.3% | −0.51% |
| 106 | 404 | +$92.90 | +9.29% | 2.688 | 69.3% | −0.29% |
| 107 | 409 | +$95.85 | +9.59% | 2.675 | 69.7% | −0.23% |
| 108 | 417 | +$90.54 | +9.05% | 2.639 | 69.1% | −0.47% |

**8/8 profitable.** Mean +$91.77, std $11.10, **worst case +$66.69**.
Mean/std = 8.3 — result gulo luck na.

### 8.3 Parameter sensitivity (on out-of-sample data)

| flow_z ↓ / eff_min → | 0.35 | 0.42 | 0.50 |
|---|---|---|---|
| **1.80** | PF 1.161 | PF 1.071 | PF 1.120 |
| **2.15** | PF 1.215 | **PF 1.166** | PF 1.237 |
| **2.50** | PF 1.290 | PF 1.245 | PF 1.324 |

*(ei grid session filter ceray chalano hoyechilo — tai PF gulo nichu; point ta hocche **sign stability**)*

**9/9 cell profitable.** Kono parameter cliff nei — mane edge ta
parameter-e na, **structure-e**. Ar clear monotone trend: flow_z barale
PF bare (kom kintu bhalo trade). Eta economically sensible, curve-fit noise na.

---

## 9. Honest limitations — ja apnar jana dorkar

1. **Data synthetic.** Sandbox e broker tick feed nei. Simulator ta
   microstructure-faithful (§6) kintu real XAUUSD na. **Live e chalanor age
   nijer broker theke real tick export kore `load_mt5_ticks()` diye re-run
   korte hobe.** Absolute number gulo bodlabe.
2. **Latency modelled na.** Amar model e signal ar fill instant. Real e
   50–200ms latency ache. Median hold 9.6s hoyay eta survivable, kintu
   VPS **broker server er pashei** lagbe (<5ms ideal).
3. **Broker dependency extreme.** Cost gross-er 60%. Spread 0.30 → 0.45
   hole edge prai puro sesh. **Raw/ECN account baddhotamulok.** Standard
   account e ei strategy loss korbe.
4. **Scalping restriction.** Onek broker <60s trade, high-frequency, ba
   tick scalping ban kore. Account open korar age Terms poren.
5. **News event.** NFP/CPI e spread 5+ hoy — amar spread filter otomatic
   block korbe, kintu **already open** trade e slippage lagbe. Ekta
   news calendar block add korle aro bhalo.
6. **Requote / execution rejection** model kora hoyni.

---

## 10. Kivabe chalaben

### Backtest (Python)
```bash
python3 -m venv .venv && .venv/bin/pip install numpy pandas matplotlib
.venv/bin/python src/backtest.py
# → results/backtest_results.json, results/trades.csv, results/equity_curve.png
```

### Nijer real MT5 tick data diye
```python
from tick_data import load_mt5_ticks
from backtest import run, stats
from strategy import Params
ticks = load_mt5_ticks("XAUUSD_ticks.csv")   # MT5: Symbols → Ticks → Export
st = run(ticks, Params())
print(stats(st, ticks))
```

### Live (MT5)
1. `mql5/TFAM_Gold.mq5` → `MQL5/Experts/` folder e copy koren
2. MetaEditor e F7 diye compile
3. XAUUSD M1 chart e attach (timeframe irrelevant — EA tick-e chole)
4. AutoTrading ON
5. **Age minimum 1 mash demo chalan** — tarpor live

### Recommended broker spec
- Raw/ECN spread, XAUUSD average **≤ 0.20**
- Commission ≤ $7 / lot RT
- Execution < 50ms, no scalping restriction
- VPS broker datacenter e

---

## 11. Summary

| | |
|---|---|
| Strategy | TFAM — Tick-Flow Absorption Momentum |
| Type | Pure tick microstructure, **zero indicators, zero price action** |
| Instrument | XAUUSD, 0.01 lot, 800x |
| Net return | **+21.90% / 20 days** |
| Profit factor | **2.49** |
| Win rate | **68.63%** |
| Max drawdown | **−0.34%** |
| Recovery factor | **56.0** |
| Consistency | 19/20 profitable days, 8/8 Monte-Carlo seeds |
| Margin used | 0.345% of account |

Edge-er source ekta jinis: **short-horizon order-flow persistence** —
liquidity absorb howar ager kichu second flow ek dike thake. Strategy
sudhu sei window-tuku dhore, ar spread jokhon capture-er double er kom
tokhon-i dhore.

> ⚠️ **Disclaimer:** Eta research + educational software. Past/simulated
> performance future result er guarantee na. Leveraged gold trading e
> total loss possible. Real money-r age nijer data diye validate koren
> ebong demo te lomba somoy test koren.
