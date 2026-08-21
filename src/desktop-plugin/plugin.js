/**
 * OpenRouter Picker — desktop plugin for managing the supplemental model list.
 *
 * Shows the full OpenRouter catalog with a filter box.
 * Checkboxes toggle models in/out of the curated list.
 */

import { cn, host, Tip, useValue } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'
import { useState, useEffect, useCallback, useMemo, useRef } from 'react'

const ID = 'openrouter-picker'

// ── API helpers ────────────────────────────────────────────────────
async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } }
  if (body !== undefined) opts.body = JSON.stringify(body)
  const resp = await fetch(`/api/plugins/openrouter-picker${path}`, opts)
  return resp.json()
}

// ── Price display ──────────────────────────────────────────────────
function formatPrice(priceStr) {
  try {
    const pp = parseFloat(priceStr) * 1_000_000
    return pp === 0 ? 'free' : `$${pp.toFixed(2)}/M`
  } catch { return '' }
}

// ── Model Row (catalog) ────────────────────────────────────────────
function CatalogRow({ model, isSelected, onToggle }) {
  const ctx = model.context_length
  const ctxLabel = ctx ? `${Math.round(ctx / 1024)}K` : ''

  return jsxs('div', {
    className: cn(
      'flex items-center gap-2 px-2 py-1 rounded cursor-pointer transition-colors',
      'hover:bg-(--chrome-action-hover)',
      isSelected && 'bg-(--ui-accent-subtle, rgba(59,130,246,0.08))'
    ),
    onClick: () => onToggle(model.id, model.name),
    children: [
      // Checkbox
      jsx('div', {
        className: cn(
          'w-4 h-4 rounded border flex items-center justify-center shrink-0 transition-colors text-xs',
          isSelected
            ? 'bg-(--ui-accent) border-(--ui-accent) text-white'
            : 'border-(--ui-stroke-secondary) text-transparent'
        ),
        children: isSelected ? '✓' : ''
      }),
      // Model info
      jsxs('div', {
        className: 'flex-1 min-w-0',
        children: [
          jsx('div', {
            className: 'text-xs font-mono text-(--ui-text-primary) truncate',
            title: model.id,
            children: model.id
          }),
          model.name !== model.id && jsx('div', {
            className: 'text-[10px] text-(--ui-text-tertiary) truncate',
            children: model.name
          })
        ]
      }),
      // Metadata pills
      jsxs('div', {
        className: 'flex gap-1 shrink-0',
        children: [
          ctxLabel && jsx('span', {
            className: 'text-[10px] px-1 py-0.5 rounded bg-(--chrome-background-inset) text-(--ui-text-tertiary)',
            children: ctxLabel
          }),
          model.description && model.description.includes('$') && jsx('span', {
            className: 'text-[10px] px-1 py-0.5 rounded bg-(--chrome-background-inset) text-(--ui-text-tertiary)',
            children: model.description.split(' — ').pop()
          })
        ]
      })
    ]
  }, model.id)
}

