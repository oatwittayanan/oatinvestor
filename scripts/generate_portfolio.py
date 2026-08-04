"""
generate_portfolio.py
Reads both "AI PORT" and "DCA S&P500" tabs from Google Sheets,
downloads historical prices, and writes data/portfolio.json.

Usage:
    python3 scripts/generate_portfolio.py
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
SHEET_ID  = "1jlSF2S6e6wSkf2KnnfmC9-zIx-RjRg8y_L69FUnL_90"
CRED_FILE = os.environ.get(
    "GOOGLE_CRED_FILE",
    "/Users/wittayanan/DATA/Credentials/oat-portfolio-dd6c8e0730ab.json"
)
OUT_FILE  = Path(__file__).parent.parent / "data" / "portfolio.json"

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

def read_tab(svc, tab: str) -> list[list[str]]:
    # Read through AN: deposit log lives in AI:AL, past the old Z cutoff.
    res = svc.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=f"'{tab}'!A1:AN100"
    ).execute()
    rows = res.get("values", [])
    out = []
    for row in rows:
        padded = [clean(c) for c in row]
        while len(padded) < 40:
            padded.append("")
        out.append(padded)
    return out

# ── Parse sheet ───────────────────────────────────────────────────
def parse_holdings(rows: list) -> tuple[dict, list, list, list]:
    """Returns (summary, holdings, transactions, deposits)."""
    summary = {}
    holdings = []
    transactions = []
    deposits = []

    # Row 2 (index 1): summary totals
    if len(rows) > 1:
        r = rows[1]
        summary = {
            "total_cost":  to_float(r[4]) or 0.0,
            "total_value": to_float(r[5]) or 0.0,
            "pl_usd":      to_float(r[7]) or 0.0,
            "pl_pct":      to_float(clean(r[8]).replace("%", "")) or 0.0,
        }

    # Rows 4+ (index 3+): holdings (col B–J) and transactions (col N–T)
    for row in rows[3:]:
        ticker = clean(row[1]).upper()
        # Holdings
        if ticker and ticker not in ("#N/A",):
            shares    = to_float(row[2])
            avg_cost  = to_float(row[3])
            tot_cost  = to_float(row[4])
            tot_val   = to_float(row[5])
            price     = to_float(row[6])
            pl_usd    = to_float(row[7])
            pl_pct_s  = clean(row[8]).replace("%", "")
            pl_pct    = to_float(pl_pct_s)
            pos_pct_s = clean(row[9]).replace("%", "")
            pos_pct   = to_float(pos_pct_s)
            if shares is not None and tot_cost is not None:
                holdings.append({
                    "ticker":   ticker,
                    "shares":   shares,
                    "avg_cost": avg_cost,
                    "cost":     tot_cost or 0.0,
                    "value":    tot_val  or 0.0,
                    "price":    price,
                    "pl_usd":   pl_usd   or 0.0,
                    "pl_pct":   pl_pct   or 0.0,
                    "pos_pct":  pos_pct  or 0.0,
                })

        # Transactions (col N = index 13)
        tx_date_raw = clean(row[13])
        tx_ticker   = clean(row[14]).upper()
        tx_type     = clean(row[15]).upper()
        tx_shares   = to_float(row[16])
        tx_price    = to_float(row[17])
        tx_total    = to_float(row[19])
        if tx_date_raw and tx_ticker and tx_type in ("BUY","SELL","DIV"):
            d = parse_thai_date(tx_date_raw)
            # DIV has no shares; BUY/SELL require shares
            valid = d and (tx_type == "DIV" or tx_shares is not None)
            if valid:
                transactions.append({
                    "date":   d.isoformat(),
                    "ticker": tx_ticker,
                    "type":   tx_type,
                    "shares": tx_shares or 0.0,
                    "price":  tx_price  or 0.0,
                    "total":  tx_total  or 0.0,
                })

        # Deposit log (col AI = index 34): date, USD, THB, rate
        dep_date_raw = clean(row[34])
        dep_usd      = to_float(row[35])
        if dep_date_raw and dep_usd:
            dd = parse_thai_date(dep_date_raw)
            if dd:
                deposits.append({
                    "date": dd.isoformat(),
                    "usd":  dep_usd,
                    "thb":  to_float(row[36]) or 0.0,
                    "rate": to_float(row[37]) or 0.0,
                })

    transactions.sort(key=lambda x: x["date"])
    deposits.sort(key=lambda x: x["date"])
    return summary, holdings, transactions, deposits

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
                  holdings: list | None = None) -> dict:
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

    - holdings (optional): current holdings used as a price fallback so a
      transient price-fetch failure for one ticker can't silently drop that
      position to $0 while its deployed capital still counts (phantom loss bug).
    """
    deposits = list(deposits or [])
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
    dep_i, applied = 0, set()

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
def main():
    print("📊 Generating portfolio.json ...")
    svc = get_sheets_service()

    # ── AI PORT ──────────────────────────────────────────────────
    print("\n[1/2] AI PORT tab")
    ai_rows = read_tab(svc, "AI PORT")
    ai_summary, ai_holdings, ai_txs, ai_deposits = parse_holdings(ai_rows)
    print(f"  holdings: {[h['ticker'] for h in ai_holdings]}")
    print(f"  transactions: {len(ai_txs)}")
    print(f"  deposits: {len(ai_deposits)} = ${sum(d['usd'] for d in ai_deposits):.2f}")
    print(f"  total cost: ${ai_summary.get('total_cost',0):.2f}, value: ${ai_summary.get('total_value',0):.2f}")

    ai_history = {}
    if ai_txs:
        ai_history = build_history(ai_txs, ["VOO", "QQQM"],
                                   deposits=ai_deposits, holdings=ai_holdings)
    ai_dividends = round(sum(t["total"] for t in ai_txs if t["type"] == "DIV"), 2)
    print(f"  dividends received: ${ai_dividends:.2f}")

    # ── DCA S&P500 ────────────────────────────────────────────────
    print("\n[2/2] DCA S&P500 tab")
    sp_rows = read_tab(svc, "DCA S&P500")
    sp_summary, sp_holdings, sp_txs, sp_deposits = parse_holdings(sp_rows)
    print(f"  holdings: {[h['ticker'] for h in sp_holdings]}")
    print(f"  transactions: {len(sp_txs)}")
    print(f"  deposits: {len(sp_deposits)} = ${sum(d['usd'] for d in sp_deposits):.2f}")
    print(f"  total cost: ${sp_summary.get('total_cost',0):.2f}, value: ${sp_summary.get('total_value',0):.2f}")

    sp_history = {}
    if sp_txs:
        sp_history = build_history(sp_txs, ["QQQM"],
                                   deposits=sp_deposits, holdings=sp_holdings)
    sp_dividends = round(sum(t["total"] for t in sp_txs if t["type"] == "DIV"), 2)
    print(f"  dividends received: ${sp_dividends:.2f}")

    # ── Output ────────────────────────────────────────────────────
    output = {
        "ai_port": {
            "name": "ลงทุนกับ AI",
            "tab":  "AI PORT",
            **ai_summary,
            "total_dividends": ai_dividends,
            "holdings":    ai_holdings,
            "transactions": ai_txs,
            "history":     ai_history,
        },
        "sp500_port": {
            "name": "พอร์ตออม S&P500",
            "tab":  "DCA S&P500",
            **sp_summary,
            "total_dividends": sp_dividends,
            "holdings":    sp_holdings,
            "transactions": sp_txs,
            "history":     sp_history,
        },
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\n✅  portfolio.json → {OUT_FILE}")

    # Print summary
    for key, label in [("ai_port","ลงทุนกับ AI"), ("sp500_port","พอร์ตออม S&P500")]:
        p = output[key]
        s = p.get("history", {}).get("summary", {})
        print(f"  [{label}] cost=${p.get('total_cost',0):.2f} value=${p.get('total_value',0):.2f} "
              f"P/L={p.get('pl_pct',0):+.2f}% | "
              f"vs VOO={s.get('voo_pct', s.get('qqqm_pct',0)):+.2f}%")

if __name__ == "__main__":
    main()
