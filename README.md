# Polyarb

Polyarb 是一个 Polymarket BTC / ETH / XRP / SOL 日线及以上周期套利扫描与纸面模拟交易系统。

> 当前版本：`v1.0.5`；稳定回退点：`v1.0.0`。

系统只读取公开行情并执行本地模拟交易：

- 不连接钱包
- 不读取私钥
- 不提交真实订单
- 不做长期交易对

## 功能范围

纳入市场：

- BTC / ETH / XRP / SOL 的四类日线市场：`Up or Down on <日期>`、`above/below $X on <日期>`、`between $X and $Y on <日期>`、`reach/hit $X on <日期>`
- BTC / ETH / XRP / SOL 的 `reach/dip` 周单
- 季单、年单仅在距结束日期小于 30 天时纳入

排除市场：

- 小时、分钟 `Up or Down` 市场
- `in <月份>` 月单
- 距结束日期大于等于 30 天的季单/年单，例如 8 月 2 日看到的 12 月 30 日市场
- 没有 CLOB token id、没有活跃盘口、不能接单的市场

## 默认风控

系统默认使用稳健档：

- `MIN_24H_VOLUME_USD=1000`
- `MIN_ARBITRAGE_DEPTH_USD=100`
- `SLIPPAGE_BUFFER_CENTS=2`
- `ALLOW_NEAR_EXPIRY_LONG_PERIODS=true`
- `NEAR_EXPIRY_DAYS=30`

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

`start.sh` 默认会沿用已有 `polyarb.service` 里的 `POLYARB_DB` 数据库路径，避免重新启动时切到当前目录下的新空库。只有显式指定 `POLYARB_DB=... bash start.sh` 时，才会切换数据库。

常用服务命令：

```bash
sudo systemctl status polyarb
sudo journalctl -u polyarb -f
sudo systemctl restart polyarb
sudo systemctl stop polyarb
```

页面会显示：

- 当前扫描状态
- 收益概览：默认初始本金、BTC/ETH/XRP/SOL 分配本金、已用本金、累计收益、收益率
- 实时交易对：按到期时间最近排序，一个 event 一个序号，默认只显示接近实时币价的条件，其他条件折叠，默认 5 行滚动
- 模拟持仓：每笔未结算模拟成交形成的 YES/NO 两腿持仓、成本、最低赔付和预估收益
- 页面金额统一保留 2 位小数，不显示 `USDT` 单位
- 已过滤后的 BTC / ETH / XRP / SOL 市场数量
- 可分析的确定性交易对数量
- 最近套利机会
- 模拟成交记录

页面会按 BTC、ETH、XRP、SOL 分成四个相同排版的面板展示。页面上的“触发扫描”按钮会立即启动一次只读扫描；后台默认分别使用 Polymarket CLOB WebSocket 实时监听盘口更新。页面每 5 秒局部刷新指标和表格，不会整页刷新。

## 命令行用法

单次扫描（BTC / ETH / XRP / SOL）：

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
ALLOW_NEAR_EXPIRY_LONG_PERIODS=true
NEAR_EXPIRY_DAYS=30
PAPER_INITIAL_CAPITAL_USDT=10000
REFRESH_SECONDS=30
POLYARB_DB=data/paper.sqlite3
HOST=0.0.0.0
PORT=8787
```

如果系统已存在 `polyarb.service` 且旧数据库文件还在，`POLYARB_DB` 留空会自动复用旧路径。需要主动迁移数据库时，先复制旧 sqlite 文件，再用新路径启动：

```bash
POLYARB_DB=/path/to/paper.sqlite3 bash start.sh
```

示例：

```bash
SLIPPAGE_BUFFER_CENTS=3 MIN_ARBITRAGE_DEPTH_USD=500 bash start.sh
```

如果服务器访问 Polymarket 需要本机代理，先导出代理再启动。`start.sh` 会把代理变量写入 systemd 服务，避免终端关闭后服务丢失代理环境：

```bash
export http_proxy="http://127.0.0.1:7890"
export https_proxy="http://127.0.0.1:7890"
bash start.sh
```

脚本会同时传递大小写代理变量，并为 WebSocket 派生 `ws_proxy` / `wss_proxy`。重启后可检查：

```bash
sudo systemctl show polyarb -p Environment
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
- 收益统计默认初始本金为 `10000`，BTC 分配 `40%`，ETH 分配 `30%`，XRP 分配 `15%`，SOL 分配 `15%`。
- 同一资产同时有多个可执行机会时，按结束日期最近优先执行，再进入下一次扫描。
- 页面收益按已执行纸面成交的累计保证利润计算，不做未结算市值浮盈浮亏。
- 如果页面显示“行情源连接失败”，说明服务器无法访问 Polymarket 行情 API，需要检查服务器出站网络、DNS、代理或防火墙。
