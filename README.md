# Robo-advisor with HK Portfolio Backtest 

A self-contained, pure-stdlib Python project that (1) **profiles an investor's
risk aversion** with a 15-question multiple-choice survey and (2) **backtests an
adjusted HK equity portfolio** across risk-tolerance levels, giving each investor
a relative allocation of assets (stock / hedge / cash sleeves), a stop-loss
level, and a take-profit level. The **trading skill (entry/exit signals) is
provided by the user**; every script applies that skill consistently, and only
the allocation and stop/target levels change between risk profiles.

**Workflow (recommended):**

```text
risk_profiler.py  -> 15-question survey -> CRRA gamma -> RISK-TAKE / RISK-NEUTRAL / RISK-AVERSE
      |                     (recommended allocation plan printed)
      v
plan_rt.py  (risk-taker)   -> full backtest outputs (2022-2023 + 2024-2026)
plan_rn.py  (risk-neutral) -> full backtest outputs (2022-2023 + 2024-2026)
plan_ra.py  (risk-averse)  -> full backtest outputs (2022-2023 + 2024-2026)
plan_reuse.py              -> reuse case, 2023-2025 window
```

`plan_v2.py` itself is the **quick-run** variant of the v3 rule set: by default it
**prints an approximate console summary only and creates no output files**. Full
deliverables (CSV/JSON/xlsx/charts) are generated per window by the risk-profile
runner variants.

Created **2026-11-09** at the user's request (plan_v2); the risk-profile runners
and the reuse case were added **2026-11-15**; the risk-aversion survey
(`risk_profiler.py`) was added **2026-11-16** and fixed/validated **2026-11-17**.
Evolved from `enhance_plan.py` (5-enhancement variant, 2026-11-08).

---

## 1. User, task, and supported scope

**Intended user.** A retail investor who wants portfolios matched to their
measured risk tolerance. Research backtest, **not** a live trading system.

**Task.** (1) Estimate the investor's CRRA risk-aversion coefficient γ from a
15-question survey and classify the investor as RISK-TAKE / RISK-NEUTRAL /
RISK-AVERSE; (2) give investors — with different risk-tolerance levels — a
relative allocation of assets (stock / hedge / cash sleeves), a stop-loss level,
and a take-profit level. The **trading skill is provided by the user** and is
applied identically by every risk profile.

**Trading skill (provided by the user):**

1. **Stock downtrend (exit trigger)**: close < SMA(20) **and** MACD line (DIF) < -0.1.
2. **Hedge regime**: HSI close < SMA(50) **only** — the MACD condition is dropped
   for hedges, and the **commodity buy filter is dropped**: hedges are bought
   whenever the regime is on (no requirement that Gold/Silver/Oil look bullish).
