# Handoff

## 2026-06-30 Virtual position fallback

- When a paper opportunity passes existing execution gates but real paper
  allocation is insufficient for the normal position size, the runner now
  records a virtual trade instead of shrinking it into a dust position.
- Virtual trades use a fixed `1000.00` cost budget per trade and are stored in
  `paper_trades` with `is_virtual=1`.
- Normal `latest_trades()`, `latest_positions()`, portfolio used capital, and
  ordinary `模拟持仓` / `模拟成交` exclude virtual trades.
- Added `latest_virtual_trades()` and `latest_virtual_positions()` plus a
  dashboard `虚拟持仓` section. Virtual trades still mark matching recent
  opportunities as `已成交`.
- SQLite migration adds `paper_trades.is_virtual` with default `0` for existing
  databases.
- Verification:
  - `python3 -m pytest -p no:cacheprovider tests/test_runner_position_sizing.py tests/test_paper_store.py::test_paper_store_lists_virtual_positions_separately tests/test_web.py::test_dashboard_shows_profit_and_positions tests/test_web.py::test_virtual_trade_marks_matching_opportunity_as_executed -q`: passed.
  - `python3 -m pytest -p no:cacheprovider tests -q`: 38 passed.
  - `bash -n start.sh deploy.sh && git diff --check`: passed.
  - Playwright check on a temp DB: `收益概览` used capital stayed `0.00`,
    ordinary `模拟持仓` stayed empty, and `虚拟持仓` showed the fixed
    `1,000.00` virtual cost row.

## 2026-06-30 Dust paper position guard

- Diagnosed a dashboard symptom where `模拟持仓` could show `预估收益 +0.00`
  and `YES 数量 0.00`.
- Local `data/paper.sqlite3` had no trades, so the screenshot row was not
  reproducible from the local DB; code review and regression tests found the
  likely path: position sizing could scale an otherwise valid opportunity down
  to a dust trade when remaining allocation was only a tiny positive amount.
- `PaperRunner._sized_opportunity()` now skips sized paper trades whose scaled
  share count or guaranteed profit would render below `0.01`.
- `PaperStore.record_paper_trade()` also rejects dust trades, and
  `latest_trades()` filters old dust rows so existing invalid paper records do
  not keep appearing in dashboard positions/trades.
- Verification:
  - `python3 -m pytest -p no:cacheprovider tests/test_paper_store.py::test_paper_store_ignores_dust_trade_that_would_render_as_zero tests/test_runner_position_sizing.py::test_runner_skips_dust_position_that_would_render_as_zero -q`: passed.
  - `python3 -m pytest -p no:cacheprovider tests -q`: 36 passed.

## 2026-06-29 Dashboard spread color update

- Dashboard spread values now render through a shared `spread-value` span.
- `spread-value` is styled blue and bold, covering opportunity, open position,
  settled position, and trade tables through the shared `_spread()` formatter.
- Verification:
  - `python3 -m pytest -p no:cacheprovider tests/test_web.py::test_dashboard_renders_chinese_status tests/test_web.py::test_dashboard_shows_profit_and_positions tests/test_web.py::test_opportunity_table_shows_spread_and_execution_state -q`: passed.
  - `python3 -m pytest -p no:cacheprovider tests -q`: 34 passed.
  - `bash -n start.sh deploy.sh && git diff --check`: passed.

## 2026-06-29 Dashboard runtime clock update

- Dashboard header now shows a compact runtime panel before the action buttons.
- The panel displays second-precision current Beijing time and service runtime
  duration from the Web process start time.
- The browser updates the clock every second; `/api/dashboard` partial refresh
  remains unchanged.
- Added regression coverage for the header clock DOM, fixed Asia/Shanghai time
  formatting, startup timestamp, and one-second update interval.
