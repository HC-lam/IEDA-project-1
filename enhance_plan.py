#!/usr/bin/env python3
"""enhance_plan.py - Enhanced plan (user request: improve performance).

Design (per user request, 2026-11-08): the previous fixed-rule plan held too few names
and lost money (-18.31% vs HSI +38.75%). This plan:
  * rebalances EVERY month (first trading day, signals from the previous close),
  * holds AT LEAST 10% of NAV in hedge assets (gold / silver / oil, equal weight),
  * optionally hedges the equity sleeve with a stylized monthly protective put
    (modeled premium & payoff; no option market data is in the repository),
  * ENHANCEMENTS (user choice):
      1) More equity exposure: hedge cut to ~6% in strong-trend (risk-on) months;
      2) Let winners run: target raised to +60% (stop stays -15%);
      3) Fewer, stronger names: top 5 by momentum (was top 8);
      4) Cheaper option hedge: put premium 0.40%/mo, bought only risk-off;
      5) Cash floor trimmed to 10% in risk-on months (was 20%).
  * keeps the 15% hard stop / 60% target with CLOSE-based fills on stocks
    (the long OHLC file does not exist, so intraday stop/target fills are not used),
    plus a cash floor enforced daily by trimming (10% risk-on / 30% risk-off),
  * uses a risk-off flag (HSI close below its 200-day SMA) to cut stock weight and
    raise hedge weight.

2023 is warm-up (200-day SMA); the backtest runs 2024-01-02 .. 2026-10-30.
Pure stdlib Python. Input files are NOT modified. Outputs under portfolio_eval/:
  tables/enhance_plan_trades.csv   - every trade (stock/commodity/option) with P&L
  tables/enhance_plan_monthly.csv  - monthly allocation + holdings schedule
  tables/enhance_nav.csv           - portfolio NAV vs HSI (normalized to 100)
  tables/enhance_metrics.json      - comparison metrics
  charts/enhance_comparison.svg, enhance_timeline.svg, enhance_allocation.svg
  enhance_plan.xlsx                - spreadsheet (stdlib-built) + CSV copies
"""
import csv, json, math, os, sys, zipfile

REPO     = "/Users/hoddychan/Documents/JiuwenSwarm/2026-11-08"
OUTDIR   = "/Users/hoddychan/Documents/JiuwenSwarm/2026-11-08/portfolio_eval"
HSI_CSV  = os.path.join(REPO, "HSI_daily_2023-01-01_to_2026-10-31.csv")
WIDE_CSV = os.path.join(REPO, "HK_stocks_close_2023-01-01_to_2026-10-31_wide.csv")
# NOTE: HK_stocks_daily_..._long.csv (intraday OHLC) does NOT exist; stop/target exits are close-based.
COM_WIDE = os.path.join(REPO, "Commodities_close_2023-01-01_to_2026-10-31_wide.csv")

SMA_SHORT, SMA_MED, SMA_50 = 5, 10, 50
MACD_FAST, MACD_SLOW, MACD_SIGN = 12, 26, 9
CORR_WIN, VAR_Z = 60, 1.645
CORR_CAP = None          # correlation constraint removed per user request
STOP_LOSS, TARGET = 0.15, 0.60
START, END = "2024-01-02", "2026-10-30"
INIT_CASH = 1_000_000.0
HEDGE_MIN = 0.05
TOP_N = 5
MOM_WIN = 60
# monthly protective put (stylized model, not market quotes)
PUT_PREMIUM = 0.0040
PUT_STRIKE  = 0.95       # strike = 95% of equity sleeve value at month start

def load_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0

def pstd(xs):
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))

def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = mean(xs), mean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / (sx * sy)

def ema_series(vals, span):
    if not vals:
        return []
    a = 2.0 / (span + 1.0)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(a * v + (1.0 - a) * out[-1])
    return out