3. Held stocks are **not rebalanced monthly**.
4. **Transaction cost: 0.11%** of the traded amount on every buy and sell
   (stocks & commodities; the stylized put's premium counts as its cost).

**Per-profile parameters** (set according to the investor's risk tolerance):

| Profile | Script | Downtrend alloc. stock/hedge/cash | Uptrend alloc. stock/hedge/cash | Stop | Target | Max stocks | Max hedges |
|---|---|---|---|---|---|---|---|
| Default v3 | `plan_v2.py` | 40 / 30 / 30 | 84 / 0 / 16 | -15% | +60% | 10 | 2 |
| Risk-averse | `plan_ra.py` | 20 / 30 / 50 | 20 / 30 / 50 (same) | -10% | +20% | 3 | 3 |
| Risk-neutral | `plan_rn.py` | 60 / 20 / 20 | 70 / 10 / 20 | -10% | +50% | 5 | 3 |
| Risk-taker | `plan_rt.py` | 75 / 15 / 10 | 90 / 0 / 10 | -15% | +75% | 15 | 3 |
| Reuse case | `plan_reuse.py` | v3 rules (2023-2025 window) | v3 rules | -15% | +60% | 10 | 2 |

For the default (v3) profile implemented in `plan_v2.py`:

* Max **10 stocks**; hedge holdings capped at **2** (MAX_HEDGE = 2).
* A stock exits on **-15% stop** → own **downtrend** (close < SMA20 & DIF < -0.1)
  → **+60% target** (priority in that order; close-based fills).
* Stylized monthly protective put on the stock sleeve, bought in risk-off months
  (premium 0.40%/month, strike 95%), payoff settled at the next rebalance against
  the modeled sleeve **including intra-month flows**.
* Allocation: **stock 40 / hedge 30 / cash 30** in the HSI downtrend regime;
  **stock 84 / cash 16** in the uptrend regime (hedges exit when the regime is off).

**The risk profiler (`risk_profiler.py`)** — a 15-question multiple-choice survey:

* **Q1–Q6 (weight 0.20)** — gamble / certainty-equivalent choices. Each answer is
  a guaranteed amount (CE); γ is solved numerically from
  `u(CE) = p·u(high) + (1−p)·u(low)` with CRRA utility
  `u(x) = x^(1−γ)/(1−γ)` (bisection on γ ∈ [-2, 12]).
* **Q7–Q10 (weight 0.35)** — portfolio allocation, market behaviour, time
  horizon, risk capacity (each option carries a calibrated γ).
* **Q11–Q15 (weight 0.45)** — five-point Likert attitudes, **centred at neutral**
  (raw value − 3) so risk-tolerant answers lower γ instead of being floored.
* **Final γ = weighted mean of the three category means.**
* **Classification bands (practical):** γ < 0.5 → **RISK-TAKE**;
  0.5 ≤ γ ≤ 2.0 → **RISK-NEUTRAL**; γ > 2.0 → **RISK-AVERSE**.
* The survey then prints the recommended allocation plan that matches the
  runner variants above (e.g. RISK-TAKE → stock 75/hedge 15/cash 10 in a
  downtrend, stop −15%, target +75%).

**Supported windows (with the data provided):**

* **2021–2022** (plan_v2 default constants): backtest 2021-01-04 → 2022-12-30.
* **2022–2023**: backtest 2022-01-03 → 2023-12-29 — built by **in-memory
  merging** of the 2021–2022 files (2022 rows) + the 2023–2026 files (2023
  rows); 2021 acts as indicator warm-up.
* **2024–2026**: backtest 2024-01-02 → 2026-10-30 using the 2023–2026 files;
  2023 acts as indicator warm-up.
* **2023–2025 (reuse case, `plan_reuse.py`)**: backtest 2023-01-03 → 2025-12-31;
  2022 acts as indicator warm-up.

Out of scope: live trading, real option quotes, transaction costs beyond the
modeled 0.11%, dividends, taxes, corporate actions / splits, other markets.

---

## 2. Required software / model access and tested versions

* **Python 3 only, standard library** (`csv`, `math`, `os`, `statistics`). No pip
  installs, no API keys, no model access, no network access.
* Tested environment: macOS (Darwin 23.5.0), **Python 3.9.6**.
* Input CSVs are read as UTF-8 with BOM tolerance (`utf-8-sig`).

---

## 3. Input files / fields, units, sources, data-access instructions

Two data sets are used (uploaded by the user). Paths are relative to the folder
that contains this README (`<project_root>/2026-11-08/chat-1/work`); they are also
configured via the `REPO*` constants at the top of each script:

```
2021-2022 files: ../../2026-11-07/chat-1/outputs   (REPO_OLD)
2023-2026 files: ../..                              (REPO_NEW = <project_root>/2026-11-08)
```

| File | Columns used | Units | Role |
|---|---|---|---|
| `HSI_daily_<Y1>-01-01_to_<Y2>-…csv` | `Date`, `Close` | HSI index points | Master calendar; benchmark; regime flag |
| `HK_stocks_close_<Y1>-01-01_to_<Y2>-…_wide.csv` | `Date` + one column per HK ticker | HKD per share | Closing prices; universe; leading blanks back-filled, fully-blank columns dropped |
| `Commodities_close_<Y1>-01-01_to_<Y2>-…_wide.csv` | `Date`, `Gold`, `Silver`, `Oil` | market quotation units | Hedge sleeve prices (forward/back-filled blanks, aligned to HSI dates) |

Notes:

* Actual files:
  `HSI_daily_2021-01-01_to_2022-12-31.csv`,
  `HK_stocks_close_2021-01-01_to_2022-12-31_wide.csv`,
  `Commodities_close_2021-01-01_to_2022-12-31_wide.csv`
  and
  `HSI_daily_2023-01-01_to_2026-10-31.csv`,
  `HK_stocks_close_2023-01-01_to_2026-10-31_wide.csv`,
  `Commodities_close_2023-01-01_to_2026-10-31_wide.csv`.
* There is **no intraday OHLC long file** — stops/targets use close-based fills.
* Both wide files share the same 79 ticker columns (verified), so the 2022–2023
  merge is safe. The HSI file drives the master calendar; the wide stock file is
  row-aligned with it; commodity dates are aligned by date string.
* The scripts only ever **read** the CSVs; they never modify them.

---

## 4. How to start

Run from the folder that contains the scripts (paths below are relative to that
folder; `risk_profiler.py` lives at the project root).

**1) Risk-aversion survey** (from the project root — 15 questions, one at a
time, answer `1`–`5`):

```bash
python3 risk_profiler.py
```

Example output for a neutral-answers profile:

```text
Risk-aversion coefficient gamma : +0.744
Investor risk level             : RISK-NEUTRAL
RECOMMENDED INVESTMENT ALLOCATION
   Bull market: stock 70%, commodity 10%, risk-free asset 20%
   Bear market: stock 60%, commodity 20%, risk-free asset 20%
   Max stock holdings      : 5
   Stop-loss / take-profit : -10% / +50%
```

**2) Quick-run backtest** (default 2021–2022):

