# 第二节课作业：Wiki 初始化与 VeighNa 源码学习

更新日期：2026-10-08。状态：初始化及三模块源码接入、主链路静态阅读完成；未安装平台或运行策略，提交与同步情况以 Git 记录为准。

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

相关：[总索引](../index.md)
