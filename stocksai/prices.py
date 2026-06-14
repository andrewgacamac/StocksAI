"""Batched, retrying price downloads from Yahoo Finance via yfinance.

All functions return data in *long* (tidy) format so it can be inserted straight
into the OHLCV tables. Raw OHLC is preserved (auto_adjust=False); the adjusted
close is kept separately as `adj_close`.
"""

import time
from typing import Iterable, Iterator, Optional

import pandas as pd
import yfinance as yf

from . import config


def chunked(items: list[str], size: int) -> Iterator[list[str]]:
    """Yield successive `size`-length chunks from a list."""
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _to_long(df: pd.DataFrame, symbols: list[str], interval: str) -> pd.DataFrame:
    """Reshape yfinance's wide (ticker, field) frame into long form."""
    if df is None or df.empty:
        return pd.DataFrame()

    # With a single ticker yfinance returns flat columns; add the ticker level
    # so the reshape logic below is uniform.
    if not isinstance(df.columns, pd.MultiIndex):
        df = pd.concat({symbols[0]: df}, axis=1)

    time_name = "ts" if interval == config.HOURLY_INTERVAL else "date"
    long = (
        df.stack(level=0, future_stack=True)
        .rename_axis(index=[time_name, "symbol"])
        .reset_index()
    )
    long.columns = [str(c).lower().replace(" ", "_") for c in long.columns]
    long = long.dropna(subset=["close"])
    return long


def _download_once(symbols: list[str], period: str, interval: str) -> pd.DataFrame:
    raw = yf.download(
        symbols,
        period=period,
        interval=interval,
        group_by="ticker",
        auto_adjust=False,
        actions=False,
        threads=True,
        progress=False,
    )
    return _to_long(raw, symbols, interval)


def fetch_batch(
    symbols: list[str], period: str, interval: str
) -> Optional[pd.DataFrame]:
    """Download one batch with exponential-backoff retry.

    Returns a long-format DataFrame, or None if every attempt failed.
    """
    delay = config.RETRY_BACKOFF
    last_err: Optional[Exception] = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return _download_once(symbols, period, interval)
        except Exception as err:  # noqa: BLE001 - yfinance raises many types
            last_err = err
            if attempt < config.MAX_RETRIES:
                time.sleep(delay)
                delay *= 2
    print(f"  ! batch failed after {config.MAX_RETRIES} attempts: {last_err}")
    return None
