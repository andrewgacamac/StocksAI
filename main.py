"""StocksAI command-line entrypoint.

Examples:
    python main.py update-universe
    python main.py backfill-daily --limit 50
    python main.py refresh-daily
    python main.py backfill-hourly --limit 50
    python main.py refresh-hourly
    python main.py status
"""

import argparse

from stocksai import loaders
from stocksai.db import connect, init_schema
from stocksai.universe import update_universe


def _cmd_update_universe(_args):
    count = update_universe()
    print(f"Universe updated: {count:,} active securities")


def _cmd_backfill_daily(args):
    loaders.backfill("daily", limit=args.limit, resume=not args.no_resume)


def _cmd_refresh_daily(args):
    loaders.refresh("daily", limit=args.limit)


def _cmd_backfill_hourly(args):
    loaders.backfill("hourly", limit=args.limit, resume=not args.no_resume)


def _cmd_refresh_hourly(args):
    loaders.refresh("hourly", limit=args.limit)


def _cmd_status(_args):
    con = connect(read_only=False)
    try:
        init_schema(con)
        active = con.execute(
            "SELECT count(*) FROM securities WHERE is_active"
        ).fetchone()[0]
        daily = con.execute("SELECT count(*) FROM ohlcv_daily").fetchone()[0]
        hourly = con.execute("SELECT count(*) FROM ohlcv_hourly").fetchone()[0]
        print(f"Active securities : {active:,}")
        print(f"Daily rows        : {daily:,}")
        print(f"Hourly rows       : {hourly:,}")
        print("\nLoad log by interval/status:")
        for interval, status, n in con.execute(
            "SELECT interval, status, count(*) FROM load_log "
            "GROUP BY 1, 2 ORDER BY 1, 2"
        ).fetchall():
            print(f"  {interval:7} {status:6} {n:,}")
    finally:
        con.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stocksai", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_limit(p):
        p.add_argument("--limit", type=int, default=None,
                       help="process at most N symbols (for testing)")

    sub.add_parser("update-universe").set_defaults(func=_cmd_update_universe)

    p = sub.add_parser("backfill-daily")
    add_limit(p)
    p.add_argument("--no-resume", action="store_true",
                   help="reprocess symbols even if already completed")
    p.set_defaults(func=_cmd_backfill_daily)

    p = sub.add_parser("refresh-daily")
    add_limit(p)
    p.set_defaults(func=_cmd_refresh_daily)

    p = sub.add_parser("backfill-hourly")
    add_limit(p)
    p.add_argument("--no-resume", action="store_true",
                   help="reprocess symbols even if already completed")
    p.set_defaults(func=_cmd_backfill_hourly)

    p = sub.add_parser("refresh-hourly")
    add_limit(p)
    p.set_defaults(func=_cmd_refresh_hourly)

    sub.add_parser("status").set_defaults(func=_cmd_status)
    return parser


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
