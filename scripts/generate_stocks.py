"""
generate_stocks.py
Generates data/stocks.json by:
  1. Running oat-public-website's generate_site_data.py (full wiki + valuation parse)
  2. Enriching the output:
     - Promotes story_gate.tier → top-level tier
     - Merges latest charlie review per ticker from charlie_watchlist_reviews.json
  3. Copying result to oat-investor/data/stocks.json

Usage: python3 scripts/generate_stocks.py
"""
import json
import subprocess
import shutil
import sys
from pathlib import Path

ROOT     = Path(__file__).parent.parent
OAT_OS   = ROOT.parent
PUB      = OAT_OS / "oat-public-website"
CRED_DIR = OAT_OS / "investment-system" / "portfolio"

PUB_STOCKS_OUT = PUB / "data" / "stocks.json"
CHARLIE_JSON   = CRED_DIR / "charlie_watchlist_reviews.json"
OUT_FILE       = ROOT / "data" / "stocks.json"

PIPELINE_STATUS = OAT_OS / "investment-system" / "scripts" / "pipeline_status.py"
KNOW_PORTFOLIO  = OAT_OS / "oat-investment-knowledge" / "portfolio"   # git mirror
MIRROR_FILES    = ["charlie_watchlist_reviews.json", "watchlist_valuations.json",
                   "papers.json", "pipeline_log.json"]


def warn_consistency():
    """เตือนถ้า card sections ไม่ consistent + wikilink broken (ผ่าน pipeline_status.py)."""
    if not PIPELINE_STATUS.exists():
        return
    print("[consistency] ตรวจ card sections + wikilink ...")
    subprocess.run([sys.executable, str(PIPELINE_STATUS), "--consistency", "--quiet"], cwd=OAT_OS)


def sync_git_mirror():
    """copy canonical portfolio state → oat-investment-knowledge/portfolio (git backup)."""
    if not KNOW_PORTFOLIO.exists():
        return
    synced = 0
    for fn in MIRROR_FILES:
        src = CRED_DIR / fn
        if src.exists():
            shutil.copy2(src, KNOW_PORTFOLIO / fn)
            synced += 1
    print(f"  ✅ synced {synced} portfolio state files → git mirror")


# ── Step 1: Run oat-public-website generator ─────────────────────────────────
def run_pub_generator():
    print("[1/3] Running oat-public-website generate_site_data.py ...")
    result = subprocess.run(
        [sys.executable, "scripts/generate_site_data.py"],
        cwd=PUB, capture_output=False
    )
    if result.returncode != 0:
        print("  ⚠️  Generator finished with errors (output may still be usable)")
    if not PUB_STOCKS_OUT.exists():
        raise FileNotFoundError(f"Expected output not found: {PUB_STOCKS_OUT}")
    print(f"  ✅ {PUB_STOCKS_OUT}")


# ── Step 2: Load and enrich ───────────────────────────────────────────────────
def load_charlie() -> dict:
    """Return {ticker: latest_charlie_review} across all charlie_watchlist_reviews entries."""
    if not CHARLIE_JSON.exists():
        print(f"  ⚠️  charlie_watchlist_reviews.json not found: {CHARLIE_JSON}")
        return {}

    with open(CHARLIE_JSON, encoding="utf-8") as f:
        entries = json.load(f)

    # Sort by date ascending → later entries overwrite earlier ones
    entries_sorted = sorted(entries, key=lambda e: e.get("date", ""))
    per_ticker: dict = {}
    for entry in entries_sorted:
        tr = entry.get("ticker_reviews", {})
        if isinstance(tr, dict):
            for ticker, review in tr.items():
                per_ticker[ticker.upper()] = _normalize_charlie(review, entry.get("date"))
        elif isinstance(tr, list):
            for item in tr:
                t = (item.get("ticker") or "").upper()
                if t:
                    per_ticker[t] = _normalize_charlie(item, entry.get("date"))

    print(f"  charlie tickers: {sorted(per_ticker.keys())}")
    return per_ticker


def _normalize_charlie(raw: dict, review_date: str | None) -> dict:
    """Normalize charlie review to the fields stock.html expects."""
    verdict = (raw.get("verdict") or raw.get("charlie_verdict") or "").upper()
    # verified_claims — support both field names
    claims = raw.get("verified_claims") or raw.get("claims") or []
    # concerns
    concerns = raw.get("concerns") or raw.get("risks") or []
    return {
        "charlie_verdict": verdict,
        "verified_claims": claims[:4],
        "concerns":        concerns[:4],
        "summary":         raw.get("summary") or "",
        "review_date":     review_date or "",
    }


def enrich(stocks: dict, charlie: dict) -> dict:
    enriched = 0
    for ticker, data in stocks.items():
        # Promote story_gate.tier → top-level tier
        sg = data.get("story_gate") or {}
        if sg.get("tier") and not data.get("tier"):
            data["tier"] = sg["tier"]

        # Merge charlie
        if ticker in charlie:
            data["charlie"] = charlie[ticker]
            enriched += 1

    print(f"  charlie merged: {enriched} tickers")
    return stocks


PETE_FIELDS = [
    "mark_easy", "mark_full", "warren_easy", "charlie_easy",
    "idea_th", "story_gate_th", "bull_th", "risk_th",
]


def save_pete_fields(existing_path: Path) -> dict:
    """Read existing stocks.json and extract Pete-authored fields per ticker."""
    if not existing_path.exists():
        return {}
    with open(existing_path, encoding="utf-8") as f:
        existing = json.load(f)
    saved = {}
    for ticker, data in existing.items():
        pete = {k: data[k] for k in PETE_FIELDS if k in data}
        if pete:
            saved[ticker] = pete
    if saved:
        print(f"  preserving Pete fields for: {sorted(saved.keys())}")
    return saved


def restore_pete_fields(stocks: dict, pete_saved: dict) -> dict:
    for ticker, pete in pete_saved.items():
        if ticker in stocks:
            stocks[ticker].update(pete)
    return stocks


# ── Step 3: Write output ──────────────────────────────────────────────────────
def main():
    print("📦 generate_stocks.py\n")

    # Save Pete-authored fields before overwriting
    pete_saved = save_pete_fields(OUT_FILE)

    run_pub_generator()

    print("\n[2/3] Loading and enriching ...")
    with open(PUB_STOCKS_OUT, encoding="utf-8") as f:
        stocks = json.load(f)
    print(f"  loaded {len(stocks)} tickers from pub")

    charlie = load_charlie()
    stocks  = enrich(stocks, charlie)
    stocks  = restore_pete_fields(stocks, pete_saved)

    print(f"\n[3/3] Writing → {OUT_FILE}")
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(stocks, ensure_ascii=False, indent=2))

    # Quick summary
    has_tier    = sum(1 for v in stocks.values() if v.get("tier"))
    has_charlie = sum(1 for v in stocks.values() if v.get("charlie"))
    print(f"  ✅ {len(stocks)} tickers | tier: {has_tier} | charlie: {has_charlie}")

    # Guards: consistency warning + git mirror of canonical portfolio state
    warn_consistency()
    print()
    sync_git_mirror()


if __name__ == "__main__":
    main()
