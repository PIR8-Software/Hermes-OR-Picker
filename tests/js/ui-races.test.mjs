/**
 * F11 — UI race and error-surface behavior tests against the SHIPPED
 * catalog/desktop/plugin.js (real component handlers, mock host API with
 * controlled deferred promises). Synthetic data only.
 *
 * Contract under test:
 *  - rapid duplicate taps on one row produce ONE request (per-id pending);
 *  - concurrent toggles on different rows both proceed;
 *  - a toggle handler snapshotted before a state change decides add-vs-remove
 *    from CURRENT state (no stale closure re-add);
 *  - failed add/remove surface the actual failed request; pending clears
 *    (no stuck pending after failure or unmount);
 *  - file dialog + intervening user selection: import consults current
 *    authoritative + pending state, not the dialog-open snapshot;
 *  - stale (out-of-order) fetch responses cannot clobber newer state;
 *  - ChangelogView distinguishes failure / retry / genuine no-changes;
 *  - accepted live composer invalidation is preserved;
 *  - component cleanup: no state updates after unmount.
 */
import './register.mjs'
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  MockStore, storeWith, mountPicker, flush, findByAria, findAll, textOf,
} from './harness.mjs'
import { composerInvalidations } from './stubs/plugin-sdk.mjs'

const ROW = { name: 'Row', provider: 'pco', prompt_price: 1, completion_price: 1, context_length: 1000 }

function rowBox(tree, id) {
  return findAll(tree, n => n.type === 'checkbox-mock').find(b => textOf(b.parent).includes(id))
}

function errorBanner(tree) {
  const node = findAll(tree, n => n.type === 'div' && textOf(n).startsWith('⚠'))[0]
  return node ? textOf(node) : ''
}

/** Hold the first matching call; later calls run the real handler. */
function holdFirst(store, method, path, match) {
  const held = []
  const orig = store._handle.bind(store)
  store._handle = (m, p, b) => {
    if (m === method && p === path && match(b) && held.length === 0) {
      return new Promise(res => held.push(() => res(orig(m, p, b))))
    }
    return orig(m, p, b)
  }
  return held
}

// ── duplicate toggles / rapid clicks ─────────────────────────────────────

test('F11: rapid double-tap on one row issues ONE request and no spurious error', async () => {
  const store = new MockStore()
  store.catalog = [{ id: 'x/one', ...ROW }]
  const held = holdFirst(store, 'POST', '/models', b => b.id === 'x/one')
  const h = await mountPicker(store)
  await flush()
  const box = rowBox(h.tree, 'x/one')
  assert.ok(box)

  const p1 = box.props.onCheckedChange()
  const p2 = box.props.onCheckedChange() // rapid second tap while first in flight
  await flush()
  assert.equal(store.callsTo('POST', '/models').length, 1,
    'second tap while pending must not issue another request')
  assert.equal(errorBanner(h.tree), '', 'no spurious already-in-list banner')
  assert.equal(rowBox(h.tree, 'x/one').props.disabled, true,
    'honest pending state: row disabled while request in flight')

  held[0]()
  await p1
  await p2
  await flush()
  assert.equal(rowBox(h.tree, 'x/one').props.disabled, false, 'pending cleared after completion')
  assert.equal(store.entries.length, 1)
  assert.ok(textOf(h.tree).includes('1 selected'))
})

test('F11: a stale toggle handler decides from current state (no duplicate add re-add)', async () => {
  const store = new MockStore()
  store.catalog = [{ id: 'y/one', ...ROW }]
  const h = await mountPicker(store)
  await flush()
  const staleHandler = rowBox(h.tree, 'y/one').props.onCheckedChange

  await staleHandler() // add completes; component re-renders
  await flush()
  const adds = store.callsTo('POST', '/models').length
  const removes = store.callsTo('POST', '/remove').length

  await staleHandler() // rapid action using the snapshotted closure
  await flush()
  assert.equal(store.callsTo('POST', '/remove').length, removes + 1,
    'snapshotted handler must toggle OFF from current state')
  assert.equal(store.callsTo('POST', '/models').length, adds,
    'snapshotted handler must not re-add')
  assert.equal(errorBanner(h.tree), '')
  assert.equal(store.entries.length, 0)
})

