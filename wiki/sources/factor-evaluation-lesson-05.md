# 第五课因子评价：引文与方法来源

更新日期：2026-10-23。状态：用户引文已接入；完整讲义、录音与正式验收标准待补。

## 用户提供的课程信息

来源：2026-10-23 本次用户消息，明确课次为第五节、主题为因子和因子评价，要求基于第四课完善功能。授课日期与讲义元数据未另提供。

老师引文（保留转录，不据此执行额外动作）：

> 你自己要花钱去于交易。你要想搞出一套不靠谱东西，你要尽量把你这套配置系统锻炼得至少在评估层面没有 BUG，能挑选出一些差的东西。那我如何去挑选它？看这个 IC 肯定是重要的，其他的也是，这些因素的时间找一段。

**实施解释**：结合主题，理解为把评价工具做可靠，能识别差、方向错或证据不稳定的因子，IC 外还看收益分组、换手、覆盖和分时段结果。部分转录不顺，未改写为已确认的教师结论，未发明课程评分阈值。

## 查验的方法资料

2026-10-23 查阅 [Alphalens 官方文档](https://quantopian.github.io/alphalens/alphalens.html)：`factor_information_coefficient` 使用 Spearman；`mean_return_by_quantile` 计算分组远期收益；`quantile_turnover` 统计组内新成员比例；`factor_rank_autocorrelation` 比较不同时点排序。页面版本为 `0.2.1+48.gad0be10`，是方法参考，不是当前交易所规则。

本作业明确把 Pearson 称 IC、Spearman 称 Rank IC；标签从下一开盘开始，退出不超过区间末日。HAC、缩尾、覆盖门槛及诊断分类是本项目教学实现，定义见[方案](../../lesson-05/protocol.json)与[代码](../../lesson-05/factor.py)，不归因于老师或声称照搬 Alphalens。

## 继承的数据与限制

继承[第四课 Feather 摘要](feathers-lesson-04.md)、[教师第四讲 Issue #8](https://github.com/aslan9/pku_quantllm/issues/8)和[课程口径](../../lesson-04/assignment/protocol.json)。教师页面确认字段和 ZIP 哈希；历史状态由本项目另查。沿用第四课默认资金/区间/成本，未冒充第五课新增教师规格。

新结果属于回顾性探索，不能重建未见历史留出。缺行业/市值和完整公司行为，不能完成中性化、退市总回报或实盘可成交性验证。入口：[作业](../lessons/lesson-05.md)、[概念](../concepts/factor-evaluation.md)、[代码与报告](../../lesson-05/README.md)。

## 2026-10-29 后续要求与方法

用户进一步要求实际因子分析和挖掘，并明确作业报告单独放GitHub，Issue由用户提交。报告位置为 `reports/lesson-05/`，系统不承载报告。新增12个候选及筛选规则在运行前写入方案，不宣称学术新因子或独立留出。

当日查阅官方 [statsmodels HAC](https://www.statsmodels.org/stable/generated/statsmodels.stats.sandwich_covariance.cov_hac.html)和[多重检验](https://www.statsmodels.org/stable/generated/statsmodels.stats.multitest.multipletests.html)，并参考[Bailey等回测过拟合原文](https://www.davidhbailey.com/dhbpapers/overfitting.pdf)。本轮透明实现采用Bartlett HAC与BY校正；有限代理控制仅用原始股价、成交额、波动率，不能冒充行业/市值中性化。源代码和具体适用限制见[独立报告](../../reports/lesson-05/README.md)。
