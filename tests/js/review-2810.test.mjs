/**
 * F10/F11 regression probes against the SHIPPED
 * catalog/desktop/plugin.js through its real registration surface.
 *
 * Contract under test (synthetic fixtures only — never real picks):
 *  1. per-id ownership is SHARED across import/toggle/concurrent imports:
 *     one writer per id at a time, unrelated rows keep full concurrency;
 *  2. GET responses cannot clobber acknowledged mutations (read/mutation
 *     fence), including a refresh issued while writes are pending;
 *  3. transport-rejected import entries keep partial successes, are reported
 *     per-entry, later entries still run, and authoritative reconciliation
 *     always happens; a failed final GET never erases current state;
 *  4. explicit non-string descriptions are rejected clearly (omitted/null
 *     keep the legacy id fallback); never silently replaced;
 *  5. explicit description strings — including empty and whitespace — round
 *     trip byte-for-byte through export -> import -> store;
 *  6. after unmount no new model writes may start (file-read completion,
 *     mid-loop cleanup) and no setState may hit a dead component.
 */
import './register.mjs'
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  MockStore, storeWith, mountPicker, flush, findByAria, findAll, textOf, deferred,
} from './harness.mjs'

const ROW = { id: 'x/one', name: 'Row', provider: 'pco', prompt_price: 1, completion_price: 1, context_length: 1000 }

function errorBanner(tree) {
  const node = findAll(tree, n => n.type === 'div' && textOf(n).startsWith('⚠'))[0]
  return node ? textOf(node) : ''
}

async function input(h) {
  findByAria(h.tree, 'Import list').props.onClick()
  return h.dom.lastFileInput()
}

const choose = (i, p) => i.onchange({ target: { files: [{ text: async () => JSON.stringify(p) }] } })

async function exported(h) {
  findByAria(h.tree, 'Export list').props.onClick()
  return JSON.parse(await h.dom.exportedText())
}

const boxOf = (h, id) => findAll(h.tree, n => n.type === 'checkbox-mock').find(b => textOf(b.parent).includes(id))

// ── 1. shared per-id ownership ───────────────────────────────────────────

test('2810-1a: import reserves its id — concurrent toggle is dropped, file description wins', async () => {
  const s = new MockStore()
  s.catalog = [ROW]
  const d = deferred()
  s.intercept('POST', '/models', async c => { await d.promise; return s._handle(c.method, c.path, c.body) })
  const h = await mountPicker(s)
  await flush()
  const p = choose(await input(h), [{ id: 'x/one', description: 'From file' }])
  await flush()
  const q = boxOf(h, 'x/one').props.onCheckedChange() // races the in-flight import
  await flush()
  d.resolve()
  await Promise.all([p, q])
  await flush()
  assert.equal(s.callsTo('POST', '/models').length, 1,
    'import must reserve/disable its id, not race a toggle into a second POST')
  assert.deepEqual(s.entries, [{ id: 'x/one', description: 'From file' }],
    'the intentional file description must win, not the row name')
})

test('2810-1b: toggle reserves its id — concurrent import entry is skipped, nothing overwritten', async () => {
  const s = new MockStore()
  s.catalog = [ROW]
  const d = deferred()
  s.intercept('POST', '/models', async c => { await d.promise; return s._handle(c.method, c.path, c.body) })
  const h = await mountPicker(s)
  await flush()
  const q = boxOf(h, 'x/one').props.onCheckedChange() // toggle owns x/one now
  await flush()
  const p = choose(await input(h), [{ id: 'x/one', description: 'From file' }, { id: 'z/one', description: 'Z' }])
  await flush()
  d.resolve()
  await Promise.all([p, q])
  await flush()
  assert.equal(s.callsTo('POST', '/models').filter(c => c.body.id === 'x/one').length, 1,
    'import must not race the toggle that owns the id')
  assert.deepEqual(s.entries, [{ id: 'z/one', description: 'Z' }, { id: 'x/one', description: 'Row' }],
    'toggle write wins the owned id; the unrelated entry still imports (order = completion order)')
  assert.match(errorBanner(h.tree), /skipped/i, 'the skipped file entry is reported, not silent')
})

