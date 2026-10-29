# 灵境智游

AI 数字人智慧景区导览系统。游客端覆盖文本、语音、图片问答、实时行程陪伴、互动故事和文创社区；管理端覆盖知识库、RAG 修复复测、数字人配置、演示准备和运营分析。

第十五届“中国软件杯”大赛 A5「景区导览服务 AI 数字人」全国二等奖作品 demo。

## 核心功能

- **游客端**：React + TypeScript 响应式网页，适配手机、平板和桌面。
- **数字人**：五个讯飞虚拟人角色，Redis 协调唯一 WebSDK 通道并保证游客优先。
- **智能问答**：DeepSeek + PostgreSQL/pgvector + 本地 BGE-M3，支持流式回答和不同回答长度。
- **路线与定位**：按兴趣、位置、时长和体力规划路线，支持到站、跳过、疲劳和重规划。
- **互动与文创**：互动故事、图片识景、知识讲解、游记和照片明信片。
- **管理后台**：知识修复与真实复测、数字人配置、运营分析和中文 PDF 报告。

演示数据由脚本明确标记，不代表景区真实经营数据。

## 架构

```text
游客端 / 管理端
  ├─ FastAPI：问答、行程、故事、文创、管理接口
  ├─ PostgreSQL + pgvector：业务数据与知识向量
  ├─ Redis：数字人通道租约与缓存
  ├─ 嵌入服务：本地 BGE-M3，CPU 或 NVIDIA GPU
  └─ 外部服务：DeepSeek、讯飞、视觉模型
```

浏览器负责语音、图片和页面交互；后端负责检索、生成与业务协调；讯飞 WebSDK 负责数字人视频流。

## 环境要求

- Docker Compose。
- 本地检查前端时：Node.js 22.12+。
- 本地检查后端时：Python 3.11。
- 使用真实问答、语音、图片或数字人能力时，需要相应的 DeepSeek、讯飞和视觉模型账号。
- 默认 API 会等待嵌入服务健康。请准备本地 BGE-M3 权重；没有 NVIDIA GPU 时使用下文的 CPU 启动方式。

## 首次启动

### 1. 配置环境变量

```powershell
Copy-Item .env.example .env
```

按实际开通情况填写：

```dotenv
DEEPSEEK_API_KEY=
XFYUN_APP_ID=
XFYUN_API_KEY=
XFYUN_API_SECRET=
XFYUN_AVATAR_SCENE_ID=
VISION_API_KEY=
ADMIN_PASSWORD=
JWT_SECRET=
```

`JWT_SECRET` 必须换成新的随机长字符串。形象 ID、音色和地域地址只有在账号未授权原资源时才需要修改；空的形象 ID 会回退到示例配置中的默认值。

### 2. 准备模型

从 Hugging Face 的 [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) 页面下载权重到：

```text
models/bge-m3/
```

模型权重约 2GB，不纳入 Git。原始景区 Word/Excel 不参与默认入库；规范化资料位于 `backend/scripts/a5_official_materials.json`。

### 3. 启动服务

没有 NVIDIA GPU 时，使用 CPU 覆盖配置：

```powershell
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up -d --build
```

已有可用的 NVIDIA 驱动和 GPU 容器运行时时，可以使用默认 CUDA 配置：

```powershell
docker compose up -d --build
```

两种配置都会启动 API、游客端、管理端、PostgreSQL、Redis 和嵌入服务。`docker-compose.cpu.yml` 仅覆盖嵌入相关镜像、CPU 设备和 GPU 申请，不改变业务代码。

### 4. 初始化数据

CPU 环境：

```powershell
docker compose -f docker-compose.yml -f docker-compose.cpu.yml exec api python -m scripts.init_db
docker compose -f docker-compose.yml -f docker-compose.cpu.yml exec api python -m scripts.init_data
docker compose -f docker-compose.yml -f docker-compose.cpu.yml exec api python -m scripts.init_storylines
docker compose -f docker-compose.yml -f docker-compose.cpu.yml exec api python -m scripts.ingest_knowledge
docker compose -f docker-compose.yml -f docker-compose.cpu.yml run --rm embedding-worker
```

GPU 环境可以将上述命令简写为 `docker compose ...`，参数保持一致。

| 服务 | 地址 |
|------|------|
| 游客端 | http://127.0.0.1:3000 |
| 管理后台 | http://127.0.0.1:3001 |
| 后端 API | http://127.0.0.1:8000/docs |
| 嵌入服务 | http://127.0.0.1:8010/health |

管理账号来自 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD`。需要演示图表和社区样例时，可另外执行 `scripts.seed_demo_analytics` 与 `scripts.seed_community_showcase`。

## 本地验证

后端：

```powershell
Set-Location backend
python -m pip install -r requirements-dev.txt
python -m compileall -q app tests
python -m unittest discover -s tests -v
```

游客端：

```powershell
Set-Location ../frontend
npm ci
npm run lint
npm run build
```

管理端：

```powershell
Set-Location ../admin-web
npm ci
npm run lint
npm run build
```

Compose 配置检查：

```powershell
Set-Location ..
docker compose config --quiet
docker compose -f docker-compose.yml -f docker-compose.cpu.yml config --quiet
```

真实数据库迁移、GPU 推理、外部云 API、讯飞授权和浏览器麦克风需要在相应环境中单独验收，不能由静态检查替代。

## 大文件与本地内容

- `models/`：模型权重，不提交。
- `示范景区公开资料包/`：原始 Word/Excel，仅在重新聚合时使用，不提交。
- `材料/`：比赛方案、手册和 PPT，不提交。
- 演示视频：保留在本机，不提交。
- `backend/app/static/community-images/` 与 `backend/app/static/avatar-previews/`：运行期生成内容，不提交；应用启动时会自动创建目录。

## 项目结构

```text
backend/        FastAPI、检索、对话、定位、故事、讯飞接口
frontend/       游客端
admin-web/      管理端
init-scripts/   PostgreSQL 初始化
models/         本地模型目录，不提交
```

## 许可与第三方内容

项目代码采用 [MIT License](LICENSE)。该许可只覆盖贡献者拥有权利的部分。

讯飞 SDK、WebRTC adapter、官方资料包、字体、模型和其他第三方内容遵循各自条款，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。公开下载不自动等同于获得任意再分发权。

当前默认用户头像和角色卡片头像为项目生成的抽象图形；景区主图已裁去近景游客。运行期上传和预览截图不纳入仓库。
