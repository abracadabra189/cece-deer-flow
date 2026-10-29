---
name: hydc-industry-insight
description: 连接「行业洞察数据（HYDC）」run-cli 接口，把命令行式查询封装成可供模型直接调用的数据查询工具。当用户需要查询宏观/行业/县域/企业/财务数据、行情/K线/分时、资讯/公告/研报/招投标、ECharts 图表参数、多工具组合场景，或提到行业洞察、HYDC、hydc、行业数据接口时使用。执行流程固定为：先用 help 发现可用命令与参数，再用 query 执行查询并回传数据。
---

# 行业洞察数据（HYDC）连接

## Overview

行业洞察数据接口（HYDC）通过 `run-cli` 命令行式查询提供结构化的行业与市场数据。本技能把该接口封装成两个动作：**help**（按层发现命令与参数）和 **query**（执行命令并返回数据），由 `scripts/hydc.mjs` 负责 HTTP 调用。模型不需要记住任何命令，一律先 `help` 确认命令名与参数，再 `query` 执行。

## 配置

- **API Key**：接口需要鉴权。Key 来自环境变量（默认 `HYDC_API_KEY`）或 `--api-key` 参数；两者都缺时脚本报错并给出设置指引。
  - PowerShell 设置一次：`$env:HYDC_API_KEY='<KEY>'`
  - 或单次调用传入：`node hydc.mjs --api-key <KEY> query "<命令>"`
- **接口地址**：默认生产地址，可用 `--endpoint <url>` 覆盖以切换测试/环境。
- **超时**：默认 30s，可用 `--timeout <ms>` 调整。

脚本级选项（`--endpoint`/`--timeout`/`--api-key`/`--api-key-env`）必须放在命令之前；命令内部以 `--` 开头的参数会原样传给接口，不会被脚本截取。

## 命令组织（五大类）

命令统一形如 `<工具名> <functionName> [--参数 值]`：

- **economicData**：宏观 / 行业 / 县域 / 企业 / 财务数据。
- **marketData**：行情 / K线 / 分时。
- **news**：资讯 / 公告 / 研报 / 招投标。
- **chartData**：ECharts 图表参数。
- **querySkill**：多工具组合场景。

各工具完整命令清单快照见 `references/commands.md`（快照可能过期，命令名与参数以实时 `<工具> help --name <命令名>` 为准）。

## 调用流程（先 help 后 query）

1. **发现命令** —— 向用户说明数据来源与可选项之前，先调用 help：
   - `node hydc.mjs help` → 返回工具总览。
   - `node hydc.mjs help "<工具名> help"` → 列出该工具全部命令，如 `help "economicData help"`。
   - `node hydc.mjs help "<工具名> help --name <命令名>"` → 查看单命令参数与返回结构。
   - `node hydc.mjs help "marketData fields --command <接口名>"` → 查询行情接口字段。
2. **执行查询** —— 用 help 返回的命令名与参数构造完整命令：
   - `node hydc.mjs query "economicData querySecuMain --keyword PAYH --limit 5"`
   - 省略 `query` 前缀等价：`node hydc.mjs "economicData querySecuMain --keyword PAYH --limit 5"`

## 脚本用法

```powershell
# 先设好 Key，再查询
$env:HYDC_API_KEY='<KEY>'
node "C:\Users\jindongyi\AppData\Local\Doubao\User Data\Default\.doubao\agent_mode\workspace\.user_skills\hydc-industry-insight\scripts\hydc.mjs" help "economicData help"
node "C:\Users\jindongyi\AppData\Local\Doubao\User Data\Default\.doubao\agent_mode\workspace\.user_skills\hydc-industry-insight\scripts\hydc.mjs" query "economicData querySecuMain --keyword PAYH --limit 5"
```

接口返回的 `data` 为 JSON 或文本，脚本直接原样输出到 stdout；失败信息输出到 stderr 并以非零码退出。

## 错误处理

- **未配置 Key**：按提示设置 `HYDC_API_KEY` 环境变量或加 `--api-key`。
- **HTTP 非 200 / 非 JSON / `success:false`**：脚本打印可读错误与响应片段，据此修正命令或参数。
- **命令不存在或参数错误**：用 help 重新确认命令名与参数名，不要猜测。

调用完成后，把返回的数据按用户需要整理成答案或图表；涉及结构化关系、占比、趋势等内容时按可视化规范配图。
