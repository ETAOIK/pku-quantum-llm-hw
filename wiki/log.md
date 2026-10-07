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

## [2026-10-08] query | 第二节底层 CTP 行情 DEMO

- 用户要求连接认证登录、订阅合约与打印行情，授权使用本地 SimNow 账号并由 LLM 选择合约；默认教学代码为 `rb2701`，当前柜台有效性未验证。
- 开发 `demos/lesson-02/ctp_minimal/demo.py`，直接继承底层 `TdApi/MdApi`；加入配置模板、依赖、离线测试和运行说明，写回 [DEMO Wiki](concepts/ctp-minimal-demo.md)。
- 9 个离线测试通过，覆盖正常流程、认证/登录/订阅失败、请求发送失败、超时、关闭与账号不打印。
- Mac 6.7.11.4 因上游 C++/头文件不匹配而构建失败；6.7.7.2 的 PyPI 源码包缺 framework，改用官方 Gitee 完整源码提交编译成功。实测环境为 Python 3.12.2、vnpy 4.5.0、vnpy_ctp 6.7.7.2，依赖检查通过。
- 真实 SDK 导入与交易 API 启动/关闭成功。给定两端口 TCP 检查均连接被拒绝；真实 DEMO 在交易连接/登录阶段等待 10 秒后超时，尚无真实登录、订阅或行情记录。
- 本地账号配置设置仅所有者读写权限；配置、虚拟环境、原始运行日志与 SDK 文件均在 Git 忽略范围；原始 `raw/` 快照不修改。

## [2026-10-08] lint | CTP DEMO 交付检查

- 9 个 unittest 及已安装环境的依赖检查通过，依赖文件语法有效。
- 检查本项目维护的 19 个 Markdown 文件、251 个本地链接与 Wiki 索引，全部有效。
- 原始 `raw/` 和 `llm-wiki.md` 没有改动；本地账号文件未跟踪、被忽略且权限为 600。端到端验证仍受给定前置连接拒绝限制。
