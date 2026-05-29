"""
fix_sheet_formulas.py
Fixes formula issues in both portfolio sheet tabs to handle DIV rows correctly.

Columns fixed (rows 4-15):
  T = Total (BUY/SELL auto-calc, DIV = "" so user enters manually)
  U = Running Shares (cumulative BUY-SELL, fixes range bug where last data row
      referenced the next row instead of itself)
  V = Price $ (GOOGLEFINANCE, hidden for DIV rows)
  W = %P/L (hidden for DIV rows, no more #DIV/0!)

Special cases:
  DCA S&P500 — T7 has static DIV amount 0.28 (skip to preserve)
  AI PORT    — V4 is CASH row with special formula T4 (not GOOGLEFINANCE, skip)
"""
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build

SHEET_ID  = "1jlSF2S6e6wSkf2KnnfmC9-zIx-RjRg8y_L69FUnL_90"
CRED_FILE = os.environ.get(
    "GOOGLE_CRED_FILE",
    "/Users/wittayanan/DATA/Credentials/oat-portfolio-dd6c8e0730ab.json"
)
ROW_START, ROW_END = 4, 15

def fix_tab(svc, tab: str, skip_t_rows: list = [], skip_v_rows: list = []):
    """
    Fix T/U/V/W columns for a portfolio tab.
    skip_t_rows: rows where T has a static DIV amount (preserve user-entered value)
    skip_v_rows: rows with special V formula (e.g. CASH row shows T not GOOGLEFINANCE)
    """
    updates = []
    for r in range(ROW_START, ROW_END + 1):
        # T — Total: BUY/SELL auto-calc; DIV = blank so user types amount manually
        if r not in skip_t_rows:
            updates.append({
                "range": f"'{tab}'!T{r}",
                "values": [[
                    f'=IF(N{r}="","",IF(UPPER(P{r})="BUY",'
                    f'Q{r}*R{r}+IF(ISBLANK(S{r}),0,S{r}),'
                    f'IF(UPPER(P{r})="SELL",'
                    f'Q{r}*R{r}-IF(ISBLANK(S{r}),0,S{r}),"")))'
                ]]
            })

        # U — Running Shares: always cumulate up to current row (fixes off-by-one bug)
        updates.append({
            "range": f"'{tab}'!U{r}",
            "values": [[
                f'=IF(N{r}="","",('
                f'SUMIFS($Q$4:Q{r},$O$4:O{r},O{r},$P$4:P{r},"BUY")-'
                f'SUMIFS($Q$4:Q{r},$O$4:O{r},O{r},$P$4:P{r},"SELL")))'
            ]]
        })

        # V — Price $: use GOOGLEFINANCE; hide for empty and DIV rows
        if r not in skip_v_rows:
            updates.append({
                "range": f"'{tab}'!V{r}",
                "values": [[
                    f'=IFS(OR(N{r}="",UPPER(P{r})="DIV"),"",U{r}=0,"",TRUE,GOOGLEFINANCE(O{r}))'
                ]]
            })

        # W — %P/L: hide for empty and DIV rows; no more #DIV/0!
        updates.append({
            "range": f"'{tab}'!W{r}",
            "values": [[
                f'=IFS(OR(N{r}="",UPPER(P{r})="DIV"),"",U{r}=0,"",TRUE,(V{r}-R{r})/R{r})'
            ]]
        })

    body = {"valueInputOption": "USER_ENTERED", "data": updates}
    svc.spreadsheets().values().batchUpdate(spreadsheetId=SHEET_ID, body=body).execute()
    print(f"  ✅ {len(updates)} cells fixed in '{tab}'")

def main():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds  = service_account.Credentials.from_service_account_file(CRED_FILE, scopes=scopes)
    svc    = build("sheets", "v4", credentials=creds)

    print("🔧 Fixing sheet formulas ...")

    # DCA S&P500: skip T7 (static 0.28 DIV amount entered by user)
    print("\n[1/2] DCA S&P500")
    fix_tab(svc, "DCA S&P500", skip_t_rows=[7])

    # AI PORT: skip V4 (CASH row uses =T4 instead of GOOGLEFINANCE)
    print("\n[2/2] AI PORT")
    fix_tab(svc, "AI PORT", skip_v_rows=[4])

    print("\n✅ Both tabs fixed:")
    print("   T: BUY/SELL auto-calc, DIV = blank (type amount manually)")
    print("   U: Running shares — cumulative range bug fixed")
    print("   V: Price $ — hidden for DIV rows")
    print("   W: %P/L — hidden for DIV rows, no more #DIV/0!")

if __name__ == "__main__":
    main()
