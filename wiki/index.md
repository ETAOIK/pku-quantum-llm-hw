# Wiki 总索引

更新日期：2026-10-08。当前阶段：第二节 DEMO 的连续有效行情与单次价格触发仿真成交闭环已验证；继续系统学习，跳空因子挖掘待历史数据。

## 学习与维护

- [学习路线](roadmap.md)：基础词汇到系统开发的暂定阶段与理解检查。
- [待解问题](questions.md)：当前资料缺口、范围选择与待验证问题。
- [维护日志](log.md)：按时间追加的初始化、资料接入、问答与检查记录。

## 课程作业

- [第二节课：Wiki 与 CTP DEMO](lessons/lesson-02.md)：初始化、源码阅读、DEMO 开发与验收记录。

## 来源

- [LLM Wiki 方法摘要](sources/llm-wiki.md)：三层结构与 ingest、query、lint 流程，链接用户提供的原文。
- [vnpy 核心框架](sources/vnpy.md)：主引擎、事件引擎、网关、数据对象与 OMS 的源码地图。
- [vnpy_ctp 接口](sources/vnpy-ctp.md)：行情/交易双通道、登录准备、CTP 请求和 C++ 桥接。
- [vnpy_ctastrategy 应用](sources/vnpy-ctastrategy.md)：策略模板、实盘引擎、示例与回测实现。

## 概念

- [量化交易系统的学习入口](concepts/trading-system.md)：系统环节及问题，连接新的源码学习资料。
- [VeighNa 三模块架构](concepts/veighna-architecture.md)：模块分工、平台装配与指令/回报路径。
- [VeighNa 系统分层与策略应用](concepts/veighna-system-layers.md)：标准数据与流程、事件总线、OMS、指令路由，以及时序/组合/价差策略的区别。
- [VeighNa 订单生命周期](concepts/veighna-order-lifecycle.md)：从买入请求、部分成交到撤单和策略持仓。
- [CTA 策略与回测](concepts/cta-strategy-and-backtesting.md)：双均线、预热、状态条件、模拟撮合与成本。
- [底层 CTP 最小 DEMO](concepts/ctp-minimal-demo.md)：认证登录、多合约持续行情、单次价格触发下单与成交回报、版本差异及验证边界。

## 项目入口

- [仓库说明](../README.md)：使用方法与目录结构。
- [原始资料入口](../raw/README.md)：资料放置与来源保留方式。
- [LLM 维护规范](../AGENTS.md)：页面约定、课次隔离与维护流程。
- [DEMO 运行说明](../demos/lesson-02/ctp_minimal/README.md)：安装、配置、启动命令和测试结果。
