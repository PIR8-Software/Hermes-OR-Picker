/**
 * Behavior-test harness for the shipped OR Picker desktop plugin.
 *
 * Provides:
 *  - a mock host API (ctx.rest) backed by a tiny in-memory store that mirrors
 *    the backend contract ({id, description} entries, "already in list",
 *    "not found", invalid-id errors), with per-call deferred control so tests
 *    can interleave responses and simulate slow/failed requests;
 *  - DOM stubs (document.createElement input/a, Blob, URL) sufficient for the
 *    export/import buttons to run their real code paths;
 *  - click/find helpers over the rendered tree.
 */
import { createRoot, findAll, textOf, jsx } from './runtime.mjs'
import { composerInvalidations, host } from './stubs/plugin-sdk.mjs'

// Resolved before the DOM stubs replace globalThis.URL.
export const PLUGIN_URL = new URL('../../catalog/desktop/plugin.js', import.meta.url).href

// ── deferred ─────────────────────────────────────────────────────────────
export function deferred() {
  let resolve, reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

// ── DOM stubs (global) ───────────────────────────────────────────────────
export function installDomStubs() {
  const created = []
  const blobs = []
  const revoked = []
  const urlMap = new Map()
  let urlSeq = 0

  globalThis.Blob = class Blob {
    constructor(parts, opts) {
      this.parts = parts
      this.type = (opts && opts.type) || ''
    }
    async text() { return this.parts.map(String).join('') }
  }

  const URLStub = {
    createObjectURL(blob) {
      const u = `blob:mock/${++urlSeq}`
      urlMap.set(u, blob)
      blobs.push(blob)
      return u
    },
    revokeObjectURL(u) { revoked.push(u) },
  }
  globalThis.URL = URLStub

  globalThis.document = {
    createElement(tag) {
      const el = {
        tag,
        type: '', accept: '', href: '', download: '', onchange: null,
        clicked: 0,
        click() {
          this.clicked += 1
          // file input: nothing happens until the test drives onchange
        },
      }
      created.push(el)
      return el
    },
    _created: created,
  }

  globalThis.localStorage = {
    _m: new Map(),
    getItem(k) { return this._m.has(k) ? this._m.get(k) : null },
    setItem(k, v) { this._m.set(k, String(v)) },
    removeItem(k) { this._m.delete(k) },
  }

  return {
    created, blobs, revoked, urlMap,
    lastFileInput: () => created.filter(e => e.tag === 'input').at(-1),
    lastAnchor: () => created.filter(e => e.tag === 'a').at(-1),
    async exportedText() {
      const a = created.filter(e => e.tag === 'a').at(-1)
      if (!a) throw new Error('no export anchor created')
      const blob = urlMap.get(a.href)
      if (!blob) throw new Error(`export anchor href ${a.href} has no captured blob`)
      return blob.text()
    },
  }
}

// ── mock host API ────────────────────────────────────────────────────────
const VALID_ID = /^~?[A-Za-z0-9_.-]+\/[A-Za-z0-9_.:/-]+$/
export function validId(mid) {
  return typeof mid === 'string' && !mid.includes('..') && !mid.includes('//') && VALID_ID.test(mid)
}

export class MockStore {
  constructor() {
    this.entries = []   // [{id, description}] in stored order
    this.catalog = []   // synthetic catalog models for row-level tests
    this.calls = []     // {method, path, body} in order
    this.hooks = []     // per-route interceptors
  }

  /**
   * Queue a one-shot interceptor for calls matching method+path prefix (and an
   * optional predicate over the call). fn may return a value or a promise.
   */
  intercept(method, pathPrefix, fn, when = null) {
    this.hooks.push({ method, pathPrefix, fn, when, used: false })
  }

  /** All calls matching method (+ optional path prefix), in order. */
  callsTo(method, pathPrefix = '') {
    return this.calls.filter(c => c.method === method && c.path.startsWith(pathPrefix))
  }

  _handle(method, path, body) {
    if (method === 'GET' && path === '/models') {
      return { models: this.entries.map(e => ({ ...e })), count: this.entries.length }
    }
    if (method === 'POST' && path === '/models') {
      const id = body && typeof body.id === 'string' ? body.id.trim() : ''
      // mirrors add_model/_add_id: explicit description strings are stored
      // verbatim (no trim); omitted/null fall back to the id (review 2810)
      const raw = body ? body.description : undefined
      if (raw !== undefined && raw !== null && typeof raw !== 'string') {
        return { error: 'description must be a string or omitted' }
      }
      if (!id) return { error: 'id required' }
      if (!validId(id)) return { error: `Invalid model ID format: ${id}` }
      if (this.entries.some(e => e.id === id)) return { error: `Model ${id} already in list` }
      this.entries.push({ id, description: typeof raw === 'string' ? raw : id })
      return { ok: true, added: id, count: this.entries.length }
    }
    if (method === 'POST' && path === '/remove') {
      const id = body && typeof body.id === 'string' ? body.id.trim() : ''
      const before = this.entries.length
      this.entries = this.entries.filter(e => e.id !== id)
      if (this.entries.length === before) return { error: `Model ${id} not found` }
      return { ok: true, removed: id, count: this.entries.length }
    }
    if (method === 'GET' && path.startsWith('/catalog')) {
      return {
        models: this.catalog.map(m => ({ ...m })),
        count: this.catalog.length,
        providers: [...new Set(this.catalog.map(m => m.provider).filter(Boolean))],
        modalities: [],
      }
    }
    if (method === 'GET' && path === '/blog') return { posts: [] }
    if (method === 'GET' && path === '/credits') return { remaining: 4.2 }
    if (method === 'GET' && path === '/default-models') return { ids: [] }
    if (method === 'GET' && path === '/changelog') {
      return {
        total_added: 0, total_removed: 0, total_price_changed: 0,
        added: [], removed: [], price_changed: [], history: [], snapshot_size: 0,
      }
    }
    return { error: `unmocked ${method} ${path}` }
  }

  makeCtx() {
    const store = this
    return {
      rest(path, opts = {}) {
        const method = opts.method || 'GET'
        const body = opts.body
        store.calls.push({ method, path, body })
        const hook = store.hooks.find(h =>
          !h.used && h.method === method && path.startsWith(h.pathPrefix) &&
          (!h.when || h.when({ method, path, body })))
        if (hook) {
          hook.used = true
          return Promise.resolve().then(() => hook.fn({ method, path, body, store }))
        }
        return Promise.resolve(store._handle(method, path, body))
      },
    }
  }
}

/** Store pre-loaded with the given [{id, description}] entries in order. */
export function storeWith(entries) {
  const s = new MockStore()
  s.entries = entries.map(e => ({ ...e }))
  return s
}

// ── render + interaction helpers ─────────────────────────────────────────
export function mount(renderFn) {
  const root = createRoot(renderFn)
  return {
    root,
    get tree() { return root.tree },
    get violations() { return root.violations },
  }
}

export function findButtons(tree) {
  return findAll(tree, n => n.type === 'button')
}

export function buttonByText(tree, text) {
  return findButtons(tree).find(b => textOf(b).includes(text))
}

export function findByAria(tree, label) {
  return findAll(tree, n => n.props && n.props['aria-label'] === label)[0]
}

export async function flush(rounds = 20) {
  for (let i = 0; i < rounds; i++) {
    await new Promise(r => setTimeout(r, 0))
  }
}

/** Click a node's onClick handler and flush microtasks/timers. */
export async function click(node, event = {}) {
  if (!node || !node.props || typeof node.props.onClick !== 'function') {
    throw new Error('node has no onClick')
  }
  const e = { stopPropagation() {}, preventDefault() {}, ...event }
  const r = node.props.onClick(e)
  if (r && typeof r.then === 'function') await r
  await flush()
  return r
}

export { findAll, textOf, jsx }

/**
 * Mount the shipped PickerPage through the plugin's real registration surface:
 * plugin.default.register(ctx) -> registered page item -> render(). This runs
 * the actual artifact code path, not a test copy.
 */
export async function mountPicker(store) {
  const dom = installDomStubs()
  composerInvalidations.length = 0
  host.navigations.length = 0
  const ctx = store.makeCtx()
  const registered = []
  ctx.registerMany = (items) => { registered.push(...items) }
  const mod = await import(PLUGIN_URL)
  mod.default.register(ctx)
  const page = registered.find(r => r.id === 'page')
  if (!page) throw new Error('plugin registered no page item')
  const root = createRoot(page.render())
  return { root, ctx, dom, store, get tree() { return root.tree }, get violations() { return root.violations } }
}

/** Locate a catalog row's checkbox mock node by model id text in its row. */
export function rowCheckboxForId(tree, modelId) {
  const rows = findAll(tree, n => n.type === 'checkbox-mock')
  for (const cb of rows) {
    // walk up to the row container and look for the id text among siblings
    let node = cb.parent
    for (let up = 0; node && up < 4; up++, node = node.parent) {
      if (textOf(node).includes(modelId)) return cb
    }
  }
  return null
}
