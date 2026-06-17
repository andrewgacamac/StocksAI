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


import re  # noqa: E402


def security_type(symbol: str, name: str, is_etf: bool) -> str:
    """Classify a security into a coarse type from its symbol + name.

    Returns one of: etf, preferred, note, warrant, unit, right, fund, spac, stock.
    'stock' is the catch-all for common/ordinary shares, ADRs, and REITs — i.e.
    operating-company equities. Lets screens filter to real stocks instead of
    pattern-matching names each time. Heuristic (NASDAQ Trader gives no sub-type),
    but reliable for the obvious non-common-stock instruments.
    """
    s = (symbol or "").upper()
    n = (name or "").lower()
    if is_etf:
        return "etf"
    # Symbol-suffix signals (canonical Yahoo form: -P<x> pref, -U unit, -W warrant, -R right)
    if re.search(r"-P.?$", s) or "preferred" in n or "pfd" in n or "depositary" in n:
        return "preferred"
    if s.endswith("-U") or "units" in n or n.endswith(" unit"):
        return "unit"
    if re.search(r"-WS?$", s) or "warrant" in n:
        return "warrant"
    if re.search(r"-R(T)?$", s) or "rights" in n:
        return "right"
    if "notes" in n or "debenture" in n or "subordinated" in n or "% " in n:
        return "note"
    if "acquisition corp" in n or "acquisition company" in n:
        return "spac"
    if "fund" in n:
        return "fund"
    return "stock"