test('F11: concurrent toggles on different rows both proceed', async () => {
  const store = new MockStore()
  store.catalog = [{ id: 'a/one', ...ROW }, { id: 'b/two', ...ROW }]
  const heldA = holdFirst(store, 'POST', '/models', b => b.id === 'a/one')
  const heldB = holdFirst(store, 'POST', '/models', b => b.id === 'b/two')
  const h = await mountPicker(store)
  await flush()
  const pA = rowBox(h.tree, 'a/one').props.onCheckedChange()
  const pB = rowBox(h.tree, 'b/two').props.onCheckedChange()
  await flush()
  assert.equal(store.callsTo('POST', '/models').length, 2, 'different rows are not serialized')
  heldA[0](); heldB[0]()
  await pA
  await pB
  await flush()
  assert.deepEqual(store.entries.map(e => e.id).sort(), ['a/one', 'b/two'])
  assert.ok(textOf(h.tree).includes('2 selected'))
})

// ── failure surfaces / pending hygiene ───────────────────────────────────

test('F11: failed add surfaces the actual failed request and clears pending', async () => {
  const store = new MockStore()
  store.catalog = [{ id: 'f/one', ...ROW }]
  store.intercept('POST', '/models', () => ({ error: 'quota exceeded' }),
    c => c.body && c.body.id === 'f/one')
  const h = await mountPicker(store)
  await flush()
  await rowBox(h.tree, 'f/one').props.onCheckedChange()
  await flush()
  const banner = errorBanner(h.tree)
  assert.ok(banner.includes('quota exceeded'), `actual error surfaced: ${banner}`)
  assert.ok(!rowBox(h.tree, 'f/one').props.disabled, 'pending cleared after failure')

  // retry works immediately — pending must not be stuck
  const before = store.callsTo('POST', '/models').length
  await rowBox(h.tree, 'f/one').props.onCheckedChange()
  await flush()
  assert.equal(store.callsTo('POST', '/models').length, before + 1, 'retry issues a new request')
  assert.equal(store.entries.length, 1)
})

test('F11: failed remove surfaces the actual failed request and keeps selection', async () => {
  const store = storeWith([{ id: 'r/one', description: 'R' }])
  store.catalog = [{ id: 'r/one', ...ROW }]
  store.intercept('POST', '/remove', () => ({ error: 'write lock timeout' }))
  const h = await mountPicker(store)
  await flush()
  await rowBox(h.tree, 'r/one').props.onCheckedChange()
  await flush()
  const banner = errorBanner(h.tree)
  assert.ok(banner.includes('write lock timeout'), `actual error surfaced: ${banner}`)
  assert.deepEqual(store.entries.map(e => e.id), ['r/one'], 'failed remove changes nothing')
  assert.ok(textOf(h.tree).includes('1 selected'), 'selection state unchanged on failure')
})

test('F11: accepted live composer invalidation still happens on add', async () => {
  const store = new MockStore()
  store.catalog = [{ id: 'c/one', ...ROW }]
  const h = await mountPicker(store)
  await flush()
  await rowBox(h.tree, 'c/one').props.onCheckedChange()
  await flush()
  assert.ok(composerInvalidations.some(a => a && a.queryKey && a.queryKey[0] === 'model-options'),
    'queryClient.invalidateQueries({queryKey:[model-options]}) preserved')
})

// ── file dialog + intervening user selection ─────────────────────────────

async function openImport(h) {
  const btn = findByAria(h.tree, 'Import list')
  assert.ok(btn, 'import button exists')
  await btn.props.onClick({ stopPropagation() {}, preventDefault() {} })
  await flush()
  const input = h.dom.lastFileInput()
  assert.ok(input, 'import opens a file dialog')
  return input
}

function fireFile(input, payload) {
  const json = typeof payload === 'string' ? payload : JSON.stringify(payload)
  return input.onchange({ target: { files: [{ text: async () => json }] } })
}

test('F11: import consults CURRENT state — id removed during dialog is re-added', async () => {
  const store = storeWith([{ id: 'a/one', description: 'A' }])
  store.catalog = [{ id: 'a/one', ...ROW }]
  const h = await mountPicker(store)
  await flush()
  const input = await openImport(h)

  // intervening user selection: remove a/one while the dialog is open
  await rowBox(h.tree, 'a/one').props.onCheckedChange()
  await flush()
  assert.equal(store.entries.length, 0)

  await fireFile(input, [{ id: 'a/one', description: 'A from file' }])
  assert.deepEqual(store.entries, [{ id: 'a/one', description: 'A from file' }],
    'import must consult current state, not the dialog-open snapshot')
  assert.ok(!errorBanner(h.tree).includes('already in list'))
})

