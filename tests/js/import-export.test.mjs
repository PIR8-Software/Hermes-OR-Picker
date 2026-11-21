/**
 * F10 — lossless export/import behavior tests, run against the SHIPPED
 * catalog/desktop/plugin.js through its real registration surface.
 *
 * Contract under test (synthetic fixtures only — never real picks):
 *  - export carries {id, description} and stored order (lossless);
 *  - import accepts legacy bare-id arrays, object arrays, and the documented
 *    providers.openrouter.models manifest;
 *  - malformed entries are rejected clearly, ids validated;
 *  - intentional descriptions are preserved; existing descriptions never
 *    silently overwritten (additive merge, no unrelated removal);
 *  - deterministic dedupe (first occurrence wins) and partial-failure
 *    reporting that reflects the actual failed request;
 *  - authoritative state re-fetch after import.
 */
import './register.mjs'
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  MockStore, storeWith, mountPicker, flush, click, findByAria, textOf, findAll,
} from './harness.mjs'

function errorBanner(tree) {
  const node = findAll(tree, n => n.type === 'div' && textOf(n).startsWith('⚠'))[0]
  return node ? textOf(node) : ''
}

async function clickImportButton(h) {
  const btn = findByAria(h.tree, 'Import list')
  assert.ok(btn, 'import button exists')
  await click(btn)
  const input = h.dom.lastFileInput()
  assert.ok(input, 'import opens a file dialog')
  return input
}

async function chooseFile(input, payload) {
  const json = typeof payload === 'string' ? payload : JSON.stringify(payload)
  const p = input.onchange({ target: { files: [{ text: async () => json }] } })
  if (p && typeof p.then === 'function') await p
  await flush()
}

// ── export ───────────────────────────────────────────────────────────────

test('F10: export is lossless — {id, description} objects in stored order', async () => {
  const store = storeWith([
    { id: 'acme/alpha', description: 'Alpha description' },
    { id: 'beta/gamma', description: 'Gamma description' },
    { id: 'zeta/omega', description: '' },
  ])
  const h = await mountPicker(store)
  await flush()
  await click(findByAria(h.tree, 'Export list'))
  const payload = JSON.parse(await h.dom.exportedText())
  assert.deepEqual(payload, [
    { id: 'acme/alpha', description: 'Alpha description' },
    { id: 'beta/gamma', description: 'Gamma description' },
    { id: 'zeta/omega', description: '' },
  ])
})

test('F10: nonempty export -> import round-trip preserves descriptions and order', async () => {
  const source = storeWith([
    { id: 'acme/alpha', description: 'keep me' },
    { id: 'beta/gamma', description: 'and me' },
  ])
  const a = await mountPicker(source)
  await flush()
  await click(findByAria(a.tree, 'Export list'))
  const exported = await a.dom.exportedText()
  a.root.unmount()

  const target = new MockStore()
  const b = await mountPicker(target)
  await flush()
  const input = await clickImportButton(b)
  await chooseFile(input, exported)
  assert.deepEqual(target.entries, [
    { id: 'acme/alpha', description: 'keep me' },
    { id: 'beta/gamma', description: 'and me' },
  ])
})

// ── accepted import shapes ───────────────────────────────────────────────

test('F10: legacy bare-id array still imports (description falls back to id)', async () => {
  const store = new MockStore()
  const h = await mountPicker(store)
  await flush()
  const input = await clickImportButton(h)
  await chooseFile(input, ['legacy/one', 'legacy/two'])
  assert.deepEqual(store.entries, [
    { id: 'legacy/one', description: 'legacy/one' },
    { id: 'legacy/two', description: 'legacy/two' },
  ])
})

test('F10: object array imports with descriptions preserved', async () => {
  const store = new MockStore()
  const h = await mountPicker(store)
  await flush()
  const input = await clickImportButton(h)
  await chooseFile(input, [
    { id: 'obj/one', description: 'Object one description' },
    { id: 'obj/two' },
    { id: 'obj/three', description: '' },
  ])
  assert.deepEqual(store.entries, [
    { id: 'obj/one', description: 'Object one description' },
    { id: 'obj/two', description: 'obj/two' },
    // explicit empty description is an intentional string and round-trips
    // losslessly (F-10 corrected contract, review 2810 finding 5)
    { id: 'obj/three', description: '' },
  ])
})

