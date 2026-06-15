# StocksAI — Architecture & Project Log

> ⚠️ **KEEP THIS FILE UP TO DATE.** This document must be updated **every time**
> the project's architecture, database schema, data coverage, configuration, or
> build/run process changes. Treat updating `arch.md` as part of the change
> itself — a change is not "done" until this file reflects it. When in doubt,
> update it.

_Last updated: 2026-06-14 (indicator views + definitions + charts.py/plot command)_

## 1. Purpose
StocksAI is an ETL pipeline that maintains the **entire NYSE + NASDAQ universe of
stocks and ETFs listed today**, with daily and hourly OHLCV price history, stored
in a single embedded **DuckDB** database. It is designed for research and
backtesting.

## 2. Tech stack
- **Python 3.9.6** in a local virtualenv (`.venv/`)
- **duckdb** (Python lib 1.4.4) — embedded analytical database
- **yfinance** — Yahoo Finance price downloads
- **pandas**, **requests**, **matplotlib** (charts)
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
  indicators.py# builds the v_indicators_daily SQL view (window functions)
  charts.py    # reusable matplotlib indicator charts for any symbol
main.py        # argparse CLI dispatch
```

## 6. CLI commands
- `python main.py update-universe` — refresh `securities`
- `python main.py backfill-daily [--limit N] [--no-resume]`
- `python main.py refresh-daily [--limit N]`
- `python main.py backfill-hourly [--limit N] [--no-resume]`
- `python main.py refresh-hourly [--limit N]`
- `python main.py create-indicators` — (re)create the indicator views
- `python main.py plot SYMBOL [--years N|--start --end] [--outdir DIR]` —
  render indicator charts (PNG) for a symbol
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
- Indicator params: `SMA_WINDOWS`, `EMA_SPANS`, `MACD_SIGNAL`, `RSI_PERIOD`,
  `BOLLINGER_WINDOW/K`, `STOCH_K/D`, `ATR_PERIOD`, `ROC_WINDOWS`, `HILO_WINDOW`,
  `EMA_LOOKBACK_MULT`.

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

## 12a. Technical indicators (live SQL views)
**Two live, non-materialized views** over `ohlcv_daily` (built by
`stocksai/indicators.py`, created via `init_schema` / `create-indicators`). They
store nothing; DuckDB recomputes on demand. All computed on **adjusted prices**
(`adj_close`; intraday high/low adjusted on the fly via each day's
`adj_close/close` factor).

- **`v_indicators_daily`** (cheap, window functions): `sma_20/50/200`, `rsi_14`,
  `roc_20/60/120`, `ret_1d`, Bollinger (`bb_mid/upper/lower/pctb/bandwidth`),
  `atr_14`, `stoch_k/d`, `vol_sma_20`, `obv`, `hi_252/lo_252`,
  `golden_cross`/`death_cross`/`above_sma_200`.
- **`v_ema_daily`** (separate by design): `ema_12/26`, `macd`, `macd_signal`,
  `macd_hist`. EMA uses a geometric-weighted `array_agg` window that is ~14x more
  expensive than a plain window agg, so it lives apart so it can't slow the main
  view. **Filter by symbol** → sub-100ms (predicate pushdown limits the heavy work
  to one symbol). A full-universe EMA scan is the slow path (~90s).

**Performance (measured, 18M daily rows):** filtered-by-symbol queries on either
view are sub-100ms (the normal backtest pattern). Full-universe screens on
`v_indicators_daily` are ~11s (live, zero storage). Window-friendly variants keep
it fast: Cutler's RSI (SMA of gains/losses), SMA-smoothed ATR, and EMA/MACD via
bounded-window exponential weighting (verified to match pandas `ewm` to many
decimals). Scope is daily only; an hourly view is a trivial follow-on.

### Indicator definitions
All on adjusted price `p = adj_close`; "N bars" = N trading days; `prev` = prior
bar. Moving values are NULL during their warm-up window.

| Column | Meaning | Definition |
|---|---|---|
| `sma_20/50/200` | Simple moving average | `AVG(p)` over last 20/50/200 bars |
| `ema_12/26` | Exponential moving average | span `s`, α=2/(s+1); geometric-weighted avg of last `EMA_LOOKBACK_MULT*s` bars (≈ true EMA) |
| `macd` | MACD line | `ema_12 − ema_26` |
| `macd_signal` | MACD signal line | 9-bar EMA of `macd` |
| `macd_hist` | MACD histogram | `macd − macd_signal` |
| `rsi_14` | Relative Strength Index (Cutler) | `100 − 100/(1+RS)`, `RS = AVG(gain,14)/AVG(loss,14)`; 0–100 |
| `roc_20/60/120` | Rate of change (%) | `(p / p[N bars ago] − 1) × 100` |
| `ret_1d` | 1-day return | `p / prev − 1` |
| `bb_mid` | Bollinger middle band | `sma_20` |
| `bb_upper` / `bb_lower` | Bollinger bands | `sma_20 ± BOLLINGER_K × stddev_samp(p,20)` |
| `bb_pctb` | %B (position in bands) | `(p − bb_lower)/(bb_upper − bb_lower)`; 0=lower,1=upper |
| `bb_bandwidth` | Band width (volatility) | `(bb_upper − bb_lower)/bb_mid` |
| `atr_14` | Average True Range (SMA variant) | `AVG(TR,14)`, `TR = max(high−low, |high−prev|, |low−prev|)` on adjusted H/L |
| `stoch_k` | Stochastic %K | `100×(p − min(low,14))/(max(high,14) − min(low,14))`, clamped 0–100 |
| `stoch_d` | Stochastic %D | `SMA(stoch_k, 3)` |
| `vol_sma_20` | Average volume | `AVG(volume)` over last 20 bars (raw volume) |
| `obv` | On-Balance Volume | running cumsum: `+volume` if `p>prev`, `−volume` if `p<prev`, else 0 |
| `hi_252` / `lo_252` | 52-week high / low | `max(p)` / `min(p)` over last 252 bars |
| `golden_cross` | SMA-50 crosses above SMA-200 | `sma_50>sma_200 AND prev_sma_50≤prev_sma_200` |
| `death_cross` | SMA-50 crosses below SMA-200 | `sma_50<sma_200 AND prev_sma_50≥prev_sma_200` |
| `above_sma_200` | Price above long-term trend | `p > sma_200` |

(Window lengths above are the current `config.py` defaults.)

## 13. Operating notes
- DuckDB is embedded — nothing to "start/stop." A connection opens the file;
  closing it releases it.
- **Single writer at a time:** don't run a loader while the UI/CLI holds the
  file open for writing. Check with `lsof data/stocks.duckdb`.
- Browser UI: `duckdb -ui data/stocks.duckdb` → http://localhost:4213/.

## 14. Planned / under discussion (not yet built)
- **Hourly indicator view** (`v_indicators_hourly`) — same pattern over
  `ohlcv_hourly`; add on request.
- **Wilder-exact** EMA/RSI/ATR and/or a materialized indicator table — only if a
  hot backtest path needs it.
- **Corporate-actions tracking** (splits & dividends via `actions=True`) —
  deferred ("revisit later").
