/**
 * OpenRouter Picker — desktop plugin for managing the supplemental model list.
 *
 * Full catalog browser with OpenRouter's filter/sort options.
 * Checkboxes toggle models in/out of the curated list.
 */

import { cn, host, Tip, useValue } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'
import { useState, useEffect, useCallback, useMemo, useRef } from 'react'

const ID = 'openrouter-picker'

// ── API ────────────────────────────────────────────────────────────
async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } }
  if (body !== undefined) opts.body = JSON.stringify(body)
  const resp = await fetch(`/api/plugins/openrouter-picker${path}`, opts)
  return resp.json()
}

// ── Sort options (from OpenRouter API docs) ────────────────────────
const SORT_OPTIONS = [
  { value: 'newest', label: 'Newest' },
  { value: 'most-popular', label: 'Most Popular' },
  { value: 'pricing-low-to-high', label: 'Price ↑' },
  { value: 'pricing-high-to-low', label: 'Price ↓' },
  { value: 'context-high-to-low', label: 'Context ↓' },
  { value: 'throughput-high-to-low', label: 'Speed ↓' },
  { value: 'latency-low-to-high', label: 'Latency ↑' },
  { value: 'intelligence-high-to-low', label: 'Intelligence ↓' },
  { value: 'coding-high-to-low', label: 'Coding ↓' },
  { value: 'agentic-high-to-low', label: 'Agentic ↓' },
]

