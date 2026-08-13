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
NASDAQ100_WIKI_URL =
