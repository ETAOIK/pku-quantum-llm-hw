# 源码摘要：vnpy_ctp 交易接口

更新日期：2026-10-08。状态：完成 Python 网关和关键 C++ 桥接路径静态阅读；未编译或连接柜台。

## 来源与版本

- 官方下载地址：[Gitee vnpy_ctp](https://gitee.com/vnpy/vnpy_ctp)。
- 分支：`main`；提交：`1be9bfb5292208e5c258cc769c90be4abe83f9a9`；上游提交日期：2026-10-05。
- 包版本：`6.7.11.5`，见 [pyproject.toml](../../raw/vnpy_ctp/pyproject.toml)。[README](../../raw/vnpy_ctp/README.md) 说明基于 CTP 期货版 6.7.11 接口封装；包版本与底层 API 版本不要混用。
- 完整快照：[raw/vnpy_ctp](../../raw/vnpy_ctp/README.md)，共 93 个上游 Git 文件/符号链接，包括 SDK 库与头文件；保留 [许可证](../../raw/vnpy_ctp/LICENSE)。
- 提交和树哈希见 [源码版本清单](../../raw/source-lock.json)。

## 它是协议适配层

策略发送的是 VeighNa 的 `OrderRequest`，CTP 需要的是自己的字段，例如合约、买卖方向、开平标志、委托类型和数量。这个模块在两套表达之间转换，同时把 CTP 的回调转换成 VeighNa 的 `TickData`、`OrderData`、`TradeData` 等标准对象。

主要依据：[ctp_gateway.py](../../raw/vnpy_ctp/vnpy_ctp/gateway/ctp_gateway.py)，枚举映射、`CtpGateway`、`CtpMdApi` 与 `CtpTdApi`。

## 两条 API 通道

| 通道 | 对象 | 核心职责与源码位置 |
| --- | --- | --- |
| 行情 | `CtpMdApi` | 登录、订阅、把深度行情转为 Tick；`onRtnDepthMarketData`，309–374 行 |
| 交易 | `CtpTdApi` | 认证登录、合约查询、下单撤单、委托/成交/资金/持仓回报；426 行起 |
| 网关入口 | `CtpGateway` | 构造两个 API，连接时分别传入地址；169–200 行 |

交易通道在连接成功后走认证或直接登录；登录成功记录 `FrontID/SessionID`，请求结算确认，再请求合约资料。合约查询完成后重放此前缓存的订单与成交回报。这些是本版本实现的步骤，不能只用“服务器已连接”判断业务准备完成。依据：[ctp_gateway.py](../../raw/vnpy_ctp/vnpy_ctp/gateway/ctp_gateway.py)，463–508、538–550、624–669 行。

行情回调会过滤没有时间戳、以及尚未取得合约信息的行情；按代码规则处理日期，并设置 `Asia/Shanghai` 时区，最后调用 `gateway.on_tick`。交易回报在合约资料未就绪时是缓存，行情是过滤，两者不同。依据：同文件 309–374、671–677、734–739 行。

## 一次下单怎样返回

`CtpTdApi.send_order` 先检查开平和订单类型，构造 CTP 字段字典，再调用 `reqOrderInsert`。若本地调用返回非零值，则记录错误并返回空字符串；否则构造 `frontid_sessionid_orderref` 订单号，推送本地 `SUBMITTING` 状态，返回带网关前缀的订单号。

后续 `onRtnOrder` 才转换柜台订单状态；`onRtnTrade` 通过 `OrderSysID` 查本地订单号并转换成交信息。所以“返回订单号”只说明本地发送路径走通，不能保证柜台接受或交易所成交。依据：[ctp_gateway.py](../../raw/vnpy_ctp/vnpy_ctp/gateway/ctp_gateway.py)，671–761、826–876 行。

`cancel_order` 调用 `reqOrderAction` 发送撤单请求，没有在这里直接将订单设为已撤销。结果要通过回报确认。依据：同文件 878–897 行。

## Python 与 C++ 的边界

[api/__init__.py](../../raw/vnpy_ctp/vnpy_ctp/api/__init__.py) 导入编译扩展 `vnctpmd/vnctptd`。C++ 行情回调 `OnRtnDepthMarketData` 复制结构体并放入任务队列；`processTask` 取出任务；`processRtnDepthMarketData` 获得 Python GIL，把结构体转成字典，再回调 Python 方法。

阅读定位：[vnctpmd.cpp](../../raw/vnpy_ctp/vnpy_ctp/api/vnctp/vnctpmd/vnctpmd.cpp)，196、226、529 行；成交桥接见 [vnctptd.cpp](../../raw/vnpy_ctp/vnpy_ctp/api/vnctp/vnctptd/vnctptd.cpp)，6988–7030 行。下单字典到原生结构体的转换见同文件 `reqOrderInsert`，11091 行起。

这里至少涉及“CTP 回调 → C++ 任务队列 → Python 网关 → VeighNa 事件队列”几个阶段；不能把 CTP 原生回调线程直接当作策略执行线程。

## 运行边界

[构建配置](../../raw/vnpy_ctp/meson.build) 使用 Meson 与 pybind11 构建扩展，并针对不同系统处理 SDK 库；[README](../../raw/vnpy_ctp/README.md) 的 Mac 说明要求源码编译及 Xcode 开发工具。下载到的 `.framework` 等文件是上游提供的原始库，本次没有编译、加载或反编译它们。

本次只学习关键路径，不验证交易时段、实际柜台参数、重连行为或 SDK 的二进制兼容性。完整交易链路见 [订单生命周期](../concepts/veighna-order-lifecycle.md)。

相关：[核心框架来源](vnpy.md) · [CTA 来源](vnpy-ctastrategy.md) · [总索引](../index.md)
