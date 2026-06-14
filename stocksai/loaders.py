"""Backfill and incremental refresh for the daily and hourly OHLCV tables.

Shared properties for every load (the loader "contract"):
  * Batched      - ~100 tickers per yfinance request.
  * Throttled    - a politeness sleep between batches; backoff retry on failure.
  * Resumable    - per-symbol progress recorded in `load_log`; backfills skip
                   symbols already completed so a crash resumes, not restarts.
  * Idempotent   - INSERT ... ON CONFLICT against the primary key, so re-runs
                   never duplicate rows and only newer bars are effectively added.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from . import config
from .db import connect, init_schema
from .prices import chunked, fetch_batch

# Per-interval metadata so one code path serves both tables.
INTERVALS = {
    "daily": {
        "table": "ohlcv_daily",
        "time_col": "date",
        "interval": config.DAILY_INTERVAL,
        "backfill_period": config.DAILY_PERIOD,
        "refresh_period": "5d",
        "columns": ["symbol", "date", "open", "high", "low",
                    "close", "adj_close", "volume"],
    },
    "hourly": {
        "table": "ohlcv_hourly",
        "time_col": "ts",
        "interval": config.HOURLY_INTERVAL,
        "backfill_period": config.HOURLY_PERIOD,
        "refresh_period": "5d",
        "columns": ["symbol", "ts", "open", "high", "low", "close", "volume"],
    },
}


def _active_symbols(con) -> list[str]:
    rows = con.execute(
        "SELECT symbol FROM securities WHERE is_active ORDER BY symbol"
    ).fetchall()
    return [r[0] for r in rows]


def _completed_symbols(con, interval: str) -> set[str]:
    rows = con.execute(
        "SELECT symbol FROM load_log WHERE interval = ? AND status = 'ok'",
        [interval],
    ).fetchall()
    return {r[0] for r in rows}


def _upsert_prices(con, meta: dict, long: pd.DataFrame) -> None:
    cols = meta["columns"]
    # Normalize intraday timestamps to naive US/Eastern wall-clock.
    if meta["time_col"] == "ts" and not long.empty:
        ts = pd.to_datetime(long["ts"])
        if getattr(ts.dt, "tz", None) is not None:
            ts = ts.dt.tz_convert("America/New_York").dt.tz_localize(None)
        long = long.assign(ts=ts)

    staging = long.reindex(columns=cols)
    con.register("staging", staging)
    key = "(symbol, date)" if meta["time_col"] == "date" else "(symbol, ts)"
    updates = ", ".join(f"{c} = excluded.{c}" for c in cols[2:])
    con.execute(
        f"""
        INSERT INTO {meta['table']} ({', '.join(cols)})
        SELECT {', '.join(cols)} FROM staging
        ON CONFLICT {key} DO UPDATE SET {updates}
        """
    )
    con.unregister("staging")


def _log(con, interval: str, rows: list[dict]) -> None:
    if not rows:
        return
    df = pd.DataFrame(rows)
    con.register("log_staging", df)
    con.execute(
        """
        INSERT INTO load_log AS l
            (symbol, interval, last_loaded, status, error, updated_at)
        SELECT symbol, interval, last_loaded, status, error, updated_at
        FROM log_staging
        ON CONFLICT (symbol, interval) DO UPDATE SET
            last_loaded = excluded.last_loaded,
            status      = excluded.status,
            error       = excluded.error,
            updated_at  = excluded.updated_at
        """
    )
    con.unregister("log_staging")


def _run(interval: str, period: str, symbols: list[str]) -> dict:
    meta = INTERVALS[interval]
    time_col = meta["time_col"]
    total_rows = 0
    n_ok = n_empty = n_error = 0

    con = connect()
    try:
        init_schema(con)
        batches = list(chunked(symbols, config.BATCH_SIZE))
        for i, batch in enumerate(batches, 1):
            print(f"[{interval}] batch {i}/{len(batches)} ({len(batch)} symbols)...")
            long = fetch_batch(batch, period, meta["interval"])
            now = datetime.now()
            log_rows: list[dict] = []

            if long is None:  # whole batch failed after retries
                n_error += len(batch)
                for sym in batch:
                    log_rows.append({
                        "symbol": sym, "interval": interval,
                        "last_loaded": None, "status": "error",
                        "error": "batch download failed", "updated_at": now,
                    })
            else:
                if not long.empty:
                    _upsert_prices(con, meta, long)
                    total_rows += len(long)
                returned = set(long["symbol"]) if not long.empty else set()
                last_per_symbol = (
                    long.groupby("symbol")[time_col].max() if not long.empty
                    else pd.Series(dtype="datetime64[ns]")
                )
                for sym in batch:
                    if sym in returned:
                        n_ok += 1
                        log_rows.append({
                            "symbol": sym, "interval": interval,
                            "last_loaded": pd.to_datetime(last_per_symbol[sym]),
                            "status": "ok", "error": None, "updated_at": now,
                        })
                    else:
                        n_empty += 1
                        log_rows.append({
                            "symbol": sym, "interval": interval,
                            "last_loaded": None, "status": "empty",
                            "error": None, "updated_at": now,
                        })

            _log(con, interval, log_rows)
            if i < len(batches):
                import time as _time
                _time.sleep(config.SLEEP_BETWEEN_BATCHES)
    finally:
        con.close()

    summary = {"rows": total_rows, "ok": n_ok, "empty": n_empty, "error": n_error}
    print(f"[{interval}] done: {summary}")
    return summary


def backfill(interval: str, limit: int | None = None, resume: bool = True) -> dict:
    """One-time historical load over the full configured window."""
    meta = INTERVALS[interval]
    con = connect()
    try:
        init_schema(con)
        symbols = _active_symbols(con)
        done = _completed_symbols(con, interval) if resume else set()
    finally:
        con.close()

    pending = [s for s in symbols if s not in done]
    if limit is not None:
        pending = pending[:limit]
    print(f"[{interval}] backfill: {len(pending)} symbols "
          f"({len(done)} already complete, skipped)")
    return _run(interval, meta["backfill_period"], pending)


def refresh(interval: str, limit: int | None = None) -> dict:
    """Cheap incremental top-up: fetch a short recent window and upsert."""
    meta = INTERVALS[interval]
    con = connect()
    try:
        init_schema(con)
        symbols = _active_symbols(con)
    finally:
        con.close()

    if limit is not None:
        symbols = symbols[:limit]
    print(f"[{interval}] refresh: {len(symbols)} symbols")
    return _run(interval, meta["refresh_period"], symbols)
