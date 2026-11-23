# CeCe Harness 并发情况说明

更新日期：2026-11-18。

本文记录测试环境 `cece-harness-dev172`（172）和 `cece-harness-test224`（224）当前的并发相关配置与实际含义。它描述的是配置层面的容量，不等同于某一时刻真实正在运行的任务数量。

## 先说明：系统没有一个“总并发数”

一次用户任务可能同时占用 Gateway、模型调用、Sandbox 和子 Agent。它们的限制相互独立，因此不能只用一个数字描述整个产品并发。

- 同一个会话同一时刻只能有一个运行中的任务；不同会话可以并行。
- Gateway worker 数决定后端进程数量，不等于用户任务数上限。
- 子 Agent 容量只限制委派出来的子任务；普通对话不受它直接限制。
- Sandbox 容量限制容器复用池，不是模型调用的硬并发阀门。
- 模型调用限流才是控制外部模型 API 突发请求的主要开关。

## 172：`cece-harness-dev172`

配置来源：`D:\project\pythonProject\dev172Harness\.1117env` 与 `config1117.yaml`。

### 已生效的并发相关配置

| 项目 | 当前值 | 说明 |
| --- | ---: | --- |
| Gateway worker | 2 | `.1117env` 中 `GATEWAY_WORKERS=2`，一个 Gateway 容器内启动两个 Uvicorn worker 进程。 |
| 多实例支持 | 已开启 | `deployment.multi_instance: true`；运行事件使用数据库、流转发使用 Redis、运行归属心跳已开启。 |
| Sandbox 容器池 | `replicas: 8` | AIO Sandbox 在**每个 Gateway 进程**维护的活跃加预热容器目标容量。按两个 worker 规划时，建议将约 16 个容器视为容量量级。它是带 LRU 回收的软上限，活跃任务无法被回收时可能短时超出。 |
| Sandbox 预热创建 | 1 | `prewarm_max_concurrent: 1`，只限制启动时或补池时同时创建容器的速度，不限制正在运行的任务数。 |
| Sandbox 协调 | Redis | `sandbox.ownership.type: redis`，用于多个 Gateway worker 协调同一 Sandbox 的归属和回收。 |
| 子 Agent 执行槽 | 默认值 | 未配置 `subagent_runtime`，因此每个 Gateway 进程默认最多同时执行 3 个子 Agent，两个 worker 合计按约 6 个并发子 Agent 理解；超过后默认排队，默认队列最多 64 个、最长等待 300 秒。 |
| LLM 调用上限 | 未设置 | 未配置 `llm_call.max_concurrent_calls`，默认值为 0，即**不限制**每个 Gateway 进程同时发出的模型调用。 |

### 172 当前运行特征

1. 不同用户、不同会话的普通任务没有全局“最多 N 个”的硬性准入上限；只要 Gateway、模型服务和主机资源还能处理，就会继续进入运行。
2. 同一会话不会并行执行两个任务，避免同一线程状态被同时写入。
3. 选择 Ultra 模式时，Lead Agent 可以委派子 Agent；子 Agent 会受约 6 个进程级执行槽约束。普通任务、快速响应、思考和 Pro 模式不会因此获得子 Agent。
4. 最容易先被打满的资源不是 Gateway worker，而是外部模型 API 的并发/限流、主机 CPU/内存，以及持续占用 Sandbox 的复杂任务。
5. 由于模型调用没有上限，多个深度研究任务同时发起时，Lead Agent、子 Agent、总结等可能一起向模型服务发请求；模型供应商的速率限制或超时会成为最早可见的故障表现。

## 224：`cece-harness-test224`

配置来源：`D:\project\pythonProject\test224Harness\.1117env` 与 `config1117.yaml`。

### 已生效的并发相关配置

| 项目 | 当前值 | 说明 |
| --- | ---: | --- |
| Gateway worker | 2 | `.1117env` 中 `GATEWAY_WORKERS=2`，一个 Gateway 容器内启动两个 Uvicorn worker 进程。 |
| 多实例支持 | 已开启 | `deployment.multi_instance: true`；运行事件使用数据库、流转发使用 Redis、运行归属心跳已开启。 |
| Sandbox 容器池 | `replicas: 20` | AIO Sandbox 在**每个 Gateway 进程**维护的活跃加预热容器目标容量。按两个 worker 规划时，建议将约 40 个容器视为容量量级。它是带 LRU 回收的软上限，活跃任务无法被回收时可能短时超出。 |
| Sandbox 预热创建 | 2 | `prewarm_max_concurrent: 2`，只限制启动时或补池时同时创建容器的速度，不限制正在运行的任务数。 |
| Sandbox 协调 | Redis | `sandbox.ownership.type: redis`，用于多个 Gateway worker 协调同一 Sandbox 的归属和回收。 |
| 子 Agent 执行槽 | 默认值 | 未配置 `subagent_runtime`，因此每个 Gateway 进程默认最多同时执行 3 个子 Agent，两个 worker 合计按约 6 个并发子 Agent 理解；超过后默认排队，默认队列最多 64 个、最长等待 300 秒。 |
| LLM 调用上限 | 未设置 | 未配置 `llm_call.max_concurrent_calls`，默认值为 0，即**不限制**每个 Gateway 进程同时发出的模型调用。 |

### 224 当前运行特征

1. 不同用户、不同会话的普通任务没有全局“最多 N 个”的硬性准入上限；只要 Gateway、模型服务和主机资源还能处理，就会继续进入运行。
2. 同一会话不会并行执行两个任务，避免同一线程状态被同时写入。
3. 选择 Ultra 模式时，Lead Agent 可以委派子 Agent；子 Agent 会受约 6 个进程级执行槽约束。普通任务、快速响应、思考和 Pro 模式不会因此获得子 Agent。
4. 20 个 Sandbox 容器/worker 只是 Sandbox 资源池目标，不会限制模型 API 调用数，也不会自动限制用户同时发起的任务数。
5. 由于模型调用没有上限，多个深度研究任务同时发起时，Lead Agent、子 Agent、总结等可能一起向模型服务发请求；模型供应商的速率限制或超时会成为最早可见的故障表现。