test('F11: import consults CURRENT state — id added during dialog is not duplicated', async () => {
  const store = new MockStore()
  store.catalog = [{ id: 'b/one', ...ROW }]
  const h = await mountPicker(store)
  await flush()
  const input = await openImport(h)

  // intervening user selection: add b/one while the dialog is open
  await rowBox(h.tree, 'b/one').props.onCheckedChange()
  await flush()
  const addsAfterToggle = store.callsTo('POST', '/models').length

  await fireFile(input, [{ id: 'b/one', description: 'dup' }, { id: 'c/one', description: 'C' }])
  assert.equal(store.callsTo('POST', '/models').length, addsAfterToggle + 1,
    'no duplicate add for the just-toggled id')
  assert.deepEqual(store.entries.map(e => e.id).sort(), ['b/one', 'c/one'])
  assert.equal(errorBanner(h.tree), '', 'no already-in-list noise from stale snapshot')
})

// ── stale refresh ordering ───────────────────────────────────────────────

test('F11: stale curated refresh cannot clobber newer state (out-of-order fetches)', async () => {
  const store = new MockStore()
  const held = []
  const orig = store._handle.bind(store)
  store._handle = (m, p, b) => {
    if (m === 'GET' && p === '/models') {
      return new Promise(res => held.push(pl => res(pl)))
    }
    return orig(m, p, b)
  }
  const h = await mountPicker(store) // GET /models #1 (held)
  await flush()
  const input = await openImport(h)
  const done = fireFile(input, ['new/one']) // add + authoritative re-fetch GET #2 (held)
  await flush()
  const n = held.length
  assert.ok(n >= 2, `expected at least 2 curated fetches, got ${n}`)

  // resolve NEWEST first, then let the stale response land last
  for (let i = n - 1; i >= 0; i--) {
    held[i]({ models: [{ id: `seq/${i}`, description: `d${i}` }], count: 1 })
    await flush()
  }
  await done
  await flush()

  await findByAria(h.tree, 'Export list').props.onClick({ stopPropagation() {}, preventDefault() {} })
  const payload = JSON.parse(await h.dom.exportedText())
  assert.deepEqual(payload.map(e => e.id), [`seq/${n - 1}`],
    'the newest fetch wins; the stale response is discarded')
})

test('F11: stale catalog refresh cannot clobber newer rows (out-of-order fetches)', async () => {
  const store = new MockStore()
  store.catalog = [{ id: 'orig/model', ...ROW }]
  const held = []
  const orig = store._handle.bind(store)
  store._handle = (m, p, b) => {
    if (m === 'GET' && p.startsWith('/catalog')) {
      return new Promise(res => held.push(pl => res(pl)))
    }
    return orig(m, p, b)
  }
  const h = await mountPicker(store) // catalog fetch #1 (held)
  await flush()
  const sortSelect = findAll(h.tree, n => n.type === 'select-mock' && n.props.value === 'newest')[0]
  assert.ok(sortSelect, 'sort select rendered')
  sortSelect.props.onValueChange('most-popular') // fetch #2
  await flush()
  sortSelect.props.onValueChange('pricing-low-to-high') // fetch #3
  await flush()
  const n = held.length
  assert.equal(n, 3, `expected 3 catalog fetches, got ${n}`)

  for (let i = n - 1; i >= 0; i--) {
    held[i]({
      models: [{ id: `cat/${i}`, name: `C${i}`, provider: 'pco', prompt_price: 0, completion_price: 0, context_length: 1000 }],
      count: 1, providers: ['pco'], modalities: [],
    })
    await flush()
  }
  const t = textOf(h.tree)
  assert.ok(t.includes(`cat/${n - 1}`), 'newest catalog response rendered')
  assert.ok(!t.includes('cat/0'), 'stale catalog response discarded')
})

// ── changelog: failure / retry / no-changes distinction ──────────────────

async function openChangelog(h) {
  const btn = findAll(h.tree, n => n.type === 'button' && textOf(n).includes('Changelog'))[0]
  assert.ok(btn, 'changelog nav button exists')
  await btn.props.onClick({ stopPropagation() {}, preventDefault() {} })
  await flush()
}