- Verification:
  - `python3 -m pytest -p no:cacheprovider tests/test_web.py::test_dashboard_header_shows_live_clock_and_runtime -q`: passed.
  - `python3 -m pytest -p no:cacheprovider tests -q`: 34 passed.
  - `bash -n start.sh deploy.sh && git diff --check`: passed.
  - Playwright visual check on `http://127.0.0.1:8791` desktop
    `2048x260` and mobile `390x780`: header clock visible without overlap.

## 2026-06-29 Settled position profit panel update

- Dashboard now adds an `已结束持仓收益` section immediately below `模拟持仓`.
- The new panel uses `PaperStore.latest_settled_trades()` and renders each
  ended paper position separately from open positions.
- Columns include asset, realized `收益`, single-position `收益率`, spread,
  Beijing settlement/end time, YES/NO legs, cost, minimum payout, and opening
  time.
- Dashboard partial refresh now updates the new settled-position table through
  `payload.portfolio.settled_positions_html`.
- Test fixture `test_dashboard_infers_event_link_and_condition_for_legacy_rows`
  now uses a 2099 settlement date so it remains an open-position fixture after
  2026-06-29.
- Verification:
  - `python3 -m pytest -p no:cacheprovider tests -q`: 33 passed.
  - `bash -n start.sh deploy.sh && git diff --check`: passed.

## 2026-06-29 Opportunity table spread/status update

- `最近套利机会` now includes a `价差` column immediately after `状态`.
- Opportunity status rendering now distinguishes:
  - `已成交` when the matching `pair_key + detected_at` has already been
    written to `paper_trades`;
  - `仅观察` when displayed spread is below `2.00¢`, even if the scanner row is
    executable;
  - `可模拟成交` only for untraded opportunities with spread at least `2.00¢`.
- Verification:
  - `python3 -m pytest -p no:cacheprovider tests -q`: 33 passed.
  - `bash -n start.sh deploy.sh && git diff --check`: passed.

## 2026-06-29 Position settlement column update

- In `模拟持仓`, settlement time now appears immediately after `价差`.
- The settlement header is now `结算时间UTC+8`, matching `模拟成交`.
- Opening time remains near the end as `开仓时间`.
- Verification:
  - `python3 -m pytest -p no:cacheprovider tests -q`: 32 passed.

## 2026-06-29 Trade table lead columns update

- In `模拟成交`, `预估收益` and settlement time now appear immediately after
  `价差`.
- The settlement header is now `结算时间UTC+8`, matching the Beijing-time table
  rendering.
- The opening `时间` column remains near the end of the trade table.
- Verification:
  - `python3 -m pytest -p no:cacheprovider tests -q`: 32 passed.

## 2026-06-29 Table time wrapping update

- Dashboard trade table time cells now render date and clock on separate lines.
- This affects table cells such as `时间`, `开仓时间`, and `结算时间`.
- `format_standard_time()` still returns the standard one-line
  `YYYY-MM-DD HH:MM:SS` string for non-table uses; only the table HTML renderer
  splits it into date and clock spans.
- Verification:
  - `python3 -m pytest -p no:cacheprovider tests -q`: 32 passed.

## 2026-06-29 Spread column update

- `模拟持仓` and `模拟成交` now include a `价差` column.
- `价差` uses the dashboard cents display unit:
  `100 - ((yes_avg_price + no_avg_price) * 100)`.
  Example: `40.00¢ + 57.00¢` displays `3.00¢`.
- In `模拟持仓`, `价差` appears after `预估收益` and before `YES 持仓腿`.
- In `模拟成交`, `价差` appears as the first column before `YES 持仓腿`.
- Verification:
  - `python3 -m pytest -p no:cacheprovider tests -q`: 32 passed.

## 2026-06-29 Portfolio realized profit wording update

- `收益概览` now reports realized settled profit:
  - labels changed from `累计预估收益` / `预估收益率` to `累计收益` / `收益率`;
  - asset summary table columns changed from `预估收益` / `预估收益率` to
    `收益` / `收益率`.