## 如何查看某一时刻的实际占用

以下命令需要在对应服务器的部署目录执行；它们用于观测，不修改配置。

```bash
# 查看 Gateway、Redis、前端等容器是否在运行
docker compose ps

# 查看当前 Sandbox 容器数量
docker ps --format '{{.Names}}' | grep 'cece-harness-sandbox'

# 查看 Gateway、Sandbox 等容器的瞬时 CPU 和内存
docker stats --no-stream

# 查看 Gateway 日志中的子 Agent 排队、模型限流或 Sandbox 容量相关信息
docker compose logs --tail=500 gateway | grep -Ei 'subagent|queue|capacity|rate.limit|sandbox'
```

这些命令看到的是瞬时状态；要判断系统能稳定承受多少用户，需要在区分“快速响应”和“Ultra 深度研究”的前提下做压测，并同时观察模型供应商的限流与错误率。

## HYDC 对实际并发的影响（两个环境都适用）

`cece-hydc-data` 不是一个被网关单独排队、单独限流的服务。每一次技能调用，都是 Sandbox 中的 `hydc.mjs` 直接向 HYDC 服务发出一次 HTTP 请求：

- 单次请求超时为 30 秒。
- 当前封装没有全局并发信号量、QPS 限制、共享队列或自动重试。两个 Gateway worker 之间也不会互相限制 HYDC 请求。
- Skill 文档写的“普通问题最多 2 次、一般研究最多 4 次、用户明确要求的深度研究最多 8 次”是 Agent 的行为指引，不是后端强制的会话级或全局级硬上限。

所以，不能根据“快速响应 / 思考 / 深度研究”直接得出现在能同时打开的任务数。当任务命中 HYDC 时，实际容量同时受以下决定：HYDC 上游允许的同时请求数和 QPS，模型服务的限流，Gateway/Sandbox 资源，以及每个任务实际选择了几次 HYDC 查询。

| 产品模式 | 是否会被系统强制限制任务数 | 与 HYDC 的关系 |
| --- | --- | --- |
| 快速响应 | 否 | 如果选择 HYDC，通常应按普通问题使用（指引上最多 2 次），但系统没有全局硬并发闸门。 |
| 思考模式 | 否 | 单个任务可能因推理步数更多而驱动更多 HYDC 请求；“4 次”是一般研究指引，不是模式强绑定。 |
| 深度研究（Pro） | 否 | 明确要求深度研究时，指引允许最多 8 次 HYDC 调用；它只说明单任务的潜在压力更大。 |
| 高强度推理（Ultra） | 普通 Lead 任务无全局硬上限 | 子 Agent 同时执行槽约为 6 个，但这不是 HYDC 的全局限流；多个 Lead/Agent 仍可能同时发起 HYDC 请求。 |

### 172 未压测前的暂行并发建议

以下是为了保护 HYDC 上游和模型配额而给出的**运营建议值**，不是已压测验证的系统硬容量，也不是当前代码已强制执行的限额。未拿到 HYDC 服务的并发/QPS 约束且未完成压测前，172 应暂按全局同时占用 **8 个 HYDC 请求预算** 来做使用规划。

| 模式 | 建议同时启动的任务数 | 规划依据 | 使用说明 |
| --- | ---: | --- | --- |
| 快速响应 | **4 个** | 普通问题指引为每任务最多 2 次 HYDC 调用；`4 × 2 = 8`。 | 适合短小、结论明确的企业/行业数据查询。这是当前最安全的并发口径。 |
| 思考模式 | **2 个** | 一般研究指引为每任务最多 4 次 HYDC 调用；`2 × 4 = 8`。 | 给需要对比、整理或轻量分析的任务使用。 |
| 深度研究（Pro） | **1 个** | 明确深度研究指引允许单任务最多 8 次 HYDC 调用。 | 同一时段只建议跑 1 个；其他任务等它完成后再发起。 |
| 高强度推理（Ultra） | **1 个** | 除 HYDC 压力外，还可能占用子 Agent 槽位和更多模型请求。 | 不应与 Pro 或多个思考任务并行。 |

没有命中 HYDC 的纯文本快速响应任务，不占用上表的 HYDC 预算，但它仍会受模型供应商限流和 Gateway 资源影响；在没有另行观测的情况下，不建议一次性启动超过 8 个。

当前系统并不会自动拒绝第 5 个快速响应、第 3 个思考或第 2 个 Pro 任务。上表是人工调度上限；要让它成为真正的保护，后续需在 Gateway 前加一个跨 worker 共享的 HYDC 队列/信号量。

### 172 快速响应压测口径（暂不执行）

压测只能回答“当前这套 172 部署、当前模型和 HYDC 配额下，多少个并发快速任务还能稳定完成”，不应将结果解读为永久硬上限。测试使用独立测试账号、独立会话和固定的小范围 HYDC 查询，依次测试 1、2、4、6、8 个同时运行的快速响应任务。每一档记录：

1. 提交成功率、完成成功率、HYDC/LLM 的 429、5xx、超时和其他错误。
2. 从提交到完成的中位数与 P95 耗时。
3. 测试过程中 Gateway、Sandbox 容器的 CPU/内存与活跃任务数。
当首次出现明显的错误飙升、P95 显著恶化或环境资源持续饥和时，不再继续加压，将上一档作为暂时安全并发建议值。