test('F11: changelog fetch rejection shows the failure — not "No changes"', async () => {
  const store = new MockStore()
  store.intercept('GET', '/changelog', () => Promise.reject(new Error('gateway timeout')))
  const h = await mountPicker(store)
  await flush()
  await openChangelog(h)
  const t = textOf(h.tree)
  assert.ok(t.includes('gateway timeout'), `actual failure surfaced: ${t.slice(0, 300)}`)
  assert.ok(!t.includes('No changes since last check'), 'a failure must not masquerade as no-changes')
})

test('F11: changelog error-dict response shows the failure — not "No changes"', async () => {
  const store = new MockStore()
  store.intercept('GET', '/changelog', () => ({ error: 'changelog backend down' }))
  const h = await mountPicker(store)
  await flush()
  await openChangelog(h)
  const t = textOf(h.tree)
  assert.ok(t.includes('changelog backend down'), `actual failure surfaced: ${t.slice(0, 300)}`)
  assert.ok(!t.includes('No changes since last check'), 'an error response must not masquerade as no-changes')
})

test('F11: changelog retry re-fetches and then distinguishes no-changes from data', async () => {
  const store = new MockStore()
  store.intercept('GET', '/changelog', () => Promise.reject(new Error('boom')))
  const h = await mountPicker(store)
  await flush()
  await openChangelog(h)
  assert.ok(textOf(h.tree).includes('boom'))

  const retry = findAll(h.tree, n => n.type === 'button' && textOf(n).toLowerCase().includes('retry'))[0]
  assert.ok(retry, 'failure view offers a retry action')
  const fetches = store.callsTo('GET', '/changelog').length

  store.intercept('GET', '/changelog', () => ({
    total_added: 0, total_removed: 0, total_price_changed: 0,
    added: [], removed: [], price_changed: [], history: [], snapshot_size: 5,
  }))
  await retry.props.onClick({ stopPropagation() {}, preventDefault() {} })
  await flush()
  assert.equal(store.callsTo('GET', '/changelog').length, fetches + 1, 'retry re-fetches')
  const t = textOf(h.tree)
  assert.ok(t.includes('No changes since last check'), 'genuine empty success reads as no-changes')
  assert.ok(!t.includes('boom'), 'stale failure message cleared after successful retry')
})

test('F11: changelog success with data shows the changes', async () => {
  const store = new MockStore()
  store.intercept('GET', '/changelog', () => ({
    total_added: 1, total_removed: 0, total_price_changed: 0,
    added: [{ id: 'shiny/new', name: 'Shiny' }], removed: [], price_changed: [],
    history: [], snapshot_size: 12,
  }))
  const h = await mountPicker(store)
  await flush()
  await openChangelog(h)
  const t = textOf(h.tree)
  assert.ok(t.includes('shiny/new'), 'changes rendered')
  assert.ok(!t.includes('No changes since last check'))
})

// ── component cleanup ────────────────────────────────────────────────────

test('F11: unmount during in-flight toggle leaves no state updates / no stuck pending', async () => {
  const store = new MockStore()
  store.catalog = [{ id: 'u/one', ...ROW }]
  const held = holdFirst(store, 'POST', '/models', b => b.id === 'u/one')
  const h = await mountPicker(store)
  await flush()
  const p = rowBox(h.tree, 'u/one').props.onCheckedChange()
  await flush()
  h.root.unmount()
  held[0]() // response lands after unmount
  await p
  await flush()
  assert.deepEqual(h.violations, [], 'no setState after unmount')
})

test('F11: unmount during in-flight changelog fetch leaves no state updates', async () => {
  const store = new MockStore()
  const held = []
  const orig = store._handle.bind(store)
  store._handle = (m, p, b) => {
    if (m === 'GET' && p === '/changelog') {
      return new Promise(res => held.push(pl => res(pl)))
    }
    return orig(m, p, b)
  }
  const h = await mountPicker(store)
  await flush()
  await openChangelog(h)
  assert.equal(held.length, 1, 'changelog fetch issued')
  h.root.unmount()
  held[0]({ total_added: 0, total_removed: 0, total_price_changed: 0, added: [], removed: [], price_changed: [], history: [], snapshot_size: 0 })
  await flush()
  assert.deepEqual(h.violations, [], 'no setState after unmount')
})