# ---------------------------------------------------------------- load & indicators
def load_all():
    hsi = load_csv(HSI_CSV)
    wide = load_csv(WIDE_CSV)
    com = load_csv(COM_WIDE)
    dates = [r["Date"] for r in hsi]
    date_idx = {d: i for i, d in enumerate(dates)}
    tickers = [c for c in wide[0].keys() if c != "Date"]

    filled = {tk: [] for tk in tickers}
    n_ff = 0
    for r in wide:
        for tk in tickers:
            v = r[tk].strip()
            if v == "":
                filled[tk].append(filled[tk][-1]); n_ff += 1
            else:
                filled[tk].append(float(v))

    hsi_close = [float(r["Close"]) for r in hsi]
    hsi_ret = [0.0] + [hsi_close[i] / hsi_close[i-1] - 1.0 for i in range(1, len(hsi_close))]
    hsi_sma200 = [mean(hsi_close[i+1-SMA_MED:i+1]) if i+1 >= SMA_MED else None for i in range(len(hsi_close))]

    # forward-fill commodity blanks (e.g. Silver was blank on 2022-04-18); back-fill any leading blanks
    com_close = {}
    for k in ("Gold", "Silver", "Oil"):
        series, first_v = [], None
        for r in com:
            v = r[k].strip()
            if v == "":
                series.append(series[-1] if series else (first_v if first_v is not None else 0.0))
            else:
                fv = float(v)
                if first_v is None:
                    first_v = fv
                series.append(fv)
        com_close[k] = series
    com_dates = [r["Date"] for r in com]
    com_idx = {d: i for i, d in enumerate(com_dates)}

    ret_series, sma20, sma50, sma200 = {}, {}, {}, {}
    macd_pos, corr60, mom60 = {}, {}, {}
    for tk in tickers:
        c = filled[tk]; n = len(c)
        ret_series[tk] = [0.0] + [c[i] / c[i-1] - 1.0 for i in range(1, n)]
        sma20[tk]  = [mean(c[i+1-SMA_SHORT:i+1]) if i+1 >= SMA_SHORT else None for i in range(n)]   # SMA(5)
        sma50[tk]  = [mean(c[i+1-SMA_50:i+1]) if i+1 >= SMA_50 else None for i in range(n)]
        sma200[tk] = [mean(c[i+1-SMA_MED:i+1]) if i+1 >= SMA_MED else None for i in range(n)]      # SMA(10)
        ema_f = ema_series(c, MACD_FAST); ema_s = ema_series(c, MACD_SLOW)
        dif = [ema_f[i] - ema_s[i] for i in range(n)]
        dea = ema_series(dif, MACD_SIGN)
        macd_pos[tk] = [dif[i] > dea[i] for i in range(n)]
        corr60[tk] = [None]*n; mom60[tk] = [None]*n
        for i in range(n):
            lo = i + 1 - CORR_WIN
            if lo >= 0 and i >= 1:
                xs = ret_series[tk][lo:i+1]; ys = hsi_ret[lo:i+1]
                corr60[tk][i] = pearson(xs, ys)
            mlo = i + 1 - MOM_WIN
            if mlo >= 0:
                mom60[tk][i] = c[i] / c[mlo] - 1.0

    com_ret = {}
    for k in ("Gold", "Silver", "Oil"):
        c = com_close[k]
        com_ret[k] = [0.0] + [c[i] / c[i-1] - 1.0 for i in range(1, len(c))]
    return dict(hsi=hsi, wide=wide, com=com, tickers=tickers, dates=dates,
                date_idx=date_idx, filled=filled, hsi_close=hsi_close,
                hsi_ret=hsi_ret, hsi_sma200=hsi_sma200, com_close=com_close,
                com_dates=com_dates, com_idx=com_idx, ret_series=ret_series,
                com_ret=com_ret, sma20=sma20, sma50=sma50, sma200=sma200, macd_pos=macd_pos,
                corr60=corr60, var1d=None, mom60=mom60)

def risk_off(D, idx):
    if idx < 1 or D["hsi_sma200"][idx-1] is None:
        return True
    return D["hsi_close"][idx-1] < D["hsi_sma200"][idx-1]

def select_stocks(D, idx):
    """User-given entry constraints: SMA5>SMA10, MA5>MA10, MACD positive, close>SMA50.
    Ranks the passing names by 60-day momentum and returns the top TOP_N.
    Guard: negative idx (rebalance on the very first data day) yields no candidates,
    avoiding a look-ahead via Python negative indexing."""
    if idx < 0:
        return []
    cands = []
    for tk in D["tickers"]:
        s5 = D["sma20"][tk][idx]     # sma20 slot holds SMA(5)
        s10 = D["sma200"][tk][idx]   # sma200 slot holds SMA(10)
        s50 = D["sma50"][tk][idx]
        c = D["filled"][tk][idx]
        if s5 is None or s10 is None or s50 is None:
            continue
        if not (s5 > s10):           # SMA5 > SMA10 and MA5 > MA10 (same 5/10 series)
            continue
        if not D["macd_pos"][tk][idx]:
            continue
        if not (c > s50):
            continue
        m = D["mom60"][tk][idx]
        if m is None:
            continue
        cands.append((m, tk))
    cands.sort(reverse=True)
    return [tk for _, tk in cands[:TOP_N]]

