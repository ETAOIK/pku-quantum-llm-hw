# 第六课 Agent 驱动演化：来源与实施边界

更新日期：2026-10-30。状态：用户作业要求与公开方法参考已记录，完整教师讲义未提供。

## 用户给出的要求

2026-10-30 用户在本项目会话明确：第六次作业，在此前回测系统上，实现因子挖掘 Agent Harness、因子自动进化、Agent 驱动的因子演化与策略迭代演化，并分析挖掘结果。来源为本次直接指令，无单独文件、教师作者信息或评分细则。

## 方法参考

- Microsoft Research，[RD-Agent: An open-source solution for smarter R&D](https://www.microsoft.com/en-us/research/articles/rd-agent-an-open-source-solution-for-smarter-rd/)，2025-01-02，Research / Development 及反馈循环章节。提供“假设→实现→实验→反馈→修改”的参考；本项目是复用自身账本的教学实现，未安装或复现 RD-Agent，不引用其绩效为自己的结果。
- Quantopian，[Alphalens performance 文档](https://quantopian.github.io/alphalens/alphalens.html#alphalens.performance.factor_information_coefficient)，版本页显示 0.2.1+48.gad0be10，`factor_information_coefficient` 定义。用于核对 Spearman 相关的定义；本项目沿用第五课的自编透明评价器。
- Bailey、Borwein、López de Prado、Zhu，[The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)，作者网站的论文入口。其问题背景支持保留多次尝试及承认过拟合风险；本次未计算论文的 PBO/CSCV，也未据此获得校正后的显著性。

查阅日期为 2026-10-30。上述资料不规定本课课次、资金、候选数、门槛或正式评分要求；具体设置属于本项目实施选择，见[协议](../../lesson-06/protocol.json)。沿用的课程行情及历史状态来源见[第四课数据摘要](feathers-lesson-04.md)与[第五课来源](factor-evaluation-lesson-05.md)。

## 证据限制

历史数据、旧课结果和已有因子先验已可见。按时间划分和冻结能约束本轮工具顺序，不能恢复独立未见测试。框架“能自动改进提案”与“找到可部署 Alpha”是不同命题。具体实测证据在[第六课报告](../../reports/lesson-06/README.md)，待验证问题在[问题页](../questions.md)。
