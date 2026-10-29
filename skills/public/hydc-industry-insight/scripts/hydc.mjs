#!/usr/bin/env node
/**
 * 行业洞察数据（HYDC）run-cli 接口的调用封装 —— 豆包技能版。
 *
 * 由 DeepSeek Harness 插件 @local/dsh-plugin-hydc（hydc_help / hydc_query）移植而来，
 * 去掉 cordis 与 npm 依赖，使用 Node 内置 fetch，可在豆包本地环境直接运行。
 *
 * 命令组织：`<工具名> <functionName> [--参数 值]`，五大类见 SKILL.md。
 * - economicData  宏观 / 行业 / 县域 / 企业 / 财务
 * - marketData    行情 / K线 / 分时
 * - news          资讯 / 公告 / 研报 / 招投标
 * - chartData     ECharts 图表参数
 * - querySkill    多工具组合场景
 *
 * 用法：
 *   node hydc.mjs help                                # 工具总览
 *   node hydc.mjs help "economicData help"            # 列出该工具全部命令
 *   node hydc.mjs help "economicData help --name 命令名"  # 查看单命令参数与返回结构
 *   node hydc.mjs query "economicData querySecuMain --keyword PAYH --limit 5"
 *   node hydc.mjs "economicData querySecuMain --keyword PAYH --limit 5"   # 省略 query 等价
 *
 * API Key（三者取优先级：--api-key > 环境变量，默认 HYDC_API_KEY）：
 *   node hydc.mjs --api-key <KEY> query "..."
 *   $env:HYDC_API_KEY='<KEY>'; node hydc.mjs query "..."     # PowerShell
 *
 * 脚本级选项必须放在命令之前；命令内部以 "--" 开头的参数会原样传给接口。
 */
import process from 'node:process'

/** run-cli 接口的默认地址。 */
const DEFAULT_ENDPOINT = 'https://xhcj-h5-zg.cnfin.com/xhcj-bun-cli/d/hydc/run-cli'
/** API Key 的默认环境变量名。 */
const DEFAULT_API_KEY_ENV = 'HYDC_API_KEY'
/** 默认单次调用超时（毫秒）。 */
const DEFAULT_TIMEOUT_MS = 30000
/** 错误信息里保留的响应片段长度。 */
const ERROR_SNIPPET_LENGTH = 500

/**
 * 解析命令行参数。
 *
 * 脚本级选项（--endpoint / --timeout / --api-key / --api-key-env）只允许出现在命令
 * 之前；遇到第一个非选项内容后停止解析选项，其后的所有内容（含业务命令里以
 * "--" 开头的参数）一律拼成 command。
 * @param {string[]} argv - process.argv 去掉 node 与脚本路径后的剩余部分。
 */
export function parseArgs(argv) {
  const opts = {
    mode: 'query',
    endpoint: DEFAULT_ENDPOINT,
    timeoutMs: DEFAULT_TIMEOUT_MS,
    apiKey: null,
    apiKeyEnv: DEFAULT_API_KEY_ENV,
    command: '',
  }
  const rest = []
  let parsingOptions = true
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (parsingOptions) {
      if (a === '--endpoint') {
        opts.endpoint = argv[++i]
        continue
      }
      if (a === '--timeout') {
        opts.timeoutMs = Number(argv[++i])
        continue
      }
      if (a === '--api-key') {
        opts.apiKey = argv[++i]
        continue
      }
      if (a === '--api-key-env') {
        opts.apiKeyEnv = argv[++i]
        continue
      }
      parsingOptions = false
    }
    rest.push(a)
  }
  if (rest[0] === 'help' || rest[0] === 'query') opts.mode = rest.shift()
  opts.command = rest.join(' ')
  return opts
}

/**
 * 把 API Key 规范成可用的请求头值。
 * 已经是 `Bearer xxx` / `Basic xxx` 这类带 scheme 的值原样返回，只填 token 时补 Bearer。
 * @param {unknown} raw - 原始值。
 * @returns {string} 请求头值；空字符串表示未配置。
 */
export function normalizeAuthorization(raw) {
  const value = typeof raw === 'string' ? raw.trim() : ''
  if (value === '') return ''
  // 带 scheme 的请求头（如 `Bearer xxx`）直接使用；裸 token 没有空格。
  return /^[A-Za-z][A-Za-z0-9._~+/-]*\s+\S/.test(value) ? value : `Bearer ${value}`
}

/**
 * 解析本次调用可用的 Authorization 请求头。
 * 优先级：--api-key > 环境变量（--api-key-env 指定，默认 HYDC_API_KEY）。
 * @param {ReturnType<typeof parseArgs>} opts - 解析后的参数。
 * @returns {string} 请求头值。
 * @throws {Error} 无可用 Key 时抛出带操作指引的错误。
 */