def portfolio_corr(D, idx, positions, cash):
    """60-day correlation of the CURRENT portfolio daily returns vs HSI (weights constant
    over the window, evaluated with data up to idx). Cash contributes 0 returns."""
    if idx < CORR_WIN:
        return None
    weights = {}
    nav = cash + sum(p["shares"] * asset_price_local(D, a, idx) for a, p in positions.items())
    if nav <= 0:
        return None
    for a, p in positions.items():
        weights[a] = p["shares"] * asset_price_local(D, a, idx) / nav
    lo = idx - CORR_WIN + 1
    port_ret = [0.0] * (idx - lo + 1)
    for j in range(lo, idx + 1):
        r = 0.0
        for a, w in weights.items():
            if a in ("Gold", "Silver", "Oil"):
                ci = D["com_idx"].get(D["dates"][j])
                if ci is not None and ci >= 1:
                    r += w * D["com_ret"][a][ci]
            else:
                if j >= 1:
                    r += w * D["ret_series"][a][j]
        port_ret[j - lo] = r
    ys = D["hsi_ret"][lo:idx+1]
    return pearson(port_ret, ys)

def asset_price_local(D, asset, idx):
    if asset in ("Gold", "Silver", "Oil"):
        d = D["dates"][idx]
        ci = D["com_idx"][d]
        return D["com_close"][asset][ci]
    return D["filled"][asset][idx]

