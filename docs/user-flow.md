# DeerFlow 2.0 用户输入 → 输出生成 全流程（Mermaid 版）

> 与 `user-flow.html` 严格对齐：七个阶段、相同的配色（绿→靛→粉→黄→橙/紫→青→蓝）、相同的模块内容。
> 直接在支持 Mermaid 的渲染器中查看（GitHub / Typora / VS Code 插件均可）。

## 全流程总图

```mermaid
flowchart TD
    %% ══════════════ 阶段 0 ══════════════
    subgraph S0["阶段 0 · 用户输入 INPUT（多渠道 · 多形式 · 可修饰）"]
        direction TB
        CH1["Web 工作台<br/><small>Next.js · 输入框</small>"]:::core
        CH2["IM 渠道<br/><small>飞书 / 企微 / 钉钉 / Slack</small>"]
        CH3["Python Client<br/><small>client.chat() 嵌入式</small>"]
        IN1["输入形式<br/><small>文本 · 语音 · 文件 · 图片</small>"]
        IN2["指令修饰<br/><small>/skill 技能 · @提及 · /goal · /compact</small>"]
        IN3["输入优化<br/><small>Input Polish · LLM 润色草稿</small>"]
        IN4["文件引用<br/><small>PDF / PPT / Excel / Word → Markdown</small>"]
        CH1 ~~~ CH2 ~~~ CH3 ~~~ IN1 ~~~ IN2 ~~~ IN3 ~~~ IN4
    end

    %% ══════════════ 阶段 1 ══════════════
    subgraph S1["阶段 1 · Nginx 统一接入 ACCESS（Port 2026）"]
        NG["按路径路由<br/><small>/api/langgraph/* 重写 → Gateway /api/* · /api/* 管理面 · /* → Frontend</small><br/><small>SSE 不缓冲不压缩</small>"]
    end

    %% ══════════════ 阶段 2 ══════════════
    subgraph S2["阶段 2 · Gateway 鉴权与受理 GATEWAY（FastAPI · Port 8001）"]
        direction TB
        G1["AuthMiddleware<br/><small>HttpOnly Cookie · 未认证拒绝</small>"]
        G2["CSRF 双提交 + Trace 中间件"]
        G3["参数白名单<br/><small>mode → thinking / plan / subagent / reasoning_effort</small>"]
        G4["RunManager 准入<br/><small>幂等键 · 多任务策略 · 租约心跳</small>"]:::core
        G1 ~~~ G2 ~~~ G3 ~~~ G4
    end

    %% ══════════════ 阶段 3 ══════════════
    subgraph S3["阶段 3 · Lead Agent 装配 ASSEMBLE（assemble_lead_agent）"]
        direction LR
        A1["① 模型解析<br/><small>名称回退 · 授权回退<br/>四级容错 · thinking 契约</small>"]:::core
        A2["② 工具装配<br/><small>内置 + MCP 缓存<br/>+ task · write_todos</small>"]:::core
        A3["③ 提示词渲染<br/><small>SOUL.md · 技能目录<br/>子代理目录 · 记忆工具段</small>"]:::core
        A4["④ 中间件链<br/><small>30+ 钩子按序组装<br/>扩展中间件最后合入</small>"]:::core
        A1 ~~~ A2 ~~~ A3 ~~~ A4
    end

    %% ══════════════ 阶段 4 ══════════════
    subgraph S4["阶段 4 · 执行循环 EXECUTE"]
        direction TB

        subgraph E1["执行前置 before_agent（每轮一次）"]
            direction LR
            P1["沙箱获取<br/><small>授权门 → 独立容器/目录</small>"]
            P2["技能投影<br/><small>技能文件同步进沙箱</small>"]
            P3["记忆注入<br/><small>三层记忆 → system-reminder</small>"]
            P4["上传注入<br/><small>文件大纲入上下文</small>"]
            P1 ~~~ P2 ~~~ P3 ~~~ P4
        end

        subgraph E2["模型调用 wrap_model_call（中间件六道防线）"]
            direction LR
            F1["输入消毒<br/><small>边界标记防注入</small>"]
            F2["上下文压缩<br/><small>阈值触发自动摘要</small>"]
            F3["Todo 提醒<br/><small>防丢防停</small>"]
            F4["Token 预算<br/><small>超支熔断</small>"]
            F5["MCP 路由<br/><small>关键词自动晋升</small>"]
            F6["循环检测<br/><small>死循环熔断</small>"]
            F1 ~~~ F2 ~~~ F3 ~~~ F4 ~~~ F5 ~~~ F6
        end

        MODEL["模型推理<br/><small>Patched Provider 保留 thinking 字段</small>"]:::core
        DECIDE{"模型决策<br/>最终回答 / 工具调用 ?"}:::decision

        subgraph E3["工具分发（六类执行路径）"]
            direction TB
            T1["沙箱工具<br/><small>bash / write_file / read_file<br/>虚拟路径映射 → 容器内执行<br/>输出超预算自动落盘</small>"]:::core
            T2["MCP 工具<br/><small>stdio / SSE / HTTP 会话池 · OAuth<br/>finance · enterprise · person · NER</small>"]:::core
            T3["task → 子代理<br/><small>隔离上下文并行执行 · 容量准入（3）<br/>task_* 事件实时回传</small>"]:::loop
            T4["批处理 batch_task<br/><small>持久化队列 · 暂停/恢复/取消/重试<br/>JSONL 结果导出</small>"]
            T5{"ask_clarification<br/><small>澄清卡片（单选/表单）</small>"}:::decision
            T6["write_todos / 内置工具<br/><small>计划清单 · present_file 制品呈现<br/>view_image 图片理解</small>"]
        end

        RESULT["⟲ 工具结果回传<br/><small>自我纠错：执行报错 → 读错误 → 改写 → 重跑</small>"]:::loop
        CLARIFY["用户回答澄清卡片<br/><small>Web / IM 均可</small>"]:::loop

        subgraph E4["轮次收尾 after_model / after_agent"]
            direction LR
            Z1["记忆写入门<br/><small>三标签校验 · 异步队列 · 防抖</small>"]
            Z2["标题生成<br/><small>首轮自动命名线程</small>"]
            Z3["Token 统计<br/><small>用量与成本记录</small>"]
            Z4["沙箱租约释放<br/><small>暖池回收 · 零污染</small>"]
            Z1 ~~~ Z2 ~~~ Z3 ~~~ Z4
        end

        E1 --> E2
        E2 --> MODEL
        MODEL --> DECIDE
        DECIDE -->|工具调用| T1
        DECIDE -->|工具调用| T2
        DECIDE -->|工具调用| T3
        DECIDE -->|工具调用| T4
        DECIDE -->|工具调用| T6
        DECIDE -->|需求歧义| T5
        T1 & T2 & T3 & T4 & T6 --> RESULT
        RESULT -->|结果回传，继续下一轮推理| MODEL
        T5 -->|暂停执行，等待用户| CLARIFY
        CLARIFY -->|回答后接续运行| MODEL
        DECIDE -->|最终回答| E4
    end

    %% ══════════════ 阶段 5 ══════════════
    subgraph S5["阶段 5 · SSE 流式输出 STREAM（StreamBridge → sse_consumer → 前端）"]
        direction TB
        Q1["实时推送<br/><small>消息增量 · 工具步骤 · 子代理进度</small>"]:::core
        Q2["文件流式<br/><small>write_file 分块合并 · 制品实时预览</small>"]
        Q3["断线续传<br/><small>Last-Event-ID 重连 · gap 帧 → 持久态恢复</small>"]
        Q1 ~~~ Q2 ~~~ Q3
    end

    %% ══════════════ 阶段 6 ══════════════
    subgraph S6["阶段 6 · 最终交付 DELIVER（面向用户的完整产出）"]
        direction LR
        D1["消息渲染<br/><small>Markdown · 代码高亮<br/>图表 · 引用链接</small>"]:::core
        D2["制品落盘<br/><small>/mnt/user-data/outputs<br/>报告/PPT/代码 → 制品面板</small>"]:::core
        D3["记忆沉淀<br/><small>Markdown 事实 + FTS5<br/>跨会话生效</small>"]
        D4["追问建议<br/><small>自动生成下一步建议<br/>点击继续深挖</small>"]
        D5["IM 回投<br/><small>渠道消息队列<br/>群聊自动回复</small>"]
        D6["目标判定<br/><small>/goal 达成自检<br/>未达成持续推进</small>"]
        D1 ~~~ D2 ~~~ D3
        D4 ~~~ D5 ~~~ D6
    end

    %% ══════════════ 横切保障 ══════════════
    subgraph SX["全程横切保障"]
        direction LR
        X1["安全<br/><small>容器隔离 · 消毒脱敏<br/>写前读 · SSRF 防护</small>"]
        X2["可观测<br/><small>全链路 Trace<br/>Token 成本</small>"]
        X3["容错<br/><small>模型四级容错<br/>限流熔断 · 断线续传</small>"]
        X4["治理<br/><small>记忆写入门<br/>技能扫描 · 授权策略</small>"]
        X1 ~~~ X2 ~~~ X3 ~~~ X4
    end

    %% ══════════════ 主链路（单脊柱串联） ══════════════
    S0 ==> S1
    S1 ==> S2
    S2 ==> S3
    S3 ==> S4
    S4 ==> S5
    S5 ==> S6
    S6 -.- SX

    %% ══════════════ 配色（与 HTML 严格一致） ══════════════
    classDef plain fill:#ffffff,stroke:#c3c8cd,color:#3c4043
    classDef core fill:#ffffff,stroke:#7a9cc6,stroke-width:2px,color:#3c4043
    classDef decision fill:#fffdf5,stroke:#d8a94e,stroke-width:2px,color:#3c4043
    classDef loop fill:#faf5fd,stroke:#c58fd6,stroke-width:2px,color:#7a5a86

    class CH2,CH3,IN1,IN2,IN3,IN4,NG,G1,G2,G3,P1,P2,P3,P4,F1,F2,F3,F4,F5,F6,T4,T6,Z1,Z2,Z3,Z4,Q2,Q3,D3,D4,D5,D6,X1,X2,X3,X4 plain

    style S0 fill:#e0f2e3,stroke:#c4e4ca,color:#3c4043
    style S1 fill:#e8eaf9,stroke:#ccd0ee,color:#3c4043
    style S2 fill:#fce6f0,stroke:#f0c8de,color:#3c4043
    style S3 fill:#fdf6dc,stroke:#efe2b0,color:#3c4043
    style S4 fill:#ffffff,stroke:#f0cfc0,color:#3c4043
    style E1 fill:#fdeede,stroke:#f1d7b8,color:#3c4043
    style E2 fill:#fbe9e2,stroke:#f0cfc0,color:#3c4043
    style E3 fill:#f0e7f8,stroke:#dbccea,color:#3c4043
    style E4 fill:#fdeede,stroke:#f1d7b8,color:#3c4043
    style S5 fill:#ddf3ee,stroke:#bde0d6,color:#3c4043
    style S6 fill:#e9f1fc,stroke:#c9dbf2,color:#3c4043
    style SX fill:#f1f3f4,stroke:#c3c8cd,stroke-dasharray:5 4,color:#3c4043
```

