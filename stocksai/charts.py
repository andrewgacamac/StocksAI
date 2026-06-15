"""Reusable indicator charting for any symbol.

Generates two PNGs from the indicator views:
  <SYMBOL>_price.png        - price, SMAs, EMAs, Bollinger Bands, 52w range, crosses
  <SYMBOL>_oscillators.png  - MACD, RSI, Stochastic, ATR/ROC, Volume/OBV

Headless (Agg backend), so it works without a display. Reads the cheap
`v_indicators_daily` view plus `v_ema_daily` (filtered by symbol, so it's fast).
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from . import config  # noqa: E402
from .db import connect  # noqa: E402
from .indicators import DAILY_VIEW, EMA_VIEW  # noqa: E402


def _load(con, symbol: str, start: str, end: str):
    ind = con.execute(
        f"SELECT * FROM {DAILY_VIEW} "
        "WHERE symbol = ? AND date BETWEEN ? AND ? ORDER BY date",
        [symbol, start, end],
    ).fetchdf()
    ema = con.execute(
        f"SELECT date, ema_12, ema_26, macd, macd_signal, macd_hist FROM {EMA_VIEW} "
        "WHERE symbol = ? AND date BETWEEN ? AND ? ORDER BY date",
        [symbol, start, end],
    ).fetchdf()
    return ind.merge(ema, on="date", how="left")


def _style(ax):
    ax.grid(alpha=.25)
    ax.legend(loc="upper left", fontsize=8, ncol=4)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b'%y"))


def _price_figure(df, symbol, d):
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(15, 10), sharex=True)
    a1.plot(d, df.adj_close, color="black", lw=1.3, label="adj_close")
    a1.plot(d, df.sma_20, lw=1, label="SMA20")
    a1.plot(d, df.sma_50, lw=1, label="SMA50")
    a1.plot(d, df.sma_200, lw=1.2, label="SMA200")
    a1.fill_between(d, df.bb_lower, df.bb_upper, color="gray", alpha=.15,
                    label="Bollinger 20,2σ")
    a1.plot(d, df.hi_252, ls="--", lw=.8, color="green", label="52w high")
    a1.plot(d, df.lo_252, ls="--", lw=.8, color="red", label="52w low")
    gc = df[df.golden_cross == True]
    dc = df[df.death_cross == True]
    a1.scatter(gc.date, gc.adj_close, marker="^", s=120, color="green",
               zorder=5, label="golden cross")
    a1.scatter(dc.date, dc.adj_close, marker="v", s=120, color="red",
               zorder=5, label="death cross")
    a1.set_title(f"{symbol} daily — Price, SMAs, Bollinger Bands, "
                 "52-week range, SMA crossovers")
    a1.set_ylabel("Price $")
    _style(a1)

    a2.plot(d, df.adj_close, color="black", lw=1.1, label="adj_close")
    a2.plot(d, df.ema_12, lw=1, label="EMA12")
    a2.plot(d, df.ema_26, lw=1, label="EMA26")
    a2.set_title("Exponential moving averages (EMA12 / EMA26)")
    a2.set_ylabel("Price $")
    _style(a2)
    fig.tight_layout()
    return fig


def _oscillator_figure(df, symbol, d):
    fig, axs = plt.subplots(5, 1, figsize=(15, 16), sharex=True)
    ax = axs[0]
    ax.plot(d, df.macd, label="MACD", lw=1)
    ax.plot(d, df.macd_signal, label="signal", lw=1)
    colors = ["green" if v >= 0 else "red" for v in df.macd_hist.fillna(0)]
    ax.bar(d, df.macd_hist, color=colors, alpha=.4, width=1.0, label="histogram")
    ax.axhline(0, color="k", lw=.6)
    ax.set_title(f"{symbol} — MACD (12,26,9)")
    _style(ax)

    ax = axs[1]
    ax.plot(d, df.rsi_14, color="purple", lw=1, label="RSI14")
    ax.axhline(70, color="red", ls="--", lw=.8)
    ax.axhline(30, color="green", ls="--", lw=.8)
    ax.axhspan(70, 100, color="red", alpha=.06)
    ax.axhspan(0, 30, color="green", alpha=.06)
    ax.set_ylim(0, 100)
    ax.set_title("RSI (14) — overbought >70 / oversold <30")
    _style(ax)

    ax = axs[2]
    ax.plot(d, df.stoch_k, lw=1, label="%K")
    ax.plot(d, df.stoch_d, lw=1, label="%D")
    ax.axhline(80, color="red", ls="--", lw=.8)
    ax.axhline(20, color="green", ls="--", lw=.8)
    ax.set_ylim(0, 100)
    ax.set_title("Stochastic (%K 14, %D 3)")
    _style(ax)

    ax = axs[3]
    ax.plot(d, df.atr_14, color="brown", lw=1, label="ATR14 ($)")
    ax.set_ylabel("ATR $")
    ax.set_title("ATR (14) volatility  &  ROC momentum")
    axt = ax.twinx()
    axt.plot(d, df.roc_20, lw=.8, color="teal", label="ROC20 %")
    axt.plot(d, df.roc_60, lw=.8, color="orange", label="ROC60 %")
    axt.axhline(0, color="k", lw=.5)
    axt.set_ylabel("ROC %")
    ax.grid(alpha=.25)
    ax.legend(loc="upper left", fontsize=8)
    axt.legend(loc="upper right", fontsize=8)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b'%y"))

    ax = axs[4]
    ax.bar(d, df.volume, color="steelblue", alpha=.4, width=1.0, label="volume")
    ax.plot(d, df.vol_sma_20, color="navy", lw=1, label="vol SMA20")
    ax.set_ylabel("Volume")
    ax.set_title("Volume + 20d avg  &  OBV")
    axt = ax.twinx()
    axt.plot(d, df.obv, color="darkorange", lw=1, label="OBV")
    axt.set_ylabel("OBV")
    ax.legend(loc="upper left", fontsize=8)
    axt.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=.25)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b'%y"))
    fig.tight_layout()
    return fig


def plot_symbol(symbol: str, years: int = 3, start: str | None = None,
                end: str | None = None, outdir: str | Path = "plots",
                dpi: int = 110) -> list[Path]:
    """Render indicator charts for `symbol`; return the written file paths."""
    symbol = symbol.upper()
    end = end or date.today().isoformat()
    start = start or (date.fromisoformat(end) - timedelta(days=365 * years)).isoformat()

    con = connect(read_only=True)
    try:
        df = _load(con, symbol, start, end)
    finally:
        con.close()
    if df.empty:
        raise SystemExit(f"No indicator data for {symbol} in {start}..{end}. "
                         "Is the symbol loaded and are the views created?")

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    d = df["date"].values
    paths = []
    for suffix, fig in (("price", _price_figure(df, symbol, d)),
                        ("oscillators", _oscillator_figure(df, symbol, d))):
        p = outdir / f"{symbol}_{suffix}.png"
        fig.savefig(p, dpi=dpi)
        plt.close(fig)
        paths.append(p)
    return paths