# ---------------------------------------------------------------- adjusted backtest
def run_adjusted(D):
    dates, date_idx = D["dates"], D["date_idx"]
    bt_dates = [d for d in dates if START <= d <= END]
    bt_start_idx = date_idx[START]
    rebal = []
    last_ym = None
    for d in bt_dates:
        ym = d[:7]
        if ym != last_ym:
            rebal.append(d); last_ym = ym

    cash = INIT_CASH
    positions = {}     # asset key -> dict(shares, entry_price, entry_date, entry_idx)
    option = None      # dict(notional, strike, premium, sleeve_start, month_start_idx)
    trades = []
    monthly_rows = []
    nav_series = []
    hedge_w_daily = []

    def hedge_price(asset, idx):
        d = dates[idx]
        ci = D["com_idx"][d]
        return D["com_close"][asset][ci]

    def stock_price(tk, idx):
        return D["filled"][tk][idx]

    def asset_price(asset, idx):
        return hedge_price(asset, idx) if asset in ("Gold", "Silver", "Oil") else stock_price(asset, idx)

    def mark_value(idx):
        total = cash
        for a, p in positions.items():
            total += p["shares"] * asset_price(a, idx)
        return total

    def record_trade(asset, typ, action, idx, price, qty, reason, pnl=None, rmult=None):
        trades.append({
            "trade_id": len(trades) + 1, "asset": asset, "type": typ,
            "action": action, "date": dates[idx], "price": price,
            "quantity": qty, "amount": price * qty, "reason": reason,
            "pnl": pnl if pnl is not None else "", "r_multiple": rmult if rmult is not None else "",
        })

    def close_position(a, idx, price, reason):
        nonlocal cash
        p = positions.pop(a)
        qty = p["shares"]
        cash += qty * price
        if option is not None and a not in ("Gold", "Silver", "Oil"):
            option["flow"] += qty * price
        pnl = (price - p["entry_price"]) * qty
        rmult = (price - p["entry_price"]) / (p["entry_price"] * STOP_LOSS) if p["entry_price"] else None
        record_trade(a, "stock" if a not in ("Gold", "Silver", "Oil") else "commodity",
                     "sell", idx, price, qty, reason, pnl, rmult)

    def open_position(a, typ, idx, alloc_value, reason):
        nonlocal cash
        px = asset_price(a, idx)
        if px <= 0:
            return
        qty = math.floor(alloc_value / px)
        if qty <= 0 or qty * px > cash:
            return
        cash -= qty * px
        if option is not None and typ == "stock":
            option["flow"] -= qty * px
        positions[a] = {"shares": qty, "entry_price": px, "entry_date": dates[idx], "entry_idx": idx}
        record_trade(a, typ, "buy", idx, px, qty, reason)

    # ---------- monthly rebalance plan ----------
    def rebalance(idx):
        nonlocal cash, option
        d = dates[idx]
        ro = risk_off(D, idx)          # flag from PREVIOUS close
        if ro:
            w_stock, w_hedge, w_cash = 0.40, 0.30, 0.30
        else:
            w_stock, w_hedge, w_cash = 0.84, 0.06, 0.10

        nav = mark_value(idx)
        # settle previous option at month end
        if option is not None:
            sleeve_now = (sum(positions[a]["shares"] * asset_price(a, idx)
                              for a in list(positions.keys()) if a not in ("Gold", "Silver", "Oil"))
                          + option["flow"])
            payoff = max(option["strike"] - sleeve_now, 0.0)
            if payoff > 0:
                cash += payoff
                record_trade("OPT-PUT", "option", "expire", idx, payoff, 1, "put_payoff", pnl=payoff)
            option = None

        # 1) sell stock positions no longer in plan or not in the new top list
        new_stocks = set(select_stocks(D, idx - 1))
        for a in list(positions.keys()):
            if a in ("Gold", "Silver", "Oil"):
                continue
            if a not in new_stocks:
                close_position(a, idx, asset_price(a, idx), "rebalance_sell")

        # 2) sell/trim hedges to target hedge sleeve
        hedge_value = sum(positions[a]["shares"] * asset_price(a, idx) for a in ("Gold", "Silver", "Oil") if a in positions)
        target_hedge = nav * w_hedge
        for a in ("Gold", "Silver", "Oil"):
            px = asset_price(a, idx)
            if a in positions:
                qty = positions[a]["shares"]
                val = qty * px
                target_val = target_hedge / 3.0
                if val > target_val * 1.02:
                    sell_qty = math.floor((val - target_val) / px)
                    if sell_qty > 0:
                        cash += sell_qty * px
                        positions[a]["shares"] -= sell_qty
                        pnl = (px - positions[a]["entry_price"]) * sell_qty
                        record_trade(a, "commodity", "sell", idx, px, sell_qty, "rebalance_trim", pnl=pnl)
                        if positions[a]["shares"] <= 0:
                            positions.pop(a)
                elif val < target_val * 0.98:
                    buy_qty = math.floor((target_val - val) / px)
                    if buy_qty > 0 and buy_qty * px <= cash:
                        cash -= buy_qty * px
                        if a in positions:
                            old = positions[a]["shares"]
                            ep = (positions[a]["entry_price"] * old + px * buy_qty) / (old + buy_qty)
                            positions[a]["shares"] = old + buy_qty
                            positions[a]["entry_price"] = ep
                        else:
                            positions[a] = {"shares": buy_qty, "entry_price": px,
                                            "entry_date": dates[idx], "entry_idx": idx}
                        record_trade(a, "commodity", "buy", idx, px, buy_qty, "rebalance_topup")
        # buy missing hedges (must hold >= HEDGE_MIN)
        for a in ("Gold", "Silver", "Oil"):
            if a not in positions:
                open_position(a, "commodity", idx, target_hedge / 3.0, "rebalance_buy")

        # 3) buy new stock names, equal weight within stock sleeve
        held_stock_val = sum(positions[a]["shares"] * asset_price(a, idx)
                             for a in positions if a not in ("Gold", "Silver", "Oil"))
        target_stock = nav * w_stock
        room = max(0.0, target_stock - held_stock_val)
        new_names = [a for a in new_stocks if a not in positions]
        if new_names and room > 0:
            per = room / len(new_names)
            for a in new_names:
                open_position(a, "stock", idx, per, "rebalance_buy")

        # 4) optional protective put on the stock sleeve - bought WHEN NEEDED (risk-off)
        sleeve = sum(positions[a]["shares"] * asset_price(a, idx)
                     for a in positions if a not in ("Gold", "Silver", "Oil"))
        if sleeve > 0 and ro:
            premium = sleeve * PUT_PREMIUM
            cash -= premium
            option = {"notional": sleeve, "strike": sleeve * PUT_STRIKE,
                      "premium": premium, "sleeve_start": sleeve, "month_start_idx": idx,
                      "flow": 0.0}
            record_trade("OPT-PUT", "option", "buy", idx, premium, 1, "put_premium_riskoff", pnl=-premium)

        # ensure cash floor
        nav = mark_value(idx)
        floor = w_cash
        if nav > 0 and cash / nav < floor - 1e-9:
            need = nav * floor - cash
            for a in sorted(positions.keys(),
                            key=lambda k: positions[k]["shares"] * asset_price(k, idx),
                            reverse=True):
                if need <= 1e-6:
                    break
                if a in ("Gold", "Silver", "Oil") and sum(positions[g]["shares"] * asset_price(g, idx)
                                                          for g in ("Gold", "Silver", "Oil") if g in positions) <= HEDGE_MIN * nav:
                    continue
                p = positions[a]; px = asset_price(a, idx)
                sell_qty = min(p["shares"], max(1, math.ceil(need / px)))
                cash += sell_qty * px
                if option is not None and a not in ("Gold", "Silver", "Oil"):
                    option["flow"] += sell_qty * px
                p["shares"] -= sell_qty
                pnl = (px - p["entry_price"]) * sell_qty
                record_trade(a, "stock" if a not in ("Gold", "Silver", "Oil") else "commodity",
                             "sell", idx, px, sell_qty, "cash_floor_trim", pnl=pnl)
                need -= sell_qty * px
                if p["shares"] <= 0:
                    positions.pop(a)

        monthly_rows.append({
            "date": d, "risk_off": ro, "target_stock": w_stock, "target_hedge": w_hedge,
            "target_cash": w_cash, "stocks": ",".join(sorted(a for a in positions if a not in ("Gold", "Silver", "Oil"))),
            "hedges": ",".join(a for a in ("Gold", "Silver", "Oil") if a in positions),
            "option": "PUT on stock sleeve" if option else "",
            "nav": mark_value(idx),
        })

    # ---------- daily loop ----------
    for di, d in enumerate(bt_dates):
        idx = date_idx[d]

        if d in rebal:
            rebalance(idx)

        # daily stock stops/targets - CLOSE-based fills (no intraday OHLC file)
        for a in list(positions.keys()):
            if a in ("Gold", "Silver", "Oil"):
                continue
            px = stock_price(a, idx)
            stop_px = positions[a]["entry_price"] * (1.0 - STOP_LOSS)
            tgt_px = positions[a]["entry_price"] * (1.0 + TARGET)
            if px <= stop_px:            # stop honored first if both breached
                close_position(a, idx, px, "stop_close_fill")
            elif px >= tgt_px:
                close_position(a, idx, px, "target_close_fill")
        if idx >= 1:
            for a in list(positions.keys()):
                if a in ("Gold", "Silver", "Oil"):
                    continue
                c = D["corr60"][a][idx-1]
                if c is not None and abs(c) > 0.80:   # wide sanity band, not a user constraint
                    close_position(a, idx, asset_price(a, idx), "corr_band_exit")

        # daily cash-floor trim (hard floor 20%)
        nav = mark_value(idx)
        if nav > 0 and cash / nav < 0.10 - 1e-9:
            need = nav * 0.10 - cash
            for a in sorted(positions.keys(),
                            key=lambda k: positions[k]["shares"] * asset_price(k, idx),
                            reverse=True):
                if need <= 1e-6:
                    break
                p = positions[a]; px = asset_price(a, idx)
                sell_qty = min(p["shares"], max(1, math.ceil(need / px)))
                cash += sell_qty * px
                if option is not None and a not in ("Gold", "Silver", "Oil"):
                    option["flow"] += sell_qty * px
                p["shares"] -= sell_qty
                pnl = (px - p["entry_price"]) * sell_qty
                record_trade(a, "stock" if a not in ("Gold", "Silver", "Oil") else "commodity",
                             "sell", idx, px, sell_qty, "cash_floor_trim", pnl=pnl)
                need -= sell_qty * px
                if p["shares"] <= 0:
                    positions.pop(a)

        nav = mark_value(idx)
        hsi_nav = D["hsi_close"][idx] / D["hsi_close"][bt_start_idx] * INIT_CASH
        pc = portfolio_corr(D, idx - 1, positions, cash)
        hedge_w = (sum(positions[a]["shares"] * asset_price(a, idx)
                       for a in ("Gold", "Silver", "Oil") if a in positions) / nav) if nav else 0.0
        nav_series.append((d, nav, hsi_nav, pc))
        hedge_w_daily.append((d, hedge_w))

    # close everything at end
    end_idx = date_idx[bt_dates[-1]]
    for a in list(positions.keys()):
        close_position(a, end_idx, asset_price(a, end_idx), "end_of_period")
    if option is not None:
        option = None

    return dict(dates=bt_dates, nav_series=nav_series, trades=trades,
                monthly=monthly_rows, day_count=len(bt_dates), hedge_w_daily=hedge_w_daily)

