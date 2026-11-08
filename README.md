# enhance_plan.py — Enhanced HK Equity Backtest with Hedges & Stylized Put

A self-contained, pure-stdlib Python backtest that rebalances a Hong Kong equity
portfolio **every month** (first trading day, signals from the previous close),
holds a commodity hedge sleeve (Gold / Silver / Oil, equal weight), optionally
buys a **stylized** monthly protective put on the equity sleeve, and compares
the result against the Hang Seng Index (HSI).

Created **2026-11-08** as the "5-enhancements" variant of an earlier backtest
series (adjusted / hedge / constraint plans) at the user's request to improve
performance after the previous fixed-rule plan lost money.

**Last verified run: 2026-11-09** with the uploaded CSVs and the close-based
fill variant (see Section 8: the intraday OHLC long file is canceled).

---

## 1. User, task, and supported scope

**retail investor.** A quantitative / research user who wants to test rule-based
HK stock selection with a hedged, monthly-rebalanced portfolio and compare it
against HSI. This is a research backtest, **not** a live trading system.

**Task.** Execute the enhanced plan with these user-chosen rules:

* Monthly rebalance on the first trading day; signals use the **previous close**
  (`idx-1`).
* Equity sleeve: names passing `SMA5 > SMA10`, MACD positive
  (fast EMA 12 > slow EMA 26 vs. 9-period DEA signal), `close > SMA50`,
  ranked by 60-day momentum; hold **top 5** names (was 8).
* Hard risk controls per name: **-15% stop-loss** and **+60% target**, with
  **close-based fills** (the long OHLC file is canceled, so intraday
  stop/target price fills are not used).
* Hedge sleeve: Gold / Silver / Oil, equal weight, minimum **5%** of NAV;
  ~**6%** in risk-on months, ~**30%** in risk-off months.
* Cash floor enforced by trimming: **10%** risk-on / **30%** risk-off at monthly
  rebalance, plus a hard **10%** daily floor.
* Optional stylized protective put on the equity sleeve, bought **only in
  risk-off months**: premium **0.40%/month**, strike **95%** of the sleeve at
  month start, payoff `max(strike − sleeve_at_next_rebalance, 0)`.
* Risk-off flag: HSI close below its **moving average** (see Limitations: the
  code uses an SMA(10), despite the "200-day" label in comments).
* Start **2024-01-02**, end **2026-10-30**; 2023 is indicator warm-up.
* Starting NAV: ¥1,000,000 (HKD-equivalent cash).

**Supported scope.** Exactly the three CSV inputs described in Section 3,
covering 2023-01-01 .. 2026-10-31. The script will not run without them.
Out of scope: live trading, real option quotes, transaction costs, slippage,
dividends, taxes, corporate actions / splits, other exchanges or asset classes.

---

## 2. Required software / model access and tested versions

* **Python 3 only, standard library** (`csv`, `json`, `math`, `os`, `sys`,
  `zipfile`, `shutil`, `xml.sax.saxutils`). **No pip installs, no API keys, no
  model access, no network access.**
* Tested / verified environment for this workspace:
  * macOS (Darwin 23.5.0) with **Python 3.9.6**.
  * Code relies only on Python 3.7+ semantics (dict insertion order, f-strings);
    no 3.10+ syntax is used.
* Charts are hand-written SVG files and the spreadsheet is a minimal xlsx built
  with `zipfile` + XML — no matplotlib / openpyxl / pandas required.
* Input CSVs are read as UTF-8 with BOM tolerance (`utf-8-sig`).

---

## 3. Input files / fields, units, sources, data-access instructions

Paths are **hard-coded** at the top of the script (`REPO` and `OUTDIR`):

```
REPO   = /Users/hoddychan/Documents/JiuwenSwarm/2026-11-08
OUTDIR = /Users/hoddychan/Documents/JiuwenSwarm/2026-11-08/portfolio_eval
```

