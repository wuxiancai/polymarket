# Polyarb

Polyarb 是一个 Polymarket BTC / ETH 短周期套利扫描与纸面模拟交易系统。

系统只读取公开行情并执行本地模拟交易：

- 不连接钱包
- 不读取私钥
- 不提交真实订单
- 不做长期交易对

## 功能范围

纳入市场：

- BTC / ETH `15m` 及以上的短周期 `Up or Down` 市场
- 小时单、日单、周单
- 当前自然月的 BTC / ETH `reach/dip` 月单

排除市场：

- `5m` 市场
- 年底或跨多月长期盘，例如 `by December 31, 2026`
- 没有 CLOB token id、没有活跃盘口、不能接单的市场

## 默认风控

系统默认使用稳健档：

- `MIN_24H_VOLUME_USD=1000`
- `MIN_ARBITRAGE_DEPTH_USD=100`
- `SLIPPAGE_BUFFER_CENTS=2`
- `MIN_INTERVAL_MINUTES=15`
- `ALLOW_CURRENT_MONTH_ONLY=true`

套利判断会逐档读取 order book 深度。只有当前边际档位在扣除滑点安全垫后仍然盈利，系统才会继续吃深度；前面档位的利润不会补贴后面亏损档位。

## 一键部署

```bash
cd ~/polymarket
bash deploy.sh
```

部署脚本会：

1. 创建 `.venv`
2. 安装当前项目
3. 初始化本地 SQLite 数据库

## 一键启动系统

```bash
cd ~/polymarket
bash start.sh
```

启动脚本会写入并启动 systemd 服务 `polyarb.service`，终端关闭后系统仍会继续运行。默认监听 `0.0.0.0:8787`，可通过局域网 IP 访问：

```text
http://<服务器IP>:8787
```

常用服务命令：

```bash
sudo systemctl status polyarb
sudo journalctl -u polyarb -f
sudo systemctl restart polyarb
sudo systemctl stop polyarb
```

页面会显示：

- 当前扫描状态
- 收益概览：默认初始本金、BTC/ETH 分配本金、已用本金、累计收益、收益率
- 纸面模拟持仓：每笔纸面成交形成的两腿持仓、成本、最低赔付和收益
- 已过滤后的 BTC / ETH 市场数量
- 可分析的确定性交易对数量
- 最近套利机会
- 纸面模拟成交记录

页面会按 BTC、ETH 分成两个相同排版的面板展示。页面上的“触发扫描”按钮会立即启动一次只读扫描；后台默认分别为 BTC、ETH 使用 Polymarket CLOB WebSocket 实时监听盘口更新。页面每 5 秒局部刷新指标和表格，不会整页刷新。

## 命令行用法

单次扫描：

```bash
python3 -m polyarb scan --once
```

持续纸面模拟交易：

```bash
python3 -m polyarb run --paper
```

查看报告：

```bash
python3 -m polyarb report
```

启动 Web 页面：

```bash
python3 -m polyarb web --host 127.0.0.1 --port 8787
```

如果没有执行安装，也可以用：

```bash
PYTHONPATH=src python3 -m polyarb scan --once
```

## 配置

可通过环境变量覆盖默认参数：

```bash
MIN_24H_VOLUME_USD=1000
MIN_ARBITRAGE_DEPTH_USD=100
SLIPPAGE_BUFFER_CENTS=2
MIN_INTERVAL_MINUTES=15
ALLOW_CURRENT_MONTH_ONLY=true
PAPER_INITIAL_CAPITAL_USDT=10000
REFRESH_SECONDS=30
POLYARB_DB=data/paper.sqlite3
HOST=0.0.0.0
PORT=8787
```

示例：

```bash
SLIPPAGE_BUFFER_CENTS=3 MIN_ARBITRAGE_DEPTH_USD=500 bash start.sh
```

如果要换端口或服务名：

```bash
PORT=8888 SERVICE_NAME=polyarb bash start.sh
```

## 当前实现

- 市场发现使用 Polymarket Gamma events。
- 启动时用 Polymarket CLOB REST `/book` 初始化盘口深度。
- 启动后用 Polymarket CLOB WebSocket Market Channel 实时接收 `book` / `price_change` 盘口更新。
- Web 页面使用 Python 标准库 HTTP 服务，不依赖前端框架。
- Web 页面通过 `/api/dashboard` 局部更新数据，避免整页刷新抖动。
- 纸面交易默认保存到 `data/paper.sqlite3`。
- 收益统计默认初始本金为 `10000 USDT`，BTC 分配 `70%`，ETH 分配 `30%`。
- 页面收益按已执行纸面成交的累计保证利润计算，不做未结算市值浮盈浮亏。
- 如果页面显示“行情源连接失败”，说明服务器无法访问 Polymarket 行情 API，需要检查服务器出站网络、DNS、代理或防火墙。
