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


NASDAQ100_URL = "https://www.slickcharts.com/nasdaq100"


def get_nasdaq100_constituents() -> pd.DataFrame:
    tables = fetch_tables(NASDAQ100_URL)

    df = None
    for t in tables:
        cols = [str(c).strip().lower() for c in t.columns]
        if "symbol" in cols and "company" in cols:
            t = t.copy()
            t.columns = cols
            df = t
            break

    if df is None:
        raise RuntimeError("Could not locate the Nasdaq-100 constituents table on Slickcharts")

    df = df.rename(columns={"company": "name"})
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper().str.replace(".", "-", regex=False)
    df["name"] = df["name"].astype(str).str.strip()
    df = df[df["symbol"].str.match(r"^[A-Z]{1,6}(-[A-Z])?$")]
    df["index"] = "Nasdaq-100"
    return df[["symbol", "name", "index"]].drop_duplicates(subset="symbol")


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


def fetch_price_history(symbols, period="420d"):
    return yf.download(
        symbols,
        period=period,
        interval="1d",
        group_by="ticker",
        threads=True,
        progress=False,
        auto_adjust=True,
    )


def compute_avwap_anchors(sub: pd.DataFrame, lookback: int = 252):
    """Anchored VWAP from the 52-week high and the 52-week low.

    AVWAP tracks the average price paid by everyone who's bought since a
    specific anchor date (rather than resetting daily like normal VWAP).
    Price above the anchored VWAP suggests buyers since that anchor are
    sitting on a profit (support); below suggests they're underwater
    (resistance).
    """
    try:
        df = sub[["High", "Low", "Close", "Volume"]].dropna()
    except (KeyError, TypeError):
        return None

    if len(df) < 20:
        return None

    window = df.iloc[-lookback:] if len(df) > lookback else df
    high_idx = window["High"].idxmax()
    low_idx = window["Low"].idxmin()

    def avwap_from(anchor_idx):
        seg = df.loc[anchor_idx:]
        total_vol = seg["Volume"].sum()
        if total_vol == 0:
            return None
        return float((seg["Close"] * seg["Volume"]).sum() / total_vol)

    last_close = float(df["Close"].iloc[-1])
    result = {
        "week52_high": round(float(window["High"].max()), 2),
        "week52_high_date": pd.Timestamp(high_idx).strftime("%Y-%m-%d"),
        "week52_low": round(float(window["Low"].min()), 2),
        "week52_low_date": pd.Timestamp(low_idx).strftime("%Y-%m-%d"),
    }

    avwap_high = avwap_from(high_idx)
    if avwap_high:
        result["avwap_from_high"] = round(avwap_high, 2)
        result["avwap_from_high_diff_pct"] = round((last_close - avwap_high) / avwap_high * 100, 2)

    avwap_low = avwap_from(low_idx)
    if avwap_low:
        result["avwap_from_low"] = round(avwap_low, 2)
        result["avwap_from_low_diff_pct"] = round((last_close - avwap_low) / avwap_low * 100, 2)

    return result


def compute_signals(universe_df: pd.DataFrame, price_data, threshold_pct: float):
    results = []
    multi = len(universe_df) > 1

    for _, row in universe_df.iterrows():
        symbol = row["symbol"]
        try:
            sub = price_data[symbol] if multi else price_data
        except (KeyError, TypeError):
            continue

        try:
            closes = sub["Close"].dropna()
        except (KeyError, TypeError):
            continue

        if len(closes) < 200:
            continue

        ma200 = closes.rolling(window=200).mean().iloc[-1]
        last_close = closes.iloc[-1]

        if pd.isna(ma200) or ma200 == 0:
            continue

        pct_diff = (last_close - ma200) / ma200 * 100
        if abs(pct_diff) > threshold_pct:
            continue

        entry = {
            "symbol": symbol,
            "name": row["name"],
            "index": row["index"],
            "last_close": round(float(last_close), 2),
            "ma200": round(float(ma200), 2),
            "pct_diff": round(float(pct_diff), 2),
            "position": "above" if pct_diff >= 0 else "below",
        }

        avwap = compute_avwap_anchors(sub)
        if avwap:
            entry.update(avwap)

        results.append(entry)

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