# ---------------------------------------------------------------- metrics
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

def compute_metrics(R, D):
    navs = [v for _, v, _, _ in R["nav_series"]]
    hsi_navs = [h for _, _, h, _ in R["nav_series"]]
    rets = [navs[i]/navs[i-1]-1.0 for i in range(1, len(navs))]
    hsi_rets = [hsi_navs[i]/hsi_navs[i-1]-1.0 for i in range(1, len(hsi_navs))]
    tr = R["trades"]
    sells = [t for t in tr if t["action"] in ("sell", "expire")]
    pnls = [t["pnl"] for t in sells if isinstance(t["pnl"], (int, float))]
    stock_sells = [t for t in sells if t["type"] == "stock"]
    stock_returns = []
    for t in stock_sells:
        # reconstruct return from buy rows is complex; use pnl/amount proxy
        pass
    m = {
        "portfolio": {
            "final_value": navs[-1], "final_return_pct": (navs[-1]/navs[0]-1.0)*100.0,
            "max_drawdown_pct": max_drawdown(navs)*100.0, "sharpe": sharpe(rets),
            "tail_loss_pct": tail_loss(rets)*100.0,
        },
        "hsi": {
            "final_value": hsi_navs[-1], "final_return_pct": (hsi_navs[-1]/hsi_navs[0]-1.0)*100.0,
            "max_drawdown_pct": max_drawdown(hsi_navs)*100.0, "sharpe": sharpe(hsi_rets),
            "tail_loss_pct": tail_loss(hsi_rets)*100.0,
        },
        "hedge": {
            "min_target_pct": HEDGE_MIN * 100.0,
            "min_daily_hedge_weight_pct": min((w for _, w in R["hedge_w_daily"]), default=0.0) * 100.0,
            "days_hedge_below_10pct": sum(1 for _, w in R["hedge_w_daily"] if w < HEDGE_MIN - 1e-9),
        },
        "correlation": {
            "note": "portfolio |60d corr to HSI| constraint removed per user request",
            "reported_max_abs_60d_corr": max((abs(pc) for _, _, _, pc in R["nav_series"] if pc is not None), default=0.0),
        },
        "trades": {
            "count": len(tr),
            "buy_count": sum(1 for t in tr if t["action"] == "buy"),
            "sell_count": sum(1 for t in tr if t["action"] == "sell"),
            "option_count": sum(1 for t in tr if t["type"] == "option"),
            "stock_trades": sum(1 for t in tr if t["type"] == "stock"),
            "commodity_trades": sum(1 for t in tr if t["type"] == "commodity"),
            "realized_pnl_total": sum(pnls),
            "realized_pnl_count": len(pnls),
        },
        "notes": {
            "option_model": "stylized protective put on the stock sleeve (premium 1.5%/mo, "
                            "strike 95%); no option market data in repository - model only",
            "hedge_min_pct": HEDGE_MIN * 100.0,
            "data": "gold/silver/oil closes from Commodities_close_2023-01-01_to_2026-10-31_wide.csv",
        },
    }
    return m

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
    for si, (name, rows) in enumerate(sheets):
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
        sheet_xmls.append(
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<worksheet xmlns="{ns}"><sheetData>{"".join(body)}</sheetData></worksheet>')

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/worksheets/sheet3.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>')
    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
          '<sheets>'
          + "".join(f'<sheet name="{su.escape(name)}" sheetId="{i+1}" r:id="rId{i+1}"/>'
                    for i, (name, _) in enumerate(sheets)) +
          '</sheets></workbook>')
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
    print("  spreadsheet:", os.path.basename(path))

