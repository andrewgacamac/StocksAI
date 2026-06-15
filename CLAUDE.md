# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Keep `arch.md` up to date
`arch.md` is the living architecture & project log. **Update it as part of any
change** to architecture, DB schema, data coverage, `stocksai/config.py`, or the
build/run process — including the "_Last updated:_" date and the "Data
downloaded" table (sync with `python main.py status`). A change isn't done until
`arch.md` reflects it. Read `arch.md` first for full context.

## Commands
All commands assume the venv is active (`source .venv/bin/activate`) or use
`.venv/bin/python`.

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# Pipeline (run in this order on a fresh DB)
python main.py update-universe              # build/refresh securities catalog
python main.py backfill-daily              # full historical daily load
python main.py backfill-hourly             # full historical hourly load
python main.py refresh-daily               # cheap incremental top-up (nightly)
python main.py refresh-hourly
python main.py status                       # row counts + load_log summary

# Useful flags for any backfill/refresh
--limit N        # process only first N symbols (always smoke-test with --limit 50 first)
--no-resume      # reprocess symbols already marked 'ok' (needed after widening a history window)

# Inspect data (browser UI at http://localhost:4213/)
duckdb -ui data/stocks.duckdb
```

There is no test suite or linter configured. Verify changes by running a loader
with `--limit 50` and checking `python main.py status`.

## Architecture (big picture)
A single-file DuckDB ETL pipeline. Two upstream sources feed one catalog that
drives the price loaders — see `arch.md` for the full schema and rationale.

- **`universe.py`** builds the `securities` catalog from NASDAQ Trader's daily
  symbol directory. This is essential because **yfinance cannot enumerate
  tickers** — it only fetches symbols you already know.
- **`securities.symbol` is the canonical Yahoo-format ticker** and is used
  directly as the yfinance ticker by the loaders (no remapping). Normalization
  from NASDAQ format happens once in `symbols.py` (`.`→`-`, `$`→`-P`).
- **`loaders.py`** drives both daily and hourly via a shared `INTERVALS` dict and
  a single `_run()` path. Every load is **batched, throttled, resumable
  (via `load_log`), and idempotent (`INSERT ... ON CONFLICT` on the PK)**. The
  same `_run()` serves `backfill` (full window) and `refresh` (short lookback).
- **`prices.py`** does the yfinance download (`auto_adjust=False`) and reshapes
  the wide (ticker, field) frame into long form for insertion.

## Critical conventions & gotchas
- **Single writer at a time.** DuckDB allows only one read-write connection. A
  loader will fail if the UI/CLI holds `data/stocks.duckdb` open. Check with
  `lsof data/stocks.duckdb`; stop the UI before running a loader.
- **Indicators/returns must use `adj_close`, not raw `close`.** Raw OHLC is
  stored unadjusted (so splits show as price jumps); `adj_close` is split/
  dividend-adjusted. Computing on raw `close` produces false crossover signals.
- **Widening a history window** = edit `DAILY_PERIOD`/`HOURLY_PERIOD` in
  `config.py`, then run the backfill with `--no-resume` (resume would skip all
  already-loaded symbols). Reloads are idempotent — overlapping rows upsert, no
  duplicates.
- **Python 3.9 runtime.** Use `from __future__ import annotations` in any module
  using `X | None` union annotations (PEP 604 isn't runtime-supported on 3.9).
- **Background runs:** prefix long backfills with `PYTHONUNBUFFERED=1` so the
  `[interval] batch N/M` progress lines stream instead of buffering.
- **`empty` in `load_log` is normal**, not an error — warrants/units/thin
  preferreds that Yahoo doesn't carry.
- **`data/` and `.venv/` are gitignored.** Only code is committed; the ~2.4 GB
  database never goes to GitHub.
