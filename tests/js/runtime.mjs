/**
 * Minimal-but-real React-compatible hook runtime + renderer for behavior tests.
 *
 * The shipped catalog/desktop/plugin.js is compiled JSX (calls to jsx/jsxs) with
 * useState/useEffect/useCallback/useMemo. This runtime executes those semantics
 * for real: per-instance hook slots, effect cleanup, functional state updates,
 * async handler flows and unmount detection (state updates after unmount are
 * recorded as violations so component-cleanup tests can assert on them).
 */

// ── element model (react/jsx-runtime shape) ──────────────────────────────
export function jsx(type, props, key) {
  const p = props ? { ...props } : {}
  const k = key !== undefined ? key : p.key
  if ('key' in p) delete p.key
  return { $$el: true, type, props: p, key: k }
}
export const jsxs = jsx

// ── runtime state ────────────────────────────────────────────────────────
export const violations = []
const instances = new Map()      // path -> instance
let visited = new Set()          // instances seen during the current render
let currentInstance = null
let pendingEffects = []          // {inst, slot, fn}
let dirty = false
let rendering = false
let rootElement = null
let lastTree = null
let alive = false

export function resetRuntime() {
  // run unmount cleanups for any live instances first
  for (const inst of instances.values()) unmountInstance(inst)
  instances.clear()
  violations.length = 0
  pendingEffects = []
  currentInstance = null
  dirty = false
  rendering = false
  rootElement = null
  lastTree = null
  alive = false
}

function unmountInstance(inst) {
  if (inst.unmounted) return
  inst.unmounted = true
  for (const slot of inst.hooks) {
    if (slot && slot.kind === 'effect' && typeof slot.cleanup === 'function') {
      try { slot.cleanup() } catch { /* cleanup must not throw into the runtime */ }
      slot.cleanup = null
    }
  }
}

function scheduleRender() {
  dirty = true
  if (rendering || !alive) return
  queueMicrotask(() => {
    if (dirty && alive) doRender()
  })
}

// ── hooks ────────────────────────────────────────────────────────────────
function hookSlot(kind) {
  const inst = currentInstance
  if (!inst) throw new Error(`${kind} called outside component render`)
  const i = inst.nextHook++
  if (inst.hooks.length === i) {
    inst.hooks.push({ kind })
  } else if (inst.hooks[i].kind !== kind) {
    throw new Error(`hook order changed in ${inst.name}: ${inst.hooks[i].kind} -> ${kind}`)
  }
  return inst.hooks[i]
}

function depsChanged(prev, next) {
  if (next === undefined) return true           // no dep array: always re-run
  if (prev === undefined) return true
  if (prev.length !== next.length) return true
  for (let i = 0; i < next.length; i++) {
    if (!Object.is(prev[i], next[i])) return true
  }
  return false
}

export function useState(initial) {
  const slot = hookSlot('state')
  if (slot.value === undefined && slot.setter === undefined) {
    slot.value = typeof initial === 'function' ? initial() : initial
  }
  if (!slot.setter) {
    const boundSlot = slot
    slot.setter = (v) => {
      const inst = boundSlot.inst
      if (!inst || inst.unmounted) {
        violations.push(`setState after unmount in ${inst ? inst.name : 'unknown'}`)
        return
      }
      boundSlot.value = typeof v === 'function' ? v(boundSlot.value) : v
      scheduleRender()
    }
  }
  slot.inst = currentInstance
  return [slot.value, slot.setter]
}

export function useRef(initial) {
  const slot = hookSlot('ref')
  if (!slot.ref) slot.ref = { current: initial }
  return slot.ref
}

export function useMemo(factory, deps) {
  const slot = hookSlot('memo')
  if (!slot.init || depsChanged(slot.deps, deps)) {
    slot.value = factory()
    slot.deps = deps
    slot.init = true
  }
  return slot.value
}

export function useCallback(fn, deps) {
  return useMemo(() => fn, deps)
}

