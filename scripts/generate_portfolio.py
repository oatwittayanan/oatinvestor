"""
generate_portfolio.py
Reads the "Life Sheet" Google Sheet (tabs "Long Term Port", "DCA VOO" + the
"พอร์ต" summary tab), downloads historical prices, and writes data/portfolio.json.

2026-11-26: switched from the old "DCA Port" sheet (tabs DCA STOCK / DCA S&P500).
Old version kept as generate_portfolio_dcaport_old.py.

Usage:
    python3 scripts/generate_portfolio.py
    PORTFOLIO_OUT=/tmp/x.json python3 scripts/generate_portfolio.py   # write elsewhere
"""

import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import yfinance as yf
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ── Config ────────────────────────────────────────────────────────
SHEET_ID  = "1W8M8IDcLlBJRzTqiQUdXM6kKJbeHNapOMJWHAwZkX80"   # Life Sheet
CRED_FILE = os.environ.get(
    "GOOGLE_CRED_FILE",
    "/Users/wittayanan/DATA/Credentials/oat-portfolio-dd6c8e0730ab.json"
)
OUT_FILE  = Path(os.environ.get(
    "PORTFOLIO_OUT",
    Path(__file__).parent.parent / "data" / "portfolio.json"
))

# output key → Life Sheet port (name in 'พอร์ต'!A = tab name)
# pl_basis keeps each port's old P/L definition:
#   deposit = value − money deposited (old DCA STOCK) · cost = value − total cost (old DCA S&P500)
PORTS = {
    "ai_port":    {"tab": "Long Term Port", "name": "ลงทุนกับ AI",
                   "benchmarks": ["VOO", "QQQM"], "pl_basis": "deposit"},
    "sp500_port": {"tab": "DCA VOO",        "name": "พอร์ตออม S&P500",
                   "benchmarks": ["QQQM"],        "pl_basis": "deposit"},  # โอ๊ตเลือก 11-26: แบบ Life Sheet
}

THAI_MONTHS = {
    "ม.ค.": 1, "ก.พ.": 2, "มี.ค.": 3, "เม.ย.": 4,
    "พ.ค.": 5, "มิ.ย.": 6, "ก.ค.":  7, "ส.ค.":  8,
    "ก.ย.": 9, "ต.ค.": 10, "พ.ย.": 11, "ธ.ค.": 12,
}

# ── Helpers ───────────────────────────────────────────────────────
def clean(s) -> str:
    return str(s).strip().lstrip("'").strip() if s is not None else ""

def to_float(s) -> float | None:
    s = clean(s)
    if not s or s in ("#N/A", "#DIV/0!", "N/A", "—", "nan"):
        return None
    s = re.sub(r"[^\d.\-]", "", s)
    try:
        return float(s)
    except ValueError:
        return None

def parse_thai_date(s) -> date | None:
    s = clean(s)
    if not s:
        return None
    m = re.match(r"(\d{1,2})\s+(\S+)\s+(\d{4})", s)
    if m:
        day, mon_str, yr = int(m[1]), m[2], int(m[3])
        if mon_str in THAI_MONTHS:
            if yr > 2500:
                yr -= 543
            try:
                return date(yr, THAI_MONTHS[mon_str], day)
            except ValueError:
                pass
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None

# ── Sheets ────────────────────────────────────────────────────────
def get_sheets_service():
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds  = service_account.Credentials.from_service_account_file(CRED_FILE, scopes=scopes)
    return build("sheets", "v4", credentials=creds)

def num(v) -> float | None:
    """UNFORMATTED_VALUE cells come back as numbers; fall back to to_float for text."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return to_float(v)

def read_life_sheet(svc) -> tuple[list, list, dict]:
    """One batchGet: 'พอร์ต' summary + holdings, plus every port tab's log."""
    ranges = ["'พอร์ต'!A3:N14", "'พอร์ต'!A19:M218"] + \
             [f"'{cfg['tab']}'!A2:M501" for cfg in PORTS.values()]
    res = svc.spreadsheets().values().batchGet(
        spreadsheetId=SHEET_ID, ranges=ranges,
        valueRenderOption="UNFORMATTED_VALUE",
        dateTimeRenderOption="FORMATTED_STRING",
    ).execute()["valueRanges"]
    vals = [r.get("values", []) for r in res]
    pad = lambda rows, n: [list(r) + [""] * (n - len(r)) for r in rows]
    summ, hold = pad(vals[0], 14), pad(vals[1], 13)
    logs = {cfg["tab"]: pad(v, 13) for cfg, v in zip(PORTS.values(), vals[2:])}
    return summ, hold, logs

