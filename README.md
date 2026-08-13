# 200-Day MA Scanner

Scans the S&P 500 and Nasdaq-100 for tickers trading within 5% of their
200-day moving average, and shows them in `dashboard.html`.

## How it fits together

- **`scan.py`** — pulls constituent lists (Wikipedia), downloads ~300 days
  of price history for each ticker (via `yfinance`), computes each one's
  200-day SMA and % distance from it, and writes `scan_results.json`.
- **`dashboard.html`** — a standalone page that reads `scan_results.json`
  and displays a sortable, filterable, searchable table. Open it in any
  browser — no build step, no server required.
- **`scan-workflow.yml`** — a GitHub Actions workflow that runs `scan.py`
  twice a day on weekdays and commits the refreshed JSON automatically,
  so the dashboard stays current without you running anything by hand.

Right now `scan_results.json` has **sample/placeholder data** (clearly
labeled as such in the dashboard) so you can see how it looks before
running a real scan.

## Option A — run it locally (fastest way to test)

```bash
pip install -r requirements.txt
python scan.py --threshold 5.0
```

Then open `dashboard.html` directly in your browser — it will pick up
the freshly written `scan_results.json` automatically. To refresh twice
a day on your own machine, add two entries to your crontab
(`crontab -e`, times in your local timezone, adjusted for US market
hours):

```
15 22 * * 1-5  cd /path/to/ma200-scanner && python scan.py
45 3  * * 2-6  cd /path/to/ma200-scanner && python scan.py
```

(Example above assumes Singapore time, UTC+8 — 10:15am/3:45pm ET lands
at 10:15pm and 3:45am SGT. Adjust for your own timezone and for US
daylight saving.)

## Option B — free, fully automated, always-on (recommended)

This runs the twice-daily scan in the cloud for free and hosts the
dashboard as a public webpage, with nothing running on your own
computer:

1. Create a new **public** GitHub repo and push these files to it.
2. Move `scan-workflow.yml` to `.github/workflows/scan.yml` (the nested
   folder path matters — GitHub only picks up workflows there).
3. In the repo's **Settings → Actions → General → Workflow permissions**,
   select "Read and write permissions" (so the workflow can commit the
   updated JSON).
4. In **Settings → Pages**, set the source to "Deploy from branch" →
   `main` → `/ (root)`. GitHub will give you a URL like
   `https://yourusername.github.io/ma200-scanner/dashboard.html`.
5. That's it. The workflow runs automatically twice a day on weekdays
   (see the cron schedule inside the file) and updates the page. You
   can also trigger it manually any time from the repo's **Actions** tab.

## Customizing

- **Change the threshold:** edit `--threshold 5.0` in `scan-workflow.yml`
  (or pass `--threshold X` locally).
- **Use the full Nasdaq Composite instead of Nasdaq-100:** the Nasdaq-100
  is ~100 large tickers; swapping in the full Composite (~3,000+ tickers)
  means a different constituent source and a longer download — ask if
  you'd like this version built out.
- **Add other indexes** (Dow, Russell 2000, etc.): add another
  `get_x_constituents()` function following the same pattern and include
  it in `build_universe()`.
- **Switch to EMA instead of SMA:** replace `.rolling(window=200).mean()`
  with `.ewm(span=200).mean()` in `compute_signals()`.

## Notes and caveats

- `yfinance` is a free, unofficial wrapper around Yahoo Finance's data.
  It's reliable for this kind of use but isn't a licensed/paid data feed
  — if you ever depend on this for real trading decisions, consider a
  paid provider (e.g. Financial Modeling Prep, Polygon.io) for
  guaranteed uptime and accuracy.
- Wikipedia's constituent tables are community-maintained and usually
  accurate but can lag official index changes by a few days.
- This tool surfaces a technical pattern; it isn't investment advice,
  and being near the 200-day MA doesn't by itself indicate whether a
  stock is a buy or sell.