| File | Columns used | Units | Role |
|---|---|---|---|
| `HSI_daily_2023-01-01_to_2026-10-31.csv` | `Date`, `Close` | HSI index points | **Master calendar** (939 rows, 2023-01-03 … 2026-10-30); benchmark; risk-off flag |
| `HK_stocks_close_2023-01-01_to_2026-10-31_wide.csv` | `Date` + one column per HK ticker | HKD per share | Closing prices; universe definition; missing cells are **forward-filled** |
| `Commodities_close_2023-01-01_to_2026-10-31_wide.csv` | `Date`, `Gold`, `Silver`, `Oil` | market quotation units | Hedge sleeve prices (HKD-agnostic; only relative returns matter) |

**Canceled input.** `HK_stocks_daily_2023-01-01_to_2026-10-31_long.csv`
(intraday `Open/High/Low/Close`) **does not exist** and is no longer required.
Stock stop/target exits use daily **close** prices instead (reason strings
`stop_close_fill` / `target_close_fill`).

**Also uploaded but unused.** `HK_stocks_MA_SMA_MACD_2023-01-01_to_2026-10-31.csv`
(precomputed `MA5/MA10/MA50/SMA5/SMA10/MACD/Signal/Histogram`) is present in the
data folder but the script **computes its own indicators internally** from the
wide close file; the CSV is kept as a reference / cross-check artifact only.

Notes on units and semantics:

* All returns are relative; the portfolio NAV is simply treated as HKD cash
  (`INIT_CASH = 1,000,000.0`). Commodity prices are never currency-converted —
  only their relative returns matter internally.
* The **HSI file drives the master date list**; the **wide stock file is
  row-aligned with it** (verified: both have 939 rows in the same order).
  The commodity file is aligned by date string via an internal map (verified:
  all 939 HSI dates exist in the commodity file; the commodity file has 50 extra
  US-only trading days that are simply ignored).
* Sources: the three input CSVs were uploaded by the user on **2026-11-09** to
  `/Users/hoddychan/Documents/JiuwenSwarm/2026-11-08/`.
* Data-access instructions:
  1. Keep the three files in `REPO` (`.../2026-11-08/`) with these exact file
     names, **or** edit the `REPO` path at the top of `enhance_plan.py`.
  2. Keep column names (`Date` + ticker columns / `Gold`,`Silver`,`Oil`) and the
     2023-01-01 .. 2026-10-31 date range.
  3. The script only ever **reads** these files; it never modifies them.

---

## 4. How to start

```bash
python3 /Users/hoddychan/Documents/JiuwenSwarm/2026-11-08/chat-1/work/enhance_plan.py
```

* No skill invocation is needed — this is a standalone script (it was authored
  inside an agent chat, but it runs under plain `python3`).
* The output directory (`OUTDIR`, default
  `/Users/hoddychan/Documents/JiuwenSwarm/2026-11-08/portfolio_eval`) and its
  `tables/` and `charts/` subfolders are created automatically.
* Runtime is a few seconds (verified run: 696 backtest days, 34 monthly
  rebalances, 429 trades).

---

## 5. One small example and its expected checks

Verified console output (run on 2026-11-09 with the uploaded data):

```text
======================================================================
ENHANCED PLAN EXECUTION SUMMARY (5 enhancements)
======================================================================
Window: 2024-01-02 .. 2026-10-30 (696 days, 34 monthly rebalances)
Portfolio final return: 17.95%   HSI final return: 38.75%
Portfolio max drawdown: -20.13%   HSI max drawdown: -19.95%
Portfolio Sharpe: 0.409   HSI Sharpe: 0.631
Portfolio tail loss: -1.789%   HSI tail loss: -1.955%
Trades: 429 total (stocks=303, commodities=102, options=24); realized P&L = 219269.33
Option hedge: stylized monthly protective put on the stock sleeve (premium 0.40%/mo, strike 95%) - model only, no market quotes in data
Outputs in: /Users/hoddychan/Documents/JiuwenSwarm/2026-11-08/portfolio_eval
```