# ── Parse sheet ───────────────────────────────────────────────────
def parse_log(rows: list) -> tuple[list, list, list]:
    """Port tab log (A date · B ticker · C type · D shares · E price/amount ·
    F fee · G THB · H note · I total). Returns (transactions, deposits, adjustments).
    DEPOSIT/WITHDRAW → deposits (WITHDRAW negative) · ADJ → cash adjustments."""
    transactions, deposits, adjustments = [], [], []
    for r in rows:
        typ = clean(r[2]).upper()
        d = parse_thai_date(r[0])
        if not d or not typ:
            continue
        ticker = clean(r[1]).upper()
        total  = num(r[8])
        if total is None:
            total = num(r[4]) or 0.0
        if typ in ("BUY", "SELL", "DIV") and ticker:
            shares = num(r[3])
            if typ != "DIV" and shares is None:
                continue
            transactions.append({
                "date":   d.isoformat(),
                "ticker": ticker,
                "type":   typ,
                "shares": round(shares, 8) if (shares and typ != "DIV") else 0.0,
                "price":  round(num(r[4]) or 0.0, 4) if typ != "DIV" else 0.0,
                "total":  round(total, 4),
            })
        elif typ in ("DEPOSIT", "WITHDRAW"):
            usd = total if typ == "DEPOSIT" else -abs(total)
            thb = num(r[6]) or 0.0
            deposits.append({
                "date": d.isoformat(),
                "usd":  usd,
                "thb":  thb if typ == "DEPOSIT" else -abs(thb),
                "rate": round(abs(thb / usd), 2) if (thb and usd) else 0.0,
            })
        elif typ == "ADJ" and total:
            adjustments.append({"date": d.isoformat(), "usd": total})
    transactions.sort(key=lambda x: x["date"])   # stable: keeps sheet order within a day
    deposits.sort(key=lambda x: x["date"])
    adjustments.sort(key=lambda x: x["date"])
    return transactions, deposits, adjustments

def parse_port(port: str, cfg: dict, summ: list, hold: list,
               transactions: list) -> tuple[dict, list]:
    """Summary + holdings for one port from the 'พอร์ต' tab. Returns (summary, holdings)."""
    srow = next((r for r in summ if clean(r[0]) == port), None)
    if srow is None:
        raise SystemExit(f"❌ port '{port}' not found in 'พอร์ต'!A3:A14")
    total_value = num(srow[6]) or 0.0
    cash        = num(srow[5]) or 0.0
    net_deposit = num(srow[7]) or 0.0

    holdings = []
    if abs(cash) > 0.005:
        c = round(cash, 2)
        holdings.append({"ticker": "CASH", "shares": 1.0, "avg_cost": c, "cost": c,
                         "value": c, "price": c, "pl_usd": 0.0, "pl_pct": 0.0,
                         "pos_pct": round(cash / total_value * 100, 2) if total_value else 0.0})
    # Same order as the old sheet: first BUY date of each ticker
    first_buy = {}
    for i, t in enumerate(transactions):
        first_buy.setdefault(t["ticker"], i)
    rows = [r for r in hold if clean(r[0]) == port and clean(r[1])]
    rows.sort(key=lambda r: first_buy.get(clean(r[1]).upper(), 10**6))
    for r in rows:
        shares, cost, value = num(r[2]), num(r[3]), num(r[8])
        if shares is None or cost is None:
            continue
        pl = num(r[9]) or 0.0
        plp = num(r[10])
        holdings.append({
            "ticker":   clean(r[1]).upper(),
            "shares":   round(shares, 8),
            "avg_cost": round(num(r[4]), 2) if num(r[4]) is not None else None,
            "cost":     round(cost, 2),
            "value":    round(value or 0.0, 2),
            "price":    round(num(r[7]), 2) if num(r[7]) is not None else None,
            "pl_usd":   round(pl, 2),
            "pl_pct":   round(plp * 100, 2) if plp is not None else 0.0,
            "pos_pct":  round((value or 0.0) / total_value * 100, 2) if total_value else 0.0,
        })

    total_cost = sum(h["cost"] for h in holdings)   # holdings cost + cash (old sheet E2)
    if cfg["pl_basis"] == "deposit":                 # old DCA STOCK: value − money deposited
        pl_usd = num(srow[8]) or 0.0
        pl_pct = (num(srow[9]) or 0.0) * 100
    else:                                            # old DCA S&P500: value − total cost
        pl_usd = total_value - total_cost
        pl_pct = pl_usd / total_cost * 100 if total_cost else 0.0
    summary = {
        "total_cost":  round(total_cost, 2),
        "total_value": round(total_value, 2),
        "pl_usd":      round(pl_usd, 2),
        "pl_pct":      round(pl_pct, 2),
    }
    print(f"  [sheet] stock={num(srow[4]) or 0:.2f} cash={cash:.2f} "
          f"total={total_value:.2f} net_deposit={net_deposit:.2f}")
    return summary, holdings

