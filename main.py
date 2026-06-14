"""Download stock data from Yahoo Finance and store it in DuckDB."""

from pathlib import Path

import duckdb
import yfinance as yf

DB_PATH = Path(__file__).parent / "data" / "stocks.duckdb"
TICKERS = ["AAPL", "MSFT", "GOOGL"]
PERIOD = "1y"      # e.g. 1d, 5d, 1mo, 1y, max
INTERVAL = "1d"    # e.g. 1m, 1h, 1d, 1wk


def fetch_prices(tickers: list[str], period: str, interval: str):
    """Download OHLCV data for the given tickers as a tidy DataFrame."""
    df = yf.download(
        tickers,
        period=period,
        interval=interval,
        group_by="ticker",
        auto_adjust=True,
        progress=False,
    )
    # Reshape the (ticker, field) column MultiIndex into long format.
    df = (
        df.stack(level=0, future_stack=True)
        .rename_axis(["date", "ticker"])
        .reset_index()
    )
    df.columns = [str(c).lower() for c in df.columns]
    return df


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    prices = fetch_prices(TICKERS, PERIOD, INTERVAL)
    print(f"Fetched {len(prices):,} rows for {len(TICKERS)} tickers")

    con = duckdb.connect(str(DB_PATH))
    con.execute("CREATE OR REPLACE TABLE prices AS SELECT * FROM prices")

    rows = con.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    print(f"Stored {rows:,} rows in {DB_PATH}")

    print("\nLatest close per ticker:")
    result = con.execute(
        """
        SELECT ticker, date, close
        FROM prices
        QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) = 1
        ORDER BY ticker
        """
    ).fetchall()
    for ticker, date, close in result:
        print(f"  {ticker:6} {date}  {close:.2f}")

    con.close()


if __name__ == "__main__":
    main()
