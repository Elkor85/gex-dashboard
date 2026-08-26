# GEX Dashboard

Live options-flow analytics (GEXBot-style) built on **yfinance** data, hosted free on **GitHub Pages**.

![tickers](https://img.shields.io/badge/tickers-GLD%20SLV%20SPX%20QQQ%20SPY%20IBIT%20ETHA%20NVDA%20TSLA-blue)

## What it shows

Per ticker:
- **GEX by strike** ($ per 1% move) + Call Wall / Put Wall
- **Zero Gamma** level
- **DEX** (delta exposure), **VEX** (vanna exposure), **Theta exposure**
- **IV & Volume** per strike
- **Net GEX by expiration**
- Strike table sorted by Open Interest

Greeks are computed via **Black-Scholes** from the IVs quoted by Yahoo
(Yahoo's chain API no longer returns gamma/delta columns).

## Tickers

`GLD, SLV, SPX, QQQ, SPY, IBIT, ETHA, NVDA, TSLA`

> Note: Yahoo has no SPX options chain, so SPX uses the SPY chain as a proxy.

## Run locally

```bash
pip install -r scripts/requirements.txt
python scripts/fetch_gex.py          # writes docs/data/gex_data.json
python -m http.server 8765 --directory docs
# open http://localhost:8765
```

## Deploy to GitHub Pages (free)

1. Create a GitHub repo and push this folder:
   ```bash
   git init && git add . && git commit -m "initial"
   git remote add origin https://github.com/<you>/gex-dashboard.git
   git push -u origin main
   ```
2. Repo → **Settings → Pages → Source: Deploy from branch → `main` / `/docs`**
3. The included GitHub Action (`.github/workflows/update.yml`) refreshes the
   data every **5 minutes during US market hours** (13:30–20:00 UTC, Mon–Fri),
   plus manually from the *Actions* tab.
4. Your site: `https://<you>.github.io/gex-dashboard/`

## Notes

- GitHub Actions cron minimum interval is 5 min (3 min is not possible); runs can be delayed a few minutes at peak times.
- The page also re-fetches its JSON every 2 minutes while open.
- Dealer-positioning assumption: customers long calls / short puts (standard naive GEX).