# ── Prices ────────────────────────────────────────────────────────
def _fetch_prices_http(tickers: list[str], start: date,
                       adjusted: bool = True) -> dict[str, dict[str, float]]:
    """Yahoo Finance v8 direct HTTP — no yfinance dependency."""
    import time as _time
    import requests as _req
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    start_dt = datetime.combine(start, datetime.min.time())
    period1  = int(start_dt.timestamp())
    period2  = int(_time.time()) + 86400
    result: dict[str, dict[str, float]] = {t: {} for t in tickers}
    for sym in tickers:
        for base in ["query1", "query2"]:
            url = f"https://{base}.finance.yahoo.com/v8/finance/chart/{sym}?period1={period1}&period2={period2}&interval=1d"
            try:
                r = _req.get(url, headers=headers, timeout=20)
                data = r.json()
                chart = data.get("chart", {}).get("result", [{}])[0]
                closes = chart.get("indicators", {}).get("quote", [{}])[0].get("close", [])
                if adjusted:
                    adj = chart.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose", [])
                    if adj:
                        closes = adj
                ts_list = chart.get("timestamp", [])
                for ts_val, c in zip(ts_list, closes):
                    if c is not None and not (isinstance(c, float) and c != c):
                        dt_str = datetime.utcfromtimestamp(ts_val).strftime("%Y-%m-%d")
                        result[sym][dt_str] = round(float(c), 4)
                if result[sym]:
                    print(f"  [prices-http] {sym}: {len(result[sym])} days via {base}")
                    break
            except Exception as ex:
                print(f"  [prices-http] {sym} {base}: {ex}")
    return result

def fetch_prices(tickers: list[str], start: date, adjusted: bool = True) -> pd.DataFrame:
    """
    adjusted=True  → total-return prices (dividends folded into the price).
                     Used for VOO/QQQM benchmarks = dividends auto-reinvested.
    adjusted=False → raw market prices. Used for the portfolio's own holdings,
                     because their dividends are already counted as received
                     cash (DIV rows); adjusted prices would double-count them.
    """
    kind = "adjusted" if adjusted else "raw"
    print(f"  [prices/{kind}] {tickers} from {start}")
    # Try 1: yfinance
    try:
        raw = yf.download(tickers, start=str(start), progress=False, auto_adjust=adjusted)
        prices = raw["Close"] if "Close" in raw.columns else raw
        if isinstance(prices, pd.Series):
            prices = prices.to_frame(name=tickers[0])
        prices.columns = [str(c) for c in prices.columns]
        prices = prices.ffill()
        if not prices.empty:
            print(f"  [prices] {len(prices)} days via yfinance")
            return prices
    except Exception as e:
        print(f"  [prices] yfinance failed ({e}), trying HTTP …")

    # Try 2: Yahoo v8 direct HTTP
    http_data = _fetch_prices_http(tickers, start, adjusted=adjusted)
    all_dates = sorted(set(dt for sym in http_data.values() for dt in sym.keys()))
    if all_dates:
        idx = pd.to_datetime(all_dates)
        df = pd.DataFrame(index=idx)
        for sym in tickers:
            sym_map = http_data.get(sym, {})
            df[sym] = pd.Series({pd.Timestamp(d): v for d, v in sym_map.items()})
        df = df.ffill()
        print(f"  [prices] {len(df)} days via Yahoo HTTP")
        return df

    print("  [prices] all methods failed")
    return pd.DataFrame()