test('2810-1c: concurrent imports share per-id ownership — one POST per id, unrelated entries proceed', async () => {
  const s = new MockStore()
  const d = deferred()
  s.intercept('POST', '/models', async c => { await d.promise; return s._handle(c.method, c.path, c.body) },
    c => c.body && c.body.id === 'x/one')
  const h = await mountPicker(s)
  await flush()
  const iA = await input(h)
  const pA = choose(iA, [{ id: 'x/one', description: 'From A' }])
  await flush() // A reserves x/one; its POST is in flight
  const iB = await input(h)
  const pB = choose(iB, [{ id: 'x/one', description: 'From B' }, { id: 'z/one', description: 'Z' }])
  await pB // B skips the owned id, imports its unrelated entry
  d.resolve()
  await pA
  await flush()
  assert.equal(s.callsTo('POST', '/models').filter(c => c.body.id === 'x/one').length, 1,
    'simultaneous imports must not double-write the same id')
  assert.deepEqual(s.entries, [{ id: 'z/one', description: 'Z' }, { id: 'x/one', description: 'From A' }],
    'first owner wins deterministically; no duplicate and no overwrite')
  assert.deepEqual(await exported(h), s.entries, 'UI/export reflects the authoritative end state')
})

// ── 2. read/mutation fence ───────────────────────────────────────────────

test('2810-2a: an older GET cannot overwrite a completed toggle', async () => {
  const s = new MockStore()
  s.catalog = [ROW]
  const d = deferred()
  s.intercept('GET', '/models', () => d.promise)
  const h = await mountPicker(s)
  await flush()
  await boxOf(h, 'x/one').props.onCheckedChange()
  await flush()
  d.resolve({ models: [] })
  await flush()
  assert.deepEqual(await exported(h), s.entries,
    'old GET must not erase a later acknowledged mutation')
  assert.deepEqual(s.entries, [{ id: 'x/one', description: 'Row' }])
})

test('2810-2b: a refresh issued while writes are pending cannot clobber the acknowledged write', async () => {
  const s = new MockStore()
  s.catalog = [ROW]
  const dAdd = deferred()
  const dGet = deferred()
  s.intercept('POST', '/models', async c => { await dAdd.promise; return s._handle(c.method, c.path, c.body) },
    c => c.body && c.body.id === 'x/one')
  const h = await mountPicker(s) // initial GET resolves normally
  await flush()
  const q = boxOf(h, 'x/one').props.onCheckedChange() // toggle add is now in flight
  await flush()
  s.intercept('GET', '/models', () => dGet.promise) // the next refresh runs now,
  const pB = choose(await input(h), [{ id: 'y/one', description: 'Y' }])
  await flush() // B's add completes; its refresh is issued while x/one is pending
  dAdd.resolve()
  await q // toggle acknowledged: x/one is now persisted
  await flush()
  dGet.resolve({ models: [{ id: 'y/one', description: 'Y' }] }) // stale snapshot: missing x/one
  await pB
  await flush()
  assert.deepEqual(await exported(h), s.entries,
    'a read issued during pending writes must not drop acknowledged writes')
  assert.deepEqual(s.entries.map(e => e.id).sort(), ['x/one', 'y/one'])
})

// ── 3. partial failures + reconciliation ─────────────────────────────────

test('2810-3a: transport rejection keeps partial successes, reports per-entry, reconciles authoritatively', async () => {
  const s = new MockStore()
  s.intercept('POST', '/models', () => Promise.reject(Error('transport gone')), c => c.body.id === 'bad/two')
  const h = await mountPicker(s)
  await flush()
  const before = s.callsTo('GET', '/models').length
  await choose(await input(h), ['good/one', 'bad/two', 'good/three'])
  await flush()
  assert.ok(s.callsTo('GET', '/models').length > before,
    'must re-fetch authoritatively even when a request rejects')
  assert.deepEqual(await exported(h), s.entries, 'successful partial writes must be reflected')
  assert.deepEqual(s.entries.map(e => e.id), ['good/one', 'good/three'],
    'later entries still attempted after a transport failure')
  const banner = errorBanner(h.tree)
  assert.ok(banner.includes('bad/two'), `failed id surfaced: ${banner}`)
  assert.ok(banner.includes('transport gone'), `actual failure reason surfaced: ${banner}`)
})

