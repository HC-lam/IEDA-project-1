#!/usr/bin/env python3
"""plan_reuse_2023_2025.py - REUSE CASE: v3 rules applied to a NEW-CASE setup.

Reusable contribution built from plan_v2_outputs.py (which is left untouched):
the same v3 trading skill, backtest loop, cost model, and output pipeline are
reused verbatim; only the case inputs are changed:
  - Universe: 30 selected HK names (0001.HK ... 0868.HK)
  - Max 8 stock holdings (MAX_STOCKS = 8)
  - Hedge sleeve: Gold only (HEDGE_ASSETS = ("Gold",), MAX_HEDGE = 1)
  - Window: 2023-01-03 .. 2025-12-31 (2022 acts as indicator warm-up)
This demonstrates reuse beyond the original 2022-2023 / 2024-2026 conversation.

This generator runs the window given on the command line and writes:
  <OUT>/tables/<win>_trades.csv, _monthly.csv, _nav.csv, _metrics.json
  <OUT>/charts/<win>_comparison.svg, _timeline.svg, _allocation.svg
  <OUT>/<win>_plan.xlsx   (+ CSV copies next to the xlsx)
  <OUT>/run_manifest.json  (input hashes + resolved config: fresh-run evidence)

Portability fixes over the 2025-11-15 version (which only ran on one machine):
  * no absolute paths are baked in: the six input CSVs are discovered next to
    this script, in ./data, ./2026-11-08, ./2026-11-07/chat-1/outputs, or in any
    of the three parent directories -- or wherever $PLAN_DATA_DIR points.
  * every case parameter is a CLI flag, so a NEW case runs without editing code:
      ./plan_reuse.py --start 2023-07-03 --end 2025-06-30 --max-stocks 10 \
                      --hedges Gold,Silver --out portfolio_eval/fresh_case
  * indicator warm-up is no longer wired to a single window: the 2021-2022 file
    set is always loaded first as history and the 2023-2026 set is appended
    (filtered to Date <= END), so arbitrary START/END values work.
  * START/END are snapped to the first/last trading day actually present.
  * the SVG escaper now really escapes (it used to be a no-op, which produced
    invalid SVG whenever a label contained & < >).
  * a run_manifest.json records resolved input paths + SHA-256 of each input +
    the effective config + Python/platform, so a run is auditable.

`./plan_reuse.py --help` lists every flag. The defaults reproduce the 2023-2025
reuse case exactly (window, universe, MAX_STOCKS=8, Gold-only hedge, 0.11%/side,
-15% stop, +60% target).
"""
import argparse, csv, hashlib, json, math, os, platform, shutil, sys, zipfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

# --- input files: resolved by search, never hard-coded absolute paths ------
OLD_HSI  = "HSI_daily_2021-01-01_to_2022-12-31.csv"
OLD_WIDE = "HK_stocks_close_2021-01-01_to_2022-12-31_wide.csv"
OLD_COM  = "Commodities_close_2021-01-01_to_2022-12-31_wide.csv"
NEW_HSI  = "HSI_daily_2023-01-01_to_2026-10-31.csv"
NEW_WIDE = "HK_stocks_close_2023-01-01_to_2026-10-31_wide.csv"
NEW_COM  = "Commodities_close_2023-01-01_to_2026-10-31_wide.csv"
ALL_FILES = (OLD_HSI, OLD_WIDE, OLD_COM, NEW_HSI, NEW_WIDE, NEW_COM)

_RESOLVED = {}

def _candidate_dirs():
    """Directories searched for the input CSVs, in priority order."""
    dirs = []
    env = os.environ.get("PLAN_DATA_DIR")
    if env:
        dirs.append(env)
    dirs += [HERE,
             os.path.join(HERE, "data"),
             os.path.join(HERE, "2026-11-08"),
             os.path.join(HERE, "2026-11-07", "chat-1", "outputs")]
    up = HERE
    for _ in range(3):
        parent = os.path.dirname(up)
        if not parent or parent == up:
            break
        up = parent
        dirs += [up,
                 os.path.join(up, "2026-11-08"),
                 os.path.join(up, "2026-11-07", "chat-1", "outputs")]
    seen, out = set(), []
    for d in dirs:
        d = os.path.abspath(d)
        if os.path.isdir(d) and d not in seen:
            seen.add(d)
            out.append(d)
    return out

def resolve(name):
    """Absolute path of one input CSV; raises a helpful error when it is absent."""
    if name in _RESOLVED:
        return _RESOLVED[name]
    for d in _candidate_dirs():
        p = os.path.join(d, name)
        if os.path.isfile(p):
            _RESOLVED[name] = p
            return p
    raise FileNotFoundError(
        "missing input file: %s\nsearched these directories:\n  %s\n"
        "put the six CSVs next to this script, or set PLAN_DATA_DIR=<their folder>."
        % (name, "\n  ".join(_candidate_dirs())))

OUT_DIR   = None                       # set by --out; None -> <HERE>/portfolio_eval/plan_reuse/<win>
CASE_LABEL = "Plan Reuse 2023-2025"     # chart title label, set by --label

START, END        = "2023-01-03", "2025-12-31"
INIT_CASH         = 1_000_000.0
MAX_STOCKS        = 8
MAX_HEDGE         = 1          # cap on hedge holdings (Gold only)
HEDGE_ASSETS      = ("Gold",)  # hedge sleeve assets: Gold only
UNIVERSE          = ["0001.HK","0002.HK","0003.HK","0005.HK","0006.HK","0012.HK","0016.HK",
                     "0017.HK","0027.HK","0066.HK","0083.HK","0101.HK","0175.HK","0241.HK",
                     "0267.HK","0285.HK","0288.HK","0291.HK","0316.HK","0322.HK","0386.HK",
                     "0388.HK","0669.HK","0688.HK","0700.HK","0762.HK","0823.HK","0836.HK",
                     "0857.HK","0868.HK"]