# ── Build history ─────────────────────────────────────────────────
def build_history(transactions: list, benchmark_tickers: list[str],
                  deposits: list | None = None,
                  holdings: list | None = None,
                  adjustments: list | None = None) -> dict:
    """
    Total-portfolio model. Both sides answer the same question:
    "every dollar transferred in — what is it worth today?"

      portfolio(t) = Σ(shares × raw market price) + cash(t)
      cash(t)      = deposits≤t − buys≤t + sells≤t + dividends received≤t
      benchmark(t) = each deposit mirrored into VOO/QQQM on its own transfer
                     date, priced total-return (dividends reinvested)

    So idle cash, SGOV and received dividends all count on the portfolio side
    with no special-casing — SGOV is simply another holding.

    Portfolio holdings use RAW prices because their dividends are already
    counted as received cash; adjusted prices would double-count them.

    - adjustments (optional): ADJ rows = cash corrections inside the portfolio
      (fee/rounding true-ups). They move cash but are not deposits.
    - holdings (optional): current holdings used as a price fallback so a
      transient price-fetch failure for one ticker can't silently drop that
      position to $0 while its deployed capital still counts (phantom loss bug).
    """
    deposits = list(deposits or [])
    adjustments = sorted(adjustments or [], key=lambda a: a["date"])
    # CASH rows in the transaction log are a running *balance*, not a cash flow.
    # Cash is derived from deposits/buys/sells/divs here, so skip them entirely.
    stock_txs = [t for t in transactions if t["ticker"] != "CASH"]

    # Tabs without a deposit log fall back to the old proxy: treat each BUY as
    # money arriving that day. Less accurate (idle cash is invisible) but keeps
    # the chart working.
    if not deposits:
        print("  [history] ⚠️ no deposit log — falling back to BUY-as-deposit proxy")
        deposits = [{"date": t["date"], "usd": t["total"]}
                    for t in stock_txs if t["type"] == "BUY"]
    if not deposits:
        return {"dates": [], "portfolio": [], "summary": {}}

    deposits.sort(key=lambda d: d["date"])
    start_date = date.fromisoformat(deposits[0]["date"])

    stock_tickers = list(dict.fromkeys([t["ticker"] for t in stock_txs]))

    # Two price sets: raw for what Oat actually holds, total-return for benchmarks.
    px_stock = fetch_prices(stock_tickers, start_date, adjusted=False) if stock_tickers else pd.DataFrame()
    px_bm    = fetch_prices(benchmark_tickers, start_date, adjusted=True) if benchmark_tickers else pd.DataFrame()

    if px_stock.empty and px_bm.empty:
        print("  [history] no price data")
        return {"dates": [], "portfolio": [], "summary": {}}

    # Align both onto one trading calendar
    if not px_stock.empty and not px_bm.empty:
        idx = px_stock.index.union(px_bm.index)
    else:
        idx = px_stock.index if not px_stock.empty else px_bm.index
    if not px_stock.empty:
        px_stock = px_stock.reindex(idx).ffill()
    if not px_bm.empty:
        px_bm = px_bm.reindex(idx).ffill()

    # Guard against phantom-loss bug: a held stock whose price history failed to
    # download would contribute $0 while its capital still counts as deposited.
    cur_price = {}
    if holdings:
        cur_price = {h["ticker"].upper(): h["price"]
                     for h in holdings if h.get("price")}
    frozen: set[str] = set()   # valued at cost instead of market
    for tk in stock_tickers:
        has_px = tk in px_stock.columns and not px_stock[tk].dropna().empty
        if not has_px:
            if cur_price.get(tk):
                px_stock[tk] = float(cur_price[tk])
                print(f"  [history] ⚠️ {tk}: price history missing — "
                      f"fallback to current price ${cur_price[tk]:.2f} (flat line)")
            else:
                frozen.add(tk)
                print(f"  [history] ⚠️ {tk}: no price and no fallback — "
                      f"holding it at cost to avoid phantom loss")

    bm_shares: dict[str, float] = {bm: 0.0 for bm in benchmark_tickers}
    port_shares: dict[str, float] = {}
    cash = 0.0           # uninvested cash inside the portfolio
    frozen_value = 0.0   # cost basis of positions we cannot price
    total_deposited = 0.0

    dates_out, port_vals = [], []
    bm_vals: dict[str, list] = {bm: [] for bm in benchmark_tickers}
    dep_totals = []
    dep_i, adj_i, applied = 0, 0, set()

    for trade_date in idx:
        # Money transferred in on/before today → lands as cash, and mirrors into
        # each benchmark at that transfer date's own price.
        while dep_i < len(deposits) and pd.Timestamp(deposits[dep_i]["date"]) <= trade_date:
            dp = deposits[dep_i]
            dep_i += 1
            cash            += dp["usd"]
            total_deposited += dp["usd"]
            for bm in benchmark_tickers:
                if bm in px_bm.columns:
                    s = px_bm[bm].dropna()
                    s = s[s.index >= pd.Timestamp(dp["date"])]
                    if not s.empty and float(s.iloc[0]) > 0:
                        bm_shares[bm] += dp["usd"] / float(s.iloc[0])

        # Cash corrections (ADJ) — change cash, not the deposited total
        while adj_i < len(adjustments) and pd.Timestamp(adjustments[adj_i]["date"]) <= trade_date:
            cash += adjustments[adj_i]["usd"]
            adj_i += 1

        # Apply pending transactions — these move money *within* the portfolio
        for i, tx in enumerate(stock_txs):
            if i in applied or pd.Timestamp(tx["date"]) > trade_date:
                continue
            applied.add(i)
            tk, typ, total = tx["ticker"], tx["type"], tx["total"]

            if typ == "BUY":
                cash -= total
                if tk in frozen:
                    frozen_value += total
                else:
                    port_shares[tk] = port_shares.get(tk, 0.0) + tx["shares"]
            elif typ == "SELL":
                cash += total
                if tk in frozen:
                    frozen_value = max(0.0, frozen_value - total)
                else:
                    port_shares[tk] = max(0.0, port_shares.get(tk, 0.0) - tx["shares"])
            elif typ == "DIV":
                cash += total   # received dividends stay in the portfolio

        if total_deposited <= 0:
            continue

        pv = cash + frozen_value
        for tk, sh in port_shares.items():
            if sh > 0 and tk in px_stock.columns:
                px = px_stock[tk].get(trade_date)
                if px is not None and not pd.isna(px):
                    pv += sh * float(px)

        port_vals.append(round(pv, 4))
        dep_totals.append(round(total_deposited, 2))
        dates_out.append(trade_date.strftime("%Y-%m-%d"))

        for bm in benchmark_tickers:
            bv = 0.0
            if bm in px_bm.columns:
                px = px_bm[bm].get(trade_date)
                if px is not None and not pd.isna(px):
                    bv = bm_shares[bm] * float(px)
            bm_vals[bm].append(round(bv, 4))

    # Drop benchmarks whose price fetch failed (all-zero series). Emitting a
    # zero array makes the chart draw a bogus -100% flat line, so omit it and
    # let the frontend simply skip that benchmark.
    valid_bms = [bm for bm in benchmark_tickers if any(v > 0 for v in bm_vals[bm])]
    for bm in benchmark_tickers:
        if bm not in valid_bms:
            print(f"  [history] ⚠️ benchmark {bm}: no price data fetched — omitting (would show -100%)")

    # Summary — return measured against every dollar transferred in
    def _pct(vals, dep):
        last = next((v for v in reversed(vals) if v > 0), 0)
        return round((last / dep - 1) * 100, 2) if dep else 0.0

    dep = total_deposited
    summary = {"portfolio_pct": _pct(port_vals, dep)}
    for bm in valid_bms:
        key = bm.lower() + "_pct"
        summary[key] = _pct(bm_vals[bm], dep)
    summary["total_deposited"] = round(dep, 2)

    result = {
        "dates":     dates_out,
        "portfolio": port_vals,
        "deposited": dep_totals,
        "summary":   summary,
    }
    for bm in valid_bms:
        result[bm.lower()] = bm_vals[bm]

    return result

