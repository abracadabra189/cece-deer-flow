import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  DEFAULT_ENDPOINT,
  DEFAULT_TIMEOUT_MS,
  parseArgs,
  resolveAuthorization,
  runCommand,
} from '../../skills/public/cece-hydc-data/scripts/hydc.mjs'

test('keeps business command flags while rejecting wrapper transport overrides', () => {
  assert.deepEqual(
    parseArgs(['query', 'economicData', 'querySecuMain', '--keyword', 'PAYH']),
    {
      mode: 'query',
      command: 'economicData querySecuMain --keyword PAYH',
    },
  )

  for (const flag of ['--api-key', '--api-key-env', '--endpoint', '--timeout']) {
    assert.throws(() => parseArgs([flag, 'value', 'query', 'economicData help']), /not supported/i)
    assert.throws(
      () => parseArgs(['query', `economicData help ${flag} value`]),
      /not supported/i,
    )
  }
})

test('uses HYDC_API_KEY from environment only', () => {
  const previous = process.env.HYDC_API_KEY
  try {
    process.env.HYDC_API_KEY = 'test-token'
    assert.equal(resolveAuthorization(), 'Bearer test-token')
    delete process.env.HYDC_API_KEY
    assert.throws(() => resolveAuthorization(), /HYDC_API_KEY/)
  } finally {
    if (previous === undefined) delete process.env.HYDC_API_KEY
    else process.env.HYDC_API_KEY = previous
  }
})

test('posts to the fixed endpoint and fixed timeout', async () => {
  const previousKey = process.env.HYDC_API_KEY
  const previousFetch = globalThis.fetch
  let request
  try {
    process.env.HYDC_API_KEY = 'test-token'
    globalThis.fetch = async (url, options) => {
      request = { url, options }
      return new Response(JSON.stringify({ data: { ok: true } }), { status: 200 })
    }

    assert.equal(await runCommand(parseArgs(['query', 'economicData help'])), '{"ok":true}')
    assert.equal(request.url, DEFAULT_ENDPOINT)
    assert.equal(request.options.headers.authorization, 'Bearer test-token')
    assert.ok(request.options.signal instanceof AbortSignal)
    assert.equal(DEFAULT_TIMEOUT_MS, 30000)
  } finally {
    globalThis.fetch = previousFetch
    if (previousKey === undefined) delete process.env.HYDC_API_KEY
    else process.env.HYDC_API_KEY = previousKey
  }
})

test('skill and dev172 deployment references use the CECE-only HYDC contract', async () => {
  const [skill, config, readme] = await Promise.all([
    readFile('skills/public/cece-hydc-data/SKILL.md', 'utf8'),
    readFile('deploy/cece-harness-dev172/config.example.yaml', 'utf8'),
    readFile('deploy/cece-harness-dev172/README.md', 'utf8'),
  ])

  assert.match(skill, /^name: cece-hydc-data$/m)
  assert.match(skill, /HYDC_API_KEY/)
  assert.doesNotMatch(skill, /--api-key\s+<KEY>/)
  assert.doesNotMatch(skill, /--endpoint\s+<url>/)
  assert.match(config, /\/mnt\/skills\/public\/cece-hydc-data\/SKILL\.md/)
  assert.match(config, /node \/mnt\/skills\/public\/cece-hydc-data\/scripts\/hydc\.mjs/)
  assert.doesNotMatch(config, /hydc-industry-insight/)
  assert.match(readme, /HYDC_API_KEY/)
})