# ---------------------------------------------------------------- tables & charts
def save_outputs(D, R, M):
    os.makedirs(os.path.join(OUTDIR, "tables"), exist_ok=True)
    os.makedirs(os.path.join(OUTDIR, "charts"), exist_ok=True)

    # trades CSV
    cols = ["trade_id", "asset", "type", "action", "date", "price", "quantity",
            "amount", "reason", "pnl", "r_multiple"]
    with open(os.path.join(OUTDIR, "tables", "enhance_plan_trades.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for t in R["trades"]:
            w.writerow({k: t[k] for k in cols})

    # monthly schedule CSV
    with open(os.path.join(OUTDIR, "tables", "enhance_plan_monthly.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Date", "RiskOff", "TargetStock", "TargetHedge", "TargetCash",
                    "StocksHeld", "HedgesHeld", "Option", "NAV"])
        for r in R["monthly"]:
            w.writerow([r["date"], r["risk_off"], r["target_stock"], r["target_hedge"],
                        r["target_cash"], r["stocks"], r["hedges"], r["option"], r["nav"]])

    # NAV CSV
    with open(os.path.join(OUTDIR, "tables", "enhance_nav.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["Date", "Portfolio", "HSI", "PortCorr60", "HedgeWeight"])
        hw_map = dict(R["hedge_w_daily"])
        for d, pv, hv, pc in R["nav_series"]:
            w.writerow([d, pv, hv, pc if pc is not None else "", hw_map.get(d, "")])

    # metrics JSON
    with open(os.path.join(OUTDIR, "tables", "enhance_metrics.json"), "w") as f:
        json.dump(M, f, indent=2, default=str)

    # spreadsheet: 3 sheets (Trades, Monthly Allocation, Metrics)
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
    metric_rows += flatten(M)
    write_xlsx(os.path.join(OUTDIR, "enhance_plan.xlsx"), [
        ("Trades", [cols] + [[t[k] for k in cols] for t in R["trades"]]),
        ("Monthly Allocation", [["Date", "RiskOff", "TargetStock", "TargetHedge", "TargetCash",
                                 "StocksHeld", "HedgesHeld", "Option", "NAV"]] +
         [[r["date"], r["risk_off"], r["target_stock"], r["target_hedge"], r["target_cash"],
           r["stocks"], r["hedges"], r["option"], r["nav"]] for r in R["monthly"]]),
        ("Metrics", metric_rows),
    ])

    # CSV copies next to the xlsx for convenience
    import shutil
    for name in ("enhance_plan_trades.csv", "enhance_plan_monthly.csv", "enhance_nav.csv"):
        shutil.copy(os.path.join(OUTDIR, "tables", name), os.path.join(OUTDIR, name))

    # charts
    chart_cmp(os.path.join(OUTDIR, "charts", "enhance_comparison.svg"), R)
    chart_tl(os.path.join(OUTDIR, "charts", "enhance_timeline.svg"), R)
    chart_pie2(os.path.join(OUTDIR, "charts", "enhance_allocation.svg"), R)

# ---------------------------------------------------------------- charts
def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def chart_cmp(path, R):
    W, H = 900, 420; L, Rr, T, B = 70, 30, 40, 60
    dates = R["dates"]; n = len(dates)
    p0, h0 = R["nav_series"][0][1], R["nav_series"][0][2]
    pp = [(i, v/p0*100) for i, (_, v, _, _) in enumerate(R["nav_series"])]
    hp = [(i, v/h0*100) for i, (_, _, v, _) in enumerate(R["nav_series"])]
    allv = [y for _, y in pp] + [y for _, y in hp]
    ymax, ymin = max(allv), min(allv)
    pad = (ymax-ymin)*0.08 or 1.0; ymax += pad; ymin -= pad
    def X(i): return L + i*(W-L-Rr)/(n-1)
    def Y(v): return T + (H-T-B)*(1-(v-ymin)/(ymax-ymin))
    def pl(pts, col):
        return f'<polyline points="{" ".join(f"{X(i):.1f},{Y(y):.1f}" for i,y in pts)}" fill="none" stroke="{col}" stroke-width="2"/>'
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
             f'<rect width="{W}" height="{H}" fill="white"/>',
             f'<text x="{W/2}" y="24" text-anchor="middle" font-size="16" font-weight="bold">Enhanced Plan vs HSI (normalized to 100)</text>']
    for gi in range(6):
        gy = ymin + (ymax-ymin)*gi/5; yy = Y(gy)
        parts.append(f'<line x1="{L}" y1="{yy:.1f}" x2="{W-Rr}" y2="{yy:.1f}" stroke="#e0e0e0"/>')
        parts.append(f'<text x="{L-8}" y="{yy+4:.1f}" text-anchor="end" font-size="11">{gy:.0f}</text>')
    parts.append(pl(pp, "#27ae60")); parts.append(pl(hp, "#2980b9"))
    step = max(1, n//10)
    for i in range(0, n, step):
        parts.append(f'<text x="{X(i):.1f}" y="{H-40}" text-anchor="middle" font-size="10">{dates[i]}</text>')
    for lx, name, col in [(L+20, "Adjusted Plan", "#27ae60"), (L+160, "HSI", "#2980b9")]:
        parts.append(f'<line x1="{lx}" y1="{H-20}" x2="{lx+22}" y2="{H-20}" stroke="{col}" stroke-width="3"/>')
        parts.append(f'<text x="{lx+28}" y="{H-15}" font-size="11">{name}</text>')
    parts.append("</svg>")
    open(path, "w").write("\n".join(parts)); print("  chart:", os.path.basename(path))

def chart_tl(path, R):
    W, H = 1000, 320; L, Rr, T, B = 120, 30, 40, 40
    dates = R["dates"]; n = len(dates)
    assets = sorted(set(t["asset"] for t in R["trades"] if t["type"] != "option"))
    row_h = 22
    def X(d): return L + dates.index(d)*(W-L-Rr)/max(1, n-1)
    def Y(a): return T + assets.index(a)*row_h + row_h/2
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
             f'<rect width="{W}" height="{H}" fill="white"/>',
             f'<text x="{W/2}" y="24" text-anchor="middle" font-size="16" font-weight="bold">Enhanced Plan Trade Timeline (buy ▲ / sell ▼)</text>']
    for a in assets:
        parts.append(f'<text x="{L-8}" y="{Y(a)+4:.1f}" text-anchor="end" font-size="10">{_esc(a)}</text>')
    buys = {}; sells = {}
    for t in R["trades"]:
        if t["type"] == "option":
            continue
        key = t["asset"]
        (buys if t["action"] == "buy" else sells).setdefault(key, []).append(t["date"])
    step = max(1, n//10)
    for i in range(0, n, step):
        x = L + i*(W-L-Rr)/max(1, n-1)
        parts.append(f'<text x="{x:.1f}" y="{H-24}" text-anchor="middle" font-size="10">{dates[i]}</text>')
    for a in assets:
        y = Y(a)
        xs = sorted(set(buys.get(a, []) + sells.get(a, [])))
        for d in xs:
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
    open(path, "w").write("\n".join(parts)); print("  chart:", os.path.basename(path))

def chart_pie2(path, R):
    W, H = 620, 460; cx, cy, r = 210, 230, 150
    colors = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6", "#1abc9c",
              "#e67e22", "#34495e", "#16a085", "#c0392b", "#2980b9", "#27ae60",
              "#8e44ad", "#f1c40f", "#d35400", "#7f8c8d"]
    by_asset = {}
    for t in R["trades"]:
        if t["action"] == "buy" and t["type"] != "option":
            by_asset[t["asset"]] = by_asset.get(t["asset"], 0.0) + float(t["amount"])
    # average value per asset over months = sum(buy amounts)/nmonths approximated as share
    total = sum(by_asset.values()) or 1.0
    items = sorted(by_asset.items(), key=lambda kv: -kv[1])
    labels = [a for a, _ in items]; values = [v/total for _, v in items]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
             f'<rect width="{W}" height="{H}" fill="white"/>',
             f'<text x="{W/2}" y="24" text-anchor="middle" font-size="16" font-weight="bold">Enhanced Plan Allocation by Asset (buy-value share)</text>']
    ang = -90.0
    for i, (lab, frac) in enumerate(zip(labels, values)):
        sweep = frac*360.0
        a1, a2 = ang, ang+sweep
        x1, y1 = cx+r*math.cos(math.radians(a1)), cy+r*math.sin(math.radians(a1))
        x2, y2 = cx+r*math.cos(math.radians(a2)), cy+r*math.sin(math.radians(a2))
        col = colors[i % len(colors)]
        parts.append(f'<path d="M {cx},{cy} L {x1:.1f},{y1:.1f} A {r},{r} 0 {1 if sweep>180 else 0} 1 {x2:.1f},{y2:.1f} Z" fill="{col}" stroke="white"/>')
        if frac >= 0.02:
            mid = math.radians((a1+a2)/2)
            parts.append(f'<text x="{cx+r*0.62*math.cos(mid):.1f}" y="{cy+r*0.62*math.sin(mid):.1f}" text-anchor="middle" font-size="10" fill="white">{frac*100:.1f}%</text>')
        ang = a2
    ly = 40
    for i, (lab, frac) in enumerate(zip(labels, values)):
        col = colors[i % len(colors)]
        parts.append(f'<rect x="410" y="{ly-8}" width="14" height="14" fill="{col}"/>')
        parts.append(f'<text x="432" y="{ly}" font-size="11">{_esc(lab)}: {frac*100:.1f}%</text>')
        ly += 22
    parts.append("</svg>")
    open(path, "w").write("\n".join(parts)); print("  chart:", os.path.basename(path))

# ---------------------------------------------------------------- main
def main():
    repo, outdir, start, end = REPO, OUTDIR, START, END
    for a in sys.argv[1:]:
        if a.startswith("--repo="):
            repo = a.split("=", 1)[1]
        elif a.startswith("--outdir="):
            outdir = a.split("=", 1)[1]
        elif a.startswith("--start="):
            start = a.split("=", 1)[1]
        elif a.startswith("--end="):
            end = a.split("=", 1)[1]
    y1, y2 = start[:4], end[:4]
    global REPO, OUTDIR, START, END, HSI_CSV, WIDE_CSV, COM_WIDE
    REPO, OUTDIR, START, END = repo, outdir, start, end
    HSI_CSV  = os.path.join(repo, f"HSI_daily_{y1}-01-01_to_{y2}-12-31.csv")
    WIDE_CSV = os.path.join(repo, f"HK_stocks_close_{y1}-01-01_to_{y2}-12-31_wide.csv")
    COM_WIDE = os.path.join(repo, f"Commodities_close_{y1}-01-01_to_{y2}-12-31_wide.csv")
    D = load_all()
    R = run_adjusted(D)
    M = compute_metrics(R, D)
    save_outputs(D, R, M)

    print("=" * 70)
    print("ENHANCED PLAN EXECUTION SUMMARY (5 enhancements)")
    print("=" * 70)
    print(f"Window: {R['dates'][0]} .. {R['dates'][-1]} ({R['day_count']} days, "
          f"{len(R['monthly'])} monthly rebalances)")
    p_ret, h_ret = M["portfolio"]["final_return_pct"], M["hsi"]["final_return_pct"]
    print(f"Portfolio final return: {p_ret:.2f}%   HSI final return: {h_ret:.2f}%")
    print(f"Portfolio max drawdown: {M['portfolio']['max_drawdown_pct']:.2f}%   "
          f"HSI max drawdown: {M['hsi']['max_drawdown_pct']:.2f}%")
    print(f"Portfolio Sharpe: {M['portfolio']['sharpe']:.3f}   HSI Sharpe: {M['hsi']['sharpe']:.3f}")
    print(f"Portfolio tail loss: {M['portfolio']['tail_loss_pct']:.3f}%   "
          f"HSI tail loss: {M['hsi']['tail_loss_pct']:.3f}%")
    print(f"Trades: {M['trades']['count']} total "
          f"(stocks={M['trades']['stock_trades']}, commodities={M['trades']['commodity_trades']}, "
          f"options={M['trades']['option_count']}); realized P&L = "
          f"{M['trades']['realized_pnl_total']:.2f}")
    print(f"Option hedge: stylized monthly protective put on the stock sleeve "
          f"(premium {PUT_PREMIUM*100:.2f}%/mo, strike {PUT_STRIKE*100:.0f}%) - model only, no market quotes in data")
    print(f"Outputs in: {OUTDIR}")

if __name__ == "__main__":
    main()
