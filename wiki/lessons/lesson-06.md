# 第六次作业：Agent 驱动因子与策略演化

更新日期：2026-10-30。状态：实现、实测与结论见[独立报告](../../reports/lesson-06/README.md)；教师验收待确认。来源：用户本次明确的作业指令、[方法参考](../sources/agent-evolution-lesson-06.md)和实际运行文件。

本课在第四课回测账本和第五课评价器上实现 Agent Harness。Agent 根据每轮反馈修改因子公式、流动性条件、持仓数和调仓频率；Harness 维护预算、父子谱系、去重、工具契约、冻结及阶段隔离。原始行情及旧课结果保留。

2026-10-30补充：已接入原回测系统的 `/evolution` 页面，原回测与因子页均有入口。支持查看每代候选/父代/反馈、后台运行、切换场景，以及将任意完成候选一键交给原回测引擎。实际复测策略与原等权基准逐日权益最大差异均0元，见[集成验收](../../reports/lesson-06/integration/README.md)。未配置外部模型时，自主挖掘明确禁用，重放仍可直接运行。

- [提交用图文简报](../../reports/lesson-06/assignment.md)：2026-11-06整理，保留两张结果图、三代比较和证据边界。
- [系统与复跑说明](../../lesson-06/README.md)：会话驱动、外部模型自动模式与提案重放的区别。
- [核心实现](../../lesson-06/harness.py)、[协议](../../lesson-06/protocol.json)、[三代提案](../../lesson-06/proposals/)：实际决策、参数及停止规则。
- [报告](../../reports/lesson-06/README.md)：全部候选、逐代路径、后续负结果、容量和成本敏感性。
- [概念页](../concepts/agent-factor-evolution.md)：Agent、Harness、因子演化与策略演化的定义和例子。
- [结果指纹](../../lesson-06/results/manifest.json)、[谱系](../../lesson-06/results/lineage.csv)、[选择记录](../../lesson-06/results/selection.json)、[验收](../../lesson-06/results/verification.json)：复核入口。

2025上下半年用于演化，2026一季度一次性筛选，2026二、三季度用于冻结后检查；每段独立账户，不能拼接成连续净值。上述历史已在此前研究中可见，不称为独立未见测试，也不把工程验收等同于盈利或实盘部署。