- `PaperStore.latest_settled_trades()` was added so the portfolio summary can
  aggregate only trades whose YES and NO legs have both reached settlement
  time.
- Open positions still drive `已用本金`, `剩余本金`, and `持仓数`.
- `模拟持仓` and `模拟成交` keep `预估收益` wording for unsettled or historical
  trade rows.
- Verification:
  - `python3 -m pytest -p no:cacheprovider tests -q`: 32 passed.

## 2026-06-29 Position profit column order update

- In the `模拟持仓` table, `预估收益` now appears immediately after `币种`.
- The row cells, table header, and column group order were changed together so
  fixed column widths still align with the rendered data.
- Verification:
  - `python3 -m pytest -p no:cacheprovider tests -q`: 31 passed.

## 2026-06-29 Price display unit update

- Polymarket CLOB/WebSocket prices are stored and processed as dollar
  probability units from `0.00` to `1.00`.
- The dashboard now renders prices in Polymarket-style cents by multiplying the
  stored price by `100` and appending `¢`, e.g. stored `0.409` displays as
  `40.90¢`.
- Only display changed. Arbitrage math, paper trade storage, cost, payout, and
  profit calculations continue to use the original `0-1` dollar unit.
- Verification:
  - `python3 -m pytest -p no:cacheprovider tests -q`: 31 passed.

## 2026-06-29 Quantity precision update

- Dashboard quantity/share values now display with 2 decimal places instead of
  4 decimal places.
- This applies to all Web tables that use the shared quantity formatter,
  including opportunities, positions, and trades.
- Verification:
  - `python3 -m pytest -p no:cacheprovider tests -q`: 31 passed.

## 2026-06-29 Trade table overlap fix

- `模拟持仓` and `模拟成交` no longer show the internal `交易对` / `pair_key`
  column. Those ids remain in storage but are hidden from the dashboard tables.
- Market leg cells no longer prepend `事件：`; they show the inferred event
  title directly, followed by the condition badge such as `条件：↓ 1,500`.
- Wide trade tables now use explicit column groups:
  - market-leg columns get wider fixed space;
  - quantity, price, amount, profit, and time columns stay compact;
  - market titles wrap inside their own cells instead of overlapping adjacent
    quantity cells.
- Verification:
  - `python3 -m pytest -p no:cacheprovider tests -q`: 31 passed.
  - `bash -n start.sh deploy.sh && git diff --check`: passed.

## 2026-06-28 Trade table layout polish

- `模拟持仓` and `模拟成交` now use dedicated wide table classes instead of
  letting all columns compress equally.
- Wide tables scroll horizontally inside their panel when needed; the rest of
  the page layout stays stable.
- YES/NO market legs now render as a compact market card:
  - first line: inferred event title;
  - second line: condition badge such as `条件：↑ 70,000`.
- Market cells use normal word wrapping and a fixed readable width, avoiding the
  previous vertical one-word-per-line appearance.
- Time cells stay on one line for readability.
- Verification:
  - `python3 -m pytest -p no:cacheprovider tests -q`: 31 passed.
  - `bash -n start.sh deploy.sh && git diff --check`: passed.

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

## 2026-06-28 Polymarket connection log update

- Added a bottom-of-page `Polymarket 连接日志` panel to the Web dashboard.
- `/api/dashboard` now includes `connection_log_html`, refreshed by the existing
  5-second partial update loop.
- Realtime runners now log the actual read-only行情链路:
  - Gamma REST market bootstrap;
  - CLOB REST order book bootstrap;
  - CLOB WebSocket connect and subscription;
  - manual scan start/success/failure;
  - realtime listener failure.
