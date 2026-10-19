# 灵境智游 · AI 数字人智慧景区导览系统

面向灵山胜境示范景区的响应式 Web 导览系统。游客端覆盖文本、语音、图片问答、实时行程陪伴、互动故事和文创社区；管理端覆盖知识库、RAG 修复复测、数字人配置、演示准备、运营大屏、分析月报和用户管理。

## 当前能力

| 模块 | 当前实现 |
|------|----------|
| 游客端 | React 18 + TypeScript 响应式 Web；适配手机、iPad 横竖屏、安全区和动态视口，桌面保留原三栏导航 |
| 数字人 | 5 个讯飞虚拟人：舒窈、明朗、风屿、明泽、雨桐；Redis 统一协调唯一 WebSDK 通道并固定游客优先，常连接播报支持真实两行字幕、随时中断和字幕关键词动作 |
| 智能问答 | DeepSeek + PostgreSQL/pgvector + 本地 BGE-M3；文本回答支持 SSE 流式增量和 `auto/brief/normal/detail` 单次生成模式，追问结合当前景点、行程下一站和图片识景结果并避开最近两轮重复 |
| 路线与定位 | 5 条路线，按兴趣、位置、时长和体力评分/裁剪；活动行程可到站、完成、跳过、疲劳/30 分钟重规划并跨页面恢复，结束后生成结构化足迹 |
| 互动故事 | 5 条故事线、36 个有效节点，每节点 3 个短选项，剧情文本直接交给数字人播报 |
| 文创社区 | 一次真实视觉调用完成识景、知识核对、数字人讲解、构图/发布建议；同一游客原图可直接写游记或导出照片明信片 |
| 管理后台 | JWT 登录、知识修复与真实复测闭环、数字人配置与真实首帧预览、响应式角色卡、30 日分析及中文 PDF 报告 |
| 语音 | 讯飞 ASR、标准在线 TTS、PCM 声学情感分析；数字人专属音色只由 WebSDK 使用 |

## 2026 软件杯 A5 对齐