COST              = 0.0011     # 0.11% per buy / per sell
TARGET            = 0.60       # +60% target
STOP_LOSS         = 0.15       # -15% stop loss restored
MACD_DOWN         = -0.1       # downtrend requires DIF < -0.1
MOM_WIN           = 60
STOCK_W_RO, HEDGE_W_RO, CASH_W_RO = 0.40, 0.30, 0.30   # HSI downtrend regime
STOCK_W_ON, CASH_W_ON             = 0.84, 0.16          # HSI uptrend regime
PUT_PREMIUM, PUT_STRIKE = 0.0040, 0.95

def load(p):
    with open(p, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0

def pstd(xs):
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))

def ema_series(vals, span):
    if not vals:
        return []
    a = 2.0 / (span + 1.0)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(a * v + (1.0 - a) * out[-1])
    return out

def indicators(closes):
    n = len(closes)
    sma5  = [mean(closes[i+1-5:i+1])  if i+1 >= 5  else None for i in range(n)]
    sma10 = [mean(closes[i+1-10:i+1]) if i+1 >= 10 else None for i in range(n)]
    sma20 = [mean(closes[i+1-20:i+1]) if i+1 >= 20 else None for i in range(n)]
    sma50 = [mean(closes[i+1-50:i+1]) if i+1 >= 50 else None for i in range(n)]
    ema_f = ema_series(closes, 12); ema_s = ema_series(closes, 26)
    dif = [ema_f[i] - ema_s[i] for i in range(n)]
    dea = ema_series(dif, 9)
    macd_pos = [dif[i] > dea[i] for i in range(n)]
    return dict(sma5=sma5, sma10=sma10, sma20=sma20, sma50=sma50, dif=dif, dea=dea, macd_pos=macd_pos)

def max_drawdown(vals):
    peak = -1e18; mdd = 0.0
    for v in vals:
        if v > peak:
            peak = v
        dd = (v - peak) / peak if peak > 0 else 0.0
        if dd < mdd:
            mdd = dd
    return mdd

def sharpe(rets):
    if len(rets) < 2:
        return 0.0
    s = pstd(rets)
    return 0.0 if s == 0 else mean(rets) / s * math.sqrt(252.0)

def tail_loss(rets, q=0.05):
    if not rets:
        return 0.0
    srt = sorted(rets)
    return srt[max(1, int(round(q * len(srt)))) - 1]

def load_rows(start=None, end=None):
    """Merge both file sets in memory, for an arbitrary window.

    The 2021-2022 set is always loaded first and acts purely as indicator
    warm-up history; the 2023-2026 set is appended when the window reaches into
    2023 or later, truncated at `end`. Rows are date-sorted, de-duplicated and
    finally clipped to Date <= end, so START/END no longer select a behaviour.
    """
    start = START if start is None else start
    end = END if end is None else end
    paths = {n: resolve(n) for n in ALL_FILES}

    sets = [(OLD_HSI, OLD_WIDE, OLD_COM)]
    if end > "2022-12-31":
        sets.append((NEW_HSI, NEW_WIDE, NEW_COM))

    merged = {"hsi": [], "wide": [], "com": []}
    for hs, ws, cs in sets:
        merged["hsi"] += load(paths[hs])
        merged["wide"] += load(paths[ws])
        merged["com"] += load(paths[cs])

    out = []
    for key in ("hsi", "wide", "com"):
        rows, seen = [], set()
        for r in sorted(merged[key], key=lambda r: r["Date"]):
            d = r["Date"]
            if d in seen or d > end:
                continue
            seen.add(d)
            rows.append(r)
        out.append(rows)
    return out[0], out[1], out[2]