```
python3 plan_v2.py
```


**3) Risk-profile runner variants** (runs 2022–2023 and 2024–2026 )
```bash
python3 plan_ra.py    # risk-averse  
python3 plan_rn.py    # risk-neutral 
python3 plan_rt.py    # risk-taker   
python3 plan_reuse.py # reuse case   
```

No skill invocation needed. Runtime: a few seconds per window for the runners;
seconds for the survey.

---

## 5. One small example and its expected checks

**Risk profiler — three archetype answer patterns (all questions on the same
option), computed with the fixed scorer:**

```text
Conservative (all option 1):  gamma = +2.540 -> RISK-AVERSE
Neutral      (all option 3):  gamma = +0.744 -> RISK-NEUTRAL
Risk-taker   (all option 5):  gamma = -0.394 -> RISK-TAKE
```

Each band is reachable; a maximally aggressive profile cannot be pushed to
RISK-AVERSE (verified after the 2026-11-17 fix).

Verified console summary for `plan_v2.py` (run 2026-11-09) — **2022–2023** window:

```text
PLAN V2 (latest rules) - APPROXIMATE RESULT | 2022-2023
Window: 2022-01-03 .. 2023-12-29 (489 days, 24 monthly rebalances)
Portfolio final NAV: 801,379.50   final return: -19.67%
HSI        final NAV: 732,441.38   final return: -26.76%
Max drawdown: portfolio -24.28%   HSI -41.17%
Sharpe: portfolio -0.641   HSI -0.433
Tail loss (5%): portfolio -1.592%   HSI -2.502%
Trades: 267 total (stock buys=95, stock sells=104, commodity buys=19, commodity sells=27, options=22)
Realized P&L from sells: -178,939.11
Transaction costs paid: 43,636.55
Peak concurrent holdings: 10 stocks, 2 hedges
```

**2024–2026** window:

```text
Window: 2024-01-02 .. 2026-10-30 (696 days, 34 monthly rebalances)
Portfolio final NAV: 1,466,871.18   final return: 47.04%
HSI        final NAV: 1,387,518.28   final return: 38.75%
Max drawdown: portfolio -15.62%   HSI -19.95%
Sharpe: portfolio 0.918   HSI 0.631
Tail loss (5%): portfolio -1.526%   HSI -1.955%
Trades: 296 total (stock buys=105, stock sells=125, commodity buys=21, commodity sells=29, options=16)
```

Expected checks after a run:

* Banner shows the correct window years (`START[:4]-END[:4]`) and the window line
  shows real dates (2022-01-03 … 2023-12-29 / 2024-01-02 … 2026-10-30).
* Trade counts are plausible: commodity buys ≈ 19–21 (the old commodity-filter
  version only produced ~5) — evidence the hedge entry is now active.
* Peak concurrent holdings never exceed the per-profile limits.
* The plan_v2 quick run prints "No output files were created (requested)." and
  creates nothing; the runners create the full deliverables.

---

## 6. Output files and what they mean

`plan_v2.py` prints a console summary only. The risk-profile runner variants
(`plan_ra.py` risk-averse, `plan_rn.py` risk-neutral, `plan_rt.py` risk-taker,
`plan_reuse.py` reuse case) generate the full deliverables below, per window,
under `<project_root>/2026-11-08/portfolio_eval/<variant>/`:

