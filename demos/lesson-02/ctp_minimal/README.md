# 第二节：vnpy_ctp 行情与单次仿真交易 DEMO

直接继承 `vnpy_ctp.api.TdApi` 和 `MdApi`，实现交易前置认证登录、行情前置登录、订阅指定合约及打印推送。业务代码集中在 [demo.py](demo.py)，不使用 `MainEngine`、`CtpGateway` 或 CTA 策略引擎，默认持续打印行情；显式 `--trade` 可启用单次 SimNow 价格触发交易。

## 运行

在仓库根目录执行。Python >=3.10；这台 Mac 已创建 `.venv` 并安装完成，用户提供的账号已放入本地配置，可直接执行第 3 步。

1. 新机器安装依赖：

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install -r demos/lesson-02/ctp_minimal/requirements.txt
   ```

   Mac 需要 Xcode Command Line Tools。依赖文件将 Mac 固定到官方 `6.7.7.2` 完整 Gitee 源码提交，其他系统使用 `6.7.11.4`，核心依赖固定到 `vnpy 4.5.0`。

2. 新机器创建本地配置，填入自己的 SimNow 账号：

   ```bash
   cp demos/lesson-02/ctp_minimal/config.example.json demos/lesson-02/ctp_minimal/config.local.json
   chmod 600 demos/lesson-02/ctp_minimal/config.local.json
   ```

   配置字段为 `userid/password/brokerid/td_address/md_address/appid/auth_code`，均保留为字符串。不要在这台已配置的机器上用空模板覆盖本地账号。模板只包含空账号字段与用户指定的公开仿真前置参数。

3. 启动：

   ```bash
   .venv/bin/python demos/lesson-02/ctp_minimal/demo.py
   ```

默认持续订阅 `rb2701`（螺纹钢）、`ag2612`（白银）、`au2612`（黄金）。原始 API 使用合约代码，**不加 `.SHFE` 后缀**。

选取依据：2026-10-08 查阅[上期所日周数据](https://www.shfe.com.cn/reports/tradedata/dailyandweeklydata/)，可读取的 2026-09-30 页面快照分别显示成交量 482,408、230,063、151,024 手，均为对应品种中成交较活跃的月份。这是近期页面快照，部分收盘字段为空，不作为完整日终统计或 10 月 8 日实时成交量。实际 SimNow 合约是否有效及是否有推送，以柜台回报为准；月份到期或活跃合约变化后可通过 `--symbols` 更换。

覆盖合约或运行一段时间：

```bash
.venv/bin/python demos/lesson-02/ctp_minimal/demo.py --symbols rb2701 ag2612 au2612 --timeout 30 --duration 10
```

默认 `--timeout 0 --duration 0`：连接或首条行情迟迟未到时持续等待，每 30 秒打印等待提示；收到推送后逐条打印，直到按 Ctrl+C。没有新的推送时保持运行，不重复制造行情。

断线时 SDK 自动尝试重连；交易通道重新认证登录，行情通道重新登录后订阅全部指定合约。明确的认证、登录、订阅错误或本地请求发送失败仍返回退出码 1，便于发现账号/合约配置问题。

`--timeout` 大于 0 时才启用启动阶段的限时等待；`--duration` 大于 0 时才在首条行情后限时退出。上面的命令用于限时检查；日常持续运行使用不带这些参数的启动命令。正常定时结束或 Ctrl+C 返回 0。

## 单次价格触发交易

用户已授权完成一次 SimNow 买入开仓闭环。规则为：交易准备完成、`rb2701` 最新价严格大于阈值时，以当时卖一价发出限价买入开仓 1 手，最多尝试一次；启动时已经超过阈值也会触发，不要求先观察上穿。测试门槛为 3080，用于执行验证，不是收益预测。

```bash
.venv/bin/python demos/lesson-02/ctp_minimal/demo.py --trade --trade-symbol rb2701 --threshold 3080
```

本机已经完成本次交易；`runtime/single-order.json` 存在时会拒绝再次启用下单。日常使用上面的普通行情启动命令。需要另一次独立实验时，先核对柜台订单/持仓和本地记录，再人工归档旧记录；脚本不会自动删除记录或重新下单。

交易模式只接受本次已验证的 SimNow broker/app/前置配置，默认不下单。它在认证登录后完成结算确认与合约查询，并检查价格跳动、交易量限制和合约交易标志。触发前检查最新价、双边盘口、盘口量、涨跌停范围、交易日及行情到达时间（最近 3 秒）；SDK 无效价格在打印中显示为 `null`，不能触发交易。

发送前独占创建本地单次记录；请求发送失败、拒单、断线重连或脚本重启都不会重发。`onRtnOrder` 打印订单状态，`onRtnTrade` 对本次订单的成交去重；只有订单全部成交并收到合计 1 手成交回报，才标记 `completed`。成交后继续打印行情，按 Ctrl+C 退出。本次闭环建立仿真多头持仓，没有自动平仓规则。

退出时若订单尚未结束，尝试撤销并等待最多 3 秒；若未得到结束确认，会提示核对柜台，本地记录继续保留。该撤单分支只有离线测试证据，本次实际委托直接成交。显式限时的交易检查在未完成闭环时返回 1，不能把“请求发送成功”当作“成交成功”。

## 回调顺序

```text
创建 TdApi → registerFront → init
  onFrontConnected → reqAuthenticate
  onRspAuthenticate 成功 → reqUserLogin
  onRspUserLogin 成功 → 行情模式就绪
  交易模式：结算确认 → 查询交易合约 → 交易就绪 → 主线程继续
