"""DuckDB connection management and schema definition."""

import duckdb

from . import config

SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS securities (
    symbol            VARCHAR PRIMARY KEY,   -- canonical (Yahoo) form, e.g. BRK-A
    source_symbol     VARCHAR,               -- original NASDAQ Trader form, e.g. BRK.A
    name              VARCHAR,
    exchange          VARCHAR,               -- NASDAQ / NYSE / NYSE American / ...
    is_etf            BOOLEAN,
    market_category   VARCHAR,
    financial_status  VARCHAR,
    is_active         BOOLEAN,               -- present in today's directory file
    first_seen        DATE,
    last_seen         DATE,
    updated_at        TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ohlcv_daily (
    symbol     VARCHAR,
    date       DATE,
    open       DOUBLE,
    high       DOUBLE,
    low        DOUBLE,
    close      DOUBLE,   -- raw / unadjusted
    adj_close  DOUBLE,   -- split/dividend adjusted
    volume     BIGINT,
    PRIMARY KEY (symbol, date)
);

CREATE TABLE IF NOT EXISTS ohlcv_hourly (
    symbol  VARCHAR,
    ts      TIMESTAMP,   -- US/Eastern wall-clock market time
    open    DOUBLE,
    high    DOUBLE,
    low     DOUBLE,
    close   DOUBLE,
    volume  BIGINT,
    PRIMARY KEY (symbol, ts)
);

CREATE TABLE IF NOT EXISTS load_log (
    symbol       VARCHAR,
    interval     VARCHAR,        -- 'daily' | 'hourly'
    last_loaded  TIMESTAMP,      -- newest bar successfully stored
    status       VARCHAR,        -- 'ok' | 'empty' | 'error'
    error        VARCHAR,
    updated_at   TIMESTAMP,
    PRIMARY KEY (symbol, interval)
);
"""


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open (creating if needed) the project DuckDB database."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(config.DB_PATH), read_only=read_only)


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create all tables if they do not already exist."""
    con.execute(SCHEMA_DDL)