本项目严格对齐[A5「大模型赋能的 5A 级景区 AI 数字人智能导览系统」](https://www.cnsoftbei.com/content-3-1245-1.html)。官方资料包已规范化为 23 篇可复现知识和 100 题确定性事实集，事实准确率与语音时延通过 `backend/scripts/` 下的验收脚本真实复测。评分结构、硬指标、冲突处理与验收口径见[项目详细方案](docs/灵境智游——项目详细方案.docx)。

当前真实评测结果为 100/100；数字人浏览器已记录 2 次真实首帧与 1 次开始播报事件。后台冷启动首帧样本为建连 371ms、首帧 10.883s，首帧出现后已自动释放唯一通道；该冷启动耗时与真人语音温连接 P95 分开统计。真人麦克风证据仍为 0/10，必须在最终演示环境串行采集后才能判断 P95 是否小于 5 秒。

灵山胜境是唯一结构化路线和定位主景区；拈花湾只作为关联目的地补充知识问答，不会混入灵山内部路线或 GPS 点位。

## 启动

### 1. 配置环境变量

复制 `.env.example` 为 `.env`，填写自己的服务凭证。不要把 `.env` 提交到仓库。

```powershell
Copy-Item .env.example .env
```

至少配置：

```dotenv
DEEPSEEK_API_KEY=your-key
XFYUN_APP_ID=your-app-id
XFYUN_API_KEY=your-api-key
XFYUN_API_SECRET=your-api-secret
XFYUN_AVATAR_SCENE_ID=your-service-id
XFYUN_AVATAR_LINGXIAOCHAN_ID=your-avatar-id
XFYUN_AVATAR_WUCHANSHI_ID=your-avatar-id
XFYUN_AVATAR_XUANZANG_ID=your-avatar-id
XFYUN_AVATAR_ZHAOPUCHU_ID=your-avatar-id
XFYUN_AVATAR_XIAOWAN_ID=your-avatar-id
XFYUN_TTS_VCN=xiaoyan
VISION_PROVIDER=aliyun_bailian
VISION_API_KEY=your-vision-key
VISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VISION_MODEL=qwen3.6-flash-2026-04-16
```

图片问答和照片点评共用这组 `VISION_*` 配置，并都会把真实图片像素发送给视觉模型。Kimi 开放平台使用 `kimi`、`https://api.moonshot.cn/v1` 和 `kimi-k2.6`；Kimi Code 会员通道使用 `kimi_code`、`https://api.kimi.com/coding/v1` 和 `kimi-for-coding`，已授权 HighSpeed 时可改为 `kimi-for-coding-highspeed`。两类密钥、地址和额度不能混用；会员密钥只能走 Kimi Code 通道，开放平台密钥仍需单独创建并保证余额可用。

`XFYUN_AVATAR_*_VCN` 是虚拟人 WebSDK 音色，`XFYUN_TTS_VCN` 是普通音频接口音色，两者授权体系不同，不应互相替代。

更换讯飞账号或接口服务时，只修改根目录 `.env` 中同一应用下的 `XFYUN_APP_ID`、`XFYUN_API_KEY`、`XFYUN_API_SECRET` 和 `XFYUN_AVATAR_SCENE_ID`；只有新服务不再授权原角色、音色或地域地址时，才改对应 `XFYUN_AVATAR_*_ID`、`*_VCN` 或 `XFYUN_AVATAR_SERVER_URL`。修改后执行：

```powershell
docker compose up -d --force-recreate api
```

如果 Avatar ID 或 VCN 也发生变化，再登录管理端“数字人配置”，点击“从 .env 重载角色资源”；无论是否重载，都要逐个完成实时预览。页面上的“基础配置通过”只检查字段完整，收到 WebSDK 首帧才代表当前账号真实授权可用。无需修改 Python、TypeScript 或 Compose 源码。换号详细步骤见[部署与使用手册](docs/灵境智游——部署与使用手册.docx)。

### 2. 启动服务

```powershell
docker compose up -d
```

| 服务 | 地址 |
|------|------|
| 游客端 | http://127.0.0.1:3000 |
| 管理后台 | http://127.0.0.1:3001 |
| 后端 API | http://127.0.0.1:8000/docs |
| 嵌入服务 | http://127.0.0.1:8010/health |

管理账号由 `.env` 中的 `ADMIN_USERNAME`、`ADMIN_PASSWORD` 决定。

### 3. 初始化数据

```powershell
docker compose exec api python -m scripts.init_db
docker compose exec api python -m scripts.init_data
docker compose exec api python -m scripts.init_storylines
docker compose exec api python -m scripts.ingest_knowledge
docker compose run --rm embedding-worker
```

需要演示非零运营大屏、30 日分析、RAG 异常样例和自然社区内容时，可额外执行以下固定、可重复且明确标记为示范数据的脚本；不要把这些结果当作真实景区经营数据：

```powershell
docker compose exec api python -m scripts.seed_demo_analytics
docker compose exec api python -m scripts.seed_community_showcase
```

知识入库默认读取随 Git 提交的 `a5_official_materials.json`，不依赖本机 16MB 原始资料包；原始 Word/Excel 仅用于重新生成和核验规范化内容，且不会加入 Git。脚本会清理旧解析器留下的同源重复文档。嵌入服务默认使用本地 BGE-M3 生成 1024 维向量；GPU 环境可通过健康接口确认：

```powershell
(Invoke-RestMethod http://127.0.0.1:8010/health).runtime
```

## 验证

```powershell
# 严格健康检查：数据库、Redis、GPU、本地向量模型、DeepSeek、TTS、数字人 WebSocket
# （数字人 WebSocket 探测会先取得唯一通道租约，被游客占用时返回 skipped）
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/system/strict-health?probe_external=true&require_cuda=true"

# 随时查看唯一数字人通道的 idle / occupied / cooldown 状态
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/avatar/channel"

# 知识证据与最终回答验收
docker compose exec -T -e PYTHONPATH=/app api python -u scripts/rag_accuracy_check.py
docker compose exec -T -e PYTHONPATH=/app api python -u scripts/qa_acceptance_check.py
docker compose exec -T -e PYTHONPATH=/app api python -u scripts/route_dynamic_plan_acceptance.py

# 并发和真实语音链路
docker compose exec -T -e PYTHONPATH=/app api python -u scripts/api_stress_smoke.py
docker compose exec -T -e PYTHONPATH=/app api python -u scripts/voice_pipeline_acceptance.py

# 前端生产构建
Set-Location frontend; npm.cmd run build
Set-Location ..\admin-web; npm.cmd run lint; npm.cmd run build
```

游客端还提供：

```powershell
Set-Location frontend
npm run lint
```

## 实现说明

- 数字人主链路是讯飞虚拟人 WebSDK，账号硬约束为同一时刻最多 1 路。Redis 租约统一协调游客端、角色预览、演示首帧和后端探测：游客租约 90 秒并每 15 秒续租，后台租约 45 秒并每 3 秒续租，真实释放后统一冷却 3.5 秒。
- 游客端优先：游客占用时后台预览禁用、探测显示 `occupied` 而不是接口故障；后台占用时游客到来会撤销后台租约，后台在下一次心跳销毁 WebSDK。游客端抽屉收起、普通切页、响应式宽度变化和标签页暂时隐藏都保持连接，换角色、页面真正关闭、显式重连或不可恢复断线才释放。
- 每轮回答返回的新签名地址不属于角色配置变化，不会触发 WebSDK 重建；真实视频首帧出现后立即隐藏“准备中”，透明数字人继续使用景区底图。长时间空闲后断线或从后台返回时先向后端刷新短时签名，再自动恢复且不重复朗读上一条回复。
- 文本、快捷问题、图片和录音会先中断上一段播报但保留 WebSDK 连接；交互状态直接跟随 SSE 阶段，字幕和动作只响应讯飞真实事件，不按回答长度伪造时间轴。
- 文本问答默认使用 `/api/v1/text/stream` 按增量更新消息，服务端不支持增量时会在未输出分片的前提下安全回退为单次生成。
- 文本请求可携带 `response_mode=auto|brief|normal|detail`：快捷问题为 40–80 字简答，普通问答为 80–140 字，明确要求展开时为 180–300 字；三种模式只调整提示词与单次生成预算，不在流结束后裁字，也不增加第二次模型调用。
- RAG 只约束事实，不作为固定话术：一般景点介绍由模型结合最近上下文重新组织，重复追问侧重新角度；高度、地址、票价等精确事实仍走短快答并保持数字一致。
- 管理端低置信溯源可幂等转为知识草稿，发布后立即清缓存并沿真实问答主链路复测；对比结果会持久化，不生成游客画像或数字人任务。
- 当前 5 个形象 ID 和音色由后端统一配置；游客明确选角优先于旧景点触发关系，故事 NPC 使用临时活动角色。
- 管理端角色名称和角色编码是固定业务槽位；人物形象决定性别并过滤音色。人设描述会参与实际问答，景点触发只在游客未明确选角时使用，动作预设会约束问答动作。
- 管理端把 Avatar ID 明确表达为“形象与服装套装”：服饰由真实讯飞资源固定，不实现虚假独立换装；只有当前 Avatar ID、VCN 的真实首帧截图保存成功后才显示已验证。
- 对话讲解偏好按“本轮明确表达 > 会话最近兴趣画像 > 当前路线标签”恢复；同一景点的核心事实保持一致，历史、亲子、摄影等讲解重点和建议会明显变化。
- A5 官方知识元数据记录资料包、源文件、哈希、景区范围、有效性和冲突状态；普通灵山问答只检索灵山资料，显式询问拈花湾时才切换景区范围。
- 知识库页进入时自动执行真实 Embedding 探测；分析页 PDF 使用中文字体、自动换行和分页表头，并明确标注演示样例。
- 当前动态票价、开放时间、演出安排不会由模型猜测。知识库会提示原灵山官网已停止服务，并引导用户以景区最新公告或客服电话为准。
- GPS 使用 WGS84 和 80–300 米动态半径；精确点与公开示意图估算点在接口和页面中明确区分，不包装成现场测绘结果。
- 活动行程保存在浏览器本地，开始、到站、完成、跳过、重规划和结束事件写入现有行为日志；全局文字、语音和图片问答自动携带当前路线与已确认景点。
- 当前版本没有经过现场标定的 WiFi 指纹库；旧的模拟 SSID 映射已删除，浏览器端改用 GPS、二维码或手动选择。
- 管理端运营数据包含明确标记的示范样本，用于展示非零图表，不代表景区真实经营数据。
- 图片问答先调用配置的真实视觉模型读取像素，再用 RAG 补充已确认景点背景；文创模式一次返回画面事实、识景、构图和发布建议，随后数字人讲解、游记和明信片均复用结果，不重复调用视觉模型。社区图片当前保存在本地静态目录。
- 真实 WebSDK 验收必须串行：先关闭游客页并等待通道冷却归零，再执行后台首帧验收；首帧保存后页面会立即销毁实例并释放，冷却结束后才重新打开游客端。`avatar authentication failed` 属于账号或资源鉴权，不等同于通道占用，也不会无意义重试。

## 项目结构

```text
backend/              FastAPI、RAG、LLM、定位、故事、讯飞 ASR/TTS/数字人
backend/scripts/      初始化、知识入库、向量生成和自动验收脚本
frontend/             游客端响应式 Web
admin-web/            管理后台
models/bge-m3/        本地 BGE-M3 模型目录
示范景区公开资料包/   可选本机原始 Word/Excel（被 Git 忽略）
docs/                 产品方案介绍 PPT、部署与使用手册、项目详细方案（决赛交付文档）
```

## 本地 Git

- 源码在本目录维护。提交前确认 `.gitignore` 生效。
- 不提交 `.env`、`models/` 下的 BGE-M3 权重、`node_modules/`、`.venv/`、构建产物、`示范景区公开资料包/`、`.ican-work/` 和超过 100MB 的演示视频。
- 克隆后复制 `.env.example` 为 `.env` 并填写自己的密钥；嵌入模型单独下载到 `models/bge-m3`。

## 文档

- [产品需求文档](PRD_灵境智游_AI数字人智慧景区导览系统.md)
- [软件设计文档](软件开发设计文档_SDD_灵境智游.md)
- [产品方案介绍 PPT](docs/灵境智游——产品方案介绍PPT.pptx)
- [部署与使用手册](docs/灵境智游——部署与使用手册.docx)
- [项目详细方案](docs/灵境智游——项目详细方案.docx)
