# 原始资料入口

将用户选择的课程课件、文章、笔记或数据说明放在这里。推荐按课次建子目录，例如 `raw/lesson-03/`；具体课次由用户指定。

原始资料保持不变。LLM 的摘要与解释写入 [Wiki](../wiki/index.md)，不写回原文。每份摘要应链接原始文件，并记录页码或章节；来源未提供的信息写“未提供”。

已有的 [llm-wiki.md](../llm-wiki.md) 保留在仓库根目录，由 [来源摘要](../wiki/sources/llm-wiki.md) 引用，不另存副本。

## 已接入的 VeighNa 源码

下载日期：2026-10-08，属于第二节课的后续资料。

| 模块 | 快照入口 | 版本 | 固定提交 |
| --- | --- | --- | --- |
| 核心框架 | [vnpy](vnpy/README.md) | 4.5.0 | `c6e231caf32b7fc97e6459817fff66458cf7e7c4` |
| CTP 接口 | [vnpy_ctp](vnpy_ctp/README.md) | 6.7.11.5 | `1be9bfb5292208e5c258cc769c90be4abe83f9a9` |
| CTA 策略 | [vnpy_ctastrategy](vnpy_ctastrategy/README.md) | 1.5.0 | `7a8768de9784dda35a7b261a7ade1dbfbff50919` |

从官方 `https://gitee.com/vnpy/<模块名>.git` 浅克隆默认分支，再通过 `git archive HEAD` 导出完整版本快照到上述目录。所有上游文件、SDK 库、符号链接与许可证均保留，没有修改源码；不将嵌套 `.git` 元数据放入学习仓库，便于 GitHub 直接显示原文。这里只保存固定提交的完整文件树，不保存上游历史。

[source-lock.json](source-lock.json) 记录下载地址、分支、版本、提交、树哈希、文件数和大小。三个快照合计 341 个上游 Git 条目，导出时逐条核对 Git blob 哈希。更新资料时应新增独立版本快照及对应记录，保留旧版引用。

阅读笔记写入 [Wiki 来源](../wiki/index.md)，不写回源码。本文件和版本清单是目录管理信息，不是上游源码。尚未提供课程课件；上传其他资料前确认允许进入 GitHub，并排除密钥、账户信息和私人交易数据。
