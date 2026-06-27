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
