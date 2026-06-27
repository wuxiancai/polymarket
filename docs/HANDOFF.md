# Handoff

## 2026-06-27

Implemented a Python Polymarket BTC short-cycle arbitrage paper trading scanner
in `/Users/wuxiancai/Documents/polymarket`.

### What Exists

- `src/polyarb/parser.py` parses eligible BTC markets:
  - includes 15m+ intraday, hour/day, week, and current-month reach/dip markets;
  - excludes 5m and long-dated markets such as year-end markets.
- `src/polyarb/arbitrage.py` builds same-market and deterministic implication
  pairs, then evaluates executable depth with volume/depth/slippage gates.
- `src/polyarb/polymarket.py` reads Gamma events and CLOB order books.
- `src/polyarb/runner.py` runs one-shot scans and continuous paper loops.
- `src/polyarb/store.py` writes opportunities and paper trades to SQLite.
- `src/polyarb/__main__.py` exposes:
  - `python3 -m polyarb scan --once`
  - `python3 -m polyarb run --paper`
  - `python3 -m polyarb report`

### Verification

- `python3 -m pytest tests -q` passed: 8 tests.
- `PYTHONPATH=src python3 -m polyarb scan --once` passed against live read-only
  Polymarket APIs.
- Latest live scan result at implementation time:
  - `markets=32`
  - `pairs=219`
  - `opportunities=0`

### Notes

- The implementation is paper-only. It does not connect a wallet or submit real
  orders.
- Continuous mode uses REST polling. WebSocket integration is scaffolded but not
  yet wired as the primary live update path.
- Default risk profile:
  - 24h volume minimum: `$1,000`
  - executable arbitrage depth minimum: `$100`
  - slippage buffer: `2` cents
  - minimum interval: `15` minutes
  - current month only for monthly markets

## 2026-06-27 Web/UI update

Added local Web dashboard and one-click scripts.

### Added

- `src/polyarb/web.py`: standard-library HTTP dashboard.
- `python3 -m polyarb web --host 127.0.0.1 --port 8787`.
- `deploy.sh`: creates `.venv`, installs the project, initializes SQLite.
- `start.sh`: starts the Web dashboard with safe paper-trading defaults.
- `README.md`: rewritten in Chinese with deployment, startup, page, CLI, and
  configuration instructions.

### Web Dashboard

- Default URL: `http://127.0.0.1:8787`.
- Shows scanner state, market count, pair count, opportunity count, recent
  opportunities, and paper trades.
- Provides a manual scan button.
- Starts a background scanner by default and keeps real trading disabled.

## 2026-06-27 Git workflow update

- Initialized this directory as a git-managed project.
- Added `AGENTS.md` with the project rule: every future project-file change must
  be verified and committed with git.
- Runtime artifacts remain ignored:
  - `.venv/`
  - `data/*.sqlite3`
  - Python caches and pytest caches

## 2026-06-27 Time display update

- Web dashboard `最近扫描` now displays standard second-precision Beijing time:
  `YYYY-MM-DD HH:MM:SS`.
- Removed microseconds and ISO offset from the dashboard/API status timestamp.

## 2026-06-27 Realtime market data update

- Web dashboard background scanner now uses Polymarket CLOB WebSocket market
  channel after REST bootstrapping.
- REST is still used for market discovery and initial order book snapshots.
- Web status now reports `实时监听中` while the WebSocket listener is active.
- Dashboard/API expose `last_event_at` for the latest received order book event.
- Added tests for WebSocket subscription payload and `price_change` order book
  updates.

## 2026-06-27 Dashboard refresh update

- Removed `最近扫描` and `最近盘口事件` timestamp rows from the visible dashboard;
  the real-time status itself is the primary signal.
- Replaced full-page `location.reload()` refresh with `/api/dashboard` partial
  updates every 5 seconds.
- Kept timestamp fields in `/api/status` for debugging, but they are no longer
  displayed in the main page.

## 2026-06-27 Ubuntu systemd startup update

- `start.sh` now installs and starts a systemd service instead of running the
  Web server in the foreground.
- Default bind host changed to `0.0.0.0`, so the dashboard is reachable from LAN
  via `http://<server-ip>:8787`.
- Service name defaults to `polyarb`; useful commands:
  - `sudo systemctl status polyarb`
  - `sudo journalctl -u polyarb -f`
  - `sudo systemctl restart polyarb`

## 2026-06-27 ETH dashboard panel update

- Web dashboard now renders two same-layout asset panels:
  - `BTC 套利模拟`
  - `ETH 套利模拟`
- The Web runtime starts separate read-only realtime listeners for BTC and ETH.
- Gamma market discovery is generalized from hard-coded Bitcoin to asset specs:
  - BTC uses tag `bitcoin` and question prefix `Bitcoin`.
  - ETH uses tag `ethereum` and question prefix `Ethereum`.
- Parser now accepts Ethereum `Up or Down`, `reach`, and `dip` markets with the
  same short-cycle filters and risk rules as BTC.
- `/api/dashboard` now returns an `assets` array so the page can update BTC and
  ETH sections independently without full-page refresh.
- Verification:
  - `python3 -m pytest -p no:cacheprovider tests -q`: 16 passed.
  - Read-only Gamma check found BTC 32 markets and ETH 29 markets at the time of
    verification.
  - Local `--no-auto-scan` Web check confirmed `ETH 套利模拟` and `ETHStatusValue`
    render in the page HTML, with no `location.reload`.

## 2026-06-27 Paper portfolio dashboard update

- Added a Web `收益概览` block:
  - default initial capital: `10000 USDT`;
  - BTC default allocation: `70%`;
  - ETH default allocation: `30%`;
  - displays used capital, remaining capital, cumulative guaranteed profit, and
    return rate.
- Added a Web `纸面模拟持仓` block showing paper position legs, shares, cost,
  minimum payout, guaranteed profit, and opened time.
- Profit is calculated from executed paper trades' guaranteed profit. The page
  does not mark unsettled positions to live market prices.
- `paper_trades` now stores yes/no token ids and yes/no question text. Existing
  SQLite databases are migrated in-place by `PaperStore.initialize()`.
- `PAPER_INITIAL_CAPITAL_USDT` can override the default capital.
- Verification:
  - `python3 -m pytest -p no:cacheprovider tests -q`: 18 passed.

## 2026-06-27 Dashboard copy and error display update

- Header title changed from `Polyarb BTC 套利模拟系统` to
  `Polyarb 套利模拟系统`.
- Profit labels changed from `累计保证收益` / `保证收益` to `累计收益` / `收益`.
- Added spacing between `纸面模拟持仓` and the first asset panel.
- Long Gamma API network errors are now shortened in the dashboard. Full error
  details remain available from `/api/status`.
- `Network is unreachable` means the server cannot reach Polymarket's API from
  its outbound network path; check Ubuntu DNS, gateway, proxy, firewall, or ISP
  reachability.
