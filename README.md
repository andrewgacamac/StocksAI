# Stocks

Download stock data from Yahoo Finance (via `yfinance`) and store it in DuckDB.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
python main.py
```

This downloads OHLCV data for the tickers in `main.py`, writes it to
`data/stocks.duckdb`, and prints the latest close per ticker. Edit `TICKERS`,
`PERIOD`, and `INTERVAL` at the top of `main.py` to change what is fetched.

## Querying the database

```bash
python -c "import duckdb; print(duckdb.connect('data/stocks.duckdb').sql('SELECT * FROM prices LIMIT 5'))"
```