// ── Main Pane ──────────────────────────────────────────────────────
function PickerPane() {
  const [catalog, setCatalog] = useState([])
  const [curatedIds, setCuratedIds] = useState(new Set())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('')
  const [freeOnly, setFreeOnly] = useState(false)
  const [sortBy, setSortBy] = useState('name') // name | ctx | price
  const filterRef = useRef(null)

  // Load catalog + curated list
  const load = useCallback(async () => {
    try {
      const [catData, modelsData] = await Promise.all([
        api('GET', '/catalog'),
        api('GET', '/models')
      ])
      if (catData.error) { setError(catData.error); return }
      if (modelsData.error) { setError(modelsData.error); return }

      setCatalog(catData.models || [])
      setCuratedIds(new Set((modelsData.models || []).map(m => m.id)))
    } catch (e) {
      setError(String(e))
    }
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  // Toggle a model in/out of curated list
  const toggle = useCallback(async (id, name) => {
    if (curatedIds.has(id)) {
      // Remove
      const data = await api('DELETE', `/models/${encodeURIComponent(id)}`)
      if (data.error) { setError(data.error); return }
      setCuratedIds(prev => { const next = new Set(prev); next.delete(id); return next })
    } else {
      // Add
      const data = await api('POST', '/models', { id, description: name || id })
      if (data.error) { setError(data.error); return }
      setCuratedIds(prev => new Set(prev).add(id))
    }
  }, [curatedIds])

  // Filter + sort the catalog
  const filtered = useMemo(() => {
    let list = catalog
    if (freeOnly) {
      list = list.filter(m => m.description.includes('free') || m.description.includes('$0.00'))
    }
    if (filter.trim()) {
      const q = filter.toLowerCase()
      list = list.filter(m =>
        m.id.toLowerCase().includes(q) ||
        m.name.toLowerCase().includes(q)
      )
    }
    if (sortBy === 'ctx') {
      list = [...list].sort((a, b) => (b.context_length || 0) - (a.context_length || 0))
    } else if (sortBy === 'name') {
      list = [...list].sort((a, b) => a.id.localeCompare(b.id))
    }
    return list
  }, [catalog, filter, freeOnly, sortBy])

  const selectedCount = curatedIds.size

  return jsxs('div', {
    className: 'flex h-full flex-col text-sm',
    children: [
      // Header
      jsxs('div', {
        className: 'flex items-center justify-between px-3 py-2 border-b border-(--ui-stroke-secondary)',
        children: [
          jsx('span', { className: 'font-medium', children: 'OpenRouter Picker' }),
          jsx('span', {
            className: 'text-xs text-(--ui-text-tertiary)',
            children: `${selectedCount} selected`
          })
        ]
      }),

      // Error
      error && jsx('div', {
        className: 'px-3 py-1 text-xs text-red-400 bg-red-400/10',
        children: error
      }),

      // Filter bar
      jsxs('div', {
        className: 'px-3 py-2 flex flex-col gap-1.5 border-b border-(--ui-stroke-secondary)',
        children: [
          jsx('input', {
            ref: filterRef,
            type: 'text',
            value: filter,
            onChange: e => setFilter(e.target.value),
            placeholder: 'Filter models…',
            className: 'w-full text-xs px-2.5 py-1.5 rounded border border-(--ui-stroke-secondary) bg-(--chrome-background) text-(--ui-text-primary) placeholder:text-(--ui-text-quaternary)'
          }),
          jsxs('div', {
            className: 'flex gap-1.5 items-center',
            children: [
              // Free only toggle
              jsx('button', {
                onClick: () => setFreeOnly(!freeOnly),
                className: cn(
                  'text-[10px] px-2 py-0.5 rounded transition-colors',
                  freeOnly
                    ? 'bg-(--ui-accent) text-white'
                    : 'bg-(--chrome-background-inset) text-(--ui-text-tertiary) hover:text-(--ui-text-primary)'
                ),
                children: 'Free only'
              }),
              // Sort buttons
              jsx('span', { className: 'text-[10px] text-(--ui-text-quaternary)', children: 'Sort:' }),
              ...['name', 'ctx'].map(s => jsx('button', {
                key: s,
                onClick: () => setSortBy(s),
                className: cn(
                  'text-[10px] px-1.5 py-0.5 rounded transition-colors',
                  sortBy === s
                    ? 'bg-(--ui-accent) text-white'
                    : 'text-(--ui-text-tertiary) hover:text-(--ui-text-primary)'
                ),
                children: s === 'name' ? 'A-Z' : 'Context'
              }))
            ]
          })
        ]
      }),

      // Model list
      loading
        ? jsx('div', { className: 'flex-1 flex items-center justify-center text-(--ui-text-quaternary)', children: 'Loading catalog…' })
        : filtered.length === 0
          ? jsx('div', {
              className: 'flex-1 flex items-center justify-center text-(--ui-text-quaternary) text-xs',
              children: catalog.length === 0 ? 'Failed to load catalog' : 'No models match filter'
            })
          : jsx('div', {
              className: 'flex-1 overflow-y-auto py-1',
              children: filtered.map(m => jsx(CatalogRow, {
                key: m.id,
                model: m,
                isSelected: curatedIds.has(m.id),
                onToggle: toggle
              }))
            }),

      // Footer
      jsx('div', {
        className: 'px-3 py-1.5 text-[10px] text-(--ui-text-quaternary) border-t border-(--ui-stroke-secondary) flex justify-between',
        children: [
          jsx('span', { children: `${filtered.length} of ${catalog.length} shown` }),
          jsx('span', { children: `${selectedCount} selected` })
        ]
      })
    ]
  })
}

// ── Statusbar Chip ─────────────────────────────────────────────────
function PickerChip() {
  return jsx(Tip, {
    label: 'OpenRouter Picker — manage your model list',
    children: jsx('button', {
      className: cn(
        'inline-flex h-full items-center gap-1 px-1.5 text-[0.6875rem] transition-colors',
        'text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover) hover:text-foreground'
      ),
      type: 'button',
      onClick: () => host.navigate('/openrouter-picker'),
      children: '⬡ OR Picker'
    })
  })
}

export default {
  id: ID,
  name: 'OpenRouter Picker',
  defaultEnabled: false,
  register(ctx) {
    ctx.register({
      id: 'pane',
      area: 'panes',
      title: 'OR Picker',
      data: { placement: 'right', width: '320px' },
      render: () => jsx(PickerPane, {})
    })

    ctx.register({
      id: 'chip',
      area: 'statusBar.right',
      order: 140,
      render: () => jsx(PickerChip, {})
    })
  }
}
