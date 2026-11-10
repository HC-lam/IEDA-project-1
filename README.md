# plan_v2.py — Latest Adjusted HK Portfolio (v3 rules) 

---

## 1. User, task, and supported scope

**Retail investor.** A quantitative / research user testing a momentum-based HK
stock portfolio with commodity hedging and a stylized protective put, compared
against HSI. 

**Task — the v3 rules (as requested):**

1. Hold **at most 10 stocks**; hedge holdings capped at **2** (MAX_HEDGE = 2).
2. **Stock downtrend (exit trigger)**: close < SMA(20) **and** MACD line (DIF) < -0.1.
3. **Hedge regime**: HSI close < SMA(50) **only** — the MACD condition is dropped
   for hedges, and the **commodity buy filter is dropped**: hedges are bought
   whenever the regime is on (no requirement that Gold/Silver/Oil look bullish).
4. Held stocks are **not rebalanced monthly**. A stock exits on:
   **-15% stop** (restored) → own **downtrend** (close < SMA20 & DIF < -0.1) →
   **+60% target** (priority in that order; close-based fills).
5. **Transaction cost: 0.11%** of the traded amount on every buy and sell
   (stocks & commodities; the stylized put's premium counts as its cost).
6. Stylized monthly protective put on the stock sleeve, bought in risk-off
   months (premium 0.40%/month, strike 95%), payoff settled at the next
   rebalance against the modeled sleeve **including intra-month flows**.

**Supported windows (with the data provided):**

* **2021–2022** (default constants): backtest 2021-01-04 → 2022-12-30.
* **2022–2023**: backtest 2022-01-03 → 2023-12-29 — built by **in-memory
  merging** of the 2021–2022 files (2022 rows) + the 2023–2026 files (2023
  rows); 2021 acts as indicator warm-up.
* **2024–2026**: backtest 2024-01-02 → 2026-10-30 using the 2023–2026 files;
  2023 acts as indicator warm-up.

Out of scope: live trading, real option quotes, transaction costs beyond the
modeled 0.11%, dividends, taxes, corporate actions / splits, other markets.

---

## 2. Required software / model access and tested versions

* **Python 3 only, standard library** (`csv`, `math`, `os`). No pip installs,
  no API keys, no model access, no network access.
* Tested environment: macOS (Darwin 23.5.0), **Python 3.9.6**.
* Input CSVs are read as UTF-8 with BOM tolerance (`utf-8-sig`).

---

## 3. Input files / fields, units, sources, data-access instructions

Two data sets are used (uploaded by the user):

```
2021-2022 files: /Users/hoddychan/Documents/JiuwenSwarm/2026-11-07/chat-1/outputs
2023-2026 files: /Users/hoddychan/Documents/JiuwenSwarm/2026-11-08
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
* The script only ever **reads** the CSVs; it never modifies them.

---

## 4. How to start

Default (2021–2022):

```bash
python3 /Users/hoddychan/Documents/JiuwenSwarm/2026-11-08/chat-1/work/plan_v2.py
```

Other windows (the script intentionally has no CLI; override constants via an
inline import — this is the exact command used):

```bash
# 2022-2023 (in-memory merge; 2021 warm-up)
cd /Users/hoddychan/Documents/JiuwenSwarm/2026-11-08/chat-1/work && python3 - <<'PY'
import plan_v2
plan_v2.START = "2022-01-03"
plan_v2.END   = "2023-12-29"
plan_v2.main()
PY

# 2024-2026
cd /Users/hoddychan/Documents/JiuwenSwarm/2026-11-08/chat-1/work && python3 - <<'PY'
import os, plan_v2
plan_v2.REPO     = "/Users/hoddychan/Documents/JiuwenSwarm/2026-11-08"
plan_v2.START    = "2024-01-02"
plan_v2.END      = "2026-10-30"
plan_v2.HSI_CSV  = os.path.join(plan_v2.REPO, "HSI_daily_2023-01-01_to_2026-10-31.csv")
plan_v2.WIDE_CSV = os.path.join(plan_v2.REPO, "HK_stocks_close_2023-01-01_to_2026-10-31_wide.csv")
plan_v2.COM_CSV  = os.path.join(plan_v2.REPO, "Commodities_close_2023-01-01_to_2026-10-31_wide.csv")
plan_v2.main()
PY
```

No skill invocation needed. Runtime: a few seconds per window.

---

## 5. One small example and its expected checks

Verified console summary (run 2026-11-09) — **2022–2023** window:

```text
PLAN V3 (latest rules) - APPROXIMATE RESULT | 2022-2023
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
* Peak concurrent holdings never exceed 10 stocks / 2 hedges.
* The run prints "No output files were created (requested)." and creates nothing.

---

## 6. Output files and what they mean

**Currently: none.** The v3 script intentionally prints a console summary only.
Full deliverables (per window) are planned once approved:

| Planned file | Meaning |
|---|---|
| `tables/<window>_trades.csv` | Every buy/sell/option event with price, amount, cost, reason, P&L |
| `tables/<window>_monthly.csv` | Monthly rebalance rows (date, regime, target weights, holdings, NAV) |
| `tables/<window>_nav.csv` | Daily NAV (portfolio vs HSI, normalized to 1,000,000) |
| `tables/<window>_metrics.json` | Return, drawdown, Sharpe, tail loss, trade counts, costs |
| `charts/…comparison.svg / timeline.svg / allocation.svg` | Portfolio vs HSI; trade timeline; allocation |
| `<window>_plan.xlsx` | 3 sheets (Trades, Monthly Allocation, Metrics) |

---

## 7. How to verify / reproduce the important result

* The backtest is **deterministic** — re-running the same window reproduces the
  same numbers.
* Cross-check: final return equals `(last NAV / first NAV - 1) × 100`; NAV rows =
  489 (2022–2023) or 696 (2024–2026); HSI NAV values match
  `HSI_close_t / HSI_close_start × 1,000,000`.
* Sanity checks: peak holdings ≤ limits; commodity trade counts are non-trivial
  (hedges active); transaction-cost totals ≈ 0.11% × Σ(trade amounts).

---

## 8. Known failures and limitations

* **No CLI args yet** — windows are switched by overriding module constants
  (inline import) or editing the constants at the top of the file.
* **Hard-coded absolute paths** — moving the job requires editing `REPO*`,
  `*_CSV`, `START`, `END`.
* **Close-based fills only** — no intraday OHLC; stops/targets trigger at the
  daily close, not intraday prices.
* **2022–2023 uses an in-memory merge** of two CSV sets; requires the same 79
  ticker columns in both wide files (verified) and contiguous dates.
* **Stylized put** — constant premium, modeled payoff (strike = 95% of sleeve at
  month start, settled at next rebalance including intra-month sleeve flows);
  no market quotes. If all stocks exit mid-month the payoff only covers actual
  sleeve loss (flow-adjusted)
* **Indicator warm-up**: with the 2022–2023 window, 2021 is warm-up; with
  2024–2026, 2023 is warm-up. If a window started at the very first data row,
  the first ~60 trading days would have no stock candidates.
* Transaction costs is fixed at 0.11%/side (modeled), no dividends/taxes/splits.
* Momentum/regime signals use only closes; results are sensitive to the specific
  CSV universe and window (e.g., +47% in 2024–2026 vs -19.7% in 2022–2023).

**Disclaimer.** Research/educational use only; not investment advice.

---

## 9. Reused work, AI assistance, license, and attribution

* **Reused work**: `plan_v2.py` reuses the architecture of `enhance_plan.py`
  (same indicator math, backtest loop, stylized put model) with the v3 rule
  changes; the earlier README (`README.md`) documents `enhance_plan.py`.
* **Input data**: CSVs uploaded by the user on 2026-11-09 (2021–2022 set in
  `2026-11-07/chat-1/outputs`, 2023–2026 set in `2026-11-08`).
* **AI assistance**: script, rule implementation 
* **License**: no explicit license; treat as all-rights-reserved unless the
  owner publishes one.

---

## 10. openJiuwen GitHub link; public project version

* openJiuwen GitHub organization: **https://github.com/openJiuwen-ai**
* Flagship public repo (this agent ecosystem): **https://github.com/openJiuwen-ai/jiuwenswarm**
  (Apache-2.0)
* Official site / docs: **https://openjiuwen.com**
* **Version**: `plan_v2.py` has no formal version tag — "v3 rules" dated
  **2026-11-09**. For the public project version, check the `jiuwenswarm`
  repository's **Releases** page (no pinned release number asserted here).