export function useEffect(fn, deps) {
  const slot = hookSlot('effect')
  if (!slot.init || depsChanged(slot.deps, deps)) {
    pendingEffects.push({ inst: currentInstance, slot, fn })
    slot.deps = deps
    slot.init = true
  }
}

// ── renderer ─────────────────────────────────────────────────────────────
function childSlots(children) {
  const out = []
  const walk = (c, seg) => {
    if (Array.isArray(c)) {
      c.forEach((x, i) => walk(x, `${seg}.${i}`))
    } else {
      out.push({ el: c, seg })
    }
  }
  const emit = (x, seg) => {
    // keyed elements identify by key (React list semantics) so instance state
    // follows the row, not its current index
    if (x && typeof x === 'object' && x.$$el === true && x.key !== undefined) {
      out.push({ el: x, seg: `k:${x.key}` })
    } else {
      walk(x, seg)
    }
  }
  if (Array.isArray(children)) {
    children.forEach((x, i) => emit(x, String(i)))
  } else if (children !== undefined) {
    emit(children, '0')
  }
  return out
}

function renderElement(el, path) {
  if (el === null || el === undefined || el === false || el === true) return null
  if (typeof el === 'string' || typeof el === 'number') {
    return { type: '#text', text: String(el), children: [] }
  }
  if (!el || el.$$el !== true) {
    throw new Error(`not an element at ${path}: ${String(el && el.type)}`)
  }
  const key = el.key
  if (typeof el.type === 'function') {
    const instPath = `${path}#${el.type.name || 'anonymous'}`
    let inst = instances.get(instPath)
    if (!inst) {
      inst = {
        path: instPath, name: el.type.name || 'anonymous',
        hooks: [], nextHook: 0, unmounted: false,
      }
      instances.set(instPath, inst)
    }
    if (inst.unmounted) return null
    visited.add(instPath)
    inst.nextHook = 0
    const prev = currentInstance
    currentInstance = inst
    let out
    try {
      out = el.type(el.props)
    } finally {
      currentInstance = prev
    }
    return renderElement(out, instPath)
  }
  // host element
  const node = {
    type: el.type,
    props: el.props,
    key,
    children: [],
    path,
  }
  for (const { el: childEl, seg } of childSlots(el.props && el.props.children)) {
    const childNode = renderElement(childEl, `${path}>${seg}`)
    if (childNode) {
      childNode.parent = node
      node.children.push(childNode)
    }
  }
  return node
}

function doRender() {
  rendering = true
  dirty = false
  visited = new Set()
  const tree = renderElement(rootElement, '')
  // unmount instances that disappeared this pass
  for (const [path, inst] of [...instances.entries()]) {
    if (!visited.has(path)) {
      unmountInstance(inst)
      instances.delete(path)
    }
  }
  lastTree = tree
  // commit effects (skip effects whose instance unmounted during this pass)
  const effects = pendingEffects
  pendingEffects = []
  for (const { inst, slot, fn } of effects) {
    if (inst.unmounted) continue
    if (typeof slot.cleanup === 'function') {
      try { slot.cleanup() } catch { /* ignore */ }
      slot.cleanup = null
    }
    const ret = fn()
    if (typeof ret === 'function') slot.cleanup = ret
  }
  rendering = false
  if (dirty && alive) doRender()
}

export function createRoot(element) {
  resetRuntime()
  rootElement = element
  alive = true
  doRender()
  return {
    get tree() { return lastTree },
    get violations() { return violations },
    unmount() {
      alive = false
      for (const inst of instances.values()) unmountInstance(inst)
      instances.clear()
    },
  }
}

// ── tree helpers ─────────────────────────────────────────────────────────
export function findAll(node, pred, out = []) {
  if (!node) return out
  if (pred(node)) out.push(node)
  for (const c of node.children || []) findAll(c, pred, out)
  return out
}

export function textOf(node) {
  if (!node) return ''
  if (node.type === '#text') return node.text
  return (node.children || []).map(textOf).join('')
}