test('F10: documented providers.openrouter.models manifest imports', async () => {
  const store = new MockStore()
  const h = await mountPicker(store)
  await flush()
  const input = await clickImportButton(h)
  await chooseFile(input, {
    version: 1,
    updated_at: '2026-11-20T00:00:00+00:00',
    metadata: { source: 'Supplemental OpenRouter picker models' },
    providers: {
      openrouter: {
        metadata: { display_name: 'Supplemental OpenRouter models' },
        models: [
          { id: 'man/one', description: 'From manifest' },
          { id: 'man/two', description: 'Also from manifest' },
        ],
      },
    },
  })
  assert.deepEqual(store.entries, [
    { id: 'man/one', description: 'From manifest' },
    { id: 'man/two', description: 'Also from manifest' },
  ])
})

// ── rejection / validation ───────────────────────────────────────────────

test('F10: malformed entries are rejected clearly; valid entries still import', async () => {
  const store = new MockStore()
  const h = await mountPicker(store)
  await flush()
  const input = await clickImportButton(h)
  await chooseFile(input, [
    'good/id',
    123,
    { description: 'no id here' },
    { id: 'bad id' },
    { id: 'a/../b' },
    null,
  ])
  await flush()
  const banner = errorBanner(h.tree)
  assert.ok(banner.length > 0, 'malformed entries produce a clear rejection message')
  assert.match(banner, /reject/i, 'rejection is labeled as such')
  // every malformed entry is accounted for in the message
  for (const token of ['123', 'missing id', 'bad id', 'a/../b']) {
    assert.ok(banner.includes(token), `rejection message names ${JSON.stringify(token)}: ${banner}`)
  }
  // valid entry imported exactly once
  assert.deepEqual(store.entries, [{ id: 'good/id', description: 'good/id' }])
  // invalid ids never reach the API
  for (const c of store.callsTo('POST', '/models')) {
    assert.notEqual(c.body.id, 'bad id')
    assert.notEqual(c.body.id, 'a/../b')
  }
})

test('F10: an unusable payload (non-array, non-manifest) is a clear error with nothing imported', async () => {
  const store = new MockStore()
  const h = await mountPicker(store)
  await flush()
  const input = await clickImportButton(h)
  await chooseFile(input, '{"not": "a list"}')
  const banner = errorBanner(h.tree)
  assert.match(banner, /expect/i, 'error says what shape was expected')
  assert.equal(store.callsTo('POST', '/models').length, 0)
  assert.equal(store.entries.length, 0)
})

test('F10: import validates ids client-side before any request', async () => {
  const store = new MockStore()
  const h = await mountPicker(store)
  await flush()
  const input = await clickImportButton(h)
  await chooseFile(input, ['noslash', 'x//y', '/leading', 'ok/id'])
  const banner = errorBanner(h.tree)
  assert.match(banner, /reject/i)
  for (const bad of ['noslash', 'x//y', '/leading']) {
    assert.ok(banner.includes(bad), `names rejected id ${bad}: ${banner}`)
    assert.ok(!store.calls.some(c => c.body && c.body.id === bad), `no request for ${bad}`)
  }
  assert.deepEqual(store.entries, [{ id: 'ok/id', description: 'ok/id' }])
})

// ── merge semantics ──────────────────────────────────────────────────────

test('F10: deterministic dedupe — first occurrence wins, one add per id', async () => {
  const store = new MockStore()
  const h = await mountPicker(store)
  await flush()
  const input = await clickImportButton(h)
  await chooseFile(input, [
    { id: 'dup/id', description: 'Primary' },
    { id: 'dup/id', description: 'Secondary' },
    'dup/id',
  ])
  assert.equal(store.callsTo('POST', '/models').length, 1)
  assert.deepEqual(store.entries, [{ id: 'dup/id', description: 'Primary' }])
})