| File | Meaning |
|---|---|
| `plan_xx/202x-202x/tables/<window>_trades.csv` | Every buy/sell/option event with price, amount, cost, reason, P&L |
| `plan_xx/202x-202x/tables/<window>_monthly.csv` | Monthly rebalance rows (date, regime, target weights, holdings, NAV) |
| `plan_xx/202x-202x/tables/<window>_nav.csv` | Daily NAV (portfolio vs HSI, normalized to 1,000,000) |
| `plan_xx/202x-202x/tables/<window>_metrics.json` | Return, drawdown, Sharpe, tail loss, trade counts, costs |
| `plan_xx/202x-202x/charts/…comparison.svg / timeline.svg / allocation.svg` | Portfolio vs HSI; trade timeline; allocation |
| `plan_xx/202x-202x/<window>_plan.xlsx` | 3 sheets (Trades, Monthly Allocation, Metrics) |

* Files for plan_v2(2022-2023):
  `plan_v2/2022-2023/tables/2022-2023_trades.csv`,
  `plan_v2/2022-2023/tables/2022-2023_monthly.csv`,
  `plan_v2/2022-2023/tables/2022_2023_nav.csv`,
  `plan_v2/2022-2023/tables/2022_2023_metrics.json`,
  `plan_v2/2022-2023/charts/2022-2023_comparison.svg /2022-2023_timeline.svg /2022-2023_allocation.svg`
  `plan_v2/2022_2023/2022-2023_plan.xlsx`,
  
  and (2024-2026)
  `plan_v2/2024-2026/tables/2024-2026_trades.csv`,
  `plan_v2/2024-2026/tables/2024-2026_monthly.csv`,
  `plan_v2/2024-2026/tables/2024-2026_nav.csv`,
  `plan_v2/2024-2026/tables/2024-2026_metrics.json`,
  `plan_v2/2024-2026/charts/2024-2026_comparison.svg /2024-2026_timeline.svg /2024-2026_allocation.svg`
  `plan_v2/2024-2026/2024-2026_plan.xlsx`,
  
* (Risk adverse)Files for plan_ra(2022-2023):
  `plan_ra/2022-2023/tables/2022-2023_trades.csv`,
  `plan_ra/2022-2023/tables/2022-2023_monthly.csv`,
  `plan_ra/2022-2023/tables/2022_2023_nav.csv`,
  `plan_ra/2022-2023/tables/2022_2023_metrics.json`,
  `plan_ra/2022-2023/charts/2022-2023_comparison.svg /2022-2023_timeline.svg /2022-2023_allocation.svg`
  `plan_ra/2022_2023/2022-2023_plan.xlsx`,
  
  and (2024-2026)
  `plan_ra/2024-2026/tables/2024-2026_trades.csv`,
  `plan_ra/2024-2026/tables/2024-2026_monthly.csv`,
  `plan_ra/2024-2026/tables/2024-2026_nav.csv`,
  `plan_ra/2024-2026/tables/2024-2026_metrics.json`,
  `plan_ra/2024-2026/charts/2024-2026_comparison.svg /2024-2026_timeline.svg /2024-2026_allocation.svg`
  `plan_ra/2024-2026/2024-2026_plan.xlsx`,
  
* (Risk neutral)Files for plan_rn(2022-2023):
  `plan_rn/2022-2023/tables/2022-2023_trades.csv`,
  `plan_rn/2022-2023/tables/2022-2023_monthly.csv`,
  `plan_rn/2022-2023/tables/2022_2023_nav.csv`,
  `plan_rn/2022-2023/tables/2022_2023_metrics.json`,
  `plan_rn/2022-2023/charts/2022-2023_comparison.svg /2022-2023_timeline.svg /2022-2023_allocation.svg`
  `plan_rn/2022_2023/2022-2023_plan.xlsx`,
  
  and (2024-2026)
  `plan_rn/2024-2026/tables/2024-2026_trades.csv`,
  `plan_rn/2024-2026/tables/2024-2026_monthly.csv`,
  `plan_rn/2024-2026/tables/2024-2026_nav.csv`,
  `plan_rn/2024-2026/tables/2024-2026_metrics.json`,
  `plan_rn/2024-2026/charts/2024-2026_comparison.svg /2024-2026_timeline.svg /2024-2026_allocation.svg`
  `plan_rn/2024-2026/2024-2026_plan.xlsx`,

