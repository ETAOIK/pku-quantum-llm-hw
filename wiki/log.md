# 维护日志

日志仅追加；日期使用北京时间。记录实际执行内容，不把计划写成完成事项。

## [2026-10-08] init | 第二节课 Wiki 学习项目

- 根据用户要求阅读 `llm-wiki.md`，保留原文，建立原始资料、知识页面与维护规范三层结构。
- 创建 [索引](index.md)、[学习路线](roadmap.md)、[待解问题](questions.md)、[系统学习入口](concepts/trading-system.md) 和 [第二节作业记录](lessons/lesson-02.md)。
- 学习路线与概念入口是初始化框架；没有宣称完成课程学习、策略实现或实验。

## [2026-10-08] ingest | LLM Wiki 方法文档

- 原始资料：[llm-wiki.md](../llm-wiki.md)。
- 创建 [来源摘要](sources/llm-wiki.md)，将三层结构、ingest/query/lint、索引和追加日志落实到项目规范。
- 文档介绍知识库方法，不提供量化交易知识；可选工具未纳入初始化依赖。

## [2026-10-08] lint | 初始化结构验收

- 检查了 11 个 Markdown 文件中的 55 个本地链接，全部指向存在的仓库文件；全部知识页面已进入索引。
- 作业目录仅包含第二节课记录。原始 `llm-wiki.md` 的 SHA-256 前后相同：`a402e64fc0c46e618b01acc3502f18a992b4a42222bfd7f87c9abbee3801c98f`。
- 本次检查验证目录、链接、索引和来源保留，没有验证量化知识或交易效果。

## [2026-10-08] ingest | VeighNa 三模块官方 Gitee 源码

- 用户指定下载 `vnpy`、`vnpy_ctp`、`vnpy_ctastrategy`，作为第二节课后续资料。
- 从官方 Gitee 默认分支浅克隆并用 `git archive HEAD` 导出到 `raw/`，完整保留 341 个上游 Git 条目、SDK 库、符号链接与许可证。
- 导出时逐条计算 Git blob 哈希，与上游树中的哈希一致；没有修改源码。[版本清单](../raw/source-lock.json) 固定三个提交与树哈希。
- 接入 [核心框架摘要](sources/vnpy.md)、[CTP 摘要](sources/vnpy-ctp.md)、[CTA 摘要](sources/vnpy-ctastrategy.md)。

## [2026-10-08] query | 消化 VeighNa 交易主链路

- 静态阅读事件引擎、主引擎、OMS、标准对象、开平转换、CTP Python 网关与关键 C++ 桥接、CTA 生命周期、双均线示例及回测撮合和成本计算。
- 写回 [架构](concepts/veighna-architecture.md)、[订单生命周期](concepts/veighna-order-lifecycle.md)、[策略与回测](concepts/cta-strategy-and-backtesting.md)，更新索引、学习路线、待解问题和第二节记录。
- 记录下单/成交差异、策略初始化/交易标志、100 根数组预热、整笔模拟撮合及异常路径边界。
- 阅读并引用上游测试案例，没有执行；未安装依赖、编译 SDK、连接柜台或运行历史回测。

## [2026-10-08] lint | 源码接入与阅读笔记验收

- 检查本项目维护的 17 个 Markdown 文件、223 个本地链接，全部有效；知识页面均已进入索引，作业仍归属第二节。
- 三模块的 341 个上游 Git 条目逐条核对哈希；保留源码原有格式和许可证，资料目录没有嵌套 Git 仓库。
- 原始上游文档不改写、不纳入本项目文档链接修复范围。数值例子是源码规则的手工解释，未作为运行测试或收益结果。