Expected structural checks after a successful run:

* The window line shows `2024-01-02 .. 2026-10-30` and **34 monthly
  rebalances** (2024-01 through 2026-10, one row per month).
* All output files in Section 6 exist and are non-empty; the three SVGs parse
  as XML.
* `tables/enhance_metrics.json` contains the groups `portfolio`, `hsi`,
  `hedge`, `correlation`, `trades`, `notes` with the values printed in the
  console summary.
* `enhance_plan.xlsx` opens with exactly 3 sheets: `Trades`, `Monthly
  Allocation`, `Metrics`, and the sheet row counts match the corresponding CSVs.
* Sanity cross-check of the headline result (see Section 7 for the command):
  NAV-implied portfolio return **17.9459%** equals `portfolio.final_return_pct`,
  and the last `Portfolio` row equals `portfolio.final_value`.

---

## 6. Output files and what they mean

All outputs are written under `OUTDIR`
(`/Users/hoddychan/Documents/JiuwenSwarm/2026-11-08/portfolio_eval`).

| File | Meaning |
|---|---|
| `tables/enhance_plan_trades.csv` | Every trade (stock / commodity / option) with columns `trade_id, asset, type, action, date, price, quantity, amount, reason, pnl, r_multiple`. `r_multiple` = P&L ÷ (entry price × 0.15). Stock stop/target exits use reason `stop_close_fill` / `target_close_fill`. |
| `tables/enhance_plan_monthly.csv` | One row per monthly rebalance (34 rows): `Date, RiskOff, TargetStock, TargetHedge, TargetCash, StocksHeld, HedgesHeld, Option, NAV`. |
| `tables/enhance_nav.csv` | Daily NAV series (696 rows): `Date, Portfolio, HSI, PortCorr60, HedgeWeight`. HSI is scaled to start at `INIT_CASH` (¥1,000,000); `PortCorr60` is the portfolio's 60-day correlation to HSI (blank when unavailable). |
| `tables/enhance_metrics.json` | Comparison metrics: `portfolio` & `hsi` (final return %, max drawdown %, Sharpe, tail loss % = 5th-percentile daily loss), `hedge` (min target 5%, min daily hedge weight, days below 5%), `correlation` (max abs 60d corr reported; cap removed), `trades` (counts, realized P&L), `notes`. |
| `charts/enhance_comparison.svg` | Portfolio vs HSI, both normalized to 100. |
| `charts/enhance_timeline.svg` | Trade timeline: green ▲ buys / red ▼ sells per asset. |
| `charts/enhance_allocation.svg` | Allocation share by asset (buy-value share of months). |
| `enhance_plan.xlsx` | Same data as 3 worksheets: `Trades`, `Monthly Allocation`, `Metrics` (minimal stdlib-built xlsx, no styling/formulas). |
| `enhance_plan_trades.csv`, `enhance_plan_monthly.csv`, `enhance_nav.csv` | Convenience copies of the three CSV tables placed next to the xlsx. |

---

## 7. How to verify / reproduce the important result

The backtest is **deterministic** (no randomness), so re-running from the same
inputs reproduces identical outputs.

1. **Run**: `python3 .../enhance_plan.py`.
2. **Console ↔ JSON match**: every number printed in the execution summary must
   equal its counterpart in `tables/enhance_metrics.json` (portfolio/hsi
   returns, drawdowns, Sharpe, tail loss; `trades.count`; etc.).
