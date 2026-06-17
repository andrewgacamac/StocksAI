"""Reusable market screens over the indicator views.

Each screen returns a pandas DataFrame so it can be printed, charted, or piped
into other tools. Screens read the cheap `v_indicators_daily` view (fast,
full-universe), and use `securities.security_type` to keep results to real
operating-company stocks by default.
"""

from __future__ import annotations

import pandas as pd

from .db import connect
from .indicators import DAILY_VIEW


def strong_trend(
    months: int = 6,
    pct: float = 80.0,
    min_slope: float = 15.0,
    min_price: float = 5.0,
    min_vol: float = 100_000,
    stocks_only: bool = True,
    limit: int | None = None,
) -> pd.DataFrame:
    """Stocks in a strong, persistent uptrend.

    Qualifies a symbol when, over the last `months` months, its adjusted close was
    above SMA-50 and SMA-50 was above SMA-200 (stacked alignment) on at least
    `pct`% of trading days, the SMA-200 rose by at least `min_slope`% over the
    window, and it clears `min_price`/`min_vol` liquidity floors.
    """
    pct_frac = pct / 100.0
    slope_frac = min_slope / 100.0
    # ~21 trading days/month; require ~90% present to count as a full window.
    min_days = int(months * 21 * 0.9)
    type_filter = "AND s.security_type = 'stock'" if stocks_only else ""

    sql = f"""
    WITH w AS (
      SELECT symbol, date, adj_close, sma_50, sma_200, vol_sma_20
      FROM {DAILY_VIEW}
      WHERE date >= (SELECT max(date) - INTERVAL {int(months)} MONTH FROM ohlcv_daily)
        AND sma_50 IS NOT NULL AND sma_200 IS NOT NULL
    ),
    agg AS (
      SELECT symbol,
        count(*) AS n,
        count(*) FILTER (WHERE adj_close > sma_50 AND sma_50 > sma_200) AS n_strong,
        arg_max(adj_close, date)  AS last_px,
        arg_max(vol_sma_20, date) AS last_vol,
        arg_max(sma_200, date)    AS last_200,
        arg_min(sma_200, date)    AS first_200
      FROM w GROUP BY symbol
    )
    SELECT a.symbol, s.name,
           round(100.0 * n_strong / n, 1)             AS pct_strong,
           round(100.0 * (last_200/first_200 - 1), 1) AS slope_pct,
           round(last_px, 2)                          AS price,
           n
    FROM agg a JOIN securities s USING (symbol)
    WHERE s.is_active AND NOT s.is_etf
      AND n >= {min_days}
      AND n_strong >= {pct_frac} * n
      AND last_200 > first_200
      AND (last_200/first_200 - 1) >= {slope_frac}
      AND last_px > {min_price} AND last_vol > {min_vol}
      {type_filter}
    ORDER BY slope_pct DESC, pct_strong DESC, a.symbol
    """
    con = connect(read_only=True)
    try:
        df = con.execute(sql).fetchdf()
    finally:
        con.close()
    if limit:
        df = df.head(limit)
    return df


# Registry so the CLI can dispatch by name and stay extensible.
SCREENS = {"strong-trend": strong_trend}