# ── Main ──────────────────────────────────────────────────────────
def mask_money(output: dict) -> None:
    """Hide real dollar amounts in the public portfolio.json (โอ๊ต 2026-11-18: ปิดมูลค่าพอร์ตทั้งหมด).

    Every money field is multiplied by one factor k so that both ports' total value = 100.
    All ratios (pl_pct, pos_pct, returns, the chart, combined weights) stay exact, but no
    absolute dollar amount is recoverable. Per-share market prices stay real (public data);
    share counts are scaled instead. CASH (shares=1, price=amount) has its price scaled.
    """
    total = sum((output[k].get("total_value") or 0) for k in ("ai_port", "sp500_port"))
    if total <= 0:
        return
    k = 100.0 / total
    sc = lambda v, nd=6: round(v * k, nd) if isinstance(v, (int, float)) else v
    for key in ("ai_port", "sp500_port"):
        p = output[key]
        for f in ("total_cost", "total_value", "pl_usd", "total_dividends"):
            if f in p:
                p[f] = sc(p[f], 4)
        for h in p.get("holdings", []):
            for f in ("cost", "value", "pl_usd"):
                if f in h:
                    h[f] = sc(h[f], 4)
            if h.get("ticker") == "CASH":
                h["avg_cost"], h["price"] = sc(h.get("avg_cost")), sc(h.get("price"))
            elif "shares" in h:
                h["shares"] = sc(h["shares"], 8)
        for t in p.get("transactions", []):
            if "total" in t:
                t["total"] = sc(t["total"], 4)
            if t.get("ticker") == "CASH":
                t["price"] = sc(t.get("price"))
            elif isinstance(t.get("shares"), (int, float)):
                t["shares"] = sc(t["shares"], 8)
        hist = p.get("history") or {}
        for f, v in list(hist.items()):
            if f != "dates" and isinstance(v, list):
                hist[f] = [sc(x, 4) for x in v]
        summ = hist.get("summary") or {}
        if "total_deposited" in summ:
            summ["total_deposited"] = sc(summ["total_deposited"], 4)
    output["money_masked"] = "ตัวเลขเงินทั้งหมดถูกย่อเป็นหน่วยดัชนี (2 พอร์ตรวม = 100) — สัดส่วนและ % ถูกต้อง แต่ไม่ใช่ดอลลาร์จริง"