- Diagnosis note:
  - `curl -i polymarket.com` only proves the main site HTTP entry is reachable.
  - The dashboard depends on `https://gamma-api.polymarket.com/events`,
    `https://clob.polymarket.com/book`, and
    `wss://ws-subscriptions-clob.polymarket.com/ws/market`.
  - `[Errno 101] Network is unreachable` is an outbound network/path/proxy
    problem from the running service environment, not a normal Polymarket API
    4xx/5xx response.
- Verification:
  - `python3 -m pytest -p no:cacheprovider tests -q`: 20 passed.
  - Local `--no-auto-scan` Web smoke check confirmed the connection log block is
    present in HTML and `/api/dashboard`.
  - Local live read-only scan passed with `markets=32`, `pairs=219`,
    `opportunities=0`.

## 2026-06-28 systemd proxy startup update

- Root cause for Ubuntu proxy mismatch:
  - `export http_proxy=...` and `export https_proxy=...` in an SSH shell do not
    automatically apply to a systemd service.
  - `start.sh` previously wrote only Polyarb business configuration into
    `polyarb.service`, so the dashboard service could still report
    `Network is unreachable` even when manual `curl` worked through the proxy.
- `start.sh` now copies proxy environment variables into the generated systemd
  unit:
  - lowercase and uppercase HTTP(S)/FTP/ALL/NO proxy variables;
  - derived `ws_proxy` / `wss_proxy` and uppercase variants for WebSocket
    clients when HTTP(S) proxy is present.
- Server usage:
  - `export http_proxy="http://127.0.0.1:7890"`
  - `export https_proxy="http://127.0.0.1:7890"`
  - `bash start.sh`
  - verify with `sudo systemctl show polyarb -p Environment`.

## 2026-06-28 Dashboard wording and profit color update

- Dashboard browser-comment cleanup:
  - main page title changed from `Polyarb 套利模拟系统` to
    `Polymarket 套利模拟系统`;
  - `纸面模拟持仓` changed to `模拟持仓`;
  - `纸面模拟成交` changed to `模拟成交`;
  - related empty states now say `暂无持仓。` / `暂无成交。`.
- Profit and return-rate values now use win/loss coloring:
  - non-negative values use the green accent class;
  - negative values use the red danger class.
- Verification:
  - `python3 -m pytest -p no:cacheprovider tests -q`: 21 passed.
  - Local `--no-auto-scan` Web smoke check confirmed the title, section labels,
    and green non-negative profit classes render in HTML and `/api/dashboard`.

## 2026-06-28 WebSocket reconnect update

- Realtime Polymarket listeners no longer stop after WebSocket/network errors.
- `RealtimePaperRunner.run_forever()` now logs the failure, waits 10 seconds,
  then starts the next REST bootstrap + WebSocket subscription cycle.
- This is intended for unstable server networks: BTC and ETH listeners should
  keep retrying indefinitely instead of changing the dashboard to a stopped
  realtime state after keepalive timeout errors.
- Verification:
  - Added a regression test that simulates a WebSocket keepalive failure and
    confirms the runner waits 10 seconds before entering the next bootstrap.

## 2026-06-28 Position leg display, settlement filtering, and sizing update

- Dashboard tables now display YES and NO legs separately:
  - `模拟持仓`: `YES 持仓腿` / `YES 份额` and `NO 持仓腿` / `NO 份额`;
  - `模拟成交`: the same split leg/share layout;
  - `最近套利机会`: separate YES/NO market and share columns.
- Dashboard trade/opportunity/position timestamps now render as standard
  Beijing time: `YYYY-MM-DD HH:MM:SS`; raw ISO offsets are no longer shown in
  these tables.
- Unsettled paper positions use `预估收益` wording in position/trade tables.
- Paper trades and opportunities now store YES/NO market end dates. Existing
  SQLite files are migrated in-place with empty defaults for historical rows.
- `latest_positions()` filters out paper trades whose known YES and NO legs have
  both reached their end dates, so settled pairs no longer appear in
  `模拟持仓`. Historical rows without end dates remain visible to avoid hiding
  data that cannot be classified.
