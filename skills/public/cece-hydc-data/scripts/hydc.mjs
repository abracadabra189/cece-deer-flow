#!/usr/bin/env node
/**
 * CECE's fixed HYDC transport wrapper.
 *
 * Authentication comes only from HYDC_API_KEY in the sandbox environment.
 * The endpoint and request timeout are deliberately not CLI-configurable.
 */
import process from 'node:process'
import { pathToFileURL } from 'node:url'

export const DEFAULT_ENDPOINT = 'https://xhcj-h5-zg.cnfin.com/xhcj-bun-cli/d/hydc/run-cli'
export const DEFAULT_TIMEOUT_MS = 30_000
const ERROR_SNIPPET_LENGTH = 500
const FORBIDDEN_WRAPPER_FLAGS = new Set([
  '--api-key',
  '--api-key-env',
  '--endpoint',
  '--timeout',
])
const FORBIDDEN_WRAPPER_FLAG_PATTERN = /(?:^|\s)(--(?:api-key-env|api-key|endpoint|timeout))(?:\s|=|$)/

/**
 * Parse only the HYDC action and its business command. Business command flags
 * (for example --keyword) are kept unchanged; transport controls are rejected.
 * @param {string[]} argv
 * @returns {{mode: 'help' | 'query', command: string}}
 */
export function parseArgs(argv) {
  for (const arg of argv) {
    const forbidden = FORBIDDEN_WRAPPER_FLAGS.has(arg)
      ? arg
      : arg.match(FORBIDDEN_WRAPPER_FLAG_PATTERN)?.[1]
    if (forbidden) {
      throw new Error(`Wrapper option ${forbidden} is not supported; CECE controls HYDC transport settings.`)
    }
  }

  const rest = [...argv]
  const mode = rest[0] === 'help' || rest[0] === 'query' ? rest.shift() : 'query'
  return { mode, command: rest.join(' ') }
}

/** @param {unknown} raw */
export function normalizeAuthorization(raw) {
  const value = typeof raw === 'string' ? raw.trim() : ''
  if (value === '') return ''
  return /^[A-Za-z][A-Za-z0-9._~+/-]*\s+\S/.test(value) ? value : `Bearer ${value}`
}

export function resolveAuthorization() {
  const authorization = normalizeAuthorization(process.env.HYDC_API_KEY)
  if (authorization !== '') return authorization
  throw new Error('HYDC_API_KEY is not configured in the sandbox environment.')
}

/** @param {string} text */
function snippet(text) {
  const compact = text.replace(/\s+/g, ' ').trim()
  return compact.length > ERROR_SNIPPET_LENGTH
    ? `${compact.slice(0, ERROR_SNIPPET_LENGTH)}…`
    : compact
}

/** @param {unknown} data @param {unknown} payload */
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

/** @param {unknown} payload */
export function unwrapResponse(payload) {
  if (payload === null || typeof payload !== 'object') {
    throw new Error(`HYDC returned an unrecognized response: ${snippet(JSON.stringify(payload) ?? String(payload))}`)
  }
  if (payload.success === false) {
    throw new Error(`HYDC request failed: ${payload.error ?? snippet(JSON.stringify(payload))}`)
  }
  const data = payload.data
  if (data !== null && typeof data === 'object' && data.success === false) {
    throw new Error(`HYDC request failed: ${data.error ?? snippet(JSON.stringify(data))}`)
  }
  return renderData(data, payload)
}

/** @param {{mode: 'help' | 'query', command: string}} request */
export async function runCommand(request) {
  const authorization = resolveAuthorization()
  const timeout = AbortSignal.timeout(DEFAULT_TIMEOUT_MS)

  let response
  try {
    response = await fetch(DEFAULT_ENDPOINT, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        accept: 'application/json',
        authorization,
      },
      body: JSON.stringify({ command: request.command }),
      signal: timeout,
    })
  } catch (error) {
    if (timeout.aborted) {
      throw new Error(`HYDC request timed out after ${DEFAULT_TIMEOUT_MS}ms.`)
    }
    throw new Error(`HYDC connection failed: ${error instanceof Error ? error.message : String(error)}`)
  }

  const text = await response.text()
  if (!response.ok) throw new Error(`HYDC returned HTTP ${response.status}: ${snippet(text)}`)

  try {
    return unwrapResponse(JSON.parse(text))
  } catch (error) {
    if (error instanceof SyntaxError) throw new Error(`HYDC returned non-JSON content: ${snippet(text)}`)
    throw error
  }
}

export async function main(argv = process.argv.slice(2)) {
  const request = parseArgs(argv)
  if (request.mode === 'help' && request.command === '') request.command = 'help'
  if (request.command === '') {
    throw new Error('Usage: node hydc.mjs [help|query] <HYDC command>')
  }
  const text = await runCommand(request)
  process.stdout.write(text)
  if (!text.endsWith('\n')) process.stdout.write('\n')
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    console.error(`[cece-hydc-data] ${error instanceof Error ? error.message : String(error)}`)
    process.exitCode = 1
  })
}