def main():
    hsi, wide, com = load_rows()

    dates = [r["Date"] for r in hsi]
    date_idx = {d: i for i, d in enumerate(dates)}

    # --- stock closes (leading blanks back-filled; fully blank columns dropped) ---
    tickers_all = [c for c in wide[0].keys() if c != "Date"]
    first_val, has_val = {}, {}
    for r in wide:
        for tk in tickers_all:
            v = r.get(tk, "").strip()
            if v != "":
                has_val[tk] = True
                if tk not in first_val:
                    first_val[tk] = float(v)
    universe_set = set(UNIVERSE)
    tickers = [tk for tk in tickers_all if has_val.get(tk) and tk in universe_set]
    closes = {tk: [] for tk in tickers}
    for r in wide:
        for tk in tickers:
            v = r.get(tk, "").strip()
            closes[tk].append(float(v) if v != "" else (closes[tk][-1] if closes[tk] else first_val[tk]))

    # --- commodity closes aligned to HSI dates (forward/back fill blanks) ---
    com_raw = {k: {r["Date"]: float(r[k]) for r in com if r[k].strip() != ""} for k in HEDGE_ASSETS}
    com_close = {k: [] for k in HEDGE_ASSETS}
    for k in HEDGE_ASSETS:
        avail = [d for d in dates if d in com_raw[k]]
        first_avail = com_raw[k][avail[0]] if avail else 0.0
        prev = None
        for d in dates:
            if d in com_raw[k]:
                prev = com_raw[k][d]
                com_close[k].append(prev)
            else:
                com_close[k].append(prev if prev is not None else first_avail)

    hsi_close = [float(r["Close"]) for r in hsi]
    stock_ind = {tk: indicators(closes[tk]) for tk in tickers}
    hsi_ind = indicators(hsi_close)
    com_ind = {k: indicators(com_close[k]) for k in HEDGE_ASSETS}
    mom60 = {tk: [closes[tk][i] / closes[tk][i - MOM_WIN] - 1.0 if i >= MOM_WIN else None
                  for i in range(len(closes[tk]))] for tk in tickers}
    for k in HEDGE_ASSETS:       # commodity momentum for hedge ranking
        c = com_close[k]
        mom60[k] = [c[i] / c[i - MOM_WIN] - 1.0 if i >= MOM_WIN else None for i in range(len(c))]

    def hsi_downtrend(idx):          # combined regime (close<SMA50 AND DIF<-0.1), prev close
        if idx < 1:
            return True
        j = idx - 1
        sma50 = hsi_ind["sma50"][j]; dif = hsi_ind["dif"][j]
        if sma50 is None or dif is None:
            return True
        return hsi_close[j] < sma50 and dif < MACD_DOWN

    def hsi_hedge_regime(idx):       # hedge trigger: HSI close < SMA(50) ONLY (no MACD)
        if idx < 1:
            return True
        j = idx - 1
        sma50 = hsi_ind["sma50"][j]
        if sma50 is None:
            return True
        return hsi_close[j] < sma50

    def stock_downtrend(tk, idx):    # CURRENT close: close < SMA(20) AND DIF < -0.1
        sma20 = stock_ind[tk]["sma20"][idx]; dif = stock_ind[tk]["dif"][idx]
        if sma20 is None or dif is None:
            return False
        return closes[tk][idx] < sma20 and dif < MACD_DOWN

    def stock_entry_ok(tk, idx):
        i = stock_ind[tk]
        if i["sma5"][idx] is None or i["sma10"][idx] is None or i["sma50"][idx] is None:
            return False
        if not (i["sma5"][idx] > i["sma10"][idx]):
            return False
        if not i["macd_pos"][idx]:
            return False
        if not (closes[tk][idx] > i["sma50"][idx]):
            return False
        return mom60[tk][idx] is not None

    def com_entry_ok(k, idx):
        i = com_ind[k]
        if i["sma5"][idx] is None or i["sma10"][idx] is None or i["sma50"][idx] is None:
            return False
        return (com_close[k][idx] > i["sma50"][idx]
                and i["sma5"][idx] > i["sma10"][idx] and i["macd_pos"][idx])

    COMMOD = HEDGE_ASSETS

    def asset_price(a, idx):
        return com_close[a][idx] if a in COMMOD else closes[a][idx]

    # snap the requested window onto trading days that actually exist in the data
    bt = [d for d in dates if START <= d <= END]
    if not bt:
        raise SystemExit("no trading days between START=%s and END=%s; the data covers %s .. %s"
                         % (START, END, dates[0], dates[-1]))
    WSTART, WEND = bt[0], bt[-1]
    base_idx = date_idx[WSTART]
    rebal = []
    last_ym = None
    for d in bt:
        ym = d[:7]
        if ym != last_ym:
            rebal.append(d); last_ym = ym

    cash = INIT_CASH
    positions = {}
    option = None
    trades = []
    monthly_rows = []
    cost_total = 0.0
    nav_series = []
    peak_stocks = 0
    peak_hedges = 0

    def buy(a, idx, alloc, reason):
        nonlocal cash, cost_total
        px = asset_price(a, idx)
        if px <= 0:
            return
        qty = math.floor(alloc / px)
        if qty <= 0:
            return
        amt = qty * px
        cst = amt * COST
        if amt + cst > cash:
            return
        cash -= amt + cst
        cost_total += cst
        if option is not None and a not in COMMOD:
            option["flow"] -= amt
        positions[a] = {"shares": qty, "entry_price": px, "entry_date": dates[idx]}
        trades.append((dates[idx], a, "buy", px, qty, amt, cst, reason, 0.0))

    def sell(a, idx, reason):
        nonlocal cash, cost_total
        p = positions.pop(a)
        px = asset_price(a, idx)
        amt = p["shares"] * px
        cst = amt * COST
        cash += amt - cst
        cost_total += cst
        if option is not None and a not in COMMOD:
            option["flow"] += amt
        pnl = (px - p["entry_price"]) * p["shares"]
        trades.append((dates[idx], a, "sell", px, p["shares"], amt, cst, reason, pnl))

    def held_stock_value(idx):
        return sum(p["shares"] * asset_price(a, idx) for a, p in positions.items() if a not in COMMOD)

    def nav_value(idx):
        return cash + sum(p["shares"] * asset_price(a, idx) for a, p in positions.items())

    for d in bt:
        idx = date_idx[d]
        ro = hsi_downtrend(idx)
        hedge_regime = hsi_hedge_regime(idx)

        if d in rebal:
            # settle previous put
            if option is not None:
                sleeve_now = held_stock_value(idx) + option["flow"]
                payoff = max(option["strike"] - sleeve_now, 0.0)
                if payoff > 0:
                    cash += payoff
                    trades.append((dates[idx], "OPT-PUT", "expire", payoff, 1, payoff, 0.0, "put_payoff", payoff))
                option = None

            s = idx - 1                      # signals from previous close
            nav = nav_value(idx)

            # ---- stocks: buy new qualified names, never sell held ones ----
            if s >= 0:
                cands = [tk for tk in tickers if tk not in positions and stock_entry_ok(tk, s)]
                cands.sort(key=lambda tk: -mom60[tk][s])
                held_stocks = [a for a in positions if a not in COMMOD]
                allowed = MAX_STOCKS - len(held_stocks)
                picks = cands[:max(0, allowed)]
                target_stock = nav * (STOCK_W_RO if ro else STOCK_W_ON)
                room = max(0.0, target_stock - held_stock_value(idx))
                if picks and room > 0:
                    per = room / len(picks)
                    for tk in picks:
                        buy(tk, idx, per, "new_buy")

            # ---- hedges: entered whenever HSI hedge regime is on (commodity filter DROPPED) ----
            if hedge_regime:
                held_hedges = [a for a in positions if a in COMMOD]
                if s >= 0:
                    eligible = [k for k in COMMOD if k not in held_hedges]
                    eligible.sort(key=lambda k: -mom60[k][s] if mom60[k][s] is not None else -1e18)
                    can_add = MAX_HEDGE - len(held_hedges)
                    picks_h = eligible[:max(0, can_add)]
                    if picks_h:
                        per = (nav * HEDGE_W_RO) / len(picks_h)
                        for k in picks_h:
                            buy(k, idx, per, "hedge_entry")
                sleeve = held_stock_value(idx)
                if sleeve > 0:
                    premium = sleeve * PUT_PREMIUM
                    cash -= premium
                    cost_total += premium
                    option = {"strike": sleeve * PUT_STRIKE, "flow": 0.0}
                    trades.append((dates[idx], "OPT-PUT", "buy", premium, 1, premium, premium, "put_premium_riskoff", -premium))
            else:
                for a in list(positions):
                    if a in COMMOD:
                        sell(a, idx, "hedge_regime_exit")

            # cash floor (30% risk-off / 16% risk-on) by trimming
            nav = nav_value(idx)
            floor = CASH_W_RO if ro else CASH_W_ON
            if nav > 0 and cash / nav < floor - 1e-9:
                need = nav * floor - cash
                for a in sorted(positions, key=lambda k: positions[k]["shares"] * asset_price(k, idx), reverse=True):
                    if need <= 1e-6:
                        break
                    p = positions[a]; px = asset_price(a, idx)
                    sq = min(p["shares"], max(1, math.ceil(need / px)))
                    amt = sq * px; cst = amt * COST
                    cash += amt - cst
                    cost_total += cst
                    if option is not None and a not in COMMOD:
                        option["flow"] += amt
                    p["shares"] -= sq
                    pnl = (px - p["entry_price"]) * sq
                    trades.append((dates[idx], a, "sell", px, sq, amt, cst, "cash_floor_trim", pnl))
                    need -= amt
                    if p["shares"] <= 0:
                        positions.pop(a)

            monthly_rows.append({
                "date": d,
                "hedge_regime": hedge_regime,
                "target_stock": STOCK_W_RO if ro else STOCK_W_ON,
                "target_hedge": HEDGE_W_RO if ro else 0.0,
                "target_cash": CASH_W_RO if ro else CASH_W_ON,
                "stocks": ",".join(sorted(a for a in positions if a not in COMMOD)),
                "hedges": ",".join(a for a in COMMOD if a in positions),
                "option": "PUT on stock sleeve" if option else "",
                "nav": nav_value(idx),
            })
        else:
            # ---- daily exits (no monthly rebalancing of held stocks) ----
            for a in list(positions):
                if a in COMMOD:
                    continue
                px = closes[a][idx]
                stop_px = positions[a]["entry_price"] * (1.0 - STOP_LOSS)
                if px <= stop_px:
                    sell(a, idx, "stop_loss_exit")
                elif stock_downtrend(a, idx):
                    sell(a, idx, "downtrend_exit")
                elif px >= positions[a]["entry_price"] * (1.0 + TARGET):
                    sell(a, idx, "target_exit")
            if not hedge_regime:
                for a in list(positions):
                    if a in COMMOD:
                        sell(a, idx, "hedge_regime_exit")

            nav = nav_value(idx)
            if nav > 0 and cash / nav < 0.10 - 1e-9:
                need = nav * 0.10 - cash
                for a in sorted(positions, key=lambda k: positions[k]["shares"] * asset_price(k, idx), reverse=True):
                    if need <= 1e-6:
                        break
                    p = positions[a]; px = asset_price(a, idx)
                    sq = min(p["shares"], max(1, math.ceil(need / px)))
                    amt = sq * px; cst = amt * COST
                    cash += amt - cst
                    cost_total += cst
                    if option is not None and a not in COMMOD:
                        option["flow"] += amt
                    p["shares"] -= sq
                    pnl = (px - p["entry_price"]) * sq
                    trades.append((dates[idx], a, "sell", px, sq, amt, cst, "cash_floor_trim", pnl))
                    need -= amt
                    if p["shares"] <= 0:
                        positions.pop(a)

        nav = nav_value(idx)
        hsi_nav = hsi_close[idx] / hsi_close[base_idx] * INIT_CASH
        nav_series.append((d, nav, hsi_nav))
        peak_stocks = max(peak_stocks, sum(1 for a in positions if a not in COMMOD))
        peak_hedges = max(peak_hedges, sum(1 for a in positions if a in COMMOD))

    # close everything at end
    end_idx = date_idx[bt[-1]]
    for a in list(positions):
        sell(a, end_idx, "end_of_period")
    option = None

    # ---- metrics ----
    navs = [v for _, v, _ in nav_series]
    hsi_navs = [h for _, _, h in nav_series]
    rets = [navs[i] / navs[i-1] - 1.0 for i in range(1, len(navs))]
    hsi_rets = [hsi_navs[i] / hsi_navs[i-1] - 1.0 for i in range(1, len(hsi_navs))]
    pnl_sells = [t[8] for t in trades if t[2] == "sell" and t[8] != 0.0]
    buys = [t for t in trades if t[2] == "buy" and t[1] not in ("OPT-PUT",)]
    sells = [t for t in trades if t[2] == "sell"]
    stock_buys = [t for t in buys if t[1] not in COMMOD]
    com_buys = [t for t in buys if t[1] in COMMOD]
    option_trades = [t for t in trades if t[1] == "OPT-PUT"]
    stock_sells = [t for t in sells if t[1] not in COMMOD]
    com_sells = [t for t in sells if t[1] in COMMOD]
    trades_out = [{
        "trade_id": i + 1,
        "asset": t[1],
        "type": "option" if t[1] == "OPT-PUT" else ("commodity" if t[1] in COMMOD else "stock"),
        "action": t[2], "date": t[0], "price": t[3], "quantity": t[4],
        "amount": t[5], "cost": t[6], "reason": t[7], "pnl": t[8],
    } for i, t in enumerate(trades)]
    m = {
        "window": {"start": bt[0], "end": bt[-1], "days": len(bt), "rebalances": len(rebal)},
        "portfolio": {"final_value": navs[-1], "final_return_pct": (navs[-1] / navs[0] - 1) * 100,
                      "max_drawdown_pct": max_drawdown(navs) * 100, "sharpe": sharpe(rets), "tail_loss_pct": tail_loss(rets) * 100},
        "hsi": {"final_value": hsi_navs[-1], "final_return_pct": (hsi_navs[-1] / hsi_navs[0] - 1) * 100,
                "max_drawdown_pct": max_drawdown(hsi_navs) * 100, "sharpe": sharpe(hsi_rets), "tail_loss_pct": tail_loss(hsi_rets) * 100},
        "hedge": {"max_holdings_cap": MAX_HEDGE, "commodity_buys": len(com_buys), "commodity_sells": len(com_sells),
                  "peak_hedges": peak_hedges},
        "trades": {"count": len(trades), "stock_buys": len(stock_buys), "stock_sells": len(stock_sells),
                   "commodity_buys": len(com_buys), "commodity_sells": len(com_sells), "options": len(option_trades),
                   "realized_pnl_from_sells": sum(pnl_sells), "transaction_costs": cost_total},
        "rules": {"max_stocks": MAX_STOCKS, "max_hedge": MAX_HEDGE, "cost_per_side": COST,
                  "stop_loss": STOP_LOSS, "target": TARGET, "macd_down": MACD_DOWN,
                  "universe": "%d selected HK names" % len(UNIVERSE),
                  "hedge_assets": ", ".join(HEDGE_ASSETS) + (" only" if len(HEDGE_ASSETS) == 1 else ""),
                  "stock_downtrend": "close<SMA20 AND DIF<-0.1",
                  "hedge_regime": "HSI close<SMA50 only (no MACD), no commodity filter"},
    }
    OUTDIR = OUT_DIR or os.path.join(HERE, "portfolio_eval", "plan_reuse", WSTART[:4] + "_" + WEND[:4])
    save_outputs(bt, trades_out, monthly_rows, nav_series, m, OUTDIR)
    write_manifest(OUTDIR, bt, m, dates)

    print("=" * 72)
    print("PLAN REUSE (v3 rules) - RESULT | %s .. %s" % (WSTART, WEND))
    print("=" * 72)
    print(f"Window: {bt[0]} .. {bt[-1]} ({len(bt)} days, {len(rebal)} monthly rebalances)")
    print(f"Stock exit: -{STOP_LOSS*100:.0f}% stop | own downtrend (close<SMA20 AND DIF<{MACD_DOWN}) | +{TARGET*100:.0f}% target")
    print(f"Hedge regime: HSI close<SMA50 only (no MACD); no commodity filter; max {MAX_HEDGE} hedges")
    print(f"Limits: max {MAX_STOCKS} stocks, max {MAX_HEDGE} hedge holdings; "
          f"cost {COST*100:.2f}%/side (buy & sell)")
    print(f"Portfolio final NAV: {navs[-1]:,.2f}   final return: {(navs[-1]/navs[0]-1)*100:.2f}%")
    print(f"HSI        final NAV: {hsi_navs[-1]:,.2f}   final return: {(hsi_navs[-1]/hsi_navs[0]-1)*100:.2f}%")
    print(f"Max drawdown: portfolio {max_drawdown(navs)*100:.2f}%   HSI {max_drawdown(hsi_navs)*100:.2f}%")
    print(f"Sharpe: portfolio {sharpe(rets):.3f}   HSI {sharpe(hsi_rets):.3f}")
    print(f"Tail loss (5%): portfolio {tail_loss(rets)*100:.3f}%   HSI {tail_loss(hsi_rets)*100:.3f}%")
    print(f"Trades: {len(trades)} total "
          f"(stock buys={len(stock_buys)}, stock sells={len([t for t in sells if t[1] not in COMMOD])}, "
          f"commodity buys={len(com_buys)}, commodity sells={len([t for t in sells if t[1] in COMMOD])}, "
          f"options={len(option_trades)})")
    print(f"Realized P&L from sells: {sum(pnl_sells):,.2f}")
    print(f"Transaction costs paid: {cost_total:,.2f} "
          f"({cost_total/(navs[-1]-INIT_CASH+1e-12)*100:.2f}% of net P&L path)")
    print(f"Peak concurrent holdings: {peak_stocks} stocks, {peak_hedges} hedges")
    print(f"Outputs written to: {OUTDIR}")
    return OUTDIR

