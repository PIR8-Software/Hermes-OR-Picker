// Smoke: the harness must mount the shipped plugin and render rows.
import './register.mjs'
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  MockStore, mountPicker, flush, findAll, textOf, click, findByAria,
} from './harness.mjs'

test('smoke: mount renders rows and toggles work', async () => {
  const store = new MockStore()
  store.entries = [{ id: 'acme/one', description: 'first' }]
  store.catalog = [
    { id: 'acme/one', name: 'One', provider: 'acme', prompt_price: 1, completion_price: 2, context_length: 1000 },
    { id: 'beta/two', name: 'Two', provider: 'beta', prompt_price: 1, completion_price: 2, context_length: 1000 },
  ]
  const h = await mountPicker(store)
  await flush()
  const t = textOf(h.tree)
  assert.ok(t.includes('acme/one'), 'row id rendered: ' + t.slice(0, 200))
  assert.ok(t.includes('1 selected'), 'selected count rendered')
  const boxes = findAll(h.tree, n => n.type === 'checkbox-mock')
  assert.equal(boxes.length, 2)
  const cb = boxes.find(b => b.props.checked === true)
  assert.ok(cb, 'one checkbox is checked')
  // uncheck the selected one
  await cb.props.onCheckedChange()
  assert.equal(store.callsTo('POST', '/remove').length, 1)
  assert.equal(store.entries.length, 0)
})