3. **NAV cross-check** (verified on 2026-11-09; replace `<OUTDIR>` with your
   output dir):

   ```bash
   python3 - <<'PY'
   import csv, json
   rows = list(csv.DictReader(open("<OUTDIR>/tables/enhance_nav.csv")))
   m = json.load(open("<OUTDIR>/tables/enhance_metrics.json"))
   nav_ret = (float(rows[-1]["Portfolio"]) / float(rows[0]["Portfolio"]) - 1) * 100
   print("NAV-implied return:", round(nav_ret, 4))
   print("metrics final_return_pct:", m["portfolio"]["final_return_pct"])
   print("HSI final_value == last HSI row:", abs(float(rows[-1]["HSI"]) - m["hsi"]["final_value"]) < 1e-6)
   print("Portfolio final_value == last NAV row:", abs(float(rows[-1]["Portfolio"]) - m["portfolio"]["final_value"]) < 1e-6)
   PY
   ```

   Reference values from the verified run: NAV rows = 696
   (2024-01-02 → 2026-10-30), NAV-implied portfolio return **17.9459**,
   HSI return **38.7518**, `final_value = 1,179,459.05`.

4. **Data integrity**: confirm the three input CSVs are byte-identical
   before/after the run (the script opens them read-only).
5. **Spreadsheet**: open `enhance_plan.xlsx`; it must contain 3 sheets whose
   row counts match the CSV files in `tables/` (Trades = 429 rows, Monthly = 34
   rows, Metrics = 29 key/value rows).
6. **Charts**: the three SVGs exist, are well-formed XML, and the timeline chart
   shows both buy (▲) and sell (▼) markers; the allocation pie labels sum to
   ~100%.

---

## 8. Known failures and limitations

**Data / environment**

* **Input-data issue resolved 2026-11-09**: the three CSVs are now present in
  `REPO` and the backtest was run successfully. `python3 enhance_plan.py` will
  still fail with `FileNotFoundError` if any of the three files (or `REPO`) is
  missing/moved.
* **The long OHLC file is canceled** (`HK_stocks_daily_..._long.csv` does not
  exist). Consequence: stock stops/targets use **close-based fills**, not
  intraday stop-price fills. Stops can only trigger at the daily close, so the
  realized stop price is the close itself (≤ the −15% stop level), and the +60%
  target is only captured at a close at/above target — results differ from a
  true intraday fill model.
* **Hard-coded absolute paths** (`REPO`, `OUTDIR`) — must be edited to move the
  job to another machine.
* **HSI ↔ wide-stock row alignment is assumed, not checked** (verified OK for
  the current files: both have 939 rows in the same order). The HSI file is the
  master calendar; the wide file is consumed by position. Mismatched rows
  silently misalign dates and prices.
* **Forward-fill of blank stock cells**: if the *first* cell of a ticker column
  is blank, the filler raises `IndexError` (it appends `filled[tk][-1]`).
* **Commodity dates are mapped by exact date string** (`com_idx[d]`); any
  backtest date missing from the commodities file raises `KeyError` (verified
  OK for the current files: all 939 HSI dates are covered; the commodity file's
  50 extra non-HK days are ignored).

**Documentation-vs-code mismatches (labels are misleading; code is authoritative)**

* The docstring/comments call the HSI filter a "**200-day SMA**", but the code
  computes `hsi_sma200` as an **SMA(10)** (`SMA_MED = 10`). The risk-off flag is
  therefore `HSI close < SMA(10)`, a much faster regime filter.
* The module docstring says hedge sleeve is "**at least 10%**" of NAV, but the
  enforced minimum is `HEDGE_MIN = 0.05` (**5%**). Relatedly, the
  `hedge.days_hedge_below_10pct` metric counts days below **5%**, not 10%.
* `tables/enhance_metrics.json` `notes.option_model` says "premium **1.5%**/mo",
  but the backtest actually uses `PUT_PREMIUM = 0.0040` (**0.40%**/mo).
* The docstring cash floor ("20% risk-on / 40% risk-off") does not match the
  code (**10% / 30%**, plus a hard 10% daily floor; the daily-loop comment
  "hard floor 20%" is also stale — the code uses 10%).
