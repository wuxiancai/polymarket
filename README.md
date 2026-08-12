# Polyarb

Polyarb 是一个 Polymarket BTC / ETH / XRP / SOL 日线及以上周期套利扫描与纸面模拟交易系统。

> 当前版本：`v2.7.1`；稳定回退点：`v1.0.0`。

系统默认首页为真实交易系统，模拟系统独立保留在 `/simulation`。

- 首页：用户登录 Polymarket 账户后，自动交易默认启用，和模拟盘共用扫描、交易对、价差和资金分配逻辑，自动买入 YES/NO 两腿并记录自动成交。
- 自动交易可在页面停止/启用；页面保留未完成订单取消能力。
- 私钥和 Relayer API key 只保存在进程内存或环境变量，不写入数据库。
- `/simulation`：原有纸面模拟系统，不接钱包、不真实下单。

真实交易依赖官方 `polymarket-client` SDK，需要 Python 3.11+。系统在登录和启用自动交易时会调用官方 geoblock 接口预检服务器出口 IP；如果所在地区被 Polymarket 限制开仓，页面会显示“区域受限”，并停止继续向真实交易接口提交重复开仓订单。

## 功能范围

纳入市场：

- BTC / ETH / XRP / SOL 的日线市场：`Up or Down on <日期>`、`above/below $X on <日期>`（含 `greater than / less than` 写法）、`between $X and $Y on <日期>`、`reach/hit $X on <日期>`
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
- `SLIPPAGE_BUFFER_CENTS=3`（真实开仓要求 YES + NO 不高于 97¢，保留至少 3¢/份套利空间）
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
2. 安装当前项目和 `polymarket-client`
3. 初始化本地 SQLite 数据库

`deploy.sh` 会自动优先选择 `python3.13 / python3.12 / python3.11`，满足真实交易 SDK 的 Python 版本要求。

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

## 一键停止系统

```bash
cd ~/polymarket
bash stop.sh
```

停止脚本会先停止 systemd 服务 `polyarb`，再兜底终止本机直接运行的 `python -m polyarb` 进程。脚本不删除数据库、日志或运行数据，可随时用 `bash start.sh` 重新启动。

如果使用了自定义服务名：

```bash
SERVICE_NAME=polyarb bash stop.sh
```

页面会显示：

- 真实账户：钱包地址、签名地址、账户类型、pUSD 余额、总资产
- 当前持仓与已结束持仓收益
- 未完成订单和最近成交
- 自动真实交易状态、启用/停止按钮和自动成交记录
- 自动兑换记录：市场结算后自动调用 Polymarket redeem，胜方 pUSD 回到余额并释放占用资金
- 实时交易对：首页与 `/simulation` 共用 scanner 实时交易对，按 event 折叠，默认显示接近实时币价的条件
- 实时套利机会：和模拟盘共用扫描结果，状态显示“已成交”“已触发，未成功”“区域受限”“可成交”“仅观察”等；触发但资金不足时说明列显示“资金不足”
- 资金分配设置：首页与 `/simulation` 共用同一份 SQLite settings，BTC / ETH / XRP / SOL 使用资金的百分比，可手动修改；保存需密码确认，密码只保存哈希，不落明文，保存后立即影响模拟和真实自动交易预算
- 当前扫描状态
- 收益概览：默认初始本金、BTC/ETH/XRP/SOL 分配本金、已用本金、累计收益、收益率
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
SLIPPAGE_BUFFER_CENTS=3
ALLOW_NEAR_EXPIRY_LONG_PERIODS=true
NEAR_EXPIRY_DAYS=30
PAPER_INITIAL_CAPITAL_USDT=10000
REFRESH_SECONDS=30
POLYARB_DB=data/paper.sqlite3
HOST=0.0.0.0
PORT=8787
POLYMARKET_WALLET_ADDRESS=
POLYMARKET_PRIVATE_KEY=0x...
POLYMARKET_RELAYER_API_KEY=
POLYMARKET_RELAYER_API_KEY_ADDRESS=
POLYMARKET_AUTO_LOGIN=false
```

真实交易凭证也可在首页登录表单中填写；登录态只保留在当前进程内，不持久化私钥。默认不会在服务启动时自动登录，只有显式设置 `POLYMARKET_AUTO_LOGIN=true` 才会读取环境变量自动连接。

`POLYMARKET_WALLET_ADDRESS` 可留空：留空时会自动使用该签名者的 Polymarket 默认存款钱包。若你在 Polymarket 网页显示余额但页面为 0，通常是因为把签名者地址填到了“钱包地址”；请保持留空，或填写 Polymarket 个人资料中的地址。“钱包私钥”必须是与该地址匹配的签名者私钥。Relayer API 密钥选填，填写时必须同时填写 Relayer API 地址（签名者地址）。

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
- 已结算真实持仓通过 `SecureClient.redeem_positions()` 自动兑换，后台每 60 秒检查 redeemable positions，不需要依赖官网“自动兑换奖金”设置。
- 真实自动交易下单前通过 `https://polymarket.com/api/geoblock` 检查地区限制；新加坡等 `close-only` 地区会直接标记“区域受限”，避免每次扫描都重复调用下单接口。官方文档见 [Geographic Restrictions](https://docs.polymarket.com/developers/CLOB/geoblock)。
- 收益统计默认初始本金为 `10000`，BTC 分配 `40%`，ETH 分配 `30%`，XRP 分配 `15%`，SOL 分配 `15%`；可在首页或 `/simulation` 页面按需修改并立即生效。
- 同一资产同时有多个可执行机会时，按结束日期最近优先执行，再进入下一次扫描。
- 页面收益按已执行纸面成交的累计保证利润计算，不做未结算市值浮盈浮亏。
- 如果页面显示“行情源连接失败”，说明服务器无法访问 Polymarket 行情 API，需要检查服务器出站网络、DNS、代理或防火墙。
