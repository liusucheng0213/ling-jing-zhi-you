# 灵境智游 · AI 数字人智慧景区导览系统

第十五届“中国软件杯”大赛 A5「景区导览服务 AI 数字人」全国二等奖作品 demo。

项目以灵山胜境为示范景区，包含响应式游客端和运营管理端。游客端提供文本、语音、图片问答、行程陪伴、互动故事与文创社区；管理端提供知识库、RAG 修复复测、数字人配置、演示准备、运营分析、报告和用户管理。

## 当前能力

| 模块 | 已实现能力 |
| --- | --- |
| 游客端 | React 18 + TypeScript；适配手机、iPad 横竖屏、安全区和动态视口，桌面保留三栏导航 |
| 数字人 | 5 个讯飞虚拟人；Redis 协调唯一 WebSDK 通道，游客优先，支持真实字幕、中断和关键词动作 |
| 智能问答 | DeepSeek + PostgreSQL/pgvector + 本地 BGE-M3；支持 SSE 流式回答、上下文追问与图片识景 |
| 路线与定位 | 5 条路线；按兴趣、位置、时长和体力规划，支持到站、完成、跳过、重规划和结构化足迹 |
| 互动故事 | 5 条故事线、36 个有效节点，每节点 3 个短选项，剧情可交给数字人播报 |
| 文创社区 | 一次视觉调用完成识景、知识核对、讲解与发布建议，可复用结果写游记或导出明信片 |
| 管理后台 | JWT 登录、知识修复与真实复测、数字人配置与首帧预览、30 日分析和中文 PDF 报告 |
| 语音 | 讯飞 ASR、在线 TTS、PCM 声学情感分析；数字人专属音色仅由 WebSDK 使用 |

灵山胜境是唯一具有结构化路线和定位数据的主景区；拈花湾仅作为关联目的地补充知识问答，不混入灵山路线或 GPS 点位。

## 启动前准备

- Docker Desktop 与 Docker Compose v2。
- 默认嵌入服务使用 NVIDIA GPU，需要可用的 NVIDIA 驱动及容器 GPU 支持；没有 GPU 时，需要同时调整 Compose 中的 GPU 配置、PyTorch 基础镜像和 `EMBEDDING_DEVICE`，不能只修改一个环境变量。
- 本地 BGE-M3 模型，放在 `models/bge-m3/`。模型权重不纳入 Git。
- DeepSeek 密钥；语音和数字人功能还需要讯飞对应服务授权；图片问答需要单独配置视觉模型。

## 快速启动

以下命令以 PowerShell 为例。

### 1. 配置环境变量

```powershell
Copy-Item .env.example .env
```

至少填写：

```dotenv
DEEPSEEK_API_KEY=your-key
JWT_SECRET=replace-with-at-least-32-random-characters
ADMIN_USERNAME=admin
ADMIN_PASSWORD=replace-with-a-strong-password
```

使用语音和数字人前，继续配置 `XFYUN_APP_ID`、`XFYUN_API_KEY`、`XFYUN_API_SECRET`、`XFYUN_AVATAR_SCENE_ID` 及 5 个 `XFYUN_AVATAR_*_ID`。使用图片问答前，配置 `VISION_PROVIDER`、`VISION_API_KEY`、`VISION_BASE_URL` 和 `VISION_MODEL`。

完整选项、默认模型和不同视觉服务示例见 [`.env.example`](.env.example)。图片问答会把真实图片像素发送给所配置的视觉模型。`XFYUN_AVATAR_*_VCN` 是数字人 WebSDK 音色，`XFYUN_TTS_VCN` 是普通语音接口音色，两者不能互相替代。

> `.env` 含有私密凭证，不得提交。`JWT_SECRET` 至少需要 32 个字符，否则管理员登录会拒绝签发令牌。长期讯飞密钥只保留在后端，前端仅接收短期签名地址。跨域来源通过 `ALLOWED_ORIGINS` 配置，部署到域名时必须同步修改。

### 2. 启动服务

确认 `models/bge-m3/` 已就绪后执行：

```powershell
docker compose up -d
```

| 服务 | 地址 |
| --- | --- |
| 游客端 | http://127.0.0.1:3000 |
| 管理后台 | http://127.0.0.1:3001 |
| 后端 API | http://127.0.0.1:8000/docs |
| 嵌入服务 | http://127.0.0.1:8010/health |