# ---------------------------------------------------------------- xlsx writer (stdlib)
def write_xlsx(path, sheets):
    """Minimal xlsx writer using only zipfile + XML. sheets: list of (name, [rows])."""
    import xml.sax.saxutils as su
    def col_letter(i):
        s = ""
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            s = chr(65 + r) + s
        return s
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sheet_xmls = []
    for name, rows in sheets:
        body = []
        for ri, row in enumerate(rows):
            cells = []
            for ci, v in enumerate(row):
                ref = f"{col_letter(ci)}{ri+1}"
                if v is None:
                    cells.append(f'<c r="{ref}"/>')
                elif isinstance(v, (int, float)):
                    cells.append(f'<c r="{ref}"><v>{v}</v></c>')
                else:
                    txt = su.escape(str(v))
                    cells.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{txt}</t></is></c>')
            body.append(f'<row r="{ri+1}">{"".join(cells)}</row>')
        sheet_xmls.append(f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                          f'<worksheet xmlns="{ns}"><sheetData>{"".join(body)}</sheetData></worksheet>')
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                     + "".join(f'<Override PartName="/xl/worksheets/sheet{i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                               for i in range(len(sheets))) +
                     '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>')
    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
          '<sheets>' + "".join(f'<sheet name="{su.escape(name)}" sheetId="{i+1}" r:id="rId{i+1}"/>'
                               for i, (name, _) in enumerate(sheets)) + '</sheets></workbook>')
    wb_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               + "".join(f'<Relationship Id="rId{i+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i+1}.xml"/>'
                         for i in range(len(sheets))) +
               '</Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        for i in range(len(sheets)):
            z.writestr(f"xl/worksheets/sheet{i+1}.xml", sheet_xmls[i])

