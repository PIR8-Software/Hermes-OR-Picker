/**
 * F10/F11 boundary regression probes against the
 * SHIPPED catalog/desktop/plugin.js through its real registration surface.
 *
 * Contract under test (synthetic fixtures only — never real picks):
 *  1. an application-error envelope ({error:...}) on the final authoritative
 *     GET must NOT normalize acknowledged/current picks to an empty list; the
 *     actual failure is surfaced and stays visible alongside per-entry import
 *     errors (genuine successful {models:[]} is still authoritative empty);
 *  2. import consults the CURRENT authoritative selection and shared pending
 *     ownership immediately before EVERY entry's decision — a completed
 *     intervening toggle is honored: no duplicate POST after an intervening
 *     add (stored description never overwritten), and no erroneous omission
 *     after an intervening remove (the file entry becomes eligible again).
 * Controls (retained behavior — pass before AND after the fix):
 *  C1 valid successful {models:[]} final GET remains an authoritative empty
 *     list with no invented error;
 *  C2 a THROWN final GET preserves acknowledged state and surfaces the failure.
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

// ── 1. application-error envelope on the final authoritative GET ─────────

test('2813-1a: application-error final GET preserves acknowledged/current entries and surfaces the actual error', async () => {
  const s = storeWith([{ id: 'old/one', description: 'Original' }])
  const h = await mountPicker(s)
  await flush()
  s.intercept('GET', '/models', () => ({ error: 'curated file unreadable' }))
  await choose(await input(h), ['new/two'])
  await flush()
  assert.deepEqual(s.entries, [
    { id: 'old/one', description: 'Original' },
    { id: 'new/two', description: 'new/two' },
  ])
  assert.deepEqual(await exported(h), s.entries,
    'an application-error GET cannot normalize acknowledged state to empty')
  assert.match(textOf(h.tree), /curated file unreadable/,
    'the actual failure is surfaced, not hidden behind an empty list')
  h.root.unmount()
})

test('2813-1b: reconciliation failure stays visible alongside per-entry import errors', async () => {
  const s = storeWith([{ id: 'old/one', description: 'Original' }])
  s.intercept('POST', '/models', () => ({ error: 'quota exceeded' }),
    c => c.body && c.body.id === 'bad/two')
  const h = await mountPicker(s)
  await flush()
  s.intercept('GET', '/models', () => ({ error: 'curated file unreadable' }))
  await choose(await input(h), ['good/one', 'bad/two'])
  await flush()
  assert.deepEqual(s.entries.map(e => e.id), ['old/one', 'good/one'],
    'the acknowledged partial success survives the failed reconciliation read')
  assert.deepEqual(await exported(h), s.entries, 'UI/export keep the acknowledged entries')
  const banner = errorBanner(h.tree)
  assert.ok(banner.includes('curated file unreadable'),
    `reconciliation failure visible even with entry errors: ${banner}`)
  assert.ok(banner.includes('bad/two') && banner.includes('quota exceeded'),
    `the per-entry failure is visible too: ${banner}`)
  h.root.unmount()
})

// ── 2. import decides each entry against CURRENT state ───────────────────

test('2813-2a: completed intervening ADD suppresses the stale import POST (no description overwrite)', async () => {
  const s = new MockStore()
  s.catalog = [ROW]
  const d = deferred()
  s.intercept('POST', '/models', async c => { await d.promise; return s._handle(c.method, c.path, c.body) },
    c => c.body.id === 'slow/one')
  const h = await mountPicker(s)
  await flush()
  const p = choose(await input(h), ['slow/one', { id: 'x/one', description: 'From file' }])
  await flush()
  await boxOf(h, 'x/one').props.onCheckedChange() // completes while import awaits slow/one
  await flush()
  d.resolve()
  await p
  await flush()
  assert.equal(s.callsTo('POST', '/models').filter(c => c.body.id === 'x/one').length, 1,
    'the completed intervening toggle must suppress a duplicate import POST')
  assert.ok(s.entries.some(e => e.id === 'x/one' && e.description === 'Row'),
    'the picked row keeps its stored description — import never overwrites')
  assert.deepEqual(await exported(h), s.entries, 'UI/export reflect the authoritative end state')
  h.root.unmount()
})

test('2813-2b: completed intervening REMOVE re-enables the file entry (current state consulted per entry)', async () => {
  const s = storeWith([{ id: 'x/one', description: 'Old' }])
  s.catalog = [ROW]
  const d = deferred()
  s.intercept('POST', '/models', async c => { await d.promise; return s._handle(c.method, c.path, c.body) },
    c => c.body.id === 'slow/one')
  const h = await mountPicker(s)
  await flush()
  const p = choose(await input(h), ['slow/one', { id: 'x/one', description: 'From file' }])
  await flush()
  await boxOf(h, 'x/one').props.onCheckedChange() // toggles OFF, completes while import awaits
  await flush()
  d.resolve()
  await p
  await flush()
  assert.deepEqual(s.entries, [
    { id: 'slow/one', description: 'slow/one' },
    { id: 'x/one', description: 'From file' },
  ], 'import must consult current state before the later entry, not skip from a stale have set')
  assert.deepEqual(await exported(h), s.entries, 'UI/export reflect the authoritative end state')
  h.root.unmount()
})

// ── controls: retained behavior (pass before AND after the fix) ──────────

test('2813-C1 control: a valid successful {models:[]} remains an authoritative empty list', async () => {
  const s = storeWith([{ id: 'old/one', description: 'Original' }])
  const h = await mountPicker(s)
  await flush()
  s.intercept('GET', '/models', () => ({ models: [] }))
  await choose(await input(h), [{ id: 'old/one', description: 'unchanged' }]) // skipped: already picked
  await flush()
  assert.deepEqual(await exported(h), [], 'a successful authoritative empty read is applied')
  assert.equal(errorBanner(h.tree), '', 'no failure is invented for a successful empty list')
  h.root.unmount()
})

test('2813-C2 control: a THROWN final GET preserves acknowledged state and surfaces the failure', async () => {
  const s = new MockStore()
  const h = await mountPicker(s)
  await flush()
  s.intercept('GET', '/models', () => Promise.reject(Error('refresh exploded')))
  await choose(await input(h), ['keep/one'])
  await flush()
  assert.deepEqual(s.entries, [{ id: 'keep/one', description: 'keep/one' }], 'store unchanged by the failed read')
  assert.deepEqual(await exported(h), s.entries, 'UI state survives the failed reconciliation read')
  assert.match(errorBanner(h.tree), /refresh exploded/, 'the thrown failure is surfaced')
  h.root.unmount()
})
