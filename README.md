# StocksAI

An ETL pipeline that maintains the **entire NYSE + NASDAQ universe of stocks and
ETFs listed today**, with daily and hourly OHLCV history, in a single DuckDB file.

## Architecture

Two upstream sources feed one catalog that drives the price loaders:

```
NASDAQ Trader symbol directory ──▶ securities  (WHO is listed today)
                                       │ active symbols
Yahoo Finance (yfinance) ──────────────┴──▶ ohlcv_daily   (1 year)
                                            ohlcv_hourly  (1 month)
                                            load_log      (per-symbol progress)
```

- **`securities`** — one row per stock/ETF: name, exchange, ETF flag, active flag,
  first/last seen. Built from NASDAQ Trader's daily directory (yfinance cannot
  list tickers itself).
- **`ohlcv_daily`** — raw OHLC + `adj_close`, PK `(symbol, date)`.
- **`ohlcv_hourly`** — OHLCV at US/Eastern market time, PK `(symbol, ts)`.
- **`load_log`** — checkpoint table making backfills resumable.

Every loader is **batched, throttled, resumable, and idempotent** — re-running
only adds newer bars and never duplicates rows. History windows live in
`stocksai/config.py` (`DAILY_PERIOD`, `HOURLY_PERIOD`); widening them is a
one-line change plus a backfill rerun.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
python main.py update-universe          # refresh the securities catalog
python main.py backfill-daily           # one-time daily history load
python main.py backfill-hourly          # one-time hourly history load
python main.py refresh-daily            # cheap incremental top-up (run nightly)
python main.py refresh-hourly
python main.py status                   # row counts + load_log summary
```

Add `--limit N` to any backfill/refresh to process only the first N symbols
(useful for testing). Backfills resume by default; pass `--no-resume` to
reprocess completed symbols.

### First run

```bash
python main.py update-universe
python main.py backfill-daily --limit 50   # smoke-test on a sample first
python main.py backfill-daily              # then the full ~12.7k universe
python main.py backfill-hourly
```

## Inspecting the data (DuckDB UI)

```bash
duckdb -ui data/stocks.duckdb   # browser UI at http://localhost:4213
```

⚠️ DuckDB allows a single writer at a time — don't run a loader while the UI (or
another writer) holds the database open.

## Known limitations

- Incremental refresh uses a fixed recent lookback window + upsert; it does not
  actively hunt for interior gaps in history.
- `adj_close` shifts after corporate actions; raw OHLC is append-stable, but
  `adj_close` is only as fresh as the last load that touched each row.
