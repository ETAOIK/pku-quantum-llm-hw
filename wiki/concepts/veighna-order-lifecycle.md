# 从买入 10 手到成交 6 手：订单生命周期

更新日期：2026-10-08。状态：源码追踪与教学例子；没有真实下单。

来源：[核心框架](../sources/vnpy.md)、[CTP 网关](../sources/vnpy-ctp.md)、[CTA 引擎](../sources/vnpy-ctastrategy.md)。

## 请求、订单和成交是三个对象

教学假设：某策略原净持仓为 0，调用 `buy(100, 10)`，希望以指定限价买入开多 10 手。假设回报先成交 4 手，再成交 2 手，其余 4 手最终撤销。价格与数量只是解释源码的例子。

| 时点 | 对象表示的事实 | 策略净持仓 |
| --- | --- | --- |
| 创建请求 | `OrderRequest.volume=10`，表达下单意图 | 0 |
| 本地发送返回 | 得到 `vt_orderid`，本地订单通常为 `SUBMITTING` | 0 |
| 第一笔成交回报 | `TradeData.volume=4`；订单状态回报可显示累计成交 4 | 4 |
| 第二笔成交回报 | 另一笔 `TradeData.volume=2`；累计成交 6 | 6 |
| 撤单请求发出 | 表达撤销剩余数量的意图，尚不能确认成功 | 6，仍可能有新成交 |
| 撤单成功回报 | 订单变为 `CANCELLED`，累计成交仍是 6 | 本例没有其他成交，因此为 6 |

表用于区分对象，不承诺订单与成交回调总按表格顺序抵达。`OrderData.traded` 是订单的累计成交量，`TradeData.volume` 是这一次成交量。依据：[object.py](../../raw/vnpy/vnpy/trader/object.py)，`OrderData/TradeData`；[CtaEngine.process_trade_event](../../raw/vnpy_ctastrategy/vnpy_ctastrategy/engine.py)，196–221 行。

## 沿着下单路径阅读

| 步骤 | 方法与源码 | 做什么 |
| --- | --- | --- |
| 1 | [CtaTemplate.buy/send_order](../../raw/vnpy_ctastrategy/vnpy_ctastrategy/template.py) | `buy` 设置买入和开仓方向；`send_order` 在 `trading=False` 时返回空列表 |
| 2 | [CtaEngine.send_order](../../raw/vnpy_ctastrategy/vnpy_ctastrategy/engine.py)，470–503 行 | 查合约，按价格与数量单位取整，选择订单路径 |
| 3 | 同文件 `send_server_order`，287–341 行 | 构造标准请求，通过开平转换器，发送并记录订单与策略映射 |
| 4 | [MainEngine.send_order](../../raw/vnpy/vnpy/trader/engine.py)，265–275 行 | 按合约的网关名路由请求 |
| 5 | [CtpTdApi.send_order](../../raw/vnpy_ctp/vnpy_ctp/gateway/ctp_gateway.py)，826–876 行 | 翻译 CTP 字段，调用原生下单方法，成功发出后生成本地订单号 |
| 6 | [TdApi::reqOrderInsert](../../raw/vnpy_ctp/vnpy_ctp/api/vnctp/vnctptd/vnctptd.cpp)，11091 行起 | 将 Python 字典转成 CTP 原生结构体并调用 SDK |

策略方法返回的是订单号**列表**。例如本版本针对 SHFE/INE 的平仓转换，在假设可平今仓 3 手、昨仓 5 手且没有冻结量时，平 6 手可拆成平今 3 和平昨 3。这个例子解释代码，不代替当前交易所规则查询。依据：[PositionHolding.convert_order_request_shfe](../../raw/vnpy/vnpy/trader/converter.py)，192 行起。

## 回报怎样找到策略

订单回报 `onRtnOrder` 用 `FrontID/SessionID/OrderRef` 生成本地订单号，并建立 `OrderSysID → orderid` 映射；成交回报 `onRtnTrade` 用这个映射生成标准成交对象。框架在本地订单号前加上网关名得到 `vt_orderid`。CTA 引擎发送订单时已经建立 `vt_orderid → strategy` 映射，因此可以找到该回报属于哪个策略。

依据：[CTP 网关](../../raw/vnpy_ctp/vnpy_ctp/gateway/ctp_gateway.py)，671–761 行；[标准对象](../../raw/vnpy/vnpy/trader/object.py)；[CTA 发送和处理回报](../../raw/vnpy_ctastrategy/vnpy_ctastrategy/engine.py)，196–221、287–341 行。

CTP 网关的 `on_order/on_trade` 通过基类发出事件；事件引擎分发给 OMS 和 CTA 引擎。OMS 更新订单与成交缓存，CTA 则对同一 `vt_tradeid` 去重后更新策略 `pos`。**不要在策略 `on_trade` 中再次按同一笔成交增减 `pos`**：这个回调执行前，引擎已经更新了它。

依据：[BaseGateway](../../raw/vnpy/vnpy/trader/gateway.py)，102–119 行；[OmsEngine](../../raw/vnpy/vnpy/trader/engine.py)，420–449 行；[CtaEngine.process_trade_event](../../raw/vnpy_ctastrategy/vnpy_ctastrategy/engine.py)，196–221 行。

## 三种持仓不能混成一个变量

- 策略 `pos`：属于这个策略的带符号净持仓，由归属于该策略的成交更新，可保存到策略 JSON。
- `PositionData`：网关提供的账户合约持仓信息，可包含多空方向、昨仓等字段。
- `AccountData`：资金账户信息，由网关查询/回报更新，再被 OMS 缓存。

依据：[数据对象](../../raw/vnpy/vnpy/trader/object.py)、[策略数据同步](../../raw/vnpy_ctastrategy/vnpy_ctastrategy/engine.py)，852–861 行、[OMS 回报处理](../../raw/vnpy/vnpy/trader/engine.py)，451–468 行。多策略同账户的核对与重启恢复需要进一步分析，不能假定这三个值天然一致。

## 撤单与异常边界

服务器撤单最终走 `reqOrderAction`，发出请求后等待订单回报；回测撤单却直接修改本地状态并回调。两者语义不同。依据：[CTP cancel_order](../../raw/vnpy_ctp/vnpy_ctp/gateway/ctp_gateway.py)，878–897 行；[回测 cancel_limit_order](../../raw/vnpy_ctastrategy/vnpy_ctastrategy/backtesting.py)，990 行起。

CTA 捕获策略异常时会设置状态并写日志，但该异常分支没有自动撤销活动订单；停止策略的正常路径包含撤单。哪些状态在异常后最终生效、是否需要额外恢复措施，是 [待验证问题](../questions.md)，本次没有修补上游源码。

理解检查：买入 10 手、成交回报为 4 手和 2 手时，`pos` 是多少？如果再次收到同一成交 ID，为什么不能再加一次？只有撤单请求时，能否把剩余数量当成已撤销？

相关：[架构总览](veighna-architecture.md) · [策略与回测](cta-strategy-and-backtesting.md) · [总索引](../index.md)
