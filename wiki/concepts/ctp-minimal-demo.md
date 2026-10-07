# 底层 CTP 最小 DEMO：连接、登录、订阅与打印

更新日期：2026-10-08。状态：开发与离线测试完成；本机 SDK 构建加载成功；外部连接超时，端到端行情尚未验证。

来源：[本项目 demo.py](../../demos/lesson-02/ctp_minimal/demo.py)、[上游 CTP 摘要](../sources/vnpy-ctp.md)、[官方 Mac 兼容版本说明](https://github.com/vnpy/vnpy_ctp/releases/tag/6.7.7.2)。运行命令与完整验收记录见 [DEMO README](../../demos/lesson-02/ctp_minimal/README.md)。

## 从一个订阅动作理解异步 API

教学目标：订阅 `rb2701`，收到新行情时打印最新价、买一、卖一等字段。该代码由 LLM 选择作为默认例子，合约在当前柜台的有效性与是否正在产生行情尚未得到验证；可用 `--symbols` 改成其他明确的合约代码。

主动调用 `registerFront/init` 只是发起网络连接。SDK 确认连接后才回调 `onFrontConnected`；此时发送认证或登录。登录成功回调到来后才继续订阅；行情以后通过 `onRtnDepthMarketData` 推送。程序没有用固定的 sleep 时间来假定登录成功，而是等待回调设置的线程事件。

## 两条通道的分工

| 通道 | 主动请求 | 关键回调 | 本 DEMO 的动作 |
| --- | --- | --- | --- |
| 交易 `TdApi` | `reqAuthenticate`、`reqUserLogin` | `onRspAuthenticate`、`onRspUserLogin` | 顺序完成认证和账号登录 |
| 行情 `MdApi` | `reqUserLogin`、`subscribeMarketData` | `onRspUserLogin`、`onRspSubMarketData`、`onRtnDepthMarketData` | 登录后订阅、打印订阅回报和行情 |

请求函数的返回码表示本地请求是否成功发出；回调中的 `ErrorID` 表示服务器响应是否成功，两者分别检查。网络已连接、账号已登录、合约订阅已确认、实际收到行情，是四个独立阶段。

依据：[上游 CtpMdApi/CtpTdApi](../../raw/vnpy_ctp/vnpy_ctp/gateway/ctp_gateway.py) 与 [DEMO](../../demos/lesson-02/ctp_minimal/demo.py) 中的 `send_request/check_response/wait_for`。

## 为什么保持这个边界

这个作业从底层 Python API 开始，因此业务代码直接继承 API 类，没有通过网关、事件引擎或 CTA 组织交易。标准导入 `vnpy_ctp.api` 仍会间接导入包入口中的网关依赖，所以安装时需要核心 `vnpy`；不应误认为业务没用主引擎就完全不需要核心包。

初始化前建立独立 `runtime/.vntrader` 并切换运行目录，用于隔离该间接导入的配置与 SDK 流文件；退出时恢复目录。原生 `exit` 会等待回调线程退出，因此在主线程的 `finally` 关闭 API，不能在 API 回调线程里调用它。

依据：[包入口](../../raw/vnpy_ctp/vnpy_ctp/__init__.py)、[运行目录选择](../../raw/vnpy/vnpy/trader/utility.py)、[MdApi::exit](../../raw/vnpy_ctp/vnpy_ctp/api/vnctp/vnctpmd/vnctpmd.cpp) 及 DEMO 的 `run`。

## 源码版本与执行版本

学习快照仍是 `vnpy_ctp 6.7.11.5`。本机尝试安装 `6.7.11.4` 失败；改用官方完整 Gitee 源码提交 `fa199f70dac9e242c20e925c17e2241b877e694f`，实际运行为 `6.7.7.2`，核心为 `vnpy 4.5.0`。两条创建 API 的签名不同，代码对已支持版本分支作了处理。不能把旧 SDK 的导入成功当成新 SDK 的兼容性验证。

## 验收证据与下一步

9 个假 API 测试通过，验证了正常请求链和失败时停止、退出流程。真实 SDK 编译安装、依赖检查、导入和交易 API 启动/关闭已完成；用户给定的两端口 TCP 连接被拒绝，DEMO 等待交易前置 10 秒后超时。因此没有真实登录成功、订阅确认或行情记录；测试打印示意不能替代这些证据。

本地账号和原始运行文件在 Git 忽略范围内；仓库仅保存空账号模板与代码。当给定服务恢复可达后，重新运行 DEMO，分别观察连接、认证、登录、订阅确认和至少一条行情，再把实际结果补入本页。

理解检查：`reqUserLogin` 返回 0 是否代表账号已经登录？`onRspSubMarketData` 成功是否代表已经收到一条行情？API 为什么在主线程关闭？

相关：[第二节作业](../lessons/lesson-02.md) · [架构总览](veighna-architecture.md) · [待解问题](../questions.md) · [总索引](../index.md)
