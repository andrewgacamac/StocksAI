"""Build the `securities` table from NASDAQ Trader's daily symbol directory.

yfinance cannot enumerate tickers, so the active universe comes from two
pipe-delimited files republished every trading day:

  nasdaqlisted.txt  -> NASDAQ-listed securities
  otherlisted.txt   -> NYSE / NYSE American / NYSE Arca / Cboe / IEX securities

Each file ends with a "File Creation Time" footer line that must be dropped.
"""

from datetime import date, datetime
from io import StringIO

import pandas as pd
import requests

from . import config
from .db import connect, init_schema
from .symbols import security_type, to_yahoo


def _download(url: str) -> pd.DataFrame:
    """Fetch a pipe-delimited directory file, dropping its footer line."""
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(StringIO(resp.text), sep="|", dtype=str)
    # The last row is a "File Creation Time: ..." footer, not a security.
    footer_mask = df.iloc[:, 0].str.startswith("File Creation Time", na=False)
    return df[~footer_mask].copy()


def _parse_nasdaq_listed() -> pd.DataFrame:
    df = _download(config.NASDAQ_LISTED_URL)
    df = df[df["Test Issue"] != "Y"]
    out = pd.DataFrame({
        "source_symbol": df["Symbol"].str.strip(),
        "name": df["Security Name"].str.strip(),
        "exchange": "NASDAQ",
        "is_etf": df["ETF"].eq("Y"),
        "market_category": df["Market Category"].str.strip(),
        "financial_status": df["Financial Status"].str.strip(),
    })
    return out


def _parse_other_listed() -> pd.DataFrame:
    df = _download(config.OTHER_LISTED_URL)
    df = df[df["Test Issue"] != "Y"]
    out = pd.DataFrame({
        # ACT Symbol is the canonical CQS symbol for non-NASDAQ venues.
        "source_symbol": df["ACT Symbol"].str.strip(),
        "name": df["Security Name"].str.strip(),
        "exchange": df["Exchange"].str.strip().map(config.EXCHANGE_CODES)
                      .fillna(df["Exchange"].str.strip()),
        "is_etf": df["ETF"].eq("Y"),
        "market_category": None,
        "financial_status": None,
    })
    return out


def fetch_universe() -> pd.DataFrame:
    """Return the combined, de-duplicated active universe as a DataFrame."""
    combined = pd.concat(
        [_parse_nasdaq_listed(), _parse_other_listed()], ignore_index=True
    )
    combined = combined.dropna(subset=["source_symbol"])
    combined["symbol"] = combined["source_symbol"].map(to_yahoo)
    combined = combined.dropna(subset=["symbol"])
    combined = combined[combined["symbol"] != ""]
    # A handful of symbols appear on multiple feeds; keep the first occurrence.
    combined = combined.drop_duplicates(subset=["symbol"], keep="first")
    combined["security_type"] = [
        security_type(sym, nm, etf)
        for sym, nm, etf in zip(combined["symbol"], combined["name"],
                                combined["is_etf"])
    ]
    return combined.reset_index(drop=True)


def update_universe() -> int:
    """Refresh the `securities` table; return the active symbol count."""
    today = date.today()
    now = datetime.now()
    universe = fetch_universe()

    con = connect()
    try:
        init_schema(con)
        con.register("incoming", universe)

        # Upsert: insert new symbols, refresh existing ones, mark them active.
        # first_seen is preserved on update via COALESCE on the existing value.
        con.execute(
            """
            INSERT INTO securities AS s (
                symbol, source_symbol, name, exchange, is_etf, security_type,
                market_category, financial_status, is_active,
                first_seen, last_seen, updated_at
            )
            SELECT
                symbol, source_symbol, name, exchange, is_etf, security_type,
                market_category, financial_status, TRUE,
                $today, $today, $now
            FROM incoming
            ON CONFLICT (symbol) DO UPDATE SET
                source_symbol    = excluded.source_symbol,
                name             = excluded.name,
                exchange         = excluded.exchange,
                is_etf           = excluded.is_etf,
                security_type    = excluded.security_type,
                market_category  = excluded.market_category,
                financial_status = excluded.financial_status,
                is_active        = TRUE,
                last_seen        = excluded.last_seen,
                updated_at       = excluded.updated_at
            """,
            {"today": today, "now": now},
        )

        # Anything not in today's feed is no longer listed -> mark inactive.
        con.execute(
            """
            UPDATE securities SET is_active = FALSE, updated_at = $now
            WHERE symbol NOT IN (SELECT symbol FROM incoming)
              AND is_active IS NOT FALSE
            """,
            {"now": now},
        )

        active = con.execute(
            "SELECT count(*) FROM securities WHERE is_active"
        ).fetchone()[0]
    finally:
        con.close()

    return active
