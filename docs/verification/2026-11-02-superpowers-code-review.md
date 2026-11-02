# Superpowers 7.0.1 代码审计

2026-11-02。对象：Video Translate 本次清理与模型模块化增量，以及周边生产调用链。基线 `1b5d47d63aee7f5bb52a59bcfb3cfec9c646b112`；独立审计代码 `584473af495391a1e6553cff8a2009723e2a5ea6`。此后两处文档修正由原 reviewer 单独复核。

## 插件与执行方式

本机原插件5.1.3；核对时作者[最新稳定版本为7.0.1](https://github.com/obra/superpowers/releases/tag/v7.0.1)。通过 Codex 插件机制从作者仓库安装 `superpowers@superpowers-dev`，固定标签 `v7.0.1`、提交 `2ce8aa15d05bd57213e6f746f953aafb7ded7a8b`，停用旧的 `superpowers@openai-curated` 实例并保留私有配置备份。CLI确认新版已安装且启用；安装后的插件清单和两份 reviewer 指令与标签源码逐字节一致。

按新版 `requesting-code-review/code-reviewer.md` 分别派发两个独立、无历史会话的只读子代理；reviewer 未再派发子代理，未修改代码、数据库、凭证或素材，也未提交真实推理。

## 结论与修正

| 审计领域 | 原始发现 | 复核后状态 | 完整报告 |
| --- | --- | --- | --- |
| 生产 Python、模型与公共执行边界 | 0 Critical / 0 Important / 0 Minor | 通过 | [核心代码审计](2026-11-02-superpowers-core-review.md) |
| 测试、CI、打包、部署引用与文档 | 0 Critical / 0 Important / 2 Minor | 两项均已修正并由原 reviewer 复核，无未解决项 | [测试与工程检查审计](2026-11-02-superpowers-gates-review.md) |

1. README 的全量测试示例原用泛化的 `TEST_USER`，而现有 PostgreSQL fixture 固定 `OWNER vt_test`。现在明确预建隔离实例的 `vt_test` LOGIN/CREATEDB角色并配置密码，URL也使用该角色；未改动测试或生产数据库。
2. 上游“已经过 LLM 时跳过重复改写”的结论正确，但链接原指向上下文缓存。已按固定上游版本核对并改为1247–1259行说明和1295–1315行分支。

## 采用的验证证据

- 协调者实际执行 `make check`：147项后端契约测试、127项前端测试、Ruff/249文件格式、77包冻结锁文件、TypeScript与Vite构建通过；`make package`与分发内容核对通过。测试调用显式测试提供方，没有真实推理费用。
- 核心 reviewer 独立执行函数AST、HTTP适配器枚举/角色、生产调用者搜索和实际源代码导入探针；检查准备/提交/接受/终态缓存/下载及发布边界。
- 工程 reviewer 独立读取测试断言，核对5个Action提交在各自上游仓库真实存在，并核对现用Dockerfile只引用 `deploy/nginx.conf`。
- 文档修正后 `git diff --check`通过；原 reviewer精确复核两处修改，不重复执行全套测试。

## 协调者对范围外事项的处理

- 两位 reviewer 将各自分工之外的代码交由另一位检查：接受，两个领域均已得到独立结论。
- 未重复全量后端媒体/PostgreSQL回归：接受，使用本次快速检查与此前相关阶段检查；不把本次147项称为全量覆盖。
- 实际模型可用性、性能、计费、商业许可和人工听审：保持独立验收状态。本轮无新推理，不以源码审计或QC结果声称音质已获批准。
- 远端GitHub Actions、Linux容器、托管PG/S3/TLS和公网发布：未执行；本机检查及Action引用核验不替代部署验证。
- 第三方对已删除私有Python快捷函数的依赖：接受有意删除；兼容契约是现有HTTP API和持久化数据，仓库内无生产调用者。
- 手工破坏数据库适配器ID：没有引入此类迁移，不扩展为数据库修复功能；正常配置写入仍按既有验证。
- 现有Dockerfile的pnpm11.25.0与本机/CI的9.12.2不同：保留为既有部署验证边界，本次未证明由此产生不兼容，也未擅自改动部署依赖。
- 上游整体AGPL法律判断与完整本地模型实现审计：不作结论；本轮仅核对选定源码流程，未复制其实现。

本轮修改保存在本地开发分支，不执行Git push、合并或公网部署。报告中的“可合并”是代码审计判断，不代表已合并或上线。