- Paper execution sizing now uses profit-rate tiers based on
  `guaranteed_profit / total_cost`:
  - `>= 3%`: use 100% of the asset's remaining allocation, capped by available
    executable depth;
  - `>= 2%`: use 50%;
  - `>= 1%`: use 30%;
  - below `1%`: do not write a paper trade.
- Verification:
  - `python3 -m pytest -p no:cacheprovider tests -q`: 25 passed.
  - Local no-auto-scan Web smoke check on `http://127.0.0.1:8787` confirmed
    the then-current portfolio summary labels rendered in HTML and
    `/api/dashboard`, with no raw ISO timestamp match in the checked output.
    Current summary labels were later changed by the 2026-06-29 realized profit
    wording update.

## 2026-06-28 start.sh database path preservation update

- Diagnosis for "data disappeared after `start.sh`":
  - `start.sh` did not delete SQLite files, but it rewrote the systemd unit with
    `POLYARB_DB=${ROOT_DIR}/data/paper.sqlite3`.
  - If an existing `polyarb.service` had been using another SQLite path, rerunning
    `start.sh` from a different checkout/path made the dashboard point at a new
    empty database, which looked like historical data was gone.
  - On the local checkout, `data/paper.sqlite3` currently exists but has
    `opportunities=0` and `paper_trades=0`; no alternate local sqlite file was
    found under the project directory.
- Fix:
  - If `POLYARB_DB` is not explicitly set, `start.sh` now reads the existing
    `polyarb.service` environment and reuses its `POLYARB_DB` when that file
    still exists.
  - Explicit `POLYARB_DB=/path/to/paper.sqlite3 bash start.sh` still switches
    the database intentionally.
- Recovery tip for Ubuntu:
  - Run `sudo systemctl show polyarb -p Environment` to see the current DB path.
  - Search old sqlite files with `find ~/ -name '*.sqlite3' -o -name '*.db'`.
  - Once the old DB is found, restart with
    `POLYARB_DB=/old/path/paper.sqlite3 bash start.sh`.
- Verification:
  - Added `tests/test_start_script.py` covering preservation of an existing
    systemd `POLYARB_DB`.

## 2026-06-28 Position and trade quantity/price/amount display update

- Dashboard `模拟持仓` and `模拟成交` no longer label leg size as `份额`.
- Each YES/NO leg now shows:
  - `数量`: contract/share count;
  - `价格`: average entry price for that leg;
  - `金额`: `数量 * 价格`.
- `paper_trades` now stores `yes_avg_price` and `no_avg_price` so historical
  paper trade rows can render leg prices and amounts after migration. Existing
  SQLite files are migrated in-place with `0` defaults for older rows that lack
  price data.
- Verification:
  - Added regression coverage for the table headers and leg amounts, e.g.
    `300 * 0.40 = 120.00` and `300 * 0.57 = 171.00`.

## 2026-06-28 Legacy paper trade price backfill update

- Issue:
  - Paper trades created before `yes_avg_price` / `no_avg_price` were added to
    `paper_trades` rendered `0.0000` prices and `0.00 USDT` leg amounts.
- Fix:
  - `PaperStore.initialize()` now backfills zero paper-trade leg prices from
    the matching `opportunities` row using `pair_key + detected_at`.
  - This handles old records because paper execution records the opportunity
    first and then records the paper trade with the same timestamp.
  - If no matching opportunity exists, prices stay `0` rather than inventing an
    unsafe split from total cost.
- Verification:
  - Added regression coverage for an old `paper_trades` schema and a matching
    opportunity row, confirming prices are restored after initialization.

## 2026-06-28 Settlement time and table readability update

- `模拟持仓` and `模拟成交` now include `结算时间`, computed as the later known
  YES/NO leg end date and displayed in Beijing time.