// ── Model Row ──────────────────────────────────────────────────────
function CatalogRow({ model, isSelected, onToggle }) {
  const ctx = model.context_length
  const ctxLabel = ctx >= 1_000_000
    ? `${(ctx / 1_000_000).toFixed(1)}M`
    : ctx >= 1024
      ? `${Math.round(ctx / 1024)}K`
      : ctx || ''

  const formatPrice = (p) => p === 0 ? 'free' : `$${p.toFixed(2)}`

  return jsxs('div', {
    className: cn(
      'flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer transition-colors',
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
          jsxs('div', {
            className: 'flex items-center gap-1.5',
            children: [
              jsx('span', {
                className: 'text-xs font-mono text-(--ui-text-primary) truncate',
                title: model.id,
                children: model.id
              }),
              model.variant === 'free' && jsx('span', {
                className: 'text-[9px] px-1 py-0.5 rounded bg-green-500/15 text-green-400 font-medium',
                children: 'FREE'
              }),
              model.variant === 'batch' && jsx('span', {
                className: 'text-[9px] px-1 py-0.5 rounded bg-blue-500/15 text-blue-400 font-medium',
                children: 'BATCH'
              })
            ]
          }),
          model.name !== model.id && jsx('div', {
            className: 'text-[10px] text-(--ui-text-tertiary) truncate',
            children: model.name
          })
        ]
      }),
      // Metadata pills
      jsxs('div', {
        className: 'flex gap-1 shrink-0 items-center',
        children: [
          // Output modality badges
          ...(model.output_modalities || []).filter(m => m !== 'text').map(m =>
            jsx('span', {
              key: m,
              className: 'text-[9px] px-1 py-0.5 rounded bg-(--chrome-background-inset) text-(--ui-text-tertiary) capitalize',
              children: m
            }, m)
          ),
          ctxLabel && jsx('span', {
            className: 'text-[10px] px-1 py-0.5 rounded bg-(--chrome-background-inset) text-(--ui-text-tertiary)',
            children: ctxLabel
          }),
          model.prompt_price > 0 && jsx('span', {
            className: 'text-[10px] px-1 py-0.5 rounded bg-(--chrome-background-inset) text-(--ui-text-tertiary)',
            children: `${formatPrice(model.prompt_price)}/${formatPrice(model.completion_price)}`
          }),
          model.prompt_price === 0 && jsx('span', {
            className: 'text-[10px] px-1 py-0.5 rounded bg-green-500/10 text-green-400/70',
            children: 'free'
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
  const [providers, setProviders] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [loadingCatalog, setLoadingCatalog] = useState(false)

  // Filter state
  const [filter, setFilter] = useState('')
  const [sort, setSort] = useState('newest')
  const [freeOnly, setFreeOnly] = useState(false)
  const [selectedOnly, setSelectedOnly] = useState(false)
  const [providerFilter, setProviderFilter] = useState('')
  const [minContext, setMinContext] = useState(0)
  const [modalityFilter, setModalityFilter] = useState('') // '' = all, 'text', 'image', etc.
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [showProviders, setShowProviders] = useState(false)

  // Load curated list
  const loadCurated = useCallback(async () => {
    try {
      const data = await api('GET', '/models')
      setCuratedIds(new Set((data.models || []).map(m => m.id)))
    } catch (e) { setError(String(e)) }
  }, [])

  // Load catalog with server-side filters
  const loadCatalog = useCallback(async () => {
    setLoadingCatalog(true)
    try {
      const params = new URLSearchParams()
      if (sort) params.set('sort', sort)
      if (modalityFilter) params.set('output_modalities', modalityFilter)
      if (minContext > 0) params.set('min_context_length', String(minContext))

      const qs = params.toString()
      const data = await api('GET', `/catalog${qs ? '?' + qs : ''}`)
      if (data.error) { setError(data.error); return }
      setCatalog(data.models || [])
      setProviders(data.providers || [])
    } catch (e) {
      setError(String(e))
    }
    setLoading(false)
    setLoadingCatalog(false)
  }, [sort, modalityFilter, minContext])

  useEffect(() => { loadCurated() }, [loadCurated])
  useEffect(() => { loadCatalog() }, [loadCatalog])

  // Toggle model
  const toggle = useCallback(async (id, name) => {
    if (curatedIds.has(id)) {
      const data = await api('DELETE', `/models/${encodeURIComponent(id)}`)
      if (data.error) { setError(data.error); return }
      setCuratedIds(prev => { const next = new Set(prev); next.delete(id); return next })
    } else {
      const data = await api('POST', '/models', { id, description: name || id })
      if (data.error) { setError(data.error); return }
      setCuratedIds(prev => new Set(prev).add(id))
    }
  }, [curatedIds])

  // Client-side filtering
  const filtered = useMemo(() => {
    let list = catalog
    if (freeOnly) list = list.filter(m => m.variant === 'free' || m.prompt_price === 0)
    if (selectedOnly) list = list.filter(m => curatedIds.has(m.id))
    if (providerFilter) list = list.filter(m => m.provider === providerFilter)
    if (filter.trim()) {
      const q = filter.toLowerCase()
      list = list.filter(m =>
        m.id.toLowerCase().includes(q) ||
        m.name.toLowerCase().includes(q) ||
        m.provider.toLowerCase().includes(q)
      )
    }
    return list
  }, [catalog, filter, freeOnly, selectedOnly, providerFilter, curatedIds])

  const selectedCount = curatedIds.size

  return jsxs('div', {
    className: 'flex h-full flex-col text-sm',
    children: [
      // Header
      jsxs('div', {
        className: 'flex items-center justify-between px-3 py-2 border-b border-(--ui-stroke-secondary)',
        children: [
          jsx('span', { className: 'font-medium', children: 'OpenRouter Picker' }),
          jsxs('div', {
            className: 'flex items-center gap-2',
            children: [
              loadingCatalog && jsx('span', {
                className: 'text-[10px] text-(--ui-text-quaternary)',
                children: '⟳'
              }),
              jsx('span', {
                className: 'text-xs text-(--ui-text-tertiary)',
                children: `${selectedCount} selected`
              })
            ]
          })
        ]
      }),

      // Error
      error && jsx('div', {
        className: 'px-3 py-1 text-xs text-red-400 bg-red-400/10 cursor-pointer',
        onClick: () => setError(''),
        children: `⚠ ${error}`
      }),

      // ── Filter Controls ──
      jsxs('div', {
        className: 'px-3 py-2 flex flex-col gap-1.5 border-b border-(--ui-stroke-secondary)',
        children: [
          // Search box
          jsx('input', {
            type: 'text',
            value: filter,
            onChange: e => setFilter(e.target.value),
            placeholder: 'Filter models…',
            className: 'w-full text-xs px-2.5 py-1.5 rounded border border-(--ui-stroke-secondary) bg-(--chrome-background) text-(--ui-text-primary) placeholder:text-(--ui-text-quaternary)'
          }),

          // Sort dropdown
          jsxs('div', {
            className: 'flex gap-1.5 items-center',
            children: [
              jsx('span', { className: 'text-[10px] text-(--ui-text-quaternary) shrink-0', children: 'Sort' }),
              jsx('select', {
                value: sort,
                onChange: e => setSort(e.target.value),
                className: 'flex-1 text-[10px] px-1.5 py-0.5 rounded border border-(--ui-stroke-secondary) bg-(--chrome-background) text-(--ui-text-primary)',
                children: SORT_OPTIONS.map(o => jsx('option', { key: o.value, value: o.value, children: o.label }))
              })
            ]
          }),

          // Quick toggles
          jsxs('div', {
            className: 'flex gap-1 flex-wrap',
            children: [
              jsx('button', {
                onClick: () => setFreeOnly(!freeOnly),
                className: cn(
                  'text-[10px] px-2 py-0.5 rounded transition-colors',
                  freeOnly ? 'bg-green-500/20 text-green-400' : 'bg-(--chrome-background-inset) text-(--ui-text-tertiary) hover:text-(--ui-text-primary)'
                ),
                children: 'Free'
              }),
              jsx('button', {
                onClick: () => setSelectedOnly(!selectedOnly),
                className: cn(
                  'text-[10px] px-2 py-0.5 rounded transition-colors',
                  selectedOnly ? 'bg-(--ui-accent) text-white' : 'bg-(--chrome-background-inset) text-(--ui-text-tertiary) hover:text-(--ui-text-primary)'
                ),
                children: `Selected (${selectedCount})`
              }),
              jsx('button', {
                onClick: () => setShowProviders(!showProviders),
                className: cn(
                  'text-[10px] px-2 py-0.5 rounded transition-colors',
                  providerFilter ? 'bg-(--ui-accent) text-white' : 'bg-(--chrome-background-inset) text-(--ui-text-tertiary) hover:text-(--ui-text-primary)'
                ),
                children: providerFilter || 'Provider'
              }),
              jsx('button', {
                onClick: () => setShowAdvanced(!showAdvanced),
                className: cn(
                  'text-[10px] px-2 py-0.5 rounded transition-colors',
                  showAdvanced ? 'bg-(--ui-accent) text-white' : 'bg-(--chrome-background-inset) text-(--ui-text-tertiary) hover:text-(--ui-text-primary)'
                ),
                children: '▸ Advanced'
              })
            ]
          }),

          // Provider dropdown
          showProviders && jsx('div', {
            className: 'flex gap-1.5 items-center',
            children: [
              jsx('select', {
                value: providerFilter,
                onChange: e => { setProviderFilter(e.target.value); setShowProviders(false) },
                className: 'flex-1 text-[10px] px-1.5 py-0.5 rounded border border-(--ui-stroke-secondary) bg-(--chrome-background) text-(--ui-text-primary)',
                children: [
                  jsx('option', { key: '', value: '', children: 'All providers' }),
                  ...providers.map(p => jsx('option', { key: p, value: p, children: p }))
                ]
              }),
              providerFilter && jsx('button', {
                onClick: () => setProviderFilter(''),
                className: 'text-[10px] px-1 text-(--ui-text-quaternary) hover:text-(--ui-text-primary)',
                children: '✕'
              })
            ]
          }),

          // Advanced filters
          showAdvanced && jsxs('div', {
            className: 'flex flex-col gap-1.5 pt-1 border-t border-(--ui-stroke-secondary)',
            children: [
              // Modality
              jsxs('div', {
                className: 'flex gap-1.5 items-center',
                children: [
                  jsx('span', { className: 'text-[10px] text-(--ui-text-quaternary) shrink-0', children: 'Output' }),
                  jsx('select', {
                    value: modalityFilter,
                    onChange: e => setModalityFilter(e.target.value),
                    className: 'flex-1 text-[10px] px-1.5 py-0.5 rounded border border-(--ui-stroke-secondary) bg-(--chrome-background) text-(--ui-text-primary)',
                    children: [
                      jsx('option', { key: '', value: '', children: 'All modalities' }),
                      jsx('option', { key: 'text', value: 'text', children: 'Text' }),
                      jsx('option', { key: 'image', value: 'image', children: 'Image' }),
                      jsx('option', { key: 'text,image', value: 'text,image', children: 'Text + Image' }),
                      jsx('option', { key: 'text,audio', value: 'text,audio', children: 'Text + Audio' }),
                    ]
                  })
                ]
              }),
              // Min context
              jsxs('div', {
                className: 'flex gap-1.5 items-center',
                children: [
                  jsx('span', { className: 'text-[10px] text-(--ui-text-quaternary) shrink-0', children: 'Min Ctx' }),
                  jsx('select', {
                    value: String(minContext),
                    onChange: e => setMinContext(Number(e.target.value)),
                    className: 'flex-1 text-[10px] px-1.5 py-0.5 rounded border border-(--ui-stroke-secondary) bg-(--chrome-background) text-(--ui-text-primary)',
                    children: [
                      jsx('option', { key: '0', value: '0', children: 'Any' }),
                      jsx('option', { key: '8192', value: '8192', children: '8K+' }),
                      jsx('option', { key: '32768', value: '32768', children: '32K+' }),
                      jsx('option', { key: '131072', value: '131072', children: '128K+' }),
                      jsx('option', { key: '262144', value: '262144', children: '256K+' }),
                      jsx('option', { key: '524288', value: '524288', children: '512K+' }),
                      jsx('option', { key: '1048576', value: '1048576', children: '1M+' }),
                    ]
                  })
                ]
              })
            ]
          })
        ]
      }),

      // ── Model List ──
      loading
        ? jsx('div', { className: 'flex-1 flex items-center justify-center text-(--ui-text-quaternary)', children: 'Loading catalog…' })
        : filtered.length === 0
          ? jsx('div', {
              className: 'flex-1 flex items-center justify-center text-(--ui-text-quaternary) text-xs',
              children: catalog.length === 0 ? 'Failed to load catalog' : 'No models match filters'
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
      data: { placement: 'right', width: '340px' },
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