def main():
    print("📊 Generating portfolio.json (Life Sheet) ...")
    svc = get_sheets_service()
    summ, hold, logs = read_life_sheet(svc)

    output = {}
    for n, (key, cfg) in enumerate(PORTS.items(), 1):
        tab = cfg["tab"]
        print(f"\n[{n}/{len(PORTS)}] {tab} tab")
        txs, deposits, adjs = parse_log(logs[tab])
        summary, holdings = parse_port(tab, cfg, summ, hold, txs)
        print(f"  holdings: {[h['ticker'] for h in holdings]}")
        print(f"  transactions: {len(txs)}")
        print(f"  deposits: {len(deposits)} = ${sum(d['usd'] for d in deposits):.2f}")
        print(f"  adjustments: {len(adjs)} = ${sum(a['usd'] for a in adjs):.2f}")
        print(f"  total cost: ${summary['total_cost']:.2f}, value: ${summary['total_value']:.2f}")

        history = {}
        if txs:
            history = build_history(txs, cfg["benchmarks"], deposits=deposits,
                                    holdings=holdings, adjustments=adjs)
        dividends = round(sum(t["total"] for t in txs if t["type"] == "DIV"), 2)
        print(f"  dividends received: ${dividends:.2f}")

        output[key] = {
            "name": cfg["name"],
            "tab":  tab,
            **summary,
            "total_dividends": dividends,
            "holdings":     holdings,
            "transactions": txs,
            "history":      history,
        }
    output["generated_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    # Print summary (real numbers — local log only, before masking)
    for key, cfg in PORTS.items():
        p = output[key]
        s = p.get("history", {}).get("summary", {})
        print(f"  [{cfg['name']}] cost=${p.get('total_cost',0):.2f} value=${p.get('total_value',0):.2f} "
              f"P/L={p.get('pl_pct',0):+.2f}% | "
              f"vs VOO={s.get('voo_pct', s.get('qqqm_pct',0)):+.2f}%")

    mask_money(output)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\n✅  portfolio.json → {OUT_FILE} (money masked: index units, both ports sum to 100)")

if __name__ == "__main__":
    main()