test('2810-3b: a failed final GET never erases current state and surfaces the failure', async () => {
  const s = new MockStore()
  const h = await mountPicker(s)
  await flush()
  s.intercept('GET', '/models', () => Promise.reject(Error('refresh exploded')))
  await choose(await input(h), ['keep/one'])
  await flush()
  assert.deepEqual(s.entries, [{ id: 'keep/one', description: 'keep/one' }], 'store unchanged by the failed read')
  assert.deepEqual(await exported(h), s.entries, 'UI state survives the failed reconciliation read')
  assert.match(errorBanner(h.tree), /refresh exploded/, 'the actual read failure is surfaced')
})

// ── 4. malformed explicit descriptions ──────────────────────────────────

test('2810-4: explicit non-string descriptions are rejected clearly; omitted/null fall back to id', async () => {
  const s = new MockStore()
  const h = await mountPicker(s)
  await flush()
  await choose(await input(h), [
    { id: 'num/desc', description: 5 },
    { id: 'obj/desc', description: { intent: 'not a string' } },
    { id: 'arr/desc', description: [1, 2] },
    { id: 'bool/desc', description: true },
    { id: 'null/desc', description: null },
    { id: 'ok/id', description: 'fine' },
    { id: 'legacy/id' },
  ])
  await flush()
  for (const bad of ['num/desc', 'obj/desc', 'arr/desc', 'bool/desc']) {
    assert.ok(!s.calls.some(c => c.body && c.body.id === bad), `no request posted for ${bad}`)
    assert.ok(errorBanner(h.tree).includes(bad), `rejection names ${bad}`)
  }
  assert.match(errorBanner(h.tree), /description must be a string/, 'rejection is explicit about the contract')
  assert.deepEqual(s.entries, [
    { id: 'null/desc', description: 'null/desc' },   // explicit null ≡ omitted: legacy id fallback
    { id: 'ok/id', description: 'fine' },
    { id: 'legacy/id', description: 'legacy/id' },   // omitted: legacy id fallback
  ])
})

// ── 5. lossless description round-trip ──────────────────────────────────

test('2810-5: explicit descriptions round trip verbatim — whitespace, empty and plain', async () => {
  const src = storeWith([
    { id: 'white/space', description: '  intentional\n' },
    { id: 'empty/desc', description: '' },
    { id: 'plain/desc', description: 'plain text' },
  ])
  const a = await mountPicker(src)
  await flush()
  const payload = await exported(a)
  assert.deepEqual(payload, [
    { id: 'white/space', description: '  intentional\n' },
    { id: 'empty/desc', description: '' },
    { id: 'plain/desc', description: 'plain text' },
  ], 'export is byte-for-byte')
  a.root.unmount()
  const dst = new MockStore()
  const b = await mountPicker(dst)
  await flush()
  await choose(await input(b), payload)
  await flush()
  assert.deepEqual(dst.entries, src.entries, 'import must preserve intentional strings end-to-end')
})

// ── 6. unmount / cleanup liveness ───────────────────────────────────────

test('2810-6a: file-read completion after unmount starts no model writes', async () => {
  const s = new MockStore()
  const h = await mountPicker(s)
  await flush()
  const i = await input(h)
  const d = deferred()
  const p = i.onchange({ target: { files: [{ text: () => d.promise }] } })
  h.root.unmount()
  d.resolve(JSON.stringify(['after/unmount']))
  await p
  await flush()
  assert.equal(s.callsTo('POST', '/models').length, 0, 'no write may start after cleanup')
  assert.deepEqual(h.violations, [], 'no setState after unmount')
})

test('2810-6b: unmount mid-import stops later entries and leaves no state updates', async () => {
  const s = new MockStore()
  const d = deferred()
  s.intercept('POST', '/models', async c => { await d.promise; return s._handle(c.method, c.path, c.body) })
  const h = await mountPicker(s)
  await flush()
  const p = choose(await input(h), ['first/one', 'second/two'])
  await flush()
  assert.equal(s.callsTo('POST', '/models').length, 1, 'first entry in flight')
  h.root.unmount()
  d.resolve()
  await p
  await flush()
  assert.equal(s.callsTo('POST', '/models').length, 1,
    'cleanup stops the import loop: no further entries are attempted')
  assert.deepEqual(h.violations, [], 'no setState after unmount')
})