管理账号由 `.env` 中的 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD` 决定。PostgreSQL、Redis 和嵌入服务只绑定到本机回环地址，减少局域网暴露。当前 Compose 使用开发服务器与热重载，适合本地演示，不应直接作为公网生产部署配置。

### 3. 初始化数据

```powershell
docker compose exec api python -m scripts.init_db
docker compose exec api python -m scripts.init_data
docker compose exec api python -m scripts.init_storylines
docker compose exec api python -m scripts.ingest_knowledge
docker compose run --rm embedding-worker
```

知识入库默认读取随 Git 提交的 `a5_official_materials.json`，不依赖本机原始 Word / Excel 资料包。嵌入服务使用本地 BGE-M3 生成 1024 维向量，可查看运行状态：

```powershell
(Invoke-RestMethod http://127.0.0.1:8010/health).runtime
```

如需展示非零运营图表、RAG 异常样例和社区内容，可执行：

```powershell
docker compose exec api python -m scripts.seed_demo_analytics
docker compose exec api python -m scripts.seed_community_showcase
```

这些脚本生成的是**明确标记的示范数据**，不代表真实景区经营情况。

## 验证

```powershell
# 严格健康检查：数据库、Redis、GPU、本地向量模型和外部服务
# 数字人被游客占用时，WebSocket 探测会返回 skipped
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/system/strict-health?probe_external=true&require_cuda=true"

# 查看唯一数字人通道状态
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/avatar/channel"

# 知识证据、回答与动态路线验收
docker compose exec -T -e PYTHONPATH=/app api python -u scripts/rag_accuracy_check.py
docker compose exec -T -e PYTHONPATH=/app api python -u scripts/qa_acceptance_check.py
docker compose exec -T -e PYTHONPATH=/app api python -u scripts/route_dynamic_plan_acceptance.py

# 并发和真实语音链路
docker compose exec -T -e PYTHONPATH=/app api python -u scripts/api_stress_smoke.py
docker compose exec -T -e PYTHONPATH=/app api python -u scripts/voice_pipeline_acceptance.py

# 前端检查与生产构建
Set-Location frontend; npm.cmd run lint; npm.cmd run build
Set-Location ..\admin-web; npm.cmd run lint; npm.cmd run build
```

真实 WebSDK 验收必须串行：先关闭游客页并等待通道冷却，再执行后台首帧验收；完成并释放通道后再打开游客端。`avatar authentication failed` 表示账号或资源鉴权失败，不等同于通道占用。

## 关键实现约束

- **单通道数字人**：账号同一时刻最多 1 路。Redis 租约统一协调游客端、后台预览和探测，游客优先；字幕和动作只响应讯飞真实事件，不按文本长度伪造时间轴。
- **问答与 RAG**：默认走 `/api/v1/text/stream`。RAG 约束事实而非固定话术；票价、开放时间和演出安排等动态信息不由模型猜测，应以景区最新公告为准。
- **定位与行程**：GPS 使用 WGS84 和动态半径；精确点与公开示意图估算点明确区分。当前没有经过现场标定的 WiFi 指纹库，定位使用 GPS、二维码或手动选择。
- **管理端角色**：Avatar ID 表示“形象与服装套装”，不提供虚假独立换装；只有真实首帧截图保存成功后才标记为已验证。
- **图片与社区**：图片问答先调用视觉模型读取像素，再用 RAG 补充背景；文创结果由讲解、游记和明信片复用。社区图片当前保存在本地静态目录。

## 项目结构

```text
backend/              FastAPI、RAG、LLM、定位、故事、讯飞 ASR/TTS/数字人
backend/scripts/      初始化、知识入库、向量生成和自动验收脚本
frontend/             游客端响应式 Web
admin-web/            管理后台
models/bge-m3/        本地 BGE-M3 模型目录（不提交）
init-scripts/         PostgreSQL / pgvector 初始化脚本
示范景区公开资料包/   可选本机原始 Word / Excel（不提交）
材料/                 比赛方案、手册和 PPT（不提交）
```

## 提交前检查

不要提交 `.env`、模型权重、`node_modules/`、`.venv/`、构建产物、原始资料包、比赛材料、`.ican-work/` 或超过 100 MB 的演示视频。修改讯飞账号或角色资源后，应重建 `api` 服务，并在管理端逐个完成真实首帧预览。
