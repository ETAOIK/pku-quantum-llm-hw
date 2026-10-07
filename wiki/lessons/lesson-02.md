# 第二节课作业：Wiki 学习与 CTP 行情 DEMO

更新日期：2026-10-08。状态：Wiki、源码阅读与底层 CTP DEMO 开发完成；专用 SDK 环境和离线验证通过，外部连接超时；未运行策略，提交与同步情况以 Git 记录为准。

## 作业要求

用户指定本次为第二节作业，要求：“我正在准备学习量化交易系统的开发，请阅读 llm-wiki.md 中的内容，帮我将当前目录初始化为一个 WIKI 学习项目。”

本节初始化来源：[llm-wiki.md 原文](../../llm-wiki.md) 与 [来源摘要](../sources/llm-wiki.md)。后续资料接入见下文；尚未提供课程课件。

## 本次交付

- [仓库说明](../../README.md) 与 [原始资料入口](../../raw/README.md)：明确资料、知识和规范三层结构。
- [AGENTS.md](../../AGENTS.md)：明确接入、问答、检查、来源保护与课次区分的流程。
- [总索引](../index.md) 与 [维护日志](../log.md)：支持导航与持续积累。
- [学习路线](../roadmap.md)、[系统学习入口](../concepts/trading-system.md) 与 [待解问题](../questions.md)：提供后续学习框架。

## 验收标准

1. 原始 `llm-wiki.md` 的字节内容不变。
2. 原始资料、生成知识与维护规范有明确位置。
3. 所有知识页面进入索引，仓库内相对 Markdown 文件链接有效。
4. 本节独立记录为 `lesson-02.md`；后续课次新增页面。
5. 待学习内容与已阅读来源明确区分，Git 提交只包含本次项目文件。

结构验收通过：11 个 Markdown 文件、55 个本地链接、知识页面索引覆盖、第二节课独立记录及原文哈希一致。详情见 [验收日志](../log.md)。

本节没有要求实现交易策略或运行回测；知识来源与实现任务等待后续课程要求补充。

## 后续要求：下载并消化 VeighNa 三模块

用户在本节初始化后继续要求：在 `raw/` 下载 `vnpy`、`vnpy_ctp`、`vnpy_ctastrategy`，阅读源码并进行消化，可优先使用 Gitee。此要求作为第二节的后续工作记录，不新增或混入其他课次。

### 源码交付

- 从官方 Gitee 默认分支浅克隆后导出完整快照：[vnpy](../../raw/vnpy/README.md)、[vnpy_ctp](../../raw/vnpy_ctp/README.md)、[vnpy_ctastrategy](../../raw/vnpy_ctastrategy/README.md)。
- 保留 341 个上游 Git 文件/链接、全部许可证与 SDK 文件；[版本清单](../../raw/source-lock.json) 固定下载地址、版本、提交和树哈希。
- 上游源码不作修改；下载与接入方式见 [raw 说明](../../raw/README.md)。

### 阅读与消化交付

- 三个来源摘要：[核心框架](../sources/vnpy.md)、[CTP](../sources/vnpy-ctp.md)、[CTA](../sources/vnpy-ctastrategy.md)，记录版本、已读位置与边界。
- 三个专题：[架构](../concepts/veighna-architecture.md)、[订单生命周期](../concepts/veighna-order-lifecycle.md)、[策略与回测](../concepts/cta-strategy-and-backtesting.md)，用具体例子交叉追踪方法、对象和事件。
- 更新索引、学习入口、学习路线和待解问题。没有将源码阅读等同于掌握课程或获得交易效果。

### 后续验收标准

完整导出文件树与上游 Git 条目一致；版本号可追溯到源码；新增知识页面进入索引且相对链接有效；阅读结论注明源码与教学假设；本次不安装依赖、编译 SDK、连接柜台或运行回测。

## 后续要求：开发底层 vnpy_ctp 最小 DEMO

用户要求从底层 Python API 实现连接登录、订阅合约和打印行情，并授权使用其 SimNow 仿真账号。用户将合约选择交给 LLM；本 DEMO 选择 `rb2701` 为默认教学合约，保留参数覆盖，未验证其当前柜台状态。账号信息不写入课次记录或 Git。

交付：[demo.py](../../demos/lesson-02/ctp_minimal/demo.py)、[空账号配置模板](../../demos/lesson-02/ctp_minimal/config.example.json)、[依赖文件](../../demos/lesson-02/ctp_minimal/requirements.txt)、[离线测试](../../demos/lesson-02/ctp_minimal/tests/test_demo.py)、[运行说明](../../demos/lesson-02/ctp_minimal/README.md) 与 [Wiki 讲解](../concepts/ctp-minimal-demo.md)。

验收：9 个离线测试通过；Mac arm64 / Python 3.12.2 中从官方完整源码编译安装 `vnpy_ctp 6.7.7.2`、核心 `vnpy 4.5.0`，依赖检查通过，真实 SDK 加载、交易 API 启动/关闭成功。用户给定两前置端口均拒绝 TCP 连接；真实 DEMO 在交易连接/登录阶段等待 10 秒后超时退出，尚无登录成功、订阅确认和真实行情。

本地账号配置、虚拟环境和 SDK 运行文件均被 Git 忽略；`raw/` 原始快照保持不变。没有增加下单、策略、回测或自动切换前置的功能。网络恢复后的端到端验证见 [待解问题](../questions.md)。

## 后续调整：持续打印与活跃合约

用户要求脚本保持运行并订阅几个成交活跃的合约。默认改为持续等待连接与首条行情，收到推送后持续打印，Ctrl+C 退出；断线自动重连后重新登录并恢复全部行情订阅。明确账号/合约错误仍报告并退出，显式 `--timeout/--duration` 保留用于限时检查。

默认选择 `rb2701/ag2612/au2612`，近期交易所数据依据见 [运行说明](../../demos/lesson-02/ctp_minimal/README.md)。13 个离线测试通过；真实 SDK 持续运行检查见该说明的验收表。仍未获得真实登录和行情证据。

相关：[总索引](../index.md)