def _esc(s):
    return str(s).replace("&", "&").replace("<", "<").replace(">", ">")

def chart_cmp(path, dates, nav_series):
    W, H, L, Rr, T, B = 900, 420, 70, 30, 40, 60
    n = len(dates)
    p0, h0 = nav_series[0][1], nav_series[0][2]
    pp = [(i, v / p0 * 100) for i, (_, v, _) in enumerate(nav_series)]
    hp = [(i, v / h0 * 100) for i, (_, _, v) in enumerate(nav_series)]
    allv = [y for _, y in pp] + [y for _, y in hp]
    ymax, ymin = max(allv), min(allv)
    pad = (ymax - ymin) * 0.08 or 1.0
    ymax += pad; ymin -= pad
    def X(i): return L + i * (W - L - Rr) / (n - 1)
    def Y(v): return T + (H - T - B) * (1 - (v - ymin) / (ymax - ymin))
    def pl(pts, col):
        return f'<polyline points="{" ".join(f"{X(i):.1f},{Y(y):.1f}" for i, y in pts)}" fill="none" stroke="{col}" stroke-width="2"/>'
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
             f'<rect width="{W}" height="{H}" fill="white"/>',
             f'<text x="{W/2}" y="24" text-anchor="middle" font-size="16" font-weight="bold">{CASE_LABEL} vs HSI (normalized to 100)</text>']
    for gi in range(6):
        gy = ymin + (ymax - ymin) * gi / 5
        parts.append(f'<line x1="{L}" y1="{Y(gy):.1f}" x2="{W-Rr}" y2="{Y(gy):.1f}" stroke="#e0e0e0"/>')
        parts.append(f'<text x="{L-8}" y="{Y(gy)+4:.1f}" text-anchor="end" font-size="11">{gy:.0f}</text>')
    parts.append(pl(pp, "#27ae60")); parts.append(pl(hp, "#2980b9"))
    step = max(1, n // 10)
    for i in range(0, n, step):
        parts.append(f'<text x="{X(i):.1f}" y="{H-40}" text-anchor="middle" font-size="10">{dates[i]}</text>')
    for lx, name, col in [(L+20, CASE_LABEL, "#27ae60"), (L+160, "HSI", "#2980b9")]:
        parts.append(f'<line x1="{lx}" y1="{H-20}" x2="{lx+22}" y2="{H-20}" stroke="{col}" stroke-width="3"/>')
        parts.append(f'<text x="{lx+28}" y="{H-15}" font-size="11">{name}</text>')
    parts.append("</svg>")
    open(path, "w").write("\n".join(parts))

def chart_tl(path, dates, trades):
    W, H, L, Rr, T, B = 1000, 320, 120, 30, 40, 40
    n = len(dates)
    assets = sorted(set(t["asset"] for t in trades if t["type"] != "option"))
    row_h = 22
    def X(d): return L + dates.index(d) * (W - L - Rr) / max(1, n - 1)
    def Y(a): return T + assets.index(a) * row_h + row_h / 2
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
             f'<rect width="{W}" height="{H}" fill="white"/>',
             f'<text x="{W/2}" y="24" text-anchor="middle" font-size="16" font-weight="bold">{CASE_LABEL} Trade Timeline (buy ▲ / sell ▼)</text>']
    for a in assets:
        parts.append(f'<text x="{L-8}" y="{Y(a)+4:.1f}" text-anchor="end" font-size="10">{_esc(a)}</text>')
    buys, sells = {}, {}
    for t in trades:
        if t["type"] == "option":
            continue
        (buys if t["action"] == "buy" else sells).setdefault(t["asset"], []).append(t["date"])
    step = max(1, n // 10)
    for i in range(0, n, step):
        x = L + i * (W - L - Rr) / max(1, n - 1)
        parts.append(f'<text x="{x:.1f}" y="{H-24}" text-anchor="middle" font-size="10">{dates[i]}</text>')
    for a in assets:
        y = Y(a)
        for d in sorted(set(buys.get(a, []) + sells.get(a, []))):
            x = X(d)
            parts.append(f'<line x1="{x:.1f}" y1="{y-10:.1f}" x2="{x:.1f}" y2="{y+10:.1f}" stroke="#bdc3c7" stroke-width="1"/>')
        for d in buys.get(a, []):
            x = X(d)
            parts.append(f'<polygon points="{x:.1f},{y-7:.1f} {x-5:.1f},{y+3:.1f} {x+5:.1f},{y+3:.1f}" fill="#27ae60"/>')
        for d in sells.get(a, []):
            x = X(d)
            parts.append(f'<polygon points="{x:.1f},{y+7:.1f} {x-5:.1f},{y-3:.1f} {x+5:.1f},{y-3:.1f}" fill="#c0392b"/>')
    parts.append(f'<text x="{L}" y="{H-8}" font-size="10" fill="#27ae60">▲ buy</text>')
    parts.append(f'<text x="{L+80}" y="{H-8}" font-size="10" fill="#c0392b">▼ sell</text>')
    parts.append("</svg>")
    open(path, "w").write("\n".join(parts))

def chart_pie2(path, trades):
    W, H, cx, cy, r = 620, 460, 210, 230, 150
    colors = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6", "#1abc9c",
              "#e67e22", "#34495e", "#16a085", "#c0392b", "#2980b9", "#27ae60",
              "#8e44ad", "#f1c40f", "#d35400", "#7f8c8d"]
    by_asset = {}
    for t in trades:
        if t["action"] == "buy" and t["type"] != "option":
            by_asset[t["asset"]] = by_asset.get(t["asset"], 0.0) + float(t["amount"])
    total = sum(by_asset.values()) or 1.0
    items = sorted(by_asset.items(), key=lambda kv: -kv[1])
    labels = [a for a, _ in items]; values = [v / total for _, v in items]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
             f'<rect width="{W}" height="{H}" fill="white"/>',
             f'<text x="{W/2}" y="24" text-anchor="middle" font-size="16" font-weight="bold">{CASE_LABEL} Allocation by Asset (buy-value share)</text>']
    ang = -90.0
    for i, frac in enumerate(values):
        sweep = frac * 360.0
        a1, a2 = ang, ang + sweep
        x1, y1 = cx + r * math.cos(math.radians(a1)), cy + r * math.sin(math.radians(a1))
        x2, y2 = cx + r * math.cos(math.radians(a2)), cy + r * math.sin(math.radians(a2))
        col = colors[i % len(colors)]
        parts.append(f'<path d="M {cx},{cy} L {x1:.1f},{y1:.1f} A {r},{r} 0 {1 if sweep > 180 else 0} 1 {x2:.1f},{y2:.1f} Z" fill="{col}" stroke="white"/>')
        if frac >= 0.02:
            mid = math.radians((a1 + a2) / 2)
            parts.append(f'<text x="{cx+r*0.62*math.cos(mid):.1f}" y="{cy+r*0.62*math.sin(mid):.1f}" text-anchor="middle" font-size="10" fill="white">{frac*100:.1f}%</text>')
        ang = a2
    ly = 40
    for i, (lab, frac) in enumerate(zip(labels, values)):
        col = colors[i % len(colors)]
        parts.append(f'<rect x="410" y="{ly-8}" width="14" height="14" fill="{col}"/>')
        parts.append(f'<text x="432" y="{ly}" font-size="11">{_esc(lab)}: {frac*100:.1f}%</text>')
        ly += 22
    parts.append("</svg>")
    open(path, "w").write("\n".join(parts))