export function resolveAuthorization(opts) {
  if (opts.apiKey) return normalizeAuthorization(opts.apiKey)
  const fromEnv = normalizeAuthorization(process.env[opts.apiKeyEnv])
  if (fromEnv !== '') return fromEnv
  const hint = `请在运行前设置环境变量 ${opts.apiKeyEnv}（PowerShell: $env:${opts.apiKeyEnv}='<KEY>'）`
    + `，或通过 --api-key <KEY> 直接传入 API Key。`
  throw new Error(`行业洞察接口未配置 API Key。${hint}`)
}

/**
 * 截断错误信息中的响应体片段。
 * @param {string} text - 原始文本。
 * @returns {string} 单行片段。
 */
function snippet(text) {
  const compact = text.replace(/\s+/g, ' ').trim()
  return compact.length > ERROR_SNIPPET_LENGTH ? `${compact.slice(0, ERROR_SNIPPET_LENGTH)}…` : compact
}

/**
 * 把接口返回的 data 转成模型可读文本。
 * 帮助类命令直接返回字符串，或把长文档放在单一字符串字段里（如 `{ skill: "..." }`）；
 * 业务数据返回对象或数组。文本保持原文，避免 JSON 转义把 markdown 压成一行。
 * @param {unknown} data - 接口返回的 data 字段。
 * @param {unknown} payload - 完整响应，data 缺失时兜底。
 * @returns {string} 模型可读文本。
 */
export function renderData(data, payload) {
  if (typeof data === 'string') return data
  if (data === undefined || data === null) return JSON.stringify(payload)
  if (typeof data === 'object' && !Array.isArray(data)) {
    for (const key of ['skill', 'text', 'markdown']) {
      if (typeof data[key] === 'string') return data[key]
    }
    const keys = Object.keys(data)
    if (keys.length === 1 && typeof data[keys[0]] === 'string') return data[keys[0]]
  }
  return JSON.stringify(data)
}

/**
 * 从接口响应中取出数据，或抛出可读的调用错误。
 * 接口在 HTTP 200 下也可能返回 `{ success: false }` 或 `data.success === false`（例如 token 失效）。
 * @param {unknown} payload - 已解析的响应 JSON。
 * @returns {string} 模型可读文本。
 */
export function unwrapResponse(payload) {
  if (payload === null || typeof payload !== 'object') {
    throw new Error(`行业洞察接口返回了无法识别的响应：${snippet(JSON.stringify(payload) ?? String(payload))}`)
  }
  if (payload.success === false) {
    throw new Error(`行业洞察接口调用失败：${payload.error ?? snippet(JSON.stringify(payload))}`)
  }
  const data = payload.data
  if (data !== null && typeof data === 'object' && data.success === false) {
    throw new Error(`行业洞察接口调用失败：${data.error ?? snippet(JSON.stringify(data))}`)
  }
  return renderData(data, payload)
}

/**
 * 执行一条 run-cli 命令并返回模型可读文本。
 * @param {ReturnType<typeof parseArgs>} opts - 解析后的参数。
 * @returns {Promise<string>} 接口数据文本。
 */
export async function runCommand(opts) {
  const authorization = resolveAuthorization(opts)
  const timeout = AbortSignal.timeout(opts.timeoutMs)

  let response
  try {
    response = await fetch(opts.endpoint, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        accept: 'application/json',
        authorization,
      },
      body: JSON.stringify({ command: opts.command }),
      signal: timeout,
    })
  } catch (error) {
    if (timeout.aborted) {
      throw new Error(`行业洞察接口请求超时（${opts.timeoutMs}ms）：${opts.command}`)
    }
    throw new Error(`行业洞察接口连接失败：${error instanceof Error ? error.message : String(error)}`)
  }

  const text = await response.text()
  if (!response.ok) {
    throw new Error(`行业洞察接口返回 HTTP ${response.status}：${snippet(text)}`)
  }

  let payload
  try {
    payload = JSON.parse(text)
  } catch {
    throw new Error(`行业洞察接口返回了非 JSON 内容：${snippet(text)}`)
  }
  return unwrapResponse(payload)
}

/** 入口：解析参数、执行命令、打印结果。 */
async function main() {
  const opts = parseArgs(process.argv.slice(2))
  // 与原插件语义一致：省略命令的 help 等价于发送 "help"（工具总览）。
  if (opts.mode === 'help' && opts.command === '') opts.command = 'help'
  if (opts.command === '') {
    console.error('用法：node hydc.mjs [脚本选项] [help|query] <命令>')
    console.error('  node hydc.mjs help                                 # 工具总览')
    console.error('  node hydc.mjs help "economicData help --name 命令名"  # 单命令参数')
    console.error('  node hydc.mjs query "<工具名> <functionName> [--参数 值]"')
    console.error('脚本选项（必须在命令之前）：--endpoint <url> --timeout <ms> --api-key <KEY> --api-key-env <名称>')
    process.exit(2)
  }
  try {
    const text = await runCommand(opts)
    process.stdout.write(text)
    if (!text.endsWith('\n')) process.stdout.write('\n')
  } catch (error) {
    console.error(`[hydc] ${error instanceof Error ? error.message : String(error)}`)
    process.exit(1)
  }
}

main()
