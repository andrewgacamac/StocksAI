# StocksAI — Architecture & Project Log

> ⚠️ **KEEP THIS FILE UP TO DATE.** This document must be updated **every time**
> the project's architecture, database schema, data coverage, configuration, or
> build/run process changes. Treat updating `arch.md` as part of the change
> itself — a change is not "done" until this file reflects it. When in doubt,
> update it.

_Last updated: 2026-06-14_

## 1. Purpose
StocksAI is an ETL pipeline that maintains the **entire NYSE + NASDAQ universe of
stocks and ETFs listed today**, with daily and hourly OHLCV price history, stored
in a single embedded **DuckDB** database. It is designed for research and
backtesting.

## 2. Tech stack
- **Python 3.9.6** in a local virtualenv (`.venv/`)
- **duckdb** (Python lib 1.4.4) — embedded analytical database
- **yfinance** — Yahoo Finance price downloads
- **pandas**, **requests**
- **DuckDB CLI 1.5.3** (Homebrew, `/opt/homebrew/bin/duckdb`) — used for the
  browser UI (`duckdb -ui`)

## 3. Data sources
- **Universe (which tickers exist):** NASDAQ Trader daily symbol directory —
  `nasdaqlisted.txt` (NASDAQ) and `otherlisted.txt` (NYSE / NYSE American /
  NYSE Arca / Cboe / IEX). Republished every trading day; carries ETF, test-issue,
  and financial-status flags. Required because yfinance cannot enumerate tickers.
- **Prices:** Yahoo Finance via `yfinance` (raw OHLC, `auto_adjust=False`,
  `actions=False`).

## 4. Database schema (`data/stocks.duckdb`)
- **`securities`** (dimension): `symbol` PK (Yahoo form), `source_symbol`
  (NASDAQ form), `name`, `exchange`, `is_etf`, `market_category`,
  `financial_status`, `is_active`, `first_seen`, `last_seen`, `updated_at`.
- **`ohlcv_daily`**: `symbol`, `date`, `open`, `high`, `low`, `close` (raw),
  `adj_close`, `volume`. PK `(symbol, date)`.
- **`ohlcv_hourly`**: `symbol`, `ts` (US/Eastern wall-clock), `open`, `high`,
  `low`, `close`, `volume`. PK `(symbol, ts)`.
- **`load_log`** (checkpoint): `symbol`, `interval`, `last_loaded`, `status`
  (`ok`/`empty`/`error`), `error`, `updated_at`. PK `(symbol, interval)`.

Design choice: store **raw OHLC + a separate `adj_close`** so raw prices stay
append-stable while adjusted close is available for return/indicator math.

## 5. Code layout
```
stocksai/
  __init__.py
  config.py    # history windows + loader tuning constants
  db.py        # connect() + init_schema() (CREATE TABLE IF NOT EXISTS)
  symbols.py   # NASDAQ -> Yahoo symbol normalization
  universe.py  # download/parse NASDAQ Trader files -> upsert securities
  prices.py    # batched yf.download with backoff retry; wide -> long reshape
  loaders.py   # backfill/refresh for daily & hourly (resumable, idempotent)
main.py        # argparse CLI dispatch
```

## 6. CLI commands
- `python main.py update-universe` — refresh `securities`
- `python main.py backfill-daily [--limit N] [--no-resume]`
- `python main.py refresh-daily [--limit N]`
- `python main.py backfill-hourly [--limit N] [--no-resume]`
- `python main.py refresh-hourly [--limit N]`
- `python main.py status` — row counts + load_log summary

## 7. Loader contract (both intervals)
- **Batched:** ~100 tickers per `yf.download` request.
- **Throttled:** sleep between batches; exponential-backoff retry (4 attempts).
- **Resumable:** per-symbol progress in `load_log`; backfills skip completed
  symbols (unless `--no-resume`).
- **Idempotent:** `INSERT ... ON CONFLICT` on the PK — re-runs never duplicate.
- **Symbol normalization:** `.`→`-` (share classes, BRK.A→BRK-A) and `$`→`-P`
  (preferred shares, ABR$D→ABR-PD).
- **Backfill vs refresh:** backfill = full window; refresh = short recent
  lookback + upsert.

## 8. Current configuration (`stocksai/config.py`)
- `DAILY_PERIOD = "10y"`, `DAILY_INTERVAL = "1d"`
- `HOURLY_PERIOD = "1y"`, `HOURLY_INTERVAL = "1h"`
- `BATCH_SIZE = 100`, `MAX_RETRIES = 4`, `RETRY_BACKOFF = 2.0`,
  `SLEEP_BETWEEN_BATCHES = 1.0`

## 9. Data downloaded (as of 2026-06-14)
| Table | Rows | Symbols | Coverage |
|---|---|---|---|
| securities (active) | 12,770 | — | listed today |
| ohlcv_daily | 18,073,373 | 12,641 | 10 years (2016-06-13 → 2026-06-12) |
| ohlcv_hourly | 15,717,903 | 12,576 | 1 year (2025-06-13 → 2026-06-12) |

**Database file size: ~2.4 GB** (`data/stocks.duckdb`, gitignored).

## 10. Build history (what we did)
1. Created `.venv`; installed duckdb, yfinance, pandas, requests.
2. Prototype `main.py` (3 hardcoded tickers) — later replaced.
3. Git repo initialized; pushed to `https://github.com/andrewgacamac/StocksAI`.
4. Designed the 3-table + `load_log` architecture.
5. Built the `stocksai` package and CLI.
6. Loaded the universe → 12,770 active securities.
7. Daily backfill, widened in stages (idempotent reloads): 1y → 2y → 7y → 10y.
8. Hourly backfill: 50-symbol sample (1mo) → full universe (1y).
9. Installed DuckDB CLI (Homebrew) for the browser UI.

## 11. Git state
- Pipeline code committed (`1f6d0f5`).
- `stocksai/config.py` window changes (10y/1y) **uncommitted**.
- Latest changes **not yet pushed** to GitHub.
- `.venv/` and `data/` are gitignored (data never goes to GitHub).

## 12. Known limitations
- **Survivorship bias:** universe = currently-listed only; delisted/bankrupt
  names are absent (backtests will look optimistic).
- **Empty symbols:** ~130–195 per table are warrants/units/thin preferreds
  Yahoo doesn't carry (logged `empty`, not failures).
- **Hourly = regular session only** (09:30–16:00 ET; no pre/post-market).
- **`adj_close` freshness:** only correct as of the last full backfill; a new
  split makes historical `adj_close` stale until a full reload.
- **No explicit corporate-actions tables yet** (`actions=False`) — split/dividend
  events are not separately recorded; only their net effect via `adj_close`.
- **Incremental refresh** uses a fixed recent lookback; it does not hunt for
  interior history gaps.

## 13. Operating notes
- DuckDB is embedded — nothing to "start/stop." A connection opens the file;
  closing it releases it.
- **Single writer at a time:** don't run a loader while the UI/CLI holds the
  file open for writing. Check with `lsof data/stocks.duckdb`.
- Browser UI: `duckdb -ui data/stocks.duckdb` → http://localhost:4213/.

## 14. Planned / under discussion (not yet built)
- **Technical indicators** (SMA 50/200, etc.) via **SQL views** over
  `ohlcv_daily` (computed on `adj_close`, trading-day windows). Views add zero
  storage and recompute in seconds; a materialized table is an opt-in later for
  hot backtest paths. Scope (indicator set, daily-only vs daily+hourly) TBD.
- **Corporate-actions tracking** (splits & dividends via `actions=True`) —
  deferred ("revisit later").
