# 第六课：Agent Harness 与因子、策略演化

更新日期：2026-10-30。状态：实现与实测结果见[独立作业报告](../reports/lesson-06/README.md)。数据与交易假设沿用第四课，因子评价沿用第五课；旧课次代码、数据和结果不覆盖。

## 在原回测网页中使用

Agent演化已整合到原系统；沿用第五课启动命令即可同时使用三个模块，无需单独启动第六课服务：

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 lesson-05/app.py --port 8768
```

打开[原研究工作台](http://127.0.0.1:8768/)、[Agent演化](http://127.0.0.1:8768/evolution)或[策略回测](http://127.0.0.1:8768/backtest)，顶部导航可相互进入。第四课原来的 `server.py` 启动方式也直接提供 `/evolution`。报告仍独立存放，不增加报告页面路由。

演化页可查看已保存的18个候选、按代筛选、点击候选查看公式/筛选/经济假设/反馈变更与父代，切换资金/成本场景，或启动原提案的后台重放。演化、因子评价与普通回测共享忙碌锁，避免并发抢占数据和输出。新运行写入忽略目录 `runtime/web/`，不会覆盖冻结结果。

完成后点击候选的“在策略回测中复测”，会真正调用原回测引擎，再跳到该次运行，保留公式、条件、资金、持仓数、调仓间隔、成本与后续日期；等权基准仍按原演化的5日调仓。可在原页继续编辑参数、查看净值/订单/持仓并导出CSV。带来源的候选复测记录会在服务重启后恢复。实际逐日权益与保存结果对照，两条曲线最大差异均0元，见[集成验收](../reports/lesson-06/integration/checks.json)。

网页明确区分“重放”与“模型自主挖掘”。后者需在服务启动时传入可信模型命令，例如 `--agent-command '["python3", "/absolute/path/to/your_agent_adapter.py"]'`；传输协议见下文。当前服务未配置额外模型连接，不能把网页重放称作新模型发现。网页不接受命令或密钥。失败任务可继续；重启后若旧进程仍在运行或无法确认停止，则不允许在同一目录继续。

实现：[网页控制器](evolution_web.py)、[页面](web/index.html)、[集成测试](tests/test_evolution_web.py)。界面与原回测的实际截图见[集成记录](../reports/lesson-06/integration/README.md)。

Agent 负责提出假设、阅读反馈和修改因子/策略；Harness 负责限制输入、运行工具、保存记忆、维护谱系和停止研究。候选是一份 JSON：公式、筛选条件、持仓数、调仓间隔、父代与理由。它不是可执行 Python，不能改变日期、资金、成本、评价目标或门槛。

本次 Agent 是**当前 Codex 会话**：第一批评完后才撰写第二批，第二批评完后才撰写第三批；原始提案和工具反馈全部保留。不是在 Python 内实现了一个新 LLM，也没有把规则搜索冒充 LLM。`auto` 可接入用户已有的模型命令实现独立进程自动循环；其接口已用明确标注的模拟Agent完成全流程测试，本次实数据采用会话工具循环。`replay` 只重放本次提案，不产生新模型思考。

原始会话的上下文、反馈、开发账本和当时源码保存在[会话证据](provenance/interactive-session/)。修复自定义ID、保留ID、输入类型及空CSV接口边界后，最终 `results/` 由最终代码重放原提案生成，明确记录 `replay of ...`；18个候选及开发指标与原会话完全一致，没有按后续收益改选策略。

## 复跑本次实验

在仓库根目录执行，依赖沿用[第四课 requirements](../lesson-04/requirements.txt)，无新增依赖。需要本地 `lesson-04/data/feathers.zip` 和 `lesson-04/data/status.parquet`；准备说明见[第四课 README](../lesson-04/README.md)。输入数据不入 Git。

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 -m pytest -q lesson-04/tests lesson-05/tests lesson-06/tests
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 lesson-06/harness.py replay --output lesson-06/runtime/replay
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 lesson-06/verify.py --results lesson-06/runtime/replay
MPLCONFIGDIR=/tmp/lesson06-mpl python3 lesson-06/report.py --results lesson-06/runtime/replay --output lesson-06/runtime/report
```

`replay` 重用[三代提案](proposals/)，会根据新运行实际生成的上下文重新绑定指纹，并标注为重放；它用于数值复现，不能算第二次独立 Agent 发现。已有完成结果禁止覆盖。首次运行如需单独指定输入，使用 `--data /path/to/feathers.zip --status /path/to/status.parquet`。

## Agent 的逐步工具接口

