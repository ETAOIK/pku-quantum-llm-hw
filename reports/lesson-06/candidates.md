# 全部因子、参数与父子谱系

更新日期：2026-10-30。状态：实际运行记录。来源：[原始提案](../../lesson-06/proposals/)与[全部谱系](../../lesson-06/results/lineage.csv)。

| 候选 | 父代 | 公式 | 条件 |
| --- | --- | --- | --- |
| g0_lowvol60 | 祖先 | `-ts_std(returns(close, 1), 60)` | `True` |
| g0_reversal5 | 祖先 | `-returns(close, 5)` | `True` |
| g0_lowamount20 | 祖先 | `-ts_mean(amount, 20)` | `True` |
| g0_rev_lowvol | 祖先 | `rank(-returns(close, 5)) + rank(-ts_std(returns(close, 1), 60))` | `True` |
| g0_intraday20 | 祖先 | `-ts_mean(close / open - 1, 20)` | `True` |
| g0_momentum60 | 祖先 | `returns(close, 60)` | `True` |
| g1_rev200_5 | g0_reversal5 | `-returns(close, 5)` | `True` |
| g1_rev100_10 | g0_reversal5 | `-returns(close, 5)` | `True` |
| g1_rev10_200 | g0_reversal5 | `-returns(close, 10)` | `True` |
| g1_liquid_rev | g0_reversal5, g0_lowamount20 | `-returns(close, 5)` | `ts_mean(amount, 20) > 100000000` |
| g1_lowamt200 | g0_lowamount20 | `-ts_mean(amount, 20)` | `True` |
| g1_intraday5 | g0_intraday20 | `-ts_mean(close / open - 1, 5)` | `True` |
| g2_amount_floor | g1_lowamt200 | `-ts_mean(amount, 20)` | `ts_mean(amount, 20) > 50000000` |
| g2_amount_slow | g1_lowamt200 | `-ts_mean(amount, 20)` | `True` |
| g2_amount_rev10 | g1_lowamt200, g1_rev10_200 | `rank(-ts_mean(amount, 20)) + 0.5 * rank(-returns(close, 10))` | `True` |
| g2_amount60 | g1_lowamt200 | `-ts_mean(amount, 60)` | `True` |
| g2_rev10_slow | g1_rev10_200, g1_rev100_10 | `-returns(close, 10)` | `True` |
| g2_intraday_amount | g1_intraday5, g1_lowamt200 | `rank(-ts_mean(close / open - 1, 5)) + rank(-ts_mean(amount, 20))` | `True` |
