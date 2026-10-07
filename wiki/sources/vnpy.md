# 源码摘要：vnpy 核心框架

更新日期：2026-10-08。状态：完成交易主链路静态阅读；未安装或启动平台。

## 来源与版本

- 官方下载地址：[Gitee vnpy](https://gitee.com/vnpy/vnpy)。
- 分支：`master`；提交：`c6e231caf32b7fc97e6459817fff66458cf7e7c4`。
- 源码版本：`4.5.0`，见 [包入口](../../raw/vnpy/vnpy/__init__.py)。上游提交日期：2026-10-06。
- 本地完整快照：[raw/vnpy](../../raw/vnpy/README.md)，共 210 个上游文件；保留 [MIT 许可证](../../raw/vnpy/LICENSE)。
- 下载、树哈希与文件统计见 [源码版本清单](../../raw/source-lock.json)。说明只适用于该提交。

## 先理解它负责什么

假设策略想买入 10 手某个合约。核心框架提供统一的订单对象和网关路由，把请求交给选定的交易接口；接口发回行情、委托、成交、持仓和账户信息时，事件引擎再分发给订阅者。策略判断和 CTP 协议转换由另外两个模块承担。

## 已读源码地图

| 文件与定位 | 本次阅读结论 |
| --- | --- |
| [event/engine.py](../../raw/vnpy/vnpy/event/engine.py)，`EventEngine`，44–120 行 | 使用线程安全队列；一个分发线程按事件类型调用处理函数，另一个线程产生定时事件 |
| [trader/engine.py](../../raw/vnpy/vnpy/trader/engine.py)，`MainEngine`，94–175 行 | 构造时启动事件引擎、创建内置引擎；`add_gateway` 注册接口，`add_app` 创建应用引擎 |
| 同文件，`MainEngine.send_order`，265–275 行 | 按 `gateway_name` 转交请求，不自行判断策略买卖方向 |
| 同文件，`OmsEngine`，375–480 行 | 缓存 Tick、订单、成交、账户、持仓、合约，并维护活动订单和开平转换器 |
| [trader/gateway.py](../../raw/vnpy/vnpy/trader/gateway.py)，`BaseGateway.on_*` | 将网关回报包装成标准事件；行情等同时发通用事件和特定标的事件 |
| [trader/object.py](../../raw/vnpy/vnpy/trader/object.py)，`OrderRequest/OrderData/TradeData` | 区分请求、订单状态和单次成交，用 `vt_symbol/vt_orderid/vt_tradeid` 建立关联 |
| [trader/converter.py](../../raw/vnpy/vnpy/trader/converter.py)，`PositionHolding` | 根据持仓、冻结量与开平模式处理请求，平仓可能拆成多笔 |
| [trader/utility.py](../../raw/vnpy/vnpy/trader/utility.py)，`BarGenerator/ArrayManager` | 将 Tick 聚合为 K 线，维护滚动数组并调用 TA-Lib 计算指标 |
| [启动例子](../../raw/vnpy/examples/veighna_trader/run.py) | 在同一个主引擎中接入 CTP 与 CTA 应用，示例还导入了另外两个应用模块 |

## 三个需要准确理解的地方

**事件分发有顺序和耗时。** `_process` 在同一个分发线程中逐个调用处理函数，没有给每个策略单独创建线程。根据这个实现可以推断，耗时回调会延迟后续事件处理；本次没有测量延迟。`_run` 只处理队列空异常，不能据此认为任意处理函数异常都会自动被隔离。依据：[事件引擎](../../raw/vnpy/vnpy/event/engine.py)，57–80 行。

**OMS 的状态来自回报。** `process_account_event` 缓存账户对象，`process_position_event` 缓存持仓对象。不能把它描述为“核心框架收到每笔成交后自动重建完整资金账本”。CTA 的策略净持仓、网关的账户持仓和可用资金是不同对象。依据：[OMS](../../raw/vnpy/vnpy/trader/engine.py)，439–468 行。

**创建应用与连接服务器是独立步骤。** `add_gateway` 只是构造接口，`connect` 才调用其连接方法。`add_app` 创建 CTA 引擎后，其 `init_engine` 在 [CTA 界面构造](../../raw/vnpy_ctastrategy/vnpy_ctastrategy/ui/widget.py)，42 行被调用。无界面流程不能仅凭 `add_app` 就假定所有策略事件已经注册。

## 运行边界

[pyproject.toml](../../raw/vnpy/pyproject.toml) 声明 Python >=3.10，并列出 PySide6、NumPy、TA-Lib 等依赖；源码版本满足 CTA 插件声明的 `vnpy>=4.4.0` 下界，但这不是运行兼容性测试。

[utility.py](../../raw/vnpy/vnpy/trader/utility.py) 的运行目录选择，以及 `MainEngine.__init__` 的 `os.chdir(TRADER_DIR)`，意味着运行路径不一定是当前仓库。默认数据库配置是 SQLite，驱动由 [get_database](../../raw/vnpy/vnpy/trader/database.py) 动态加载；三个源码仓库并不包含 `vnpy_sqlite`。

本次没有逐一分析 Alpha 研究、图表、RPC、通知等全部子系统。下一步的阅读入口是 [架构总览](../concepts/veighna-architecture.md) 和 [订单生命周期](../concepts/veighna-order-lifecycle.md)。

相关：[CTP 来源](vnpy-ctp.md) · [CTA 来源](vnpy-ctastrategy.md) · [总索引](../index.md)