```bash
python3 lesson-06/harness.py init --output lesson-06/runtime/new
python3 lesson-06/harness.py context --output lesson-06/runtime/new
python3 lesson-06/harness.py evaluate --output lesson-06/runtime/new --proposal /path/to/proposal.json
# 每轮读取反馈、生成下一代；完成三代后：
python3 lesson-06/harness.py freeze --output lesson-06/runtime/new
python3 lesson-06/harness.py finalize --output lesson-06/runtime/new
```

`context` 返回当前协议、此前开发结果、公式语言和 `context_sha256`。提案顶层恰含 `generation / context_sha256 / agent / candidates`；每个候选的具体字段可参考[真实第一代提案](proposals/round-00.json)。每代固定 6 个候选，共 3 代；子代必须引用先前已评价的 1–2 个父代。重复表达式/筛选/参数组合、未来窗口、任意 Python、越界参数、过期反馈和冻结后的修改都会拒绝。结构相同的公式会去重；数学等价但结构不同的公式没有完整符号去重。

运行中断可重交**完全相同的提案**，已完成候选按折恢复；不能修改已开始的一代。本次只有一个控制进程，不支持多个控制器并发写同一结果目录。输入、协议及核心源码指纹必须与初始化时一致；修改后应开新运行。

## 接入外部模型自动循环

准备一个可信的模型命令：从标准输入读取一份 `context` JSON，调用用户已配置的模型，并把符合上述契约的提案 JSON 写到标准输出。日志写标准错误，不在命令行或提案里写密钥。然后执行：

```bash
python3 lesson-06/harness.py auto \
  --output lesson-06/runtime/auto \
  --agent-command '["python3", "/absolute/path/to/your_agent_adapter.py"]'
```

这里的路径是接口示例，仓库不包含用户的模型服务适配器。Harness 不依赖具体供应商、没有内置付费 API，也不会在缺少模型命令时偷偷退化成规则 Agent。模型调用超时或返回无效 JSON 会停止，保留此前已完成代；修复后用同一输出目录恢复。每次调用有 600 秒超时，最多剩余代数次调用。

上下文只提供开发反馈，冻结后才运行筛选，筛选落盘后才运行后续区间。这是**流程与接口约束**：外部模型命令仍是用户信任的本地程序，未为其建立文件系统安全隔离；当前 Agent 也已有历史作业知识，不能宣称从未接触后期行情。

## 评价与停止

完整设置见[冻结协议](protocol.json)。2025 上、下半年是两折开发期，每折独立开立十亿元账户；2026 一季度是一次性筛选期；2026 二、三季度是冻结后的后续检查。状态表仅覆盖 2024-12 起，因此未沿用最初考虑的 2023–2024 非 ST 开发方案。所有历史已被查看，均为回顾性研究。

每个候选同时记录 5 日 Rank IC、Q5−Q1 毛收益、覆盖、成本后收益、回撤、换手和成交比例。开发目标是“两折年化算术超额的较小值 − 0.25 × 两折最差回撤绝对值 − 0.0001 × 公式及条件 AST 节点数”。超额来自与同日动态等权**日收益相减再取均值 ×252**；目标是教学决策标尺，不是收益率或统计显著性。

开发通过要求每折 Rank IC、分组差和净算术超额均正，条件内因子覆盖≥80%、标签覆盖≥95%、条件池占原池≥20%。门槛是本项目事先设定，不冒充教师正式标准。按通过优先、目标降序、ID排序冻结前三；三个逐代冠军也预先冻结用于事后比较。2026Q1 对前三同口径评分及门槛，再决定合格候选；无人通过则输出 `qualified_candidate=null`，另保留明确标注的诊断领先者，不强造合格策略。

成本场景为原成本、佣金/滑点加倍（卖出税不变）、资金降为一百万元；每场景都重算等权对照。每折/阶段新账户、相同末20日渐进退出，不是连续资金曲线。与旧课全年结果的日期不同，不应直接比较累计收益。证券池、零成交额停牌代理、复权份额、开盘门禁、状态时点和公司行为限制沿用第四课。单次自适应搜索不能证明 Agent 比随机搜索或固定搜索更优；名义区间也没有校正自适应选模和历史反复查看。

核心实现：[harness.py](harness.py) · [验收代码](verify.py) · [测试](tests/test_harness.py) · [报告生成器](report.py)。证据：[输入/源码指纹](results/manifest.json) · [谱系](results/lineage.csv) · [冻结记录](results/freeze.json) · [选择记录](results/selection.json) · [完整后续结果](results/followup.csv)。报告与图单独存放在 [reports/lesson-06/](../reports/lesson-06/README.md)，系统不增加报告网页路由。
