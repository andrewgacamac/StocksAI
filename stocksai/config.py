"""Central configuration for the StocksAI pipeline.

History windows are deliberately small for the first build. Widening them later
(e.g. DAILY_PERIOD = "10y") is a one-line change plus a backfill rerun — no schema
or loader changes are required.
"""

from pathlib import Path

# --- Paths -----------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "stocks.duckdb"

# --- History windows -------------------------------------------------------
# Passed straight to yfinance's `period` argument.
DAILY_PERIOD = "7y"     # 7 years of daily bars
HOURLY_PERIOD = "1mo"   # 1 month of hourly bars (Yahoo caps 1h history at 730d)

DAILY_INTERVAL = "1d"
HOURLY_INTERVAL = "1h"

# --- Universe sources (NASDAQ Trader daily symbol directory) ---------------
NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

# Single-letter exchange codes used in otherlisted.txt -> human-readable names.
EXCHANGE_CODES = {
    "A": "NYSE American",
    "N": "NYSE",
    "P": "NYSE Arca",
    "Z": "Cboe BZX",
    "V": "IEX",
}

# --- Loader tuning ---------------------------------------------------------
BATCH_SIZE = 100          # tickers per yfinance request
MAX_RETRIES = 4           # attempts per batch before giving up
RETRY_BACKOFF = 2.0       # seconds; doubles each retry (2, 4, 8, ...)
SLEEP_BETWEEN_BATCHES = 1.0  # politeness delay to avoid throttling
