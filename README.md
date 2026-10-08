# 当代量化系统原理与实现 · 学习 Wiki

本仓库用于课程作业与量化交易系统开发学习。LLM 将资料整理为持续更新、相互链接的 Markdown Wiki，学习者负责提供资料、提问和确认理解。

当前记录的是**第二节课作业：初始化 Wiki 学习项目，并接入 VeighNa 三模块源码**。第一节及其他课次不在本次作业范围内。

## 从这里开始

- [Wiki 总索引](wiki/index.md)：查找全部知识页面。
- [学习路线](wiki/roadmap.md)：从基础词汇逐步走向系统开发，全部阶段目前待学习。
- [第二节课作业](wiki/lessons/lesson-02.md)：本次要求、交付与验收记录。
- [VeighNa 架构与源码阅读](wiki/concepts/veighna-architecture.md)：从三模块职责开始，继续阅读订单生命周期、策略和回测。
- [第二节 CTP 最小 DEMO](demos/lesson-02/ctp_minimal/README.md)：底层 API 认证登录、持续行情与单次价格触发仿真交易。
- [第二节跳空动量因子挖掘](research/lesson-02/gap-momentum/README.md)：首轮 16 个候选、公开历史数据、固定评估方案与验证失败记录。
- [机器学习挖掘对照](research/lesson-02/gap-momentum/README-ml.md)：第 2 轮 12 个模型信号、手工基线、特征组合、方向差异与探索性结果。
- [待解问题](wiki/questions.md)：保留尚未解决的问题。
- [维护日志](wiki/log.md)：查看资料接入与知识更新历史。

## 项目结构

```text
llm-wiki.md                  用户提供的 Wiki 方法原文，保持不变
AGENTS.md                    LLM 的项目规范与维护流程
demos/lesson-02/ctp_minimal/  第二节底层 CTP 行情 DEMO 与离线测试
research/lesson-02/gap-momentum/ 第二节跳空动量挖掘与可复现结果
raw/                         原始课程资料与其他学习来源
  vnpy/                      核心框架完整源码快照
  vnpy_ctp/                  CTP 接口完整源码快照
  vnpy_ctastrategy/           CTA 策略模块完整源码快照
  source-lock.json            源码来源、提交和树哈希
wiki/
  index.md                   全部页面的导航索引
  log.md                     仅追加的维护日志
  roadmap.md                 学习阶段与验收目标
  questions.md               待解问题
  sources/                   每份原始资料的摘要与出处
  concepts/                  跨资料累积的概念页面
  lessons/                   按课次独立记录的作业
```

## 如何使用

1. 将一份课件、文章或其他资料放入 [raw](raw/README.md)，告诉 LLM 文件路径与课次，例如：“这是第三节课的资料，请阅读并更新 Wiki。”
2. LLM 读取原文，建立来源摘要，更新相关概念、索引、问题和日志；不同课次分别记录。
3. 提问时先查 Wiki；有长期价值的答案写回页面，并注明出处、推理与待验证内容。
4. 定期要求 LLM 检查链接、遗漏、冲突和过时信息。

直接打开 Markdown 即可浏览；也可以将当前目录作为 Obsidian 仓库打开。初始化不需要安装插件、数据库或搜索服务。

目前已接入 Wiki 方法文档与三个官方 Gitee 源码仓库，完成交易主链路的静态阅读，并开发底层 CTP 行情 DEMO。专用环境安装、SDK 加载和离线测试已完成；真实 SimNow 认证登录、三个合约连续有效行情，以及一次价格触发买入开仓的下单/成交闭环已验证。因子挖掘已完成 2/4 轮：首轮 16 个手工候选，第 2 轮 12 个模型信号与不同思路对照；尚无独立验证合格因子，2025 未做绩效评估，未进行实盘交易。项目维护细则见 [AGENTS.md](AGENTS.md)。
