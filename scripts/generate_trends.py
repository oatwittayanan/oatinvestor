"""
generate_trends.py
Runs oat-public-website's generate_trends.py and copies trends.js to oat-investor.

Usage: python3 scripts/generate_trends.py
"""
import subprocess
import shutil
import sys
from pathlib import Path

ROOT   = Path(__file__).parent.parent
OAT_OS = ROOT.parent
PUB    = OAT_OS / "oat-public-website"

PUB_TRENDS_OUT = PUB / "trends.js"
OUT_FILE       = ROOT / "trends.js"


def main():
    print("📈 generate_trends.py\n")

    print("[1/2] Running oat-public-website generate_trends.py ...")
    result = subprocess.run(
        [sys.executable, "scripts/generate_trends.py"],
        cwd=PUB, capture_output=False
    )
    if result.returncode != 0:
        print("  ⚠️  Generator finished with errors")

    if not PUB_TRENDS_OUT.exists():
        raise FileNotFoundError(f"Expected output not found: {PUB_TRENDS_OUT}")

    print(f"\n[2/2] Copying → {OUT_FILE}")
    shutil.copy(PUB_TRENDS_OUT, OUT_FILE)

    # Count trends
    content = OUT_FILE.read_text(encoding="utf-8")
    count = content.count('tag:')
    print(f"  ✅ {count} trends written to trends.js")


if __name__ == "__main__":
    main()