* The entry comment "MA5>MA10" duplicates "SMA5>SMA10" — they are the same
  series (`sma20` slot actually holds SMA(5); `sma200` slot holds SMA(10)).

**Model limitations**

* **The protective put is stylized**: constant premium (0.40%/month), strike =
  95% of the modeled sleeve, payoff settled only at the next rebalance against
  the modeled sleeve + intra-month cash flow. No option market data exists in
  the repository, so it is a proxy, not a tradable instrument.
* **Final month's put is discarded**: at period end, any outstanding option is
  cleared (`option = None`) without paying its payoff — the last premium is
  effectively lost in accounting.
* **No transaction costs, slippage, dividends, taxes, or corporate action
  adjustments.** Close prices (wide file) are forward-filled for missing days;
  there is no intraday OHLC.
* **Selection can return fewer than 5 names** (or zero) in a month, so the
  equity sleeve may be underinvested or empty.
* **Correlation constraint removed** per user request (`CORR_CAP = None`), but a
  wide sanity band remains: any stock whose 60-day |correlation| to HSI exceeds
  **0.80** is exited daily. `VAR_Z = 1.645` is defined but unused.
* **Small universe + short window + warm-up**: 2023 exists only to compute
  indicators; results are heavily dependent on the specific CSV universe and the
  2024-2026 regime (e.g., the plan returned +17.95% vs HSI +38.75% over this
  window).
* `write_xlsx` hard-codes **exactly 3 worksheet overrides** in `[Content_Types]
  .xml`; adding a 4th sheet would produce an invalid xlsx. The writer has no
  styling or formula support.
* Metrics like Sharpe and "tail loss" use daily returns with simple formulas
  (no risk-free rate, tail loss is a single 5%-quantile value, not CVaR).

**Disclaimer.** Research/educational use only; not investment advice.

---

## 9. Reused work, AI assistance, license, and attribution

* **Reused work**: `enhance_plan.py` shares its architecture and helper code
  (CSV loading, indicators, daily loop, SVG chart writers, minimal xlsx writer)
  with the sibling scripts in this folder (`adjusted_plan.py`, `hedge_plan.py`,
  `constraint_plan.py`, `backtest_eval.py`, `verify_eval.py`) and with the
  earlier eval outputs already under `2026-11-08/chat-1/outputs/portfolio_eval/`.
* **Input data**: the three input CSVs were uploaded by the user on 2026-11-09
  to `/Users/hoddychan/Documents/JiuwenSwarm/2026-11-08/`; the precomputed
  `HK_stocks_MA_SMA_MACD_...csv` in the same folder is not consumed by the
  script.
* **AI assistance**: this script — and this README — were produced with AI
  (agent) assistance in a JiuwenSwarm/openJiuwen agent environment at the
  user's request on 2026-11-08 (script) and 2026-11-09 (README update + close
  fill adaptation). The strategy choices (the five enhancements) were specified
  by the user; the implementation and documentation were AI-generated and
  user-reviewed.
* **License**: no explicit license is included in the file. Unless the owner
  publishes one, treat the script and outputs as all-rights-reserved. The
  openJiuwen platform (below) is Apache-2.0.

---

## 10. openJiuwen GitHub link; public project version

* openJiuwen GitHub organization: **https://github.com/openJiuwen-ai**
* Flagship public repo (this agent ecosystem): **https://github.com/openJiuwen-ai/jiuwenswarm**
  (Apache-2.0) — the JiuwenSwarm multi-agent framework/JiuwenSwarm agent used to
  run this session.
* Official site / docs: **https://openjiuwen.com**
* **Version**: `enhance_plan.py` has no formal version tag — it is the
  "5-enhancements + close-fill" variant dated **2026-11-08/2026-11-09**. For the
  *public project* version, check the `jiuwenswarm` repository's **Releases**
  page for the latest tag (no pinned release number is asserted here).
