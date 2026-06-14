"""Symbol normalization between NASDAQ Trader format and Yahoo Finance format.

NASDAQ Trader uses '.' as a class/issue separator (e.g. BRK.A, share class A)
and '$' to introduce a preferred-share series (e.g. ABR$D). Yahoo Finance uses
'-' for classes (BRK-A) and '-P<series>' for preferred shares (ABR-PD). We
canonicalize on the Yahoo form so the stored symbol can be passed straight to
yfinance with no further mapping.
"""


def to_yahoo(source_symbol: str) -> str:
    """Convert a NASDAQ Trader symbol into the Yahoo Finance equivalent."""
    s = source_symbol.strip().upper()
    if "$" in s:
        base, _, series = s.partition("$")
        s = f"{base}-P{series}"
    return s.replace(".", "-")
