# DeerFlow 2.0 平台功能与代码实现全景图

> 本文档与《DeerFlow 2.0 整体架构图》（三域八层 L1–L8）一一对应，梳理每个功能模块的**功能介绍**、**代码位置**与**实现机制**，并在文末给出**从启动到各功能激活的完整流转说明**。
>
> - 应用域（APP）：L1 接入层、L2 应用服务层
> - 运行时域（HARNESS）：L3 智能体编排层、L4 Skill 技能层、L5 工具层、L6 沙箱执行层
> - 基础设施域（INFRA）：L7 模型层、L8 数据层
>
> 依赖规则：App 域（`backend/app/*`）可调用 Harness 域（`backend/packages/harness/deerflow/*`），反向禁止，由 `backend/tests/test_harness_boundary.py` 在 CI 中强制。

---

## 目录

- [L1 接入层（Access）](#l1-接入层access)
- [L2 应用服务层（Gateway API）](#l2-应用服务层gateway-api)
- [L3 智能体编排层（Agent Orchestration）](#l3-智能体编排层agent-orchestration)
- [L4 Skill 技能层](#l4-skill-技能层)
- [L5 工具层（Tools & MCP）](#l5-工具层tools--mcp)
- [L6 沙箱执行层（Sandbox Runtime）](#l6-沙箱执行层sandbox-runtime)
- [L7 模型层（Model-Agnostic SaaS）](#l7-模型层model-agnostic-saas)
- [L8 数据层（State & Persistence）](#l8-数据层state--persistence)
- [横切能力](#横切能力)
- [启动到功能激活的完整流转](#从启动到功能激活的完整流转)

---

## L1 接入层（Access）

统一对外入口，所有外部流量经 Nginx 汇聚后按路径分发。

### 1.1 Nginx 统一入口（Port 2026）

**功能介绍**：平台唯一公网入口。将 `/api/langgraph/*` 重写为 Gateway 原生路由、其余 `/api/*` 直传 Gateway、`/` 转发前端，SSE 流刻意不压缩、不缓冲。

**代码位置**：`docker/nginx/nginx.conf`

**实现机制**：
- 监听声明（第 80-83 行）：`listen 2026 default_server;`（IPv4 + IPv6）。
- LangGraph 兼容重写（第 107-140 行）：`rewrite ^/api/langgraph/(.*) /api/$1 break;`，代理到 `gateway:8001`，设置 `X-Accel-Buffering: no` 支持 SSE、600s 超时、20M 请求体。
- 分类路由（第 143-361 行）：`/api/models`、`/api/memory`、`/api/mcp`、`/api/skills`、`/api/agents`、`/api/threads`（含 uploads、browser/stream WebSocket）各有专用 `location`，最终 `/api/` catch-all 兜底。
- 健康检查 `/health`（第 320-328 行）→ Gateway；`/api/sandboxes` → `provisioner:8002`（可选）。
- 前端服务（第 364-381 行）：`location /` → `frontend:3000`，透传 WebSocket upgrade（供 Next.js HMR 与浏览器 Live）。
- 头部 `map`（第 43-77 行）：保留上游 HTTPS scheme、按需升级连接、将 `127.0.0.1` 规范化为 `localhost`。
- gzip 仅作用于文本资源（第 20-26 行），SSE/音视频/字体不压缩。

### 1.2 Web 工作台（Next.js，Port 3000）

**功能介绍**：用户主交互界面——线程对话、制品查看、自定义 Agent、定时任务、能力中心、回收站等。

**代码位置**：`frontend/src/app/`（Next.js App Router）

**实现机制**：
- 核心路由：`workspace/chats/[thread_id]/page.tsx`（聊天页）、`workspace/agents/`（自定义 Agent）、`workspace/scheduled-tasks/`（定时任务）、`workspace/projects/`（项目）、`workspace/trash/`（回收站）、`(auth)/`（登录 + `/setup` 首启管理员引导）。
- 数据流：`core/threads/hooks.ts`（useThreadStream / useSubmitThread）经 LangGraph SDK 连接后端，默认走 nginx 同源 `/api/langgraph`，无需配置 `NEXT_PUBLIC_*`。
- 服务端鉴权：`core/auth/server.ts::getServerSideUser()` 在每个 layout 中判定 `authenticated / needs_setup / system_setup_required / unauthenticated`，分别放行或重定向。
- 前端自动登录：登录成功由后端写入 `HttpOnly access_token` Cookie；`AuthProvider` 在页面可见性恢复时调用 `GET /api/v1/auth/me` 复核会话。

### 1.3 IM 渠道（飞书 / Slack / Telegram / Discord / 企微 / 钉钉）

**功能介绍**：将 IM 消息桥接到 Agent 运行时，实现「在聊天软件里直接用 DeerFlow」。

**代码位置**：`backend/app/channels/`

**实现机制**：
- 注册表懒加载：`service.py::_CHANNEL_REGISTRY`（第 28-39 行）把渠道名映射到实现类（`feishu.py:FeishuChannel`、`slack.py:SlackChannel`、`telegram.py:TelegramChannel`、`discord.py:DiscordChannel`、`dingtalk.py:DingTalkChannel`、`wecom.py:WeComChannel` 等）。
- 凭据探测：`_CHANNEL_CREDENTIAL_KEYS`（第 42-52 行）判定渠道是否已配置。
- 生命周期：`ChannelService.start()`（第 202 行）→ `ensure_ready_channels()` → `_start_channel()` 按 `enabled: true` 懒加载启动；由 Gateway lifespan 统一拉起（app.py 第 719 行 `start_channel_service()`）。
- 消息管线：`base.py` 定义 `Channel` 抽象（start/stop/send）；`message_bus.py` 提供入站队列 + 出站分发；`manager.py::ChannelManager` 通过 langgraph-sdk 调 Gateway 创建线程与 run；`store.py` 持久化 `channel:chat_id → thread_id` 映射。

### 1.4 Python Client（嵌入式调用）

**功能介绍**：不经 HTTP 直接在 Python 进程内使用 harness，与 Gateway 共享配置与数据目录，适合脚本/二次开发。

**代码位置**：`backend/packages/harness/deerflow/client.py`（约 1900 行）

**实现机制**：
- `DeerFlowClient`（第 175 行）：懒创建 `create_agent()` + `build_middlewares()`，按 `user_id + mcp_plugins` 缓存编译后的图。
- 会话 API：`stream()`（第 857 行，产出 `StreamEvent`）、`chat()`（第 1304 行，同步返回最终文本）。
- 与 Gateway 等价的管理方法：`list_models()`、`get_mcp_config()`、`list_skills()`、`install_skill()`、`get_goal()/set_goal()`、`get_memory()/reload_memory()`、`upload_files()`、`get_artifact()` 等。

---

## L2 应用服务层（Gateway API）

FastAPI 管理面（端口 8001），承载非 Agent 执行类的全部管理面 API。

### 2.1 应用装配与启动

**代码位置**：`backend/app/gateway/app.py`

**实现机制**：
- `create_app()`（第 956 行）：创建 FastAPI 实例（docs 受 `GATEWAY_ENABLE_DOCS` 控制），注册 `lifespan`。
- 中间件栈（按注册顺序）：`AuthMiddleware`（未认证 fail-closed）→ 扩展 principal 解析器 → `CSRFMiddleware`（双提交 Cookie）→ 条件 `CORSMiddleware` → `TraceMiddleware`（X-Trace-Id）。
- 扩展加载（第 1171-1188 行）：`load_extensions(configured_plugins)`，`required: true` 的扩展加载失败即中止启动。
- 路由注册（第 1194-1351 行）：38 个内置路由器按序 `include_router`，扩展贡献的路由最后注册（宿主优先）。

### 2.2 管理面路由清单（`backend/app/gateway/routers/`）

| 功能 | 文件 | 路由前缀 | 说明 |
|---|---|---|---|
| 模型管理 | `models.py` | `/api` | `GET /api/models` 模型列表 |
| 管理员模型 | `managed_models.py` | `/api/managed-models` | 模型管理 + `/test` 流式测试 |
| 能力开关 | `features.py` | `/api` | `GET /api/features` UI 特性探测 |
| 可观测性 | `console.py` | `/api/console` | 跨线程 stats / runs / usage |
| MCP 配置 | `mcp.py` | `/api` | `/api/mcp/config` 读写、servers CRUD |
| 个人 MCP | `personal_mcp.py` | `/api/mcp/personal/config` | 用户级 MCP |
| 记忆管理 | `memory.py` | `/api` | 读取 / reload / config / status |
| 技能管理 | `skills.py` | `/api` | 列表 / 启停 / 安装 / reload |
| 文件/制品 | `uploads.py`、`artifacts.py` | `/api/threads/{id}/...` | 上传转 Markdown、制品字节范围流式读写 |
| 线程管理 | `threads.py` | `/api/threads` | 生命周期 / 分支 / goal / compact / 消息分页 |
| Run 执行 | `thread_runs.py` | `/api/threads/{id}/runs` | LangGraph 兼容 run create/stream/wait/cancel |
| 定时任务 | `scheduled_tasks.py` | `/api/scheduled-tasks` | CRUD + `/preview-cron` |
| 自定义 Agent | `agents.py` | `/api/agents` | per-agent config/prompt CRUD（SOUL.md 注入） |
| 子代理 | `subagents.py`、`subagent_batches.py` | `/api/subagents` 等 | 目录管理与批处理 |
| 项目 | `projects.py`、`project_documents.py` | `/api/projects` | 项目与文档架 |
| 渠道 | `channels.py`、`channel_connections.py` | `/api/channels` | 渠道状态与用户绑定 |
| 对话建议 | `suggestions.py` | `/api` | 追问建议生成 |
| 认证 | `auth.py` | `/api/v1/auth` | 本地登录 / OIDC / PAT / 改密 |
| 健康检查 | `app.py` + `health.py` | `/health`、`/health/ready` | 存活与就绪探针 |

**健康检查实现**：`backend/app/gateway/health.py::readiness_payload()`（第 347 行）并发探测 database / checkpointer / stream_bridge 三类门控后端（任一不可达 → 503 degraded），provisioner 仅报告不置 503；`make up` 等待 `/health` 通过后才打印就绪横幅。

---

## L3 智能体编排层（Agent Orchestration）

Agent 运行时的核心：意图解析、规划拆解、子代理委派、流式输出。

### 3.1 Lead Agent

**功能介绍**：主智能体，负责理解用户意图、拆解任务、调用工具与子代理、汇总结果。

**代码位置**：`backend/packages/harness/deerflow/agents/lead_agent/`

**实现机制**：
- `agent.py::make_lead_agent(config)` — `langgraph.json` 发布的入口；`assemble_lead_agent()` 是 Gateway 侧工厂：解析用户身份（`resolve_config_user_id`）、模型（`_resolve_model_name` + `_authorize_model_name` 授权）、自定义 Agent 配置（`load_agent_config`）、技能白名单（`filter_available_skills_by_authorization`），再通过 `deerflow.tools.get_available_tools()` 组装工具集（含 `task_tool`、记忆工具、项目文档工具），最后用 LangChain `create_agent(...)` 挂中间件链编译成图。
- `prompt.py::SYSTEM_PROMPT_TEMPLATE` — 静态基座模板（利于 prefix 缓存），`{soul}`、`{skills_section}`、`{subagent_section}`、`{memory_tool_section}` 等槽位由 `apply_prompt_template()` 渲染；动态日期/记忆由 `DynamicContextMiddleware` 以 `<system-reminder>` 注入首条 HumanMessage；所有不可信值（技能名、描述）HTML 转义防 prompt 注入。

### 3.2 动态子智能体

**功能介绍**：`task` 工具把子任务委派给隔离上下文的后台子代理并行执行，受并发与轮次限流。

**代码位置**：`backend/packages/harness/deerflow/subagents/`

**实现机制**：
- 注册解析：`registry.py::get_subagent_config(name)` 分层合并：内置（`builtins/general_purpose.py`、`bash_agent.py`）→ `config.yaml subagents.custom_agents` → 管理员 DB 定义 → per-agent 覆盖。
- 执行引擎：`executor.py::SubagentExecutor`（第 843 行）为每个任务构建全新 `ThreadState`（可选 `context_mode="snapshot"` 父历史快照），在**持久隔离事件循环**（`_execute_in_isolated_loop`）中运行子图，捕获步骤事件并发出 `task_started/running/completed/failed/timed_out` 自定义事件；超限以 `stop_reason`（`token_capped|turn_capped|loop_capped`）附加在结果上。
- 容量控制：`capacity.py::SubagentExecutionCapacity` 进程级 FIFO 准入（默认并发 3）。
- 委派工具：`tools/builtins/task_tool.py::task_tool`（第 669 行）是模型可见入口：解析子代理配置 → 校验 `allowed_subagents` 策略 → 提交隔离循环/容量槽 → 轮询结果 → 包装为带结构化 `additional_kwargs` 的 `ToolMessage`。

### 3.3 四种执行模式（flash / thinking / pro / ultra）

**功能介绍**：用户在前端选择执行档位，档位决定思考开关、计划模式与子代理开关。

**代码位置**：前端定义 + 后端消费
- `frontend/src/core/threads/hooks.ts::buildRunContext()`（第 247 行）——权威映射：
  - `thinking_enabled = mode !== "flash"`
  - `is_plan_mode = mode === "pro" || mode === "ultra"`（启用 TodoList 中间件）
  - `subagent_enabled = mode === "ultra"`（启用 `task` 工具）
  - `reasoning_effort = ultra→high / pro→medium / thinking→low`
- `backend/app/gateway/services.py`（第 615 行）——`_CONTEXT_CONFIGURABLE_KEYS` 白名单把 `mode`、`thinking_enabled`、`is_plan_mode`、`subagent_enabled` 从请求体 `context` 并入运行配置。
- 后端消费：`agent.py::_assemble_lead_agent` 读这些键；`models/reasoning.py` 翻译为 provider 特定参数。

### 3.4 中间件链

**功能介绍**：围绕模型调用与工具调用的 30+ 个横切钩子，实现安全、上下文工程、审计与纠错。

**代码位置**：`backend/packages/harness/deerflow/agents/middlewares/`，组装于 `lead_agent/agent.py::build_middlewares()`（第 483 行）

**实现机制**（关键节点，按外层→内层顺序）：
1. 运行时基座（`tool_error_handling_middleware.py::build_lead_runtime_middlewares`）：输入消毒（边界标记）→ 知识范围 → 工具输出预算（超量落盘）→ 工具结果消毒 → PII 脱敏 → 线程目录 → 上传注入 → **沙箱获取** → 悬空工具调用修补 → LLM 错误兜底 → 授权/护栏 → 沙箱审计 → 写前读校验 → 工具回执。
2. Lead 专属：动态上下文注入 → **技能激活** → 技能工具策略 → 持久上下文（委派/技能台账）→ **摘要压缩** → **Todo（计划模式）** → Token 统计 → 标题生成 → **记忆写入排队** → 视觉图片 → MCP 路由/延迟工具过滤 → 系统消息合并 → 子代理限额 → **循环检测** → Token 预算 → 终端空响应重试 → 安全 finish_reason → **澄清拦截（永远最后）**。
3. 扩展中间件：`extensions/stack.py::compose_with_extensions` 最后合入。

### 3.5 SSE 流式响应

**功能介绍**：执行过程实时推送给前端，支持断线重连与回放缺口恢复。

**代码位置**：
- 运行管理：`runtime/runs/manager.py::RunManager`（第 257 行）——准入（多任务策略 reject/interrupt/rollback、幂等键、租约心跳、孤儿接管）。
- 执行 worker：`runtime/runs/worker.py::run_agent()`（第 891 行）——构建运行时上下文、调 `graph.astream`、把 LangGraph chunk 转 SSE 事件、批量合并 `write_file`/`str_replace` 增量、盖 `deerflow_seq` 序号。
- 流桥：`runtime/stream_bridge/`（`base.py::StreamBridge` ABC + `memory.py` / `redis.py` 实现）——有界保留缓冲，过期 `Last-Event-ID` 返回 `StreamGap`。
- Gateway 消费：`app/gateway/services.py::sse_consumer()`（第 2465 行）——订阅桥并格式化 SSE 帧（含 `gap` 控制帧）。

### 3.6 上下文工程（摘要压缩 / 剪枝 / 落盘卸载）

**代码位置与机制**：
- 自动摘要：`middlewares/summarization_middleware.py::DeerFlowSummarizationMiddleware`（第 120 行）按 `config.yaml summarization` 的 tokens/messages/fraction 触发，摘要写入 `ThreadState.summary_text`（LastValue 通道），由 `DurableContextMiddleware` 投影回后续请求。
- 手动压缩：`runtime/context_compaction.py::compact_thread_context()`（第 132 行），对应 `POST /api/threads/{id}/compact`，走 `checkpoint_write` 互斥预留。
- 工具输出落盘：`tool_output_budget_middleware.py` 把超限结果外置到 `{thread}/.tool-results/`，替换为摘要 + `read_file` 引用；被覆盖的 `write_file` 参数会被擦除（`tool_call_args.py::elide_superseded_writes`）。
- 防丢保护：`DurableContextMiddleware` 在摘要前捕获委派台账（`delegations`）与技能上下文（`skill_context`）。

### 3.7 计划模式（TodoList）

**代码位置**：`middlewares/todo_middleware.py::TodoMiddleware`

**实现机制**：`is_plan_mode=True` 时启用，扩展 LangChain `TodoListMiddleware`（提供 `write_todos` 工具），额外实现两点：(a) 上下文丢失检测——摘要滚出 `write_todos` 调用时重新注入提醒；(b) 提前退出防护——最终响应但 todo 未完成时注入完成提醒并跳回模型节点。同一时间仅一个 `in_progress`。

---

## L4 Skill 技能层

技能即 Markdown（SKILL.md），声明式扩展 Agent 能力。

### 4.1 技能加载与解析

**代码位置**：`backend/packages/harness/deerflow/skills/`

**实现机制**：
- 存储基座：`storage/skill_storage.py::SkillStorage.load_skills()`（第 341 行）每次调用扫描全部类别根目录，`parser.py::parse_skill_file` 解析 SKILL.md YAML frontmatter（name、description、`allowed-tools`、`required-secrets` 等），并从 `extensions_config.json` 合并启停状态。
- 本地实现：`storage/local_skill_storage.py`（目录布局 `<root>/public/<name>/SKILL.md`、`<root>/custom/<name>/SKILL.md`），支持 `.skill` ZIP 安装。
- 用户隔离：`storage/user_scoped_skill_storage.py` 把 custom 技能重定向到 `{DEER_FLOW_HOME}/users/{user_id}/skills/custom/`，每用户启停状态存 `_skill_states.json`。

### 4.2 双层存储（public/custom 同名覆盖）

**实现机制**：`load_skills()` 按 `SkillCategory` 枚举顺序遍历并把技能累积进 `skills_by_name` 字典——后遍历的类别按名覆盖先前条目，因此 **custom 同名技能遮蔽 public**；`user_scoped_skill_storage.py` 实现「shadow-mount」语义：用户一旦有自己的 custom 目录，全局 `skills/custom/` 回退即对该用户消失。

### 4.3 渐进式加载

**实现机制**（由 `config.yaml → skills.deferred_discovery` 控制）：
- 默认（false）：`lead_agent/prompt.py::get_skills_prompt_section()` 把全量技能元数据渲染进系统提示词 `<available_skills>`，LRU 缓存 + 跨进程失效标记。
- 延迟发现（true）：`skills/catalog.py::SkillCatalog` 提供不可变目录（`select:`/`+前缀`/意图词查询，上限 5 条）；Agent 先见仅含名字的 `<skill_index>`，用 `describe_skill` 工具取元数据，再用 `read_file` 读 SKILL.md 正文（记入 `ThreadState.skill_context`）。

### 4.4 显式激活（/skill-name）

**实现机制**：
- 解析：`skills/slash.py::parse_slash_skill_reference()`，正则 `^/([a-z0-9]+(?:-[a-z0-9]+)*)(\s+|$)`，保留名集合（agent/goal/memory/models 等）除外；前后端共享契约 `contracts/slash_skill_contract.json`。
- 执行：`middlewares/skill_activation_middleware.py::SkillActivationMiddleware`（第 116 行）为当前模型调用载入被激活技能的 SKILL.md 并解析密钥绑定；`skill_tool_policy_middleware.py` 动态施加技能的 `allowed-tools` 限制。
- 前端：`input-box.tsx` 的 `/` 列表（当前列出 `/goal`、`/compact`）与 `@` 提及选择器（`components/workspace/mentions/`，以 `additional_kwargs.skill_references` 传递）。

### 4.5 内置技能与安全审查

- **内置技能 23 个**（`skills/public/`）：academic-paper-review、bootstrap、chart-visualization、claude-to-deerflow、code-documentation、consulting-analysis、data-analysis、deep-research、find-skills、frontend-design、github-deep-research、image-generation、music-generation、newsletter-generation、podcast-generation、ppt-generation、skill-creator、skill-reviewer、surprise-me、systematic-literature-review、vercel-deploy、video-generation、web-design-guidelines。
- **技能审查**：`skills/review/`（analyzer/readers/renderer，只读分析，不执行脚本、不联网）+ 内置工具 `tools/builtins/review_skill_package_tool.py::review_skill_package`；CI 豁免清单 `.github/skill-review-waivers.v1.json`。

---

## L5 工具层（Tools & MCP）

### 5.1 内置工具

**代码位置**：
- `backend/packages/harness/deerflow/tools/builtins/`：`task_tool`（子代理委派）、`batch_task_tool`、`clarification_tool`（ask_clarification）、`present_file_tool`、`view_image_tool`、`list_uploaded_files_tool`、`background_tasks_tool`、`tool_search`、`review_skill_package_tool` 等，注册表 `tools/tools.py::BUILTIN_TOOLS`。
- 沙箱/文件/Bash：`sandbox/tools.py`——`bash_tool`、`ls_tool`、`glob_tool`、`grep_tool`、`read_file_tool`、`write_file_tool`、`str_replace_tool`（各含异步变体），经 `config.yaml tools[]` 的 `use: deerflow.sandbox.tools:xxx` 接线。
- 社区工具：`community/` 29 个目录——搜索（tavily/ddg/brave/exa/serper/searxng/sofya 等）、抓取（jina_ai/firecrawl/crawl4ai/browserless 等）、图片搜索、浏览器自动化（Playwright）、知识库（ragflow/lightrag）等。

### 5.2 MCP 原生支持（stdio / SSE / HTTP · OAuth 2.0）

**代码位置**：`backend/packages/harness/deerflow/mcp/`

**实现机制**：
- 传输构造：`client.py::build_server_params()`（stdio → command/args/env/cwd；http/sse → url/headers），基于 `langchain-mcp-adapters` 的 `MultiServerMCPClient`。
- 工具装载：`tools.py::get_mcp_tools()`（第 884 行）——按服务器发现工具、施加 `tool_name_prefix`、stdio 工作区钉定、会话池包装。
- 缓存与失效：`cache.py` 按解析后路径 + `(mtime,size,sha256)` 签名判 stale，`publish_mcp_tools_cache_reset()` 跨进程重置。
- stdio 会话池：`session_pool.py::MCPSessionPool`（LRU + 硬上限），键含 `(server, scope, loop, domain)` 四元组隔离。
- OAuth：`oauth.py::OAuthTokenManager`（client_credentials/refresh_token 自动刷新），头部合法性经 `headers.py` 校验。
- 配置来源：`config/extensions_config.py::get_enabled_mcp_servers()` 读取 `extensions_config.json` 的 `mcpServers`（支持 `$ENV_VAR` 引用，热重载，原子写）。
- 凭据拦截链：静态 headers < oauth < user_auth < headers_from_context（`interceptors.py`）。
- 长时任务：`mcp/tasks/` + `app/mcp_tasks/`——提交类工具立即返回，状态轮询与取消由持久化任务运行时承担。

### 5.3 延迟加载（tool_search 先查后调）

**代码位置**：`tools/builtins/tool_search.py`

**实现机制**：`DeferredToolCatalog`（不可变目录，上限 5 条结果）；延迟工具（含 MCP 路由标记 `routing.mode="prefer"`）仅以名字出现在 `<available-deferred-tools>`，模型须先调 `tool_search` 获取完整 schema 并「晋升」到线程图状态后才能调用；`mcp_routing_middleware.py` 可按关键词自动晋升（`tool_search.auto_promote_top_k`，默认 3）。

### 5.4 Python 函数工具自动注册

**实现机制**：`tools/tools.py::get_available_tools()`（第 102 行）读取 `config.yaml tools[]`，按 `groups` 过滤，用 `deerflow.reflection.resolve_variable(cfg.use, BaseTool)` 动态解析 `use` 字符串（如 `deerflow.sandbox.tools:bash_tool`），合并 MCP 工具，并按条件附加内置工具（vision→`view_image`、子代理开启时附加 `task`、调度器开启时附加 `schedule_task` 等）。新增工具 = 在对应模块写函数 + 在 config.yaml 声明一行。

### 5.5 工具组与 tool_overrides

- 工具组：`config/tool_config.py` + `app_config.py::get_tool_group()`；自定义 Agent 可用 `tool_groups` 限制范围；`knowledge` 组受知识库开关门控，`bash` 组受 `is_host_bash_allowed()` 门控。
- 输出覆盖：`config/tool_output_config.py::tool_overrides` 按工具名单独设置输出字符上限，叠加在全局 `tool_output` 预算之上。

---

## L6 沙箱执行层（Sandbox Runtime）

### 6.1 AioSandboxProvider（Docker / K8s 生产级隔离）

**代码位置**：`backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py`（第 196 行）

**实现机制**：按 `(user_id, thread_id)` 获取/复用确定性容器（本地 Docker 或 K8s provisioner:8002），暖池保活（空闲 600s、副本 3），租约经 ownership store（内存/Redis）发布，仅持有者可回收容器；宿主数据目录 bind-mount 到容器内虚拟路径。

### 6.2 LocalSandboxProvider（本地直跑，仅开发）

**代码位置**：`sandbox/local/local_sandbox_provider.py`（第 36 行）+ `local/local_sandbox.py`

**实现机制**：`acquire(thread_id)` 返回 id 为 `local:{user}:{thread}` 的 `LocalSandbox`，携带 `PathMapping` 把虚拟路径翻译到宿主目录；LRU 缓存（默认 256）；`release()` 为 no-op（跨轮复用）。**非安全边界**，仅供受信本地开发。

### 6.3 每任务独立容器与租约

**代码位置**：`sandbox/sandbox_provider.py`（ABC + `get_sandbox_provider()` 单例）、`sandbox/lease.py`（`SandboxLeaseManager`）、`sandbox/acquire_serialization.py`

**实现机制**：`SandboxMiddleware` 在 run 开始时（或首个工具调用时惰性）获取沙箱；并发 lead/子代理各持进程内租约，仅最后释放者触发 `provider.release()`——远程沙箱进暖池而非销毁；每次获取前经 `sandbox:execute` 授权门（`authz/sandbox_authz.py`）。

### 6.4 虚拟路径映射

**代码位置**：`config/paths.py`（`VIRTUAL_PATH_PREFIX = "/mnt/user-data"`，第 13 行）、`local_sandbox_provider.py::_build_thread_path_mappings`（第 334-431 行）、`sandbox/tools.py::replace_virtual_path()`

**实现机制**：Agent 视角为 `/mnt/user-data/{workspace,uploads,outputs}`、`/mnt/skills/{public,custom,...}`；宿主侧解析到 `backend/.deer-flow/users/{user_id}/threads/{thread_id}/user-data/...`。Local 与 AIO 两种提供者遵守同一份路径契约（最长前缀匹配），工具层再做一层路径替换防御。

### 6.5 沙箱中间件与自我纠错闭环

**代码位置**：`sandbox/middleware.py::SandboxMiddleware`

**实现机制**：`before_agent` 做授权与技能投影（`ensure_thread_skill_projection`）并获取沙箱写入 `ThreadState.sandbox.sandbox_id`；`wrap_tool_call` 处理惰性获取与网络审批卡；`after_agent` 释放租约。自我纠错闭环由 Agent 循环天然完成：`bash_tool` 执行 → 错误输出回传 → 模型读错误 → `write_file`/`str_replace` 改写 → 重跑。

---

## L7 模型层（Model-Agnostic SaaS）

### 7.1 模型工厂与配置解析

**代码位置**：`models/factory.py::create_chat_model()`（第 432 行）、`config/model_config.py`、`config/app_config.py`

**实现机制**：`config.yaml models[]` 校验为 `ModelConfig`（`extra="allow"`）；工厂用 `reflection.resolve_class` 解析 `use` 类路径，剥离元数据字段（`use`、`supports_thinking`、`pricing` 等），应用 `model_overrides` 与 `reasoning_effort`，规范化 `api_base→base_url`，为 OpenAI 兼容客户端注入 `stream_usage=True` 与 240s `stream_chunk_timeout`，最后实例化并可挂追踪回调。模型名索引 O(1)（`_build_name_indexes`）。

### 7.2 多 Provider 并存

**代码位置**：`models/patched_openai.py`（保留 Gemini `thought_signature`）、`patched_deepseek.py`（跨轮保留 `reasoning_content`）、`claude_provider.py`、`vllm_provider.py`、`mindie_provider.py`、`patched_minimax.py`、`patched_stepfun.py` 等。

**实现机制**：各补丁类继承 LangChain provider 并重写 payload 序列化，补齐官方客户端丢弃的 provider 专有字段；`config.yaml` 以点分类路径引用（如 `langchain_openai:ChatOpenAI`、`deerflow.models.patched_openai:PatchedChatOpenAI`）。

### 7.3 容错降级

**实现机制**（无跨模型 failover 链，降级体现为四点）：
1. 名称解析回退：`agent.py::_resolve_model_name`（第 227 行）——未知模型名告警并回退 `models[0]`；
2. 授权回退：`_authorize_model_name`（第 242 行）——`model:use` 拒绝时扫描可见候选逐一重试（`fail_closed` 直接抛错）；
3. 错误兜底：`llm_error_handling_middleware.py`——重试预算 2 + 熔断，把 provider 故障转为可恢复的 assistant 消息；
4. 推理能力协商：`models/reasoning.py::resolve_reasoning_contract` 按声明式契约（`unsupported|optional|required`）调整 thinking 请求。

### 7.4 密钥注入（$VAR_NAME，不硬编码）

**代码位置**：`config/app_config.py::resolve_env_variables`（第 643 行）、`config/extensions_config.py`（第 554 行）

**实现机制**：YAML/JSON 解析期递归扫描字符串，凡以 `$` 开头者替换为 `os.getenv(name)`——config.yaml 缺失即抛 `ValueError`（fail-fast），extensions_config.json 缺失置 `""` 且写回时绝不持久化已解析的密钥。

### 7.5 Thinking 模式

**实现机制**：`factory.py::_apply_legacy_thinking_settings` 按 `supports_thinking` 合并 `when_thinking_enabled/disabled` 模板（深合并、模板优先、键不删除）；带 `reasoning:` 块的模型走声明式契约（方言自动推断：`openai_extra_body`/`anthropic`/`vllm_chat_template`/`ollama`，effort 词表含 aliases/default/path），统一在 `create_chat_model` 单点生效。

---

## L8 数据层（State & Persistence)

### 8.1 ThreadState + Checkpointer（断点续跑）

**代码位置**：`agents/thread_state.py`（第 362 行）、`runtime/checkpointer/`、`runtime/checkpoint_state.py`

**实现机制**：`ThreadState` 在 LangGraph `AgentState` 上扩展 `sandbox`/`artifacts`/`todos`/`goal`/`delegations`/`skill_context`/`summary_text` 等通道（自定义 reducer）。`database.backend`（memory/sqlite/postgres）统一选择 checkpointer + Store；`app/gateway/deps.py::langgraph_runtime`（第 567 行）进入 `make_checkpointer()` 挂到 `app.state.checkpointer`；checkpoint 通道模式（full/delta）在建图时进程级冻结，需重启变更。

### 8.2 三层长期记忆

**代码位置**：`agents/memory/manager.py`（ABC + 单例工厂）、默认后端 `agents/memory/backends/deermem/`

**实现机制**：(1) 共享摘要 `{base}/users/{user_id}/memory.json`（带 revision，绝不存事实）；(2) 逐事实 Markdown + YAML front matter（`users/{uid}/agents/{agent}/facts/{sha256前缀}/`）；(3) 派生可重建的 SQLite FTS5 检索索引（`.retrieval/`，签名比对、脏域惰性重建）。远程适配：mem0 / openviking / honcho / noop。注入走 `DynamicContextMiddleware`。

### 8.3 制品存储（按线程隔离）

**代码位置**：`config/paths.py::sandbox_outputs_dir`（第 360 行）、`app/gateway/path_utils.py::resolve_outputs_confined_path`（第 58 行）、`routers/artifacts.py`

**实现机制**：虚拟 `/mnt/user-data/outputs` 映射到属主 user+thread 宿主目录；路由经 confined resolver 防穿越/防符号链接；写操作走 `artifact_write` 线程级互斥预留（与活跃 run 冲突即拒），GET 支持字节范围流式（206/416），PUT 原子替换 + SHA-256/ETag。

### 8.4 配置持久化与热重载

**代码位置**：`config/app_config.py`（内容签名缓存 + `reload_boundary.py::STARTUP_ONLY_FIELDS`）、`config/extensions_config.py::atomic_write_extensions_config`（第 701 行）、`config/shared_reset_marker.py`

**实现机制**：读侧按 `(mtime,size,sha256)` 签名自动重载（坏版本保留 last-known-good）；写侧持进程锁 + 跨进程 sidecar 文件锁，向原始 dict 合并（绝不序列化已解析密钥），校验后临时文件原子替换（挂载点 `EBUSY` 时退化为原地覆盖）。模型/记忆/摘要等运行期字段热重载，`database`/`checkpointer`/`sandbox`/`plugins` 等基础设施字段需重启。

### 8.5 DeerMem 写入门（fail-closed · 异步队列 · 去重防抖）

**代码位置**：`middlewares/memory_middleware.py`、`backends/deermem/deermem/core/queue.py::MemoryUpdateQueue`（第 73 行）、`core/updater.py::MemoryUpdater`（第 844 行）

**实现机制**：中间件过滤出 user 与最终 AI 消息（PII 脱敏后）入队；队列进程内缓冲 + 防抖定时器批量出队；LLM 抽取提案必须携带 `scope=user`/`durability=durable`/`authority=descriptive` 三标签，确定性写入门拒绝其余一切（缺标签仅拒该条，自定义 prompt 缺字段整体 fail-closed）；容量驱逐与近重复合并门在落盘前执行；关停时 `shutdown_flush` 有界排空。

---

## 横切能力

| 能力 | 代码位置 | 机制 |
|---|---|---|
| 可观测性 | `app/gateway/app.py`（Monocle 初始化，lifespan 第 587 行）、`models/factory.py`（追踪回调注入） | LangSmith/Langfuse/Monocle 全链路 Trace，失败仅告警不阻断启动 |
| 扩展机制 | `backend/packages/harness/deerflow/extensions/`、`backend/packages/extension-api/` | `config.yaml plugins:` 加载可信 Python 包，贡献中间件/路由/生命周期观察者；`required: true` 失败即中止启动 |
| 部署形态 | `docker/docker-compose.yaml`（生产 4 容器）、`docker/docker-compose-dev.yaml`（开发）、`deploy/helm/` | Nginx:2026 唯一入口 + Gateway:8001 + Frontend:3000 +（可选）Provisioner:8002；默认 127.0.0.1 回环绑定 |

---

## 从启动到功能激活的完整流转

### 阶段 0：进程启动（`backend/app/gateway/app.py::lifespan`，第 541 行）

```
uvicorn app.gateway.app:app
  └─ lifespan() 启动序列（严格按依赖序）
      1. 配置加载      get_app_config() 解析 config.yaml（$ENV_VAR 替换 → Pydantic 校验）
                       ├─ 配置子代理并发容量 / 日志 / 浏览器运行时校验（失败即中止）
                       └─ 基础设施字段（database/checkpointer/sandbox/plugins）自此冻结
      2. 技能投影      ensure_public_skill_projection()（L4 公共技能落盘，离事件循环执行）
      3. 追踪          setup_monocle_tracing_if_enabled()（容错）
      4. 记忆预热      get_memory_manager() + 后台重建 FTS5 检索索引 + tiktoken 预热（5s 上限）（L8）
      5. 上传清理      cleanup_stale_upload_staging_files()
      6. 运行时装配    langgraph_runtime(app, config)（app/gateway/deps.py:567）
                       ├─ StreamBridge 启动（memory/Redis）（L3 SSE 底座）
                       ├─ SQLAlchemy 引擎 + make_checkpointer + make_store（L8）
                       ├─ RunManager 安装（L3 运行准入）
                       ├─ run-store / feedback / PAT 仓储
                       └─ 扩展加载（plugins），外层包 MCP 会话池关闭钩子
      7. 管理员引导    _ensure_admin_user()——无管理员则系统标记 system_setup_required，
                       前端访问任何页面重定向到 /setup（L2 认证闭环）
      8. 回收站清理    后台 sweep
      9. 定时任务      ScheduledTaskService.start()（scheduler.enabled 时；失败 fail-closed 中止启动）
     10. IM 渠道       start_channel_service()——按 extensions_config/config 中 enabled 渠道
                       懒加载 Feishu/Slack/Telegram/...（L1 渠道激活；失败仅告警）
     11. 通知投递      定时任务 IM 通知 worker
     12. MCP 长任务    McpTaskService（持久化任务驱动注册）
     13. 子代理批处理  SubagentBatchService
     14. yield → 开始服务请求
```

与此同时：Nginx 拉起并等待 Gateway `/health/ready` 通过后才被认为就绪；前端容器（Next.js prod server）独立启动。

### 阶段 1：用户访问与认证激活（L1 → L2）

```
浏览器 → http://localhost:2026/
  └─ Nginx: location / → frontend:3000
      └─ workspace/layout.tsx → getServerSideUser()
          ├─ system_setup_required → 302 /setup（首启建管理员：POST /api/v1/auth/initialize）
          ├─ unauthenticated       → 302 /login（POST /api/v1/auth/login/local →
          │                          后端写 HttpOnly access_token Cookie，7 天有效）
          └─ authenticated         → 渲染工作台；AuthProvider 持有用户态，
                                     页面可见性恢复时 GET /api/v1/auth/me 复核
```

### 阶段 2：发起一次问答（L1 → L2 → L3 全链路）

```
前端 input-box 提交（可选 /skill、@提及、模式档位 flash/thinking/pro/ultra）
  └─ POST /api/threads/{id}/runs/stream（routers/thread_runs.py）
      │  请求体 context 经 _CONTEXT_CONFIGURABLE_KEYS 白名单并入运行配置
      │  （mode → thinking_enabled/is_plan_mode/subagent_enabled/reasoning_effort）
      └─ services.start_run → RunManager.create_or_reject（准入/幂等/租约）
          └─ run_agent() worker（runtime/runs/worker.py:891）
              ├─ assemble_lead_agent(config)
              │    ├─ 模型解析 + 授权（失败回退 models[0]）           【L7】
              │    ├─ get_available_tools()：config tools + MCP 缓存    【L5】
              │    │    + task_tool（ultra 模式）+ write_todos（pro/ultra）
              │    ├─ 系统提示词渲染（技能目录/子代理目录/SOUL.md）      【L4】
              │    └─ build_middlewares() 组装 30+ 中间件链             【L3】
              └─ graph.astream(stream_mode=["messages-tuple","updates","custom"])
                   每个模型调用周期：
                   ├─ before_agent：沙箱获取 + 技能投影 + 记忆/日期注入   【L6/L8/L4】
                   ├─ wrap_model_call：输入消毒 → 上下文压缩检查 →
                   │    todo 提醒 → token 预算 → MCP 路由晋升 → 循环检测
                   ├─ 模型调用（Patched provider 保留 thinking 字段）     【L7】
                   ├─ wrap_tool_call：
                   │    ├─ bash/write_file/... → 沙箱内执行，输出超预算落盘 【L6】
                   │    ├─ task → SubagentExecutor 隔离事件循环并行执行     【L3】
                   │    ├─ MCP 工具 → 会话池/OAuth 拦截链                  【L5】
                   │    └─ ask_clarification → ClarificationMiddleware 拦截
                   │       （永远最后的中间件），写 human-input 卡片并 END
                   └─ after_model/after_agent：记忆写入门排队、标题生成、
                        token 统计、沙箱租约释放                          【L8/L6】
              每个 chunk → SSE 事件 → StreamBridge.publish(run_id, ...)
  └─ sse_consumer() 订阅桥 → SSE 帧实时回推浏览器
      （断线：前端携 Last-Event-ID 重连；缺口 → gap 帧 → 持久态重载后续传）
```

### 阶段 3：功能模块的按需激活路径

| 功能 | 激活入口 | 激活链路 |
|---|---|---|
| **技能激活** | 输入 `/skill-name` 或 @ 选择 | 前端解析 → `additional_kwargs.skill_references` → `SkillActivationMiddleware` 载入 SKILL.md → `SkillToolPolicyMiddleware` 施加 allowed-tools → 下次模型调用生效 |
| **计划模式** | 前端选 pro/ultra 档 | `is_plan_mode=true` → `TodoMiddleware` 注入 → `write_todos` 工具可用 → UI 展示任务清单 |
| **子代理委派** | ultra 档 + 模型自主调用 | `task` 工具 → registry 解析子代理 → 容量准入 → 隔离事件循环执行 → `task_*` 事件回传 → 子任务卡片实时渲染 |
| **MCP 工具** | `extensions_config.json` 启用服务器 | 懒加载：首次使用经 `get_cached_mcp_tools()` 建立连接/会话池 → 工具入集；`routing.prefer` 关键词命中时 `McpRoutingMiddleware` 自动晋升 |
| **tool_search** | `tool_search.enabled` | 延迟工具仅列名 → 模型调 `tool_search` → schema 晋升入图状态 → 可调用 |
| **记忆写入** | 每轮对话结束自动 | `MemoryMiddleware` 过滤入队 → 防抖批量 → LLM 抽取（三标签门）→ 确定性写入门 → Markdown 落盘 + FTS5 索引重建 |
| **记忆读取** | 每轮对话开始自动 | `DynamicContextMiddleware` 检索注入 `<system-reminder>` |
| **定时任务** | UI/对话创建 | `scheduled_tasks.py` CRUD → `ScheduledTaskService` 后台调度 → 到点经正常 run 路径非交互执行（排除 ask_clarification）→ 结果经 IM 通知 worker 投递 |
| **文件上传** | 聊天附件 | `uploads.py` 分片暂存（`.upload-*.part`）→ 原子落位 → markitdown 转 Markdown → `UploadsMiddleware` 注入大纲到上下文 |
| **制品产出** | Agent 写 `/mnt/user-data/outputs` | `write_file_tool`（沙箱内）→ 虚拟路径映射到宿主线程目录 → `artifacts.py` 提供范围读取/原子覆盖 → 前端制品面板渲染 |
| **上下文压缩** | 自动（阈值触发）或 `/compact` | 摘要中间件 → `summary_text` 通道 → 委派/技能台账由 DurableContext 保全 → 新 checkpoint 续跑 |
| **沙箱执行** | 首次工具调用 | `SandboxMiddleware` 授权门 → acquire（AIO 容器/Local 目录）→ 路径映射 → 执行 → 结果回传 → 错误驱动自我纠错 |
| **IM 渠道对话** | 飞书/Slack 等发消息 | 渠道适配器 → MessageBus → ChannelManager → 经 langgraph-sdk 创建/复用线程并发起 run → SSE 结果回传出站队列 → IM 回复 |
| **配置变更** | Gateway API 写 config | 双锁合并原始 dict → 原子替换 → 签名失效 → 读侧自动重载（运行期字段即时生效，基础设施字段提示重启） |

### 阶段 4：关停序列（lifespan `yield` 之后，严格反向）

```
回收站 sweep → OIDC 关闭 → 通知 worker → IM 渠道停止 → 调度器停止
→ MCP 任务服务 → 子代理批处理 → 浏览器会话 → 记忆检索等待
→ 记忆后端 shutdown_flush（有界排空队列）→ 运行时排空 → MCP 会话池最后关闭
```

---

## 附：一次 HTTP 请求的端口与路径速查

```
浏览器 ──► Nginx :2026
            ├─ /api/langgraph/* ──rewrite──► Gateway :8001 /api/*        (LangGraph 兼容：runs/threads)
            ├─ /api/models|memory|mcp|skills|agents|threads/* ──► Gateway :8001   (管理面)
            ├─ /api/sandboxes ──► Provisioner :8002                       (可选，K8s 沙箱)
            ├─ /health ──► Gateway :8001
            └─ /* ──► Frontend :3000 (Next.js)

Gateway 内部：
  /api/threads/{id}/runs ──► RunManager ──► Lead Agent 图
      ├─► 模型（L7：config.yaml models[]，$ENV_VAR 密钥）
      ├─► 工具（L5：内置 + community + MCP）
      ├─► 沙箱（L6：AIO/Local，虚拟路径映射）
      └─► 持久化（L8：checkpointer / 记忆 / 制品 / 配置）
```
