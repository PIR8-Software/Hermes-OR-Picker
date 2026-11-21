/**
 * CI wiring contract: both workflow jobs must run the JS behavior suites as a
 * non-optional command (F-10/F-11 regression coverage must never silently drop
 * out of CI). Lives in the JS suite on purpose so the pinned pytest count (180)
 * stays exact.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const wf = readFileSync(path.join(ROOT, '.github', 'workflows', 'test.yml'), 'utf8')

function jobBody(name) {
  const jobs = {}
  let current = null
  let inJobs = false
  for (const line of wf.split(/\r?\n/)) {
    if (line.trimEnd() === 'jobs:') { inJobs = true; continue }
    if (inJobs && /^  [A-Za-z0-9_-]+:\s*$/.test(line)) {
      current = line.trim().replace(/:$/, '')
      jobs[current] = ''
    } else if (current !== null) {
      jobs[current] += line + '\n'
    }
  }
  assert.ok(name in jobs, `workflow has no ${name} job`)
  return jobs[name]
}

test('CI: hermetic job runs node --test tests/js non-optionally', () => {
  const herm = jobBody('hermetic')
  assert.ok(herm.includes('node --test tests/js'), 'hermetic job must run the JS suites')
  assert.ok(!/continue-on-error/.test(herm), 'hermetic JS step must not be allowed to fail silently')
})

test('CI: integration (real process-lifetime) job runs node --test tests/js non-optionally', () => {
  const integ = jobBody('integration')
  assert.ok(integ.includes('node --test tests/js'), 'integration job must run the JS suites')
  assert.ok(!/continue-on-error/.test(integ), 'integration JS step must not be allowed to fail silently')
})

test('CI: the js suite directory referenced by the workflow contains the behavior tests', () => {
  const tests = ['import-export.test.mjs', 'ui-races.test.mjs', 'smoke.test.mjs', 'review-2810.test.mjs', 'review-2813.test.mjs']
  for (const t of tests) {
    const p = path.join(ROOT, 'tests', 'js', t)
    assert.ok(readFileSync(p, 'utf8').length > 0, `${t} missing`)
  }
})
