from __future__ import annotations

import argparse
import json
import time
from typing import List, Optional

from .config import Config
from .models import DEFAULT_ASSETS
from .runner import PaperRunner, format_opportunities, scan_once
from .store import PaperStore


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m polyarb")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="scan once for all configured assets")
    scan_parser.add_argument("--once", action="store_true", help="run one scan and exit")
    scan_parser.add_argument("--json", action="store_true", help="print JSON output")

    run_parser = subparsers.add_parser("run", help="run continuous paper trading scanner")
    run_parser.add_argument("--paper", action="store_true", help="required; paper trading only")
    run_parser.add_argument("--iterations", type=int, default=0, help="test hook: stop after N iterations")

    report_parser = subparsers.add_parser("report", help="show paper trades and recent opportunities")
    report_parser.add_argument("--limit", type=int, default=20)

    web_parser = subparsers.add_parser("web", help="serve web dashboard")
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=8787)
    web_parser.add_argument("--no-auto-scan", action="store_true", help="start UI without background scanner")

    args = parser.parse_args(argv)
    config = Config.from_env()

    if args.command == "scan":
        if not args.once:
            parser.error("scan requires --once")
        result = scan_once(config)
        if args.json:
            print(json.dumps([item.as_dict() for item in result.opportunities], ensure_ascii=False, indent=2))
        else:
            print(format_opportunities(result))
        return 0

    if args.command == "run":
        if not args.paper:
            parser.error("run refuses to start without --paper; real trading is not implemented")
        runners = [PaperRunner(config, asset) for asset in DEFAULT_ASSETS]
        for runner in runners:
            runner.store.initialize()
        if args.iterations:
            for _ in range(args.iterations):
                for runner in runners:
                    result = runner.run_iteration()
                    print(format_opportunities(result, limit=5))
            return 0
        while True:
            for runner in runners:
                runner.run_iteration()
            time.sleep(config.refresh_seconds)
        return 0

    if args.command == "report":
        store = PaperStore(config.database_path)
        store.initialize()
        trades = store.latest_trades(args.limit)
        opportunities = store.latest_opportunities(args.limit)
        print("paper_trades")
        print(json.dumps(trades, ensure_ascii=False, indent=2))
        print("recent_opportunities")
        print(json.dumps(opportunities, ensure_ascii=False, indent=2))
        return 0

    if args.command == "web":
        from .web import serve

        serve(config, host=args.host, port=args.port, auto_scan=not args.no_auto_scan)
        return 0

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
