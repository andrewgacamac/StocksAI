"""Technical indicators exposed as live (non-materialized) DuckDB views.

Two views over `ohlcv_daily`, both `CREATE OR REPLACE VIEW` (instant, store
nothing — DuckDB recomputes on demand):

  * `v_indicators_daily` — the cheap, window-function indicators (SMA, RSI,
    Bollinger, Stochastic, ATR, ROC, OBV, 52-week high/low, crossovers). Fast for
    full-universe screens and sub-second when filtered.
  * `v_ema_daily` — EMA(12/26) + MACD. These need a geometric-weighted window
    (array_agg) which is ~14x more expensive per the benchmark, so they live in a
    separate view. **Filter by symbol** and it's sub-second (the predicate is
    pushed down so the heavy work runs on one symbol's rows); a full-universe EMA
    scan is intentionally the slow path.

All indicators are computed on **adjusted prices** so splits/dividends don't
create false signals. Since only `adj_close` is stored, intraday high/low are
adjusted on the fly with each day's factor (`adj_close / close`).

Window-friendly variants keep things fast: Cutler's RSI (SMA of gains/losses),
SMA-smoothed ATR, and EMA/MACD via bounded-window exponential weighting (verified
to match pandas `ewm` to many decimals).
"""

from . import config

DAILY_VIEW = "v_indicators_daily"
EMA_VIEW = "v_ema_daily"

_W = "PARTITION BY symbol ORDER BY date"


def _frame(n: int) -> str:
    return f"ROWS BETWEEN {n - 1} PRECEDING AND CURRENT ROW"


def _sma(col: str, n: int) -> str:
    """Full-window SMA: NULL until `n` bars are available."""
    return f"CASE WHEN rn >= {n} THEN avg({col}) OVER ({_W} {_frame(n)}) END"


def _ema_from_array(arr_col: str, span: int) -> str:
    """Geometric-weighted average over an ascending price array.

    Weight for the element at 1-based position j is (1-alpha)^(len-j), so the most
    recent bar (j=len) has weight 1. Uses range()+list_transform to avoid the
    numeric overflow of a frame-aggregate formulation.
    """
    alpha = 2.0 / (span + 1)
    om = 1.0 - alpha
    idx = f"range(1, len({arr_col}) + 1)"
    num = (f"list_sum(list_transform({idx}, "
           f"j -> {arr_col}[j] * pow({om}, len({arr_col}) - j)))")
    den = (f"list_sum(list_transform({idx}, "
           f"j -> pow({om}, len({arr_col}) - j)))")
    return f"({num}) / ({den})"