创建 MdApi → registerFront → init
  onFrontConnected → reqUserLogin
  onRspUserLogin 成功 → 回调发送全部 subscribeMarketData（重连后也执行）
  onRspSubMarketData → 打印订阅确认或错误
  onRtnDepthMarketData → 打印与缓存行情
主线程：交易就绪 + 有效行情 + 价格超过阈值 → reqOrderInsert（最多一次）
  onRtnOrder → 更新订单状态
  onRtnTrade → 去重并累计成交 → 全部成交闭环完成
断线 → SDK 自动重连 → 再次登录 → 行情通道恢复全部订阅
Ctrl+C / 显式限时 / 明确失败 → 主线程 finally 关闭 API，恢复原工作目录
```

打印合约、交易日、自然日、更新时间、毫秒、最新价、买一、卖一及累计成交量。下面是**格式示意，不是真实行情记录**：

```text
交易认证成功，发起登录
交易登录成功
行情登录成功
订阅确认：rb2701
行情 {"InstrumentID": "rb2701", "LastPrice": 100, ...}
```

## 版本与本次验证

验证日期：2026-10-08，北京时间。

| 检查 | 结果 |
| --- | --- |
| 离线流程测试 | 22 个 unittest 通过；覆盖行情流程、交易准备、无效报价、严格阈值、防重发、订单/成交区分、拒单和退出撤单 |
| 本机环境 | macOS arm64、Python 3.12.2、vnpy 4.5.0、vnpy_ctp 6.7.7.2；依赖检查通过 |
| SDK 构建与加载 | 从官方完整源码编译安装成功，真实 SDK 加载与交易 API 初始化/关闭成功 |
| 首版前置 TCP 检查 | 两端口曾连接被拒绝，属于先前检查结果 |
| 本次前置 TCP 检查 | 2026-10-08 更新本地账号后，交易端口 30001、行情端口 30011 均可连接 |
| 首版限时检查 | 交易前置连接/登录阶段等待 10 秒后超时，退出码 1，正常关闭 API |
| 本版持续运行检查 | 默认启动真实 SDK 后超过 35 秒仍运行，输出等待提示；Ctrl+C 正常关闭 API，退出码 0 |
| 08:47 新账号认证、登录和行情 | 交易连接/认证/登录、行情登录、三个订阅确认均成功，收到 3 条行情推送；限时检查退出码 0 |
| 连续有效行情 | 09:02 三个默认合约的双边盘口、非零累计成交量持续更新 |
| 单次价格触发交易 | 结算确认、合约查询、阈值触发、订单全部成交和 1 手成交回报均通过；成交后继续打印，共收到 121 条行情，限时退出码 0 |

`6.7.11.4` 在本机因 C++ 封装与 Mac SDK 头文件不匹配而编译失败；`6.7.7.2` 的 PyPI 源码包因缺少 framework 而链接失败。使用 [官方 Mac 兼容版本的完整源码](https://github.com/vnpy/vnpy_ctp/releases/tag/6.7.7.2) 可在本机完成构建，所以 Mac 的依赖使用固定 Gitee Git 提交，而非该版本的 PyPI 源码包。原始 `raw/` 快照保持不变；本次执行的 CTP 版本与其 `6.7.11.5` 不同。

代码根据安装版本使用不同的 API 创建签名：6.7.11 系列传路径与 `False`，6.7.7 系列只传路径。`False` 对应上游网关的测试柜台协议模式；账号与前置仍决定连接环境。实际新版本分支只通过离线测试，未在本机加载成功。

本次使用用户原样提供的前置地址，没有切换其他环境。SimNow 当前网站页面未能成功读取，无法将地址或服务时间写成已核实的官方现状。若出现连接拒绝/超时，先核对 [SimNow 官网](https://www.simnow.com.cn/)、服务时段和本机网络；若登录及订阅已确认但没有推送，再检查合约与行情是否更新。

## 新账号初次联调记录（历史）

2026-10-08 北京时间约 08:47，以本地新账号运行 `--timeout 15 --duration 3`，三个默认合约各收到一条推送，`TradingDay/ActionDay` 为 `20261008`，数据内 `UpdateTime` 为 `07:47:54.500`。这里记录的是服务器字段，不将其当作本机时间或新鲜实时报价。

三条推送的累计成交量均为 0，买一/卖一为 `1.7976931348623157e+308`（无效报价哨兵），不能用这些买卖价下单。本次确认连接、账号认证登录和行情订阅推送链路；连续更新的有效盘口仍需另行观察。检查命令显式限时，日常默认运行持续等待并打印，按 Ctrl+C 退出。

本次没有发送交易订单；本地账号替换不进入 Git，运行日志保留在被忽略的 `runtime/`。

## 交易闭环验收

2026-10-08 北京时间约 09:05，在已授权的 SimNow 账号上运行 `--trade --trade-symbol rb2701 --threshold 3080 --timeout 20 --duration 20`：交易准备和价格触发成功，收到订单全部成交状态及对应 1 手成交回报，本地记录为 `completed`；随后仍持续打印行情，20 秒限时检查共收到 121 条推送，退出码 0。

账号、订单标识、触发/委托/成交价格和原始日志仅保存在本地被忽略的 `config.local.json`、`runtime/single-order.json` 与 `runtime/single-trade-validation.log`。公开作业只记录规则、阶段通过情况和验证边界。结果不代表策略收益有效，也不代表柜台持仓核对、自动平仓或原始新 SDK 分支已验证。

## 离线测试与本地文件

```bash
python3 -m unittest discover -s demos/lesson-02/ctp_minimal/tests -v
```

测试只加载假 API，不访问服务器，不使用用户账号。`config.local.json`、`.venv/`、`runtime/` 和 Python 缓存均被 Git 忽略。SDK 流文件及间接导入的 `.vntrader` 配置限制在 DEMO 的 `runtime/`；账号、原始测试日志和 SDK 运行文件不提交。

代码依据：[CTP 网关登录与订阅实现](../../../raw/vnpy_ctp/vnpy_ctp/gateway/ctp_gateway.py)、[底层 API 导出](../../../raw/vnpy_ctp/vnpy_ctp/api/__init__.py)。学习说明见 [Wiki DEMO 页面](../../../wiki/concepts/ctp-minimal-demo.md)。
