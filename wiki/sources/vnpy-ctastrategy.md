# 源码摘要：vnpy_ctastrategy 策略应用

更新日期：2026-10-08。状态：完成模板、实盘引擎、回测撮合和双均线示例的静态阅读；未运行策略。

## 来源与版本

- 官方下载地址：[Gitee vnpy_ctastrategy](https://gitee.com/vnpy/vnpy_ctastrategy)。
- 分支：`main`；提交：`7a8768de9784dda35a7b261a7ade1dbfbff50919`；上游提交日期：2026-10-05。
- 版本：`1.5.0`，见 [包入口](../../raw/vnpy_ctastrategy/vnpy_ctastrategy/__init__.py)。
- 完整快照：[raw/vnpy_ctastrategy](../../raw/vnpy_ctastrategy/README.md)，共 38 个文件；保留 [MIT 许可证](../../raw/vnpy_ctastrategy/LICENSE)。
- [依赖配置](../../raw/vnpy_ctastrategy/pyproject.toml) 声明 `vnpy>=4.4.0`；版本清单见 [source-lock.json](../../raw/source-lock.json)。

## 它负责策略的生命周期

这是面向单标的 CTA 策略的应用。[CtaStrategyApp](../../raw/vnpy_ctastrategy/vnpy_ctastrategy/__init__.py) 把应用名、引擎类和界面类交给核心框架；真正的策略逻辑继承 `CtaTemplate`，由引擎调用它的回调。

| 对象与源码 | 职责 |
| --- | --- |
| [CtaTemplate](../../raw/vnpy_ctastrategy/vnpy_ctastrategy/template.py) | 参数与变量、`inited/trading/pos` 状态、行情/订单/成交回调、买卖开平方法 |
| [CtaEngine](../../raw/vnpy_ctastrategy/vnpy_ctastrategy/engine.py) | 实盘事件分发、策略管理、请求路由、本地停止单、状态保存 |
| [BacktestingEngine](../../raw/vnpy_ctastrategy/vnpy_ctastrategy/backtesting.py) | 历史数据回放、模拟撮合、收益统计与参数优化入口 |
| [DoubleMaStrategy](../../raw/vnpy_ctastrategy/vnpy_ctastrategy/strategies/double_ma_strategy.py) | 用快慢均线交叉演示从 Tick、K 线、指标到交易决策 |

## 实盘引擎的关键实现

`symbol_strategy_map` 按合约找到策略；`orderid_strategy_map` 按订单找到策略；`strategy_orderid_map` 跟踪策略活动委托。`process_tick_event` 对 `inited=True` 的策略回调 `on_tick`；模板的 `send_order` 则检查 `trading`。所以停止交易后的策略仍可能接收行情，接收行情与允许下单是两道条件。依据：[engine.py](../../raw/vnpy_ctastrategy/vnpy_ctastrategy/engine.py)，79–99、149–194 行；[template.py](../../raw/vnpy_ctastrategy/vnpy_ctastrategy/template.py)，233–253 行。

`process_trade_event` 用 `vt_tradeid` 去重，通过订单映射找到所属策略，按买入加、卖出减的方式更新净持仓 `pos`，再调用 `on_trade`，最后保存变量。它不是直接用全账户持仓覆盖策略持仓。依据：[engine.py](../../raw/vnpy_ctastrategy/vnpy_ctastrategy/engine.py)，196–221 行。

下单前读取合约，按最小价格和数量单位取整，再选择限价单、服务器停止单或本地停止单；发送服务器订单时，还经过核心的开平转换器，一次策略调用可能产生多个订单号。依据：同文件 287–341、470–503 行。

`call_strategy_func` 捕获回调异常并将 `trading/inited` 设为 False、写日志；这个异常分支没有直接调用撤销全部活动委托。`stop_strategy` 才明确包含取消活动订单的步骤，不能把两条路径等同。初始化与启动函数在回调后还会赋状态，本次没有验证异常情况下的最终状态。依据：同文件 618–634、679–756 行。

## 已阅读的示例与回测部分

双均线示例 `on_init` 创建 `BarGenerator` 与 `ArrayManager` 并加载历史 K 线；`on_tick` 做 K 线聚合；`on_bar` 更新数组、计算两条均线，比较前后两个时刻的严格大小关系，结合 `pos` 开平仓。详细例子见 [策略与回测笔记](../concepts/cta-strategy-and-backtesting.md)。

回测的 `new_bar/new_tick` 先撮合已有订单，再调用策略。`cross_limit_order` 满足价格条件后直接全量成交，没有按盘口数量模拟部分成交。`DailyResult.calculate_pnl` 计算持仓和交易盈亏，扣除手续费与滑点。依据：[backtesting.py](../../raw/vnpy_ctastrategy/vnpy_ctastrategy/backtesting.py)，666–760、1110–1154 行。

## 未完成与待验证

本次阅读了 [上游回测测试](../../raw/vnpy_ctastrategy/tests/test_backtesting.py) 中的下一根 K 线撮合等案例，以及 [实盘引擎测试](../../raw/vnpy_ctastrategy/tests/test_cta_engine.py) 的假网关设计，没有执行这些测试。其他策略、优化器、GUI 细节与完整容错机制没有逐一分析；模拟资金、历史行情和实盘登录均未配置。

相关：[架构总览](../concepts/veighna-architecture.md) · [订单生命周期](../concepts/veighna-order-lifecycle.md) · [总索引](../index.md)