* (Risk take)Files for plan_rt(2022-2023):
  `plan_rt/2022-2023/tables/2022-2023_trades.csv`,
  `plan_rt/2022-2023/tables/2022-2023_monthly.csv`,
  `plan_rt/2022-2023/tables/2022_2023_nav.csv`,
  `plan_rt/2022-2023/tables/2022_2023_metrics.json`,
  `plan_rt/2022-2023/charts/2022-2023_comparison.svg /2022-2023_timeline.svg /2022-2023_allocation.svg`
  `plan_rt/2022_2023/2022-2023_plan.xlsx`,
  
  and (2024-2026)
  `plan_rt/2024-2026/tables/2024-2026_trades.csv`,
  `plan_rt/2024-2026/tables/2024-2026_monthly.csv`,
  `plan_rt/2024-2026/tables/2024-2026_nav.csv`,
  `plan_rt/2024-2026/tables/2024-2026_metrics.json`,
  `plan_rt/2024-2026/charts/2024-2026_comparison.svg /2024-2026_timeline.svg /2024-2026_allocation.svg`
  `plan_rt/2024-2026/2024-2026_plan.xlsx`,

* Files for plan_reuse(2023-2025):
  `plan_reuse/2023-2025/tables/2023-2025_trades.csv`,
  `plan_reuse/2023-2025/tables/2023-2025_monthly.csv`,
  `plan_reuse/2023-2025/tables/2023-2025_nav.csv`,
  `plan_reuse/2023-2025/tables/2023-2025_metrics.json`,
  `plan_reuse/2023-2025/charts/2023-2025_comparison.svg /2023-2025_timeline.svg /2023-2025_allocation.svg`
  `plan_reuse/2023-2025/2023-2025_plan.xlsx`,

---

## 7. How to verify / reproduce the important result

* The backtest is **deterministic** — re-running the same window reproduces the
  same numbers.
* Cross-check: final return equals `(last NAV / first NAV - 1) × 100`; NAV rows =
  489 (2022–2023) or 696 (2024–2026); HSI NAV values match
  `HSI_close_t / HSI_close_start × 1,000,000`.
* Sanity checks: peak holdings ≤ limits; commodity trade counts are non-trivial
  (hedges active); transaction-cost totals ≈ 0.11% × Σ(trade amounts).
* Risk profiler: the three archetype patterns above must land in the intended
  bands (conservative → RISK-AVERSE, neutral → RISK-NEUTRAL, risk-taker →
  RISK-TAKE); the survey is deterministic given the same answers.

---

## 8. Known failures and limitations
* **Close-based fills only** — no intraday OHLC; stops/targets trigger at the
  daily close, not intraday prices.
* **Stylized put** — constant premium, modeled payoff (strike = 95% of sleeve at
  month start, settled at next rebalance including intra-month sleeve flows);
  no market quotes. If all stocks exit mid-month the payoff only covers actual
  sleeve loss (flow-adjusted).
* **Risk profiler is a survey-based estimate** — self-reported answers, not a
  calibrated psychometric instrument; the classification bands
  (0.5 / 2.0) are practical conventions, not theory-derived cut-offs; the CE
  solver assumes strictly positive outcomes and clamps extremes at γ ∈ [-2, 12].
* No transaction costs beyond 0.11%/side (modeled), no dividends/taxes/splits.
* Momentum/regime signals use only closes; results are sensitive to the specific
  CSV universe and window (e.g., +47% in 2024–2026 vs -19.7% in 2022–2023).

**Disclaimer.** Research/educational use only; not investment advice.

---

## 9. Reused work, AI assistance, license, and attribution

* **Reused work**: `plan_v2.py` reuses the architecture of `enhance_plan.py`
  (same indicator math, backtest loop, stylized put model) with the v3 rule
  changes; `plan_ra.py` / `plan_rn.py` / `plan_rt.py` are built from the
  `plan_v2.py` rule set with per-profile allocation/stop/target constants;
  `plan_reuse.py` demonstrates applying the v2 rules to a new window; the
  earlier README (`README-v1.md`) documents `enhance_plan.py`.
* **Input data**: CSVs uploaded by the user (2021–2022 set in
  `2026-11-07/chat-1/outputs`, 2023–2026 set in `2026-11-08`).
* **AI assistance**: scripts, rule implementation were produced
  with AI (agent) assistance in a JiuwenSwarm/openJiuwen agent 
*  The openJiuwen platform is Apache-2.0.

---

## 10. openJiuwen GitHub link; public project version

* openJiuwen GitHub organization: **https://github.com/openJiuwen-ai**
* Flagship public repo (this agent ecosystem): **https://github.com/openJiuwen-ai/jiuwenswarm**
  (Apache-2.0)
* Official site / docs: **https://openjiuwen.com**