def build_daily_view_sql() -> str:
    """Cheap window-function indicators only (no EMA/MACD)."""
    sma_cols = ", ".join(f"{_sma('p', n)} AS sma_{n}" for n in config.SMA_WINDOWS)
    roc_cols = ", ".join(
        f"CASE WHEN rn > {n} THEN (p / lag(p, {n}) OVER ({_W}) - 1) * 100 END "
        f"AS roc_{n}"
        for n in config.ROC_WINDOWS
    )
    bw, k = config.BOLLINGER_WINDOW, config.BOLLINGER_K
    rsi_n, atr_n = config.RSI_PERIOD, config.ATR_PERIOD
    sk, sd, hl = config.STOCH_K, config.STOCH_D, config.HILO_WINDOW

    return f"""
CREATE OR REPLACE VIEW {DAILY_VIEW} AS
WITH base AS (
    SELECT
        symbol, date, volume,
        adj_close AS p,
        high * (adj_close / NULLIF(close, 0)) AS adj_high,
        low  * (adj_close / NULLIF(close, 0)) AS adj_low,
        row_number() OVER ({_W}) AS rn,
        lag(adj_close) OVER ({_W}) AS prev_p
    FROM ohlcv_daily
),
calc1 AS (
    SELECT
        symbol, date, volume, p, rn,
        {sma_cols},
        stddev_samp(p) OVER ({_W} {_frame(bw)}) AS std_bb,
        avg(greatest(p - prev_p, 0)) OVER ({_W} {_frame(rsi_n)}) AS avg_gain,
        avg(greatest(prev_p - p, 0)) OVER ({_W} {_frame(rsi_n)}) AS avg_loss,
        min(adj_low)  OVER ({_W} {_frame(sk)}) AS ll_k,
        max(adj_high) OVER ({_W} {_frame(sk)}) AS hh_k,
        avg(greatest(adj_high - adj_low,
                     abs(adj_high - prev_p),
                     abs(adj_low  - prev_p))) OVER ({_W} {_frame(atr_n)})
            AS atr_{atr_n},
        {roc_cols},
        (p / prev_p - 1) AS ret_1d,
        avg(volume) OVER ({_W} {_frame(bw)}) AS vol_sma_{bw},
        sum(CASE WHEN p > prev_p THEN volume
                 WHEN p < prev_p THEN -volume ELSE 0 END)
            OVER ({_W} ROWS UNBOUNDED PRECEDING) AS obv,
        max(p) OVER ({_W} {_frame(hl)}) AS hi_{hl},
        min(p) OVER ({_W} {_frame(hl)}) AS lo_{hl}
    FROM base
),
calc2 AS (
    SELECT
        *,
        sma_{bw} AS bb_mid,
        sma_{bw} + {k} * std_bb AS bb_upper,
        sma_{bw} - {k} * std_bb AS bb_lower,
        CASE WHEN avg_loss = 0 THEN 100
             ELSE 100 - 100 / (1 + avg_gain / avg_loss) END AS rsi_{rsi_n},
        CASE WHEN hh_k = ll_k THEN NULL
             ELSE least(100, greatest(0, 100 * (p - ll_k) / (hh_k - ll_k)))
             END AS stoch_k
    FROM calc1
),
calc3 AS (
    SELECT
        *,
        avg(stoch_k) OVER ({_W} {_frame(sd)}) AS stoch_d,
        CASE WHEN bb_upper = bb_lower THEN NULL
             ELSE (p - bb_lower) / (bb_upper - bb_lower) END AS bb_pctb,
        CASE WHEN bb_mid = 0 THEN NULL
             ELSE (bb_upper - bb_lower) / bb_mid END AS bb_bandwidth,
        lag(sma_50)  OVER ({_W}) AS prev_sma_50,
        lag(sma_200) OVER ({_W}) AS prev_sma_200
    FROM calc2
)
SELECT
    symbol, date, p AS adj_close, volume,
    sma_20, sma_50, sma_200,
    rsi_{rsi_n},
    {", ".join(f"roc_{n}" for n in config.ROC_WINDOWS)},
    ret_1d,
    bb_mid, bb_upper, bb_lower, bb_pctb, bb_bandwidth,
    atr_{atr_n},
    stoch_k, stoch_d,
    vol_sma_{bw}, obv,
    hi_{hl}, lo_{hl},
    (sma_50 > sma_200 AND prev_sma_50 <= prev_sma_200) AS golden_cross,
    (sma_50 < sma_200 AND prev_sma_50 >= prev_sma_200) AS death_cross,
    (p > sma_200) AS above_sma_200
FROM calc3
"""


def build_ema_view_sql() -> str:
    """EMA(s) + MACD. Heavy (array_agg) — filter by symbol for speed.

    One EMA column per span in config.EMA_SPANS; longer spans need a larger
    array_agg window (lookback = EMA_LOOKBACK_MULT*span) and are correspondingly
    more expensive — another reason to always filter this view by symbol.
    """
    spans = list(config.EMA_SPANS)
    mult = config.EMA_LOOKBACK_MULT

    arr_cols = ",\n        ".join(
        f"array_agg(adj_close) OVER ({_W} {_frame(mult * s)}) AS arr_{s}"
        for s in spans
    )
    ema_cols = ",\n        ".join(
        f"{_ema_from_array(f'arr_{s}', s)} AS ema_{s}" for s in spans
    )
    ema_out = ", ".join(f"ema_{s}" for s in spans)
    look_sig = mult * config.MACD_SIGNAL
    signal = _ema_from_array("arr_macd", config.MACD_SIGNAL)

    return f"""
CREATE OR REPLACE VIEW {EMA_VIEW} AS
WITH base AS (
    SELECT symbol, date, adj_close AS p,
        {arr_cols}
    FROM ohlcv_daily
),
e AS (
    SELECT symbol, date, p,
        {ema_cols}
    FROM base
),
m AS (
    SELECT *, (ema_{config.MACD_FAST} - ema_{config.MACD_SLOW}) AS macd FROM e
),
s AS (
    SELECT *, array_agg(macd) OVER ({_W} {_frame(look_sig)}) AS arr_macd FROM m
)
SELECT
    symbol, date, p AS adj_close,
    {ema_out}, macd,
    {signal} AS macd_signal,
    macd - ({signal}) AS macd_hist
FROM s
"""


def create_views(con) -> None:
    """(Re)create the indicator views. Instant; stores no data."""
    con.execute(build_daily_view_sql())
    con.execute(build_ema_view_sql())
