"""
200-Day Moving Average Scanner
===============================
Scans the S&P 500 and Nasdaq-100 constituents and finds tickers currently
trading within a chosen percentage of their 200-day simple moving average.

Writes results to a JSON file (default: scan_results.json) that the
companion dashboard.html reads and displays.

Usage:
    python scan.py --threshold 5.0 --output scan_results.json

Requires internet access to:
    - en.wikipedia.org      (constituent lists)
    - query1/2.finance.yahoo.com (price history, via yfinance)
"""
import argparse
import io
import json
import sys
from datetime import datetime, timezone

import pandas as pd
import requests
import yfinance as yf

SP500_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NASDAQ100_WIKI_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"

# Wikipedia returns HTTP 403 for requests that don't look like a real browser
# (Python's default urllib User-Agent gets blocked). Spoofing a normal
# browser User-Agent here fixes it.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def fetch_tables(url: str):
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return pd.read_html(io.StringIO(resp.text))


def get_sp500_constituents() -> pd.DataFrame:
    tables = fetch_tables(SP500_WIKI_URL)
    df = tables[0].rename(columns={"Symbol": "symbol", "Security": "name"})
    df["symbol"] = df["symbol"].astype(str).str.replace(".", "-", regex=False)
    df["index"] = "S&P 500"
    return df[["symbol", "name", "index"]]


def _flatten_col(c) -> str:
    if isinstance(c, tuple):
        parts = [str(x) for x in c if x and "Unnamed" not in str(x)]
        return " ".join(parts) if parts else str(c[0])
    return str(c)


def get_nasdaq100_constituents() -> pd.DataFrame:
    tables = fetch_tables(NASDAQ100_WIKI_URL)

    candidates = []
    for t in tables:
        flat_cols = [_flatten_col(c).strip().lower() for c in t.columns]
        # Substring match (not exact) so footnote markers like "Ticker[a]"
        # still match. Wikipedia's Nasdaq-100 page also has a smaller
        # "recent index changes" table with its own Ticker column, so we
        # collect every match and pick the biggest one below rather than
        # just the first.
        if any("ticker" in c or "symbol" in c for c in flat_cols):
            t = t.copy()
            t.columns = flat_cols
            candidates.append(t)

    if not candidates:
        raise RuntimeError("Could not locate the Nasdaq-100 constituents table on Wikipedia")

    df = max(candidates, key=len)

    rename_map = {}
    for c in df.columns:
        if "ticker" in c or "symbol" in c:
            rename_map[c] = "symbol"
        elif "company" in c or "security" in c or c == "name":
            rename_map[c] = "name"
    df = df.rename(columns=rename_map)
    df["symbol"] = df["symbol"].astype(str).str.replace(".", "-", regex=False)
    df["index"] = "Nasdaq-100"
    return df[["symbol", "name", "index"]]


def build_universe() -> pd.DataFrame:
    combined = pd.concat(
        [get_sp500_constituents(), get_nasdaq100_constituents()], ignore_index=True
    )
    grouped = (
        combined.groupby("symbol")
        .agg({"name": "first", "index": lambda vals: " + ".join(sorted(set(vals)))})
        .reset_index()
    )
    return grouped


def fetch_price_history(symbols, period="300d"):
    return yf.download(
        symbols,
        period=period,
        interval="1d",
        group_by="ticker",
        threads=True,
        progress=False,
        auto_adjust=True,
    )


def compute_signals(universe_df: pd.DataFrame, price_data, threshold_pct: float):
    results = []
    multi = len(universe_df) > 1

    for _, row in universe_df.iterrows():
        symbol = row["symbol"]
        try:
            closes = (price_data[symbol]["Close"] if multi else price_data["Close"]).dropna()
        except (KeyError, TypeError):
            continue

        if len(closes) < 200:
            continue

        ma200 = closes.rolling(window=200).mean().iloc[-1]
        last_close = closes.iloc[-1]

        if pd.isna(ma200) or ma200 == 0:
            continue

        pct_diff = (last_close - ma200) / ma200 * 100
        if abs(pct_diff) <= threshold_pct:
            results.append(
                {
                    "symbol": symbol,
                    "name": row["name"],
                    "index": row["index"],
                    "last_close": round(float(last_close), 2),
                    "ma200": round(float(ma200), 2),
                    "pct_diff": round(float(pct_diff), 2),
                    "position": "above" if pct_diff >= 0 else "below",
                }
            )

    results.sort(key=lambda r: abs(r["pct_diff"]))
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Scan S&P 500 + Nasdaq-100 for stocks near their 200-day MA"
    )
    parser.add_argument("--threshold", type=float, default=5.0,
                         help="Percent distance from the 200-day MA to include (default: 5.0)")
    parser.add_argument("--output", type=str, default="scan_results.json",
                         help="Output JSON path (default: scan_results.json)")
    args = parser.parse_args()

    print("Building ticker universe from S&P 500 + Nasdaq-100...", file=sys.stderr)
    universe = build_universe()
    symbols = universe["symbol"].tolist()
    print(f"{len(symbols)} unique tickers. Downloading price history...", file=sys.stderr)

    price_data = fetch_price_history(symbols)

    print("Computing 200-day MA signals...", file=sys.stderr)
    results = compute_signals(universe, price_data, args.threshold)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "threshold_pct": args.threshold,
        "universe_size": len(symbols),
        "matches": results,
    }

    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    print(
        f"Done. {len(results)} tickers within {args.threshold}% of their 200-day MA. "
        f"Written to {args.output}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