- Price and amount display now uses 2 decimals across the dashboard.
- Dashboard amount fields no longer append `USDT`; the column label provides
  the context and keeps table rows compact.
- The recent opportunity status cell no longer prints the internal English
  reason `executable`; non-executable reasons are translated for common volume
  and depth blocks.
- Long market text cells now use a constrained wrapping style so English market
  titles do not make the narrow UI look broken.
- Verification:
  - Added regression coverage for settlement time, 2-decimal prices, and hiding
    the internal `executable` reason.

## 2026-06-28 Dashboard amount formatting update

- All dashboard amount fields now render with exactly 2 decimals and without the
  `USDT` suffix:
  - portfolio summary and asset allocation rows;
  - position/trade leg amounts, costs, payouts, and estimated profit;
  - recent opportunity guaranteed profit.
- Percentage fields remain unchanged.
- Verification:
  - Added regression checks that dashboard HTML, portfolio fragments, position
    rows, trade rows, and opportunity rows do not include `USDT`.

## 2026-06-28 Legacy settlement time backfill update

- CLOB WebSocket market messages are used for order-book updates (`book` and
  `price_change`) and are not the source of settlement time.
- Settlement time should come from Gamma market metadata `endDate`, which is
  saved into `yes_end_date` / `no_end_date` for new paper trades.
- For old paper trades that were created before end dates were stored:
  - `PaperStore.initialize()` now first backfills end dates from the matching
    `opportunities` row using `pair_key + detected_at`.
  - If the matching opportunity also lacks end dates, it infers common weekly
    and monthly settlement times from question text such as
    `June 22-28?` or `in June?`, using the trade timestamp year and New York
    market calendar boundaries.
- This also improves settled-position filtering because old rows can now gain
  real `yes_end_date` / `no_end_date` values instead of staying visible forever.
- Verification:
  - Added regression coverage for an old `paper_trades` row with empty end
    dates and question `Will Ethereum dip to $1,500 June 22-28?`.

## 2026-06-28 Polymarket market link update

- Diagnosis for "cannot find the traded pair in Polymarket search":
  - Paper trades are simulated only; they do not appear as real Polymarket
    account trades.
  - Dashboard rows display Gamma market question text such as
    `Will Ethereum dip to $1,500 June 22-28?`.
  - Polymarket's website search often indexes/returns the broader event title,
    such as `What price will Ethereum hit June 22-28?`, rather than the exact
    market question text shown by Gamma.
- Fix:
  - `ArbOpportunity` now carries `yes_event_slug` and `no_event_slug`.
  - `opportunities` and `paper_trades` store these slugs for new records.
  - Dashboard market text in recent opportunities, positions, and trades becomes
    a direct `https://polymarket.com/event/<event_slug>` link when the slug is
    known.
  - Old rows without slugs still render as plain text.
- Verification:
  - Added regression checks that positions, trades, and opportunities include
    direct Polymarket event links when event slugs are present.

## 2026-06-28 Event title and condition label update

- Dashboard market cells no longer rely on the raw Gamma question text such as
  `Will Ethereum dip to $1,500 June 22-28?`, because that exact text is hard to
  find with Polymarket's website search.
- Market cells now render:
  - `What price will <Asset> hit <period>?`
  - `条件：↑ <threshold>` for reach/hit markets or `条件：↓ <threshold>` for dip
    markets.
- If an old row has no stored event slug, the UI infers the common crypto price
  event slug from the question text, e.g. `Will Ethereum dip to $1,500 June
  22-28?` links to `what-price-will-ethereum-hit-june-22-28-2026`.
- Interpretation:
  - The Polymarket event page in the browser may be correct, but the selected
    row must match the dashboard condition label. For the example above, the
    event is `What price will Ethereum hit June 22-28?` and the exact market row
    is `↓ 1,500`, not another row such as `↑ 2,400`.
- Verification:
  - Added regression coverage for inferred legacy event links and `↓ 1,500`
    condition labels.