## 简化版（一图速览）

```mermaid
flowchart LR
    A["用户输入<br/>Web / IM / Python Client<br/>文本·语音·文件·图片·/skill·@提及"] --> B["Nginx :2026<br/>路径路由 · SSE 直通"]
    B --> C["Gateway :8001<br/>鉴权 · CSRF · RunManager 准入"]
    C --> D["Agent 装配<br/>模型 + 工具 + 提示词 + 中间件链"]
    D --> E{"执行循环<br/>模型 ⇄ 工具"}
    E -->|"沙箱 / MCP / 子代理 / 批处理"| E
    E -->|"澄清卡片"| U["用户回答"] --> E
    E -->|"最终回答"| F["SSE 流式输出<br/>实时推送 · 断线续传"]
    F --> G["最终交付<br/>消息渲染 · 制品面板 · 记忆沉淀<br/>追问建议 · IM 回投 · 目标判定"]

    classDef core fill:#ffffff,stroke:#7a9cc6,stroke-width:2px,color:#3c4043
    classDef loop fill:#faf5fd,stroke:#c58fd6,stroke-width:2px,color:#7a5a86
    class D,E,F core
    class U loop
```

## 图例说明

| 元素 | 含义 | 对应 HTML |
|---|---|---|
| 蓝色描边节点 | 核心模块（Web 工作台、RunManager、装配四步、模型、沙箱/MCP 工具、SSE 推送、消息渲染、制品落盘） | `.box.core` / `.branch.core` |
| 金色菱形 | 决策点（模型输出决策、澄清决策） | `.box.decision` |
| 紫色节点 | 循环回路（子代理、工具结果回传、用户澄清回答） | `.box.loop` / 紫色回环标注 |
| 粗实线 `==>` | 阶段间主链路（阶段 0 → 6 单脊柱串联） | 层间箭头 |
| 隐形链 `~~~` | 子图内节点排序（仅控制布局，不画箭头） | 带内 boxes 排列 |
| 灰底虚线框 | 横切保障（不参与主流程） | `.band.b-gray` |

关键回路：

1. **模型 ⇄ 工具循环**：`RESULT → MODEL`，工具结果回传驱动多轮推理，直至产出最终回答。
2. **自我纠错闭环**：沙箱执行报错 → 读错误 → 改写 → 重跑（RESULT 节点标注）。
3. **澄清回路**：`T5 → CLARIFY → MODEL`，澄清卡片暂停执行，用户回答后从模型调用处接续。
4. **目标回路**（阶段 6 · D6）：`/goal` 未达成时持续推进，而非直接收尾。