test('F10: import never overwrites existing descriptions (additive merge)', async () => {
  const store = storeWith([{ id: 'held/one', description: 'Original description' }])
  const h = await mountPicker(store)
  await flush()
  const input = await clickImportButton(h)
  await chooseFile(input, [
    { id: 'held/one', description: 'Hijacked description' },
    { id: 'new/one', description: 'Fresh description' },
  ])
  // existing entry untouched
  assert.deepEqual(store.entries[0], { id: 'held/one', description: 'Original description' })
  // new entry appended with its own description
  assert.deepEqual(store.entries[1], { id: 'new/one', description: 'Fresh description' })
  // no request tried to mutate the held entry
  const posts = store.callsTo('POST', '/models')
  assert.equal(posts.filter(c => c.body.id === 'held/one').length, 0)
})

test('F10: additive merge keeps picks absent from the file (no unrelated removal)', async () => {
  const store = storeWith([
    { id: 'keep/a', description: 'A' },
    { id: 'keep/b', description: 'B' },
  ])
  const h = await mountPicker(store)
  await flush()
  const input = await clickImportButton(h)
  await chooseFile(input, ['add/c'])
  assert.deepEqual(store.entries.map(e => e.id), ['keep/a', 'keep/b', 'add/c'])
  assert.equal(store.callsTo('POST', '/remove').length, 0)
})

// ── partial failures + authoritative re-fetch ────────────────────────────

test('F10: partial failures report the actual failed request; successes land', async () => {
  const store = new MockStore()
  store.intercept('POST', '/models', () => ({ error: 'quota exceeded' }),
    c => c.body && c.body.id === 'b/boom')
  const h = await mountPicker(store)
  await flush()
  const before = store.callsTo('GET', '/models').length
  const input = await clickImportButton(h)
  await chooseFile(input, ['a/one', 'b/boom', 'c/three'])
  const banner = errorBanner(h.tree)
  assert.ok(banner.includes('b/boom'), `failed id surfaced: ${banner}`)
  assert.ok(banner.includes('quota exceeded'), `actual failed-request error surfaced: ${banner}`)
  assert.deepEqual(store.entries.map(e => e.id), ['a/one', 'c/three'])
  // authoritative re-fetch after import
  assert.ok(store.callsTo('GET', '/models').length > before, 'import ends with an authoritative re-fetch')
})

test('F10: import skips ids with an in-flight toggle (pending state consulted)', async () => {
  const store = new MockStore()
  store.catalog = [
    { id: 'x/model', name: 'X', provider: 'xco', prompt_price: 1, completion_price: 1, context_length: 1000 },
  ]
  // Hold ONLY the first add of x/model (the toggle); later calls run for real.
  const held = []
  const origHandle = store._handle.bind(store)
  store._handle = (method, path, body) => {
    if (method === 'POST' && path === '/models' && body && body.id === 'x/model' && held.length === 0) {
      return new Promise(res => held.push(() => res(origHandle(method, path, body))))
    }
    return origHandle(method, path, body)
  }
  const h = await mountPicker(store)
  await flush()
  const box = findAll(h.tree, n => n.type === 'checkbox-mock')
    .find(b => textOf(b.parent).includes('x/model'))
  assert.ok(box, 'row rendered')
  const togglePromise = box.props.onCheckedChange() // x/model add now in flight
  await flush()

  const input = await clickImportButton(h)
  await chooseFile(input, [
    { id: 'x/model', description: 'dup' },
    { id: 'y/model', description: 'Y' },
  ])
  // import must not race the pending toggle on x/model
  assert.equal(store.callsTo('POST', '/models').filter(c => c.body.id === 'x/model').length, 1,
    'import consults pending state — no duplicate add for the toggling id')
  assert.ok(!errorBanner(h.tree).includes('already in list'), 'no spurious already-in-list banner')
  assert.deepEqual(store.entries.map(e => e.id), ['y/model'])

  held[0]() // let the toggle's add complete for real
  await togglePromise
  await flush()
  assert.deepEqual(store.entries.map(e => e.id).sort(), ['x/model', 'y/model'])
})