def _columns(path):
    """Header row of a wide CSV (Date excluded), read without parsing the body."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [c for c in next(csv.reader(f)) if c != "Date"]

def write_manifest(outdir, bt, m, dates):
    """Auditable record of one run: what was read, hashed, configured and produced."""
    inputs = {}
    for name in ALL_FILES:
        p = resolve(name)
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        inputs[name] = {"path": p, "bytes": os.path.getsize(p), "sha256": h.hexdigest()}
    sh = hashlib.sha256()
    with open(os.path.abspath(__file__), "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            sh.update(chunk)
    outputs = sorted(os.path.relpath(os.path.join(r, f), outdir)
                     for r, _, fs in os.walk(outdir) for f in fs)
    man = {
        "case": CASE_LABEL,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "script": os.path.abspath(__file__),
        "script_sha256": sh.hexdigest(),
        "inputs": inputs,
        "config": {
            "start_requested": START, "end_requested": END,
            "window_start_used": bt[0], "window_end_used": bt[-1],
            "init_cash": INIT_CASH, "max_stocks": MAX_STOCKS, "max_hedge": MAX_HEDGE,
            "hedge_assets": list(HEDGE_ASSETS), "universe": list(UNIVERSE),
            "cost_per_side": COST, "target": TARGET, "stop_loss": STOP_LOSS,
            "macd_down": MACD_DOWN, "mom_win": MOM_WIN,
            "weights_risk_off": {"stock": STOCK_W_RO, "hedge": HEDGE_W_RO, "cash": CASH_W_RO},
            "weights_risk_on": {"stock": STOCK_W_ON, "cash": CASH_W_ON},
            "put": {"premium": PUT_PREMIUM, "strike": PUT_STRIKE},
        },
        "result": {
            "days": len(bt), "calendar_days_available": len(dates),
            "portfolio_final_value": m["portfolio"]["final_value"],
            "portfolio_final_return_pct": m["portfolio"]["final_return_pct"],
            "portfolio_max_drawdown_pct": m["portfolio"]["max_drawdown_pct"],
            "portfolio_sharpe": m["portfolio"]["sharpe"],
            "hsi_final_return_pct": m["hsi"]["final_return_pct"],
            "trades": m["trades"]["count"],
        },
        "outputs": outputs,
    }
    with open(os.path.join(outdir, "run_manifest.json"), "w") as f:
        json.dump(man, f, indent=2, default=str)

def save_outputs(dates, trades_out, monthly_rows, nav_series, m, outdir):
    os.makedirs(os.path.join(outdir, "tables"), exist_ok=True)
    os.makedirs(os.path.join(outdir, "charts"), exist_ok=True)
    w = f"{dates[0][:4]}_{dates[-1][:4]}"
    cols = ["trade_id", "asset", "type", "action", "date", "price", "quantity",
            "amount", "cost", "reason", "pnl"]
    with open(os.path.join(outdir, "tables", f"{w}_trades.csv"), "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=cols); wr.writeheader()
        for t in trades_out:
            wr.writerow({k: t[k] for k in cols})
    with open(os.path.join(outdir, "tables", f"{w}_monthly.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["Date", "HedgeRegime", "TargetStock", "TargetHedge", "TargetCash",
                     "StocksHeld", "HedgesHeld", "Option", "NAV"])
        for r in monthly_rows:
            wr.writerow([r["date"], r["hedge_regime"], r["target_stock"], r["target_hedge"],
                         r["target_cash"], r["stocks"], r["hedges"], r["option"], r["nav"]])
    with open(os.path.join(outdir, "tables", f"{w}_nav.csv"), "w", newline="") as f:
        wr = csv.writer(f); wr.writerow(["Date", "Portfolio", "HSI"])
        for d, pv, hv in nav_series:
            wr.writerow([d, pv, hv])
    with open(os.path.join(outdir, "tables", f"{w}_metrics.json"), "w") as f:
        json.dump(m, f, indent=2, default=str)
    metric_rows = [["Metric", "Value"]]
    def flatten(d, prefix=""):
        out = []
        for k, v in d.items():
            key = f"{prefix}{k}"
            if isinstance(v, dict):
                out += flatten(v, key + ".")
            else:
                out.append([key, v])
        return out
    metric_rows += flatten(m)
    write_xlsx(os.path.join(outdir, f"{w}_plan.xlsx"), [
        ("Trades", [cols] + [[t[k] for k in cols] for t in trades_out]),
        ("Monthly Allocation", [["Date", "HedgeRegime", "TargetStock", "TargetHedge", "TargetCash",
                                 "StocksHeld", "HedgesHeld", "Option", "NAV"]] +
         [[r["date"], r["hedge_regime"], r["target_stock"], r["target_hedge"], r["target_cash"],
           r["stocks"], r["hedges"], r["option"], r["nav"]] for r in monthly_rows]),
        ("Metrics", metric_rows),
    ])
    for name in (f"{w}_trades.csv", f"{w}_monthly.csv", f"{w}_nav.csv"):
        shutil.copy(os.path.join(outdir, "tables", name), os.path.join(outdir, name))
    chart_cmp(os.path.join(outdir, "charts", f"{w}_comparison.svg"), dates, nav_series)
    chart_tl(os.path.join(outdir, "charts", f"{w}_timeline.svg"), dates, trades_out)
    chart_pie2(os.path.join(outdir, "charts", f"{w}_allocation.svg"), trades_out)

def build_parser():
    ap = argparse.ArgumentParser(
        prog="plan_reuse.py",
        description="Reuse the v3 HK-portfolio rule set on an arbitrary case and window.",
        epilog="Example fresh case: ./plan_reuse.py --start 2023-07-03 --end 2025-06-30 "
               "--max-stocks 10 --max-hedge 2 --hedges Gold,Silver "
               "--label 'Fresh case A' --out portfolio_eval/fresh_case_a --zip")
    ap.add_argument("--start", default=START, help="first date of the backtest")
    ap.add_argument("--end", default=END, help="last date of the backtest")
    ap.add_argument("--out", default=None,
                    help="output folder (default: <script dir>/portfolio_eval/plan_reuse/<startyr>_<endyr>)")
    ap.add_argument("--label", default=None, help="case label used in chart titles + manifest")
    ap.add_argument("--max-stocks", type=int, default=MAX_STOCKS, help="max concurrent stock holdings")
    ap.add_argument("--max-hedge", type=int, default=MAX_HEDGE, help="max concurrent hedge holdings")
    ap.add_argument("--hedges", default=",".join(HEDGE_ASSETS),
                    help="comma-separated hedge sleeve assets drawn from Gold,Silver,Oil")
    ap.add_argument("--universe", default=None,
                    help="comma-separated HK tickers, e.g. 0001.HK,0700.HK (default: the reuse universe)")
    ap.add_argument("--cost", type=float, default=COST, help="per-side transaction cost, e.g. 0.0011")
    ap.add_argument("--target", type=float, default=TARGET, help="take-profit threshold, e.g. 0.60")
    ap.add_argument("--stop", type=float, default=STOP_LOSS, help="stop-loss threshold, e.g. 0.15")
    ap.add_argument("--init-cash", type=float, default=INIT_CASH, help="starting capital")
    ap.add_argument("--zip", action="store_true", help="also write <out>_outputs.zip beside the folder")
    return ap

def _run_all(argv=None):
    global START, END, OUT_DIR, CASE_LABEL, INIT_CASH, MAX_STOCKS, MAX_HEDGE
    global HEDGE_ASSETS, UNIVERSE, COST, TARGET, STOP_LOSS
    a = build_parser().parse_args(argv)

    START, END = a.start, a.end
    INIT_CASH, COST, TARGET, STOP_LOSS = a.init_cash, a.cost, a.target, a.stop
    MAX_STOCKS, MAX_HEDGE = a.max_stocks, a.max_hedge
    HEDGE_ASSETS = tuple(x.strip() for x in a.hedges.split(",") if x.strip())
    if a.universe:
        UNIVERSE = [x.strip() for x in a.universe.split(",") if x.strip()]
    CASE_LABEL = a.label or ("Plan Reuse %s-%s" % (START[:4], END[:4]))
    OUT_DIR = None
    if a.out:
        OUT_DIR = a.out if os.path.isabs(a.out) else os.path.join(os.getcwd(), a.out)

    # ---- fail fast, with actionable messages, before any heavy lifting ----
    if START > END:
        raise SystemExit("--start (%s) is after --end (%s)" % (START, END))
    if MAX_STOCKS < 0 or MAX_HEDGE < 0:
        raise SystemExit("--max-stocks and --max-hedge must be >= 0")
    com_cols, wide_cols = _columns(resolve(NEW_COM)), _columns(resolve(NEW_WIDE))
    bad = [h for h in HEDGE_ASSETS if h not in com_cols]
    if bad:
        raise SystemExit("unknown hedge asset(s) %s; available: %s" % (bad, com_cols))
    if not HEDGE_ASSETS:
        raise SystemExit("--hedges is empty; pick at least one of %s" % com_cols)
    missing = [t for t in UNIVERSE if t not in wide_cols]
    if missing:
        raise SystemExit("%d ticker(s) not in the price file: %s" % (len(missing), missing))
    if not UNIVERSE:
        raise SystemExit("--universe is empty")

    print("Case: %s" % CASE_LABEL)
    print("Inputs resolved automatically (no absolute paths in the script):")
    for name in ALL_FILES:
        print("  %-48s %s" % (name, resolve(name)))
    print("Config: window %s..%s | max_stocks %d | max_hedge %d | hedges %s | universe %d names | "
          "cost %.4f | stop %.2f | target %.2f"
          % (START, END, MAX_STOCKS, MAX_HEDGE, ",".join(HEDGE_ASSETS), len(UNIVERSE),
             COST, STOP_LOSS, TARGET))
    print("=" * 72)

    outdir = main()

    if a.zip:
        zpath = os.path.join(os.path.dirname(outdir), os.path.basename(outdir) + "_outputs.zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for root, _, files in os.walk(outdir):
                for f in files:
                    full = os.path.join(root, f)
                    z.write(full, os.path.relpath(full, outdir))
        print("Zip written to: %s" % zpath)

if __name__ == "__main__":
    _run_all()

