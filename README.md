# Video Translate

以视频配音为核心的 SaaS：原片上传/公开链接导入 → 音轨与片段选择 → 分离/识别 → 原文与角色检查 → 翻译 → 逐句声音克隆与 QC → 共享时间映射 → 背景混音、字幕和视频导出。

Web、API 与 CPU 媒体 Worker 分开运行；推理使用云端服务，Hugging Face 优先。工程不包含本地模型权重、Torch 或本地 ASR/TTS。语言目录包含646种语言及Auto；目录、服务声明支持和已实测语言对分别记录。

- [技术流程](docs/engineering/voice-dubbing-source-flows.md)
- [模型模块、上游审计与清理依据](docs/engineering/model-modularity-audit.md)
- [实际样片与验收边界](docs/engineering/remaining-product-obligations.md)
- [SaaS 部署](deploy/README.md)

## 开发启动

需要 Python3.12、uv、Node24、pnpm9.12.2 和 FFmpeg/FFprobe。媒体拟合还需要 Rubber Band4/R3；字幕需要 Fontconfig、可覆盖文字的 outline 字体及支持 Unicode 换行的 libass。YouTube 提取需要 Deno2.5.6；容器构建固定了这些运行依赖。

```sh
uv sync --python 3.12 --extra dev
cp .env.example .env
mkdir -p var
PYTHONPATH=src uv run --frozen uvicorn videotranslate.app:create_app --factory --host 127.0.0.1 --port 8000
```

在另一个终端启动 Worker，使用同一数据库、存储和服务端密钥：

```sh
PYTHONPATH=src uv run --frozen python -m videotranslate.execution.worker
```

启动 Web：

```sh
pnpm --dir web install --frozen-lockfile
pnpm --dir web dev
```

访问 `http://127.0.0.1:5173`，注册账号，在“服务配置”保存凭证与模型配置。API 文档在 `http://127.0.0.1:8000/docs`，作为请求字段与响应结构的权威入口。密钥只存服务端；不要放进前端环境变量、项目设置或日志。

开发环境可使用 SQLite 与文件存储。生产要求 PostgreSQL、私有 S3 兼容存储及 HTTPS，不接受开发存储或开发密钥；迁移显式执行。服务端密钥还用于凭证加密，不能通过直接更换密钥来完成安全轮换。

## 模块与职责

| 目录 | 职责 |
| --- | --- |
| `providers/` | Chat、Whisper、Demucs、OmniVoice、NVIDIA 适配；不可变 catalog；网络与 Gradio 协议 |
| `execution/` | 持久化 Worker、租约、远端提交检查点、公共 HTTP/凭证/错误策略、受限素材读取 |
| `dubbing/` | 原文/角色/参考音/译文修订、选择性复用、QC、拟合与交付编排 |
| `media/` | 受限 CPU 音视频处理、共享时间映射、峰值保护、波形与字幕 |
| `models/`、`alembic/` | 工作区归属与版本化数据库；兼容历史数据的迁移 |
| `web/` | 编辑、参考音与参数、试听/QC、流程恢复、拟合与导出工作台 |
| `deploy/` | 唯一维护的 Web/API/Worker/migration 容器与网关配置 |

目录均位于 `src/videotranslate/` 下，`web/`、`deploy/` 与 `alembic/` 除外。新增同协议模型通常只需配置；新协议需要适配模块、catalog 声明、必要的阶段接入与契约验证。

## 检查与小步交付

```sh
make check        # 静态/锁文件、模型契约、前端测试与生产构建
make test-models  # 仅模型契约与网络/配置保护
make web-check    # 前端测试、类型检查与构建
make package      # sdist + wheel
```

`make check` 是开发和 PR 的快速检查，不替代完整媒体回归。模型/网络测试使用显式测试提供方，不调用真实推理。

完整检查需要媒体依赖与**独立 PostgreSQL 实例**。请在该隔离实例预先创建具有 `LOGIN`、`CREATEDB` 权限的 `vt_test` 角色并配置密码；现有测试固定以 `OWNER vt_test` 创建临时库，使用该角色连接：

```sh
export VT_TEST_POSTGRES_ADMIN_URL='postgresql://vt_test:TEST_PASSWORD@127.0.0.1:TEST_PORT/postgres'
make test
```

不要指向业务数据库。测试创建独立命名数据库与临时素材；历史回归、源文件和模型调用收据分别保留。改动先跑涉及的契约/阶段测试，完成一个可用切片再提交；完整回归留给跨阶段集成或发布检查。`.github/workflows/ci.yml` 自动运行快速模型与 Web 检查，未加入自动部署或真实推理。

## 关键运行约束

- 模型结果、编辑修订、音频选择、人工听审和最终导出分别记录；QC 相似度不代表声音已通过试听。
- 已知远端请求 ID 恢复查询；提交结果未知时保留原任务，明确处理后才可重试。
- 取消、租约与输入当前性在发布前再次核对，旧结果不能覆盖新编辑。
- 原片、自然音频、拟合派生物和导出分别保存来源、哈希与用途；明确的缺句预览保持预览标签。
- 公开链接是可选入口；上游不可取用时保留失败任务和上传方式，不导入浏览器 Cookie。

## 当前验证边界

SIZsFGvtClM 的0–59.51秒原片已经过产品上传、真实云端英转中、8段自然配音与8段独立 QC。Smart Fit 保持自然配音速度，生成76.810秒视频。结果与收据在仓库旁的 `VideoTranslate-SIZsFGvtClM-EN-ZH` 文件夹。

样片通过文件大小、SHA256和完整解码验证，人工听审尚未通过，日语实测按用户要求暂停。字幕预览开头与原片姓名条重叠；该 YouTube 链接在当前网络的直接导入仍未成功，已完成样片使用同一原片上传处理。更多细节见[验证记录](docs/verification/2026-11-01-agile-delivery.md)。

容器文件与部署说明已提供；Docker/Podman/Nginx 在本机不可用，未宣称完成 Linux 镜像运行、云端 PG/S3/TLS 联调或公网发布。本次不执行 Git push 或部署。
