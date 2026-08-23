/**
 * OpenRouter Picker — full catalog browser with all model details.
 *
 * Shows every field the OpenRouter API returns: pricing, benchmarks,
 * context, modality, reasoning, capabilities, etc.
 */

import {
  cn, host,
  ROUTES_AREA, SIDEBAR_NAV_AREA, PALETTE_AREA,
  Checkbox,
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
  queryClient,
} from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'
import { useState, useEffect, useCallback, useMemo } from 'react'

const ID = 'openrouter-picker'
const PAGE = '/openrouter-picker'

async function api(ctx, method, path, body) {
  const opts = { method, timeoutMs: 30000 }
  if (body !== undefined) opts.body = body
  return ctx.rest(path, opts)
}

function refreshComposerPicker() {
  try {
    queryClient.invalidateQueries({ queryKey: ['model-options'] })
  } catch {}
}

function UiSelect({ value, onChange, options, className }) {
  return jsxs(Select, {
    value,
    onValueChange: onChange,
    children: [
      jsx(SelectTrigger, {
        className: cn('h-8 min-w-0 flex-1 text-xs', className),
        children: jsx(SelectValue, {})
      }),
      jsx(SelectContent, {
        children: options.map(o => jsx(SelectItem, { value: o.value, children: o.label }, o.value))
      })
    ]
  })
}

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

const MODALITY_OPTIONS = [
  { value: 'all', label: 'All modalities' },
  { value: 'text', label: 'Text' },
  { value: 'image', label: 'Image' },
  { value: 'text,image', label: 'Text + Image' },
  { value: 'text,audio', label: 'Text + Audio' },
]

const CONTEXT_OPTIONS = [
  { value: '0', label: 'Any context' },
  { value: '8192', label: '8K+' },
  { value: '32768', label: '32K+' },
  { value: '131072', label: '128K+' },
  { value: '262144', label: '256K+' },
  { value: '524288', label: '512K+' },
  { value: '1048576', label: '1M+' },
]

function formatCtx(ctx) {
  if (!ctx) return '—'
  if (ctx >= 1_000_000) return `${(ctx / 1_000_000).toFixed(1)}M`
  if (ctx >= 1024) return `${Math.round(ctx / 1024)}K`
  return String(ctx)
}

function formatPrice(p) {
  if (p === undefined || p === null) return null
  if (p === 0) return 'free'
  if (p < 0.01) return `$${p.toFixed(4)}`
  return `$${p.toFixed(2)}`
}

function Pill({ children, color, title }) {
  return jsx('span', {
    className: cn(
      'text-[10px] px-1.5 py-0.5 rounded font-medium',
      color === 'green' && 'bg-green-500/15 text-green-400',
      color === 'blue' && 'bg-blue-500/15 text-blue-400',
      color === 'yellow' && 'bg-yellow-500/15 text-yellow-400',
      color === 'red' && 'bg-red-500/15 text-red-400',
      color === 'purple' && 'bg-purple-500/15 text-purple-400',
      !color && 'bg-(--chrome-background-inset) text-(--ui-text-tertiary)',
    ),
    title,
    children
  })
}

function ScoreBar({ value, max = 100, label }) {
  if (value == null) return null
  const pct = Math.min(100, (value / max) * 100)
  const color = pct >= 70 ? 'bg-green-500' : pct >= 40 ? 'bg-yellow-500' : 'bg-red-500'
  return jsxs('div', {
    className: 'flex items-center gap-1',
    children: [
      jsx('span', { className: 'text-[10px] text-(--ui-text-quaternary) w-8 shrink-0', children: label }),
      jsx('div', {
        className: 'flex-1 h-1 rounded bg-(--chrome-background-inset) overflow-hidden',
        children: jsx('div', { className: `h-full rounded ${color}`, style: { width: `${pct}%` } })
      }),
      jsx('span', { className: 'text-[10px] text-(--ui-text-tertiary) w-6 text-right shrink-0', children: String(value) })
    ]
  })
}

function ModelDetails({ m }) {
  const pp = formatPrice(m.prompt_price)
  const cp = formatPrice(m.completion_price)
  const cacheR = formatPrice(m.cache_read_price)
  const cacheW = formatPrice(m.cache_write_price)
  const img = formatPrice(m.image_price)
  const audio = formatPrice(m.audio_price)
  const reasoning = formatPrice(m.reasoning_price)
  const ws = m.web_search_price

  return jsxs('div', {
    className: 'px-2 py-1.5 text-xs space-y-1 border-t border-(--ui-stroke-secondary)',
    children: [
      m.description && jsx('div', {
        className: 'text-(--ui-text-tertiary) leading-relaxed',
        children: m.description
      }),
      jsxs('div', {
        className: 'grid grid-cols-2 gap-x-3 gap-y-0.5',
        children: [
          jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'Input /M' }),
          jsx('span', { className: 'text-(--ui-text-primary) font-mono', children: pp || '—' }),
          jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'Output /M' }),
          jsx('span', { className: 'text-(--ui-text-primary) font-mono', children: cp || '—' }),
          cacheR && jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'Cache read /M' }),
          cacheR && jsx('span', { className: 'text-(--ui-text-primary) font-mono', children: cacheR }),
          cacheW && jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'Cache write /M' }),
          cacheW && jsx('span', { className: 'text-(--ui-text-primary) font-mono', children: cacheW }),
          img && jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'Image /M' }),
          img && jsx('span', { className: 'text-(--ui-text-primary) font-mono', children: img }),
          audio && jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'Audio /M' }),
          audio && jsx('span', { className: 'text-(--ui-text-primary) font-mono', children: audio }),
          reasoning && jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'Reasoning /M' }),
          reasoning && jsx('span', { className: 'text-(--ui-text-primary) font-mono', children: reasoning }),
          ws && jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'Web search' }),
          ws && jsx('span', { className: 'text-(--ui-text-primary) font-mono', children: `$${ws}` }),
        ]
      }),
      jsxs('div', {
        className: 'grid grid-cols-2 gap-x-3 gap-y-0.5 pt-1 border-t border-(--ui-stroke-secondary)',
        children: [
          jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'Context' }),
          jsx('span', { className: 'text-(--ui-text-primary) font-mono', children: formatCtx(m.context_length) }),
          m.max_completion_tokens && jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'Max output' }),
          m.max_completion_tokens && jsx('span', { className: 'text-(--ui-text-primary) font-mono', children: formatCtx(m.max_completion_tokens) }),
          m.tokenizer && jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'Tokenizer' }),
          m.tokenizer && jsx('span', { className: 'text-(--ui-text-primary)', children: m.tokenizer }),
          m.created && jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'Added' }),
          m.created && jsx('span', { className: 'text-(--ui-text-primary)', children: m.created }),
          m.expiration_date && jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'Expires' }),
          m.expiration_date && jsx('span', { className: 'text-yellow-400', children: m.expiration_date }),
        ]
      }),
      (m.intelligence_index != null || m.coding_index != null || m.agentic_index != null) && jsxs('div', {
        className: 'pt-1 border-t border-(--ui-stroke-secondary)',
        children: [
          jsx('div', { className: 'text-(--ui-text-quaternary) mb-0.5', children: 'Benchmarks' }),
          jsx(ScoreBar, { value: m.intelligence_index, label: 'Int' }),
          jsx(ScoreBar, { value: m.coding_index, label: 'Code' }),
          jsx(ScoreBar, { value: m.agentic_index, label: 'Agent' }),
        ]
      }),
      m.design_arena && m.design_arena.length > 0 && jsxs('div', {
        className: 'pt-1 border-t border-(--ui-stroke-secondary)',
        children: [
          jsx('div', { className: 'text-(--ui-text-quaternary) mb-0.5', children: 'Design Arena' }),
          ...m.design_arena.slice(0, 3).map((a, i) =>
            jsxs('div', {
              key: i,
              className: 'flex items-center gap-1 text-[10px]',
              children: [
                jsx('span', { className: 'text-(--ui-text-quaternary) w-16 truncate', children: a.category }),
                jsx('span', { className: 'text-(--ui-text-primary) font-mono', children: a.elo }),
                jsx('span', { className: 'text-(--ui-text-quaternary)', children: `#${a.rank}` }),
                jsx('span', { className: 'text-green-400', children: `${a.win_rate}%` }),
              ]
            }, i)
          )
        ]
      }),
      jsxs('div', {
        className: 'flex flex-wrap gap-1 pt-1 border-t border-(--ui-stroke-secondary)',
        children: [
          m.has_tools && jsx(Pill, { color: 'blue', children: 'tools' }),
          m.has_vision && jsx(Pill, { color: 'purple', children: 'vision' }),
          m.reasoning_enabled && jsx(Pill, { color: 'yellow', children: m.reasoning_mandatory ? 'reasoning (always)' : 'reasoning' }),
          m.is_moderated && jsx(Pill, { color: 'red', children: 'moderated' }),
          ...m.output_modalities.filter(o => o !== 'text').map(o =>
            jsx(Pill, { key: o, children: o }, o)
          ),
        ]
      }),
      m.supported_parameters && m.supported_parameters.length > 0 && jsx('div', {
        className: 'text-[11px] text-(--ui-text-quaternary)',
        children: `Params: ${m.supported_parameters.join(', ')}`
      }),
    ]
  })
}

function CatalogRow({ model, isSelected, onToggle, isDefault }) {
  const [expanded, setExpanded] = useState(false)
  const m = model
  const twoWeeksAgo = Math.floor(Date.now() / 1000) - (14 * 24 * 60 * 60)
  const isNew = m.created_ts > twoWeeksAgo

  return jsxs('div', {
    className: cn(
      'rounded border transition-colors',
      isSelected
        ? 'border-(--ui-accent) bg-(--ui-accent-subtle, rgba(59,130,246,0.06))'
        : 'border-transparent hover:bg-(--chrome-action-hover)'
    ),
    children: [
      jsxs('div', {
        className: 'flex items-center gap-2 px-2 py-1.5 cursor-pointer',
        onClick: () => onToggle(m.id, m.name),
        children: [
          jsx(Checkbox, {
            checked: isSelected,
            className: 'shrink-0',
            onClick: (e) => e.stopPropagation(),
            onCheckedChange: () => onToggle(m.id, m.name),
          }),
          jsxs('div', {
            className: 'flex-1 min-w-0',
            children: [
              jsxs('div', {
                className: 'flex items-center gap-1.5',
                children: [
                  jsx('span', {
                    className: 'text-[13px] font-mono text-(--ui-text-primary) truncate',
                    title: m.id,
                    children: m.id
                  }),
                  isNew && jsx('span', {
                    className: 'text-[9px] px-1 py-0 rounded font-medium',
                    style: { backgroundColor: 'rgba(34, 197, 94, 0.2)', color: '#4ade80' },
                    children: 'NEW'
                  }),
                  isDefault && jsx(Pill, { color: 'blue', title: 'Already in Hermes default OpenRouter list', children: 'DEFAULT' }),
                  m.variant === 'free' && jsx(Pill, { color: 'green', title: 'Free tier', children: 'FREE' }),
                  m.variant === 'batch' && jsx(Pill, { color: 'blue', title: 'Batch processing (lower cost, slower)', children: 'BATCH' }),
                  m.reasoning_mandatory && jsx(Pill, { color: 'yellow', title: 'Reasoning always enabled', children: 'R' }),
                  m.is_moderated && jsx(Pill, { color: 'red', title: 'Content moderated', children: 'M' }),
                  m.has_tools && jsx(Pill, { color: 'blue', title: 'Supports tool calling', children: '🔧' }),
                  m.has_vision && jsx(Pill, { color: 'purple', title: 'Supports vision (image input)', children: '👁' }),
                  m.input_modalities && m.input_modalities.includes('audio') && jsx(Pill, { color: 'yellow', title: 'Supports audio input', children: '🎤' }),
                  m.output_modalities && m.output_modalities.includes('image') && jsx(Pill, { color: 'purple', title: 'Generates images', children: '🖼' }),
                ]
              }),
              m.name !== m.id && jsx('div', {
                className: 'text-xs text-(--ui-text-tertiary) truncate',
                children: m.name
              })
            ]
          }),
          jsxs('div', {
            className: 'flex gap-1.5 shrink-0 items-center text-xs',
            children: [
              m.prompt_price === 0 && jsx('span', { className: 'text-green-400', children: 'free' }),
              m.prompt_price > 0 && jsx('span', {
                className: 'text-(--ui-text-tertiary) font-mono',
                title: `Input: $${m.prompt_price.toFixed(2)}/M  Output: $${m.completion_price.toFixed(2)}/M`,
                children: `$${m.prompt_price.toFixed(2)}→$${m.completion_price.toFixed(2)}`
              }),
              jsx('span', {
                className: 'text-(--ui-text-tertiary)',
                title: `Context: ${formatCtx(m.context_length)}  Max output: ${formatCtx(m.max_completion_tokens)}`,
                children: formatCtx(m.context_length)
              }),
            ]
          }),
          jsx('button', {
            className: 'text-xs text-(--ui-text-quaternary) hover:text-(--ui-text-primary) px-0.5',
            onClick: (e) => { e.stopPropagation(); setExpanded(!expanded) },
            children: expanded ? '▾' : '▸'
          })
        ]
      }),
      expanded && jsx(ModelDetails, { m })
    ]
  }, m.id)
}

function PickerPage({ ctx }) {
  const [view, setView] = useState('picker')
  const [catalog, setCatalog] = useState([])
  const [curatedIds, setCuratedIds] = useState(new Set())
  const [providers, setProviders] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [loadingCatalog, setLoadingCatalog] = useState(false)
  const [filter, setFilter] = useState('')
  const [sort, setSort] = useState('newest')
  const [freeOnly, setFreeOnly] = useState(false)
  const [selectedOnly, setSelectedOnly] = useState(false)
  const [providerFilter, setProviderFilter] = useState('')
  const [minContext, setMinContext] = useState(0)
  const [modalityFilter, setModalityFilter] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [hasNewPosts, setHasNewPosts] = useState(true)
  const [credits, setCredits] = useState(null)
  const [defaultModelIds, setDefaultModelIds] = useState(new Set())

  const loadCurated = useCallback(async () => {
    try {
      const data = await api(ctx, 'GET', '/models')
      setCuratedIds(new Set((data.models || []).map(m => m.id)))
    } catch (e) { setError(String(e)) }
  }, [ctx])

  const loadCatalog = useCallback(async () => {
    setLoadingCatalog(true)
    try {
      const params = new URLSearchParams()
      if (sort) params.set('sort', sort)
      if (modalityFilter) params.set('output_modalities', modalityFilter)
      if (minContext > 0) params.set('min_context_length', String(minContext))
      const qs = params.toString()
      const data = await api(ctx, 'GET', `/catalog${qs ? '?' + qs : ''}`)
      if (data && data.error) { setError(data.error); return }
      setCatalog((data && data.models) || [])
      setProviders((data && data.providers) || [])
    } catch (e) { setError(String(e)) }
    setLoading(false)
    setLoadingCatalog(false)
  }, [ctx, sort, modalityFilter, minContext])

  useEffect(() => { loadCurated() }, [loadCurated])
  useEffect(() => { loadCatalog() }, [loadCatalog])

  const loadBlog = useCallback(async () => {
    try {
      const data = await api(ctx, 'GET', '/blog?limit=1')
      if (data && data.posts && data.posts.length > 0) {
        const lastSeen = localStorage.getItem('or-picker-blog-last')
        if (!lastSeen || lastSeen !== data.posts[0].link) {
          setHasNewPosts(true)
        }
      }
    } catch {}
  }, [ctx])

  useEffect(() => { loadBlog() }, [loadBlog])

  const loadCredits = useCallback(async () => {
    try {
      const data = await api(ctx, 'GET', '/credits')
      if (data && data.remaining != null) setCredits(data)
    } catch {}
  }, [ctx])

  useEffect(() => { loadCredits() }, [loadCredits])

  const loadDefaultModels = useCallback(async () => {
    try {
      const data = await api(ctx, 'GET', '/default-models')
      if (data && data.ids) setDefaultModelIds(new Set(data.ids))
    } catch {}
  }, [ctx])

  useEffect(() => { loadDefaultModels() }, [loadDefaultModels])


  const toggle = useCallback(async (id, name) => {
    try {
      if (curatedIds.has(id)) {
        const data = await api(ctx, 'POST', '/remove', { id })
        if (data && data.error) { setError(data.error); return }
        setCuratedIds(prev => { const next = new Set(prev); next.delete(id); return next })
        refreshComposerPicker()
      } else {
        const data = await api(ctx, 'POST', '/models', { id, description: name || id })
        if (data && data.error) { setError(data.error); return }
        setCuratedIds(prev => new Set(prev).add(id))
        refreshComposerPicker()
      }
    } catch (e) { setError(String(e)) }
  }, [ctx, curatedIds])

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
        m.provider.toLowerCase().includes(q) ||
        (m.description && m.description.toLowerCase().includes(q))
      )
    }
    return list
  }, [catalog, filter, freeOnly, selectedOnly, providerFilter, curatedIds])

  const selectedCount = curatedIds.size

  return jsxs('div', {
    className: 'flex h-full flex-col text-[15px]',
    children: [
      jsxs('div', {
        className: 'flex items-center justify-between px-3 py-2 border-b border-(--ui-stroke-secondary)',
        children: [
          jsxs('div', {
            className: 'flex items-center gap-2',
            children: [
              jsx('span', { className: 'font-medium', children: 'OpenRouter Picker' }),
              credits && credits.remaining != null && jsxs('span', {
                className: 'text-[13px] font-mono font-medium',
                style: { color: credits.remaining >= 5 ? '#4ade80' : '#f87171' },
                children: [
                  jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'Balance: ' }),
                  `$${credits.remaining.toFixed(2)}`
                ]
              })
            ]
          }),
          jsxs('div', {
            className: 'flex items-center gap-2',
            children: [
              loadingCatalog && jsx('span', { className: 'text-xs text-(--ui-text-quaternary)', children: '⟳' }),
              jsx('span', { className: 'text-[13px] text-(--ui-text-tertiary)', children: `${selectedCount} selected` }),
              view === 'picker' && jsx('button', {
                className: 'text-xs px-2 py-1 rounded transition-colors',
                style: { backgroundColor: 'transparent', color: 'var(--ui-text-tertiary)' },
                onClick: () => setView('analytics'),
                children: '📊 Analytics'
              }),
              view === 'picker' && jsx('button', {
                className: 'text-xs px-2 py-1 rounded transition-colors',
                style: { backgroundColor: 'transparent', color: 'var(--ui-text-tertiary)' },
                onClick: () => { setView('news'); setHasNewPosts(false) },
                children: '📰 News'
              }),
              hasNewPosts && view === 'picker' && jsx('span', {
                className: 'text-[8px] px-1 py-0 rounded font-medium',
                style: { backgroundColor: 'rgba(34, 197, 94, 0.2)', color: '#4ade80' },
                children: 'NEW'
              }),
              view !== 'picker' && jsx('button', {
                className: 'text-xs px-2 py-1 rounded transition-colors',
                style: { backgroundColor: 'rgba(59, 130, 246, 0.2)', color: '#60a5fa' },
                onClick: () => setView('picker'),
                children: '← Picker'
              })
            ]
          })
        ]
      }),
      error && jsx('div', {
        className: 'px-3 py-1 text-xs text-red-400 bg-red-400/10 cursor-pointer',
        onClick: () => setError(''),
        children: `⚠ ${error}`
      }),
      view === 'analytics' ? jsx(AnalyticsPage, { ctx }) :
      view === 'news' ? jsx(BlogPage, { ctx }) :
      jsxs('div', {
        className: 'flex-1 flex flex-col min-h-0',
        children: [
      jsxs('div', {
        className: 'px-3 py-2 flex flex-col gap-1.5 border-b border-(--ui-stroke-secondary)',
        children: [
          jsx('input', {
            type: 'text',
            value: filter,
            onChange: e => setFilter(e.target.value),
            placeholder: 'Filter models…',
            className: 'w-full text-[13px] px-2.5 py-1.5 rounded border border-(--ui-stroke-secondary) bg-(--chrome-background) text-(--ui-text-primary) placeholder:text-(--ui-text-quaternary)'
          }),
          jsxs('div', {
            className: 'flex gap-1.5 items-center',
            children: [
              jsx('span', { className: 'text-xs text-(--ui-text-quaternary) shrink-0', children: 'Sort' }),
              jsx(UiSelect, {
                value: sort,
                onChange: setSort,
                options: SORT_OPTIONS,
              })
            ]
          }),
          jsxs('div', {
            className: 'flex gap-1.5 items-center',
            children: [
              jsx('span', { className: 'text-xs text-(--ui-text-quaternary) shrink-0', children: 'Provider' }),
              jsx(UiSelect, {
                value: providerFilter || 'all',
                onChange: v => setProviderFilter(v === 'all' ? '' : v),
                options: [{ value: 'all', label: 'All providers' }, ...providers.map(p => ({ value: p, label: p }))],
              })
            ]
          }),
          jsxs('div', {
            className: 'flex gap-1 flex-wrap',
            children: [
              jsx('button', {
                onClick: () => setFreeOnly(!freeOnly),
                className: cn('text-xs px-2 py-1 rounded transition-colors', freeOnly ? 'bg-green-500/20 text-green-400' : 'bg-(--chrome-background-inset) text-(--ui-text-tertiary) hover:text-(--ui-text-primary)'),
                children: 'Free'
              }),
              jsx('button', {
                onClick: () => setSelectedOnly(!selectedOnly),
                className: cn('text-xs px-2 py-1 rounded transition-colors', selectedOnly ? 'bg-(--ui-accent) text-white' : 'bg-(--chrome-background-inset) text-(--ui-text-tertiary) hover:text-(--ui-text-primary)'),
                children: `Selected (${selectedCount})`
              }),
              jsx('button', {
                onClick: () => setShowAdvanced(!showAdvanced),
                className: cn('text-xs px-2 py-1 rounded transition-colors', showAdvanced ? 'bg-(--ui-accent) text-white' : 'bg-(--chrome-background-inset) text-(--ui-text-tertiary) hover:text-(--ui-text-primary)'),
                children: showAdvanced ? '▾ Advanced' : '▸ Advanced'
              })
            ]
          }),
          showAdvanced && jsxs('div', {
            className: 'flex flex-col gap-1.5 pt-1 border-t border-(--ui-stroke-secondary)',
            children: [
              jsxs('div', {
                className: 'flex gap-1.5 items-center',
                children: [
                  jsx('span', { className: 'text-xs text-(--ui-text-quaternary) shrink-0', children: 'Output' }),
                  jsx(UiSelect, {
                    value: modalityFilter || 'all',
                    onChange: v => setModalityFilter(v === 'all' ? '' : v),
                    options: MODALITY_OPTIONS,
                  })
                ]
              }),
              jsxs('div', {
                className: 'flex gap-1.5 items-center',
                children: [
                  jsx('span', { className: 'text-xs text-(--ui-text-quaternary) shrink-0', children: 'Min Ctx' }),
                  jsx(UiSelect, {
                    value: String(minContext),
                    onChange: v => setMinContext(Number(v)),
                    options: CONTEXT_OPTIONS,
                  })
                ]
              })
            ]
          })
        ]
      }),
      loading
        ? jsx('div', { className: 'flex-1 flex items-center justify-center text-(--ui-text-quaternary)', children: 'Loading catalog…' })
        : filtered.length === 0
          ? jsx('div', { className: 'flex-1 flex items-center justify-center text-(--ui-text-quaternary) text-[13px]', children: catalog.length === 0 ? 'Failed to load catalog' : 'No models match filters' })
          : jsx('div', {
              className: 'flex-1 overflow-y-auto py-1',
              children: filtered.map(m => jsx(CatalogRow, {
                key: m.id,
                model: m,
                isSelected: curatedIds.has(m.id),
                isDefault: defaultModelIds.has(m.id),
                onToggle: toggle
              }))
            }),
      jsx('div', {
        className: 'px-3 py-1.5 text-xs text-(--ui-text-quaternary) border-t border-(--ui-stroke-secondary) flex justify-between',
        children: [
          jsx('span', { children: `${filtered.length} of ${catalog.length} shown` }),
          jsx('span', { children: `${selectedCount} selected` })
        ]
      })
        ]
      })
    ]
  })
}

function AnalyticsPage({ ctx }) {
  const [analytics, setAnalytics] = useState(null)
  const [activity, setActivity] = useState([])
  const [activityTotals, setActivityTotals] = useState(null)
  const [loading, setLoading] = useState(true)
  const [mgmtKey, setMgmtKey] = useState(() => {
    try { return localStorage.getItem('or-picker-mgmt-key') || '' } catch { return '' }
  })
  const [showKeyInput, setShowKeyInput] = useState(false)

  const loadAnalytics = useCallback(async () => {
    try {
      const data = await api(ctx, 'GET', '/analytics')
      setAnalytics(data)
    } catch (e) { setAnalytics({ error: String(e) }) }
  }, [ctx])

  const loadActivity = useCallback(async () => {
    try {
      const data = await api(ctx, 'GET', '/activity' + (mgmtKey ? `?mgmt_key=${encodeURIComponent(mgmtKey)}` : ''))
      if (data && data.models) {
        setActivity(data.models)
        setActivityTotals(data.totals || null)
      }
    } catch {}
    setLoading(false)
  }, [ctx, mgmtKey])

  useEffect(() => { loadAnalytics(); loadActivity() }, [loadAnalytics, loadActivity])

  const saveKey = useCallback(() => {
    try { localStorage.setItem('or-picker-mgmt-key', mgmtKey) } catch {}
    setShowKeyInput(false)
    loadActivity()
  }, [mgmtKey, loadActivity])

  if (loading) return jsx('div', { className: 'flex items-center justify-center h-full text-(--ui-text-quaternary)', children: 'Loading analytics…' })
  if (!analytics || analytics.error) return jsx('div', { className: 'flex items-center justify-center h-full text-red-400', children: analytics?.error || 'Failed to load' })

  const fmt = (v) => v != null ? `$${v.toFixed(2)}` : '—'

  return jsxs('div', {
    className: 'flex-1 overflow-y-auto p-4 space-y-4',
    children: [
      // Key info
      jsxs('div', {
        className: 'rounded-lg border border-(--ui-stroke-secondary) p-4',
        children: [
          jsx('div', { className: 'text-(--ui-text-quaternary) text-xs mb-2', children: 'API Key' }),
          jsxs('div', {
            className: 'grid grid-cols-2 gap-x-8 gap-y-2 text-sm',
            children: [
              jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'Label' }),
              jsx('span', { className: 'font-mono', children: analytics.label || '—' }),
              jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'Tier' }),
              jsx('span', { children: analytics.is_free_tier ? jsx(Pill, { color: 'yellow', children: 'Free Tier' }) : jsx(Pill, { color: 'green', children: 'Paid' }) }),
              jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'BYOK in Limit' }),
              jsx('span', { children: analytics.include_byok_in_limit ? 'Yes' : 'No' }),
            ]
          }),
        ]
      }),
      // Balance card
      jsxs('div', {
        className: 'rounded-lg border border-(--ui-stroke-secondary) p-4',
        children: [
          jsx('div', { className: 'text-(--ui-text-quaternary) text-xs mb-2', children: 'Balance' }),
          jsxs('div', {
            className: 'grid grid-cols-2 gap-4',
            children: [
              jsxs('div', { children: [
                jsx('div', { className: 'text-(--ui-text-quaternary) text-xs', children: 'Remaining' }),
                jsx('div', { className: 'text-2xl font-mono font-bold', style: { color: (analytics.limit_remaining || 0) >= 5 ? '#4ade80' : '#f87171' }, children: fmt(analytics.limit_remaining) }),
              ]}),
              jsxs('div', { children: [
                jsx('div', { className: 'text-(--ui-text-quaternary) text-xs', children: 'Limit' }),
                jsx('div', { className: 'text-2xl font-mono', children: analytics.limit != null ? fmt(analytics.limit) : 'Unlimited' }),
              ]}),
            ]
          }),
          analytics.limit_reset && jsx('div', { className: 'text-xs text-(--ui-text-quaternary) mt-2', children: `Resets: ${analytics.limit_reset}` }),
        ]
      }),
      // Credits usage
      jsxs('div', {
        className: 'rounded-lg border border-(--ui-stroke-secondary) p-4',
        children: [
          jsx('div', { className: 'text-(--ui-text-quaternary) text-xs mb-3', children: 'OpenRouter Credits Usage' }),
          jsxs('div', {
            className: 'grid grid-cols-2 gap-x-8 gap-y-2 text-sm',
            children: [
              jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'Today' }),
              jsx('span', { className: 'font-mono text-right', children: fmt(analytics.usage_daily) }),
              jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'This Week' }),
              jsx('span', { className: 'font-mono text-right', children: fmt(analytics.usage_weekly) }),
              jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'This Month' }),
              jsx('span', { className: 'font-mono text-right', children: fmt(analytics.usage_monthly) }),
              jsx('span', { className: 'text-(--ui-text-quaternary) border-t border-(--ui-stroke-secondary) pt-2', children: 'All Time' }),
              jsx('span', { className: 'font-mono text-right border-t border-(--ui-stroke-secondary) pt-2', children: fmt(analytics.usage) }),
            ]
          }),
        ]
      }),
      // BYOK usage
      jsxs('div', {
        className: 'rounded-lg border border-(--ui-stroke-secondary) p-4',
        children: [
          jsxs('div', { className: 'text-(--ui-text-quaternary) text-xs mb-3', children: [
            'BYOK Usage ',
            jsx('span', { className: 'text-[10px]', children: '(5% platform fee)' })
          ]}),
          jsxs('div', {
            className: 'grid grid-cols-2 gap-x-8 gap-y-2 text-sm',
            children: [
              jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'Today' }),
              jsx('span', { className: 'font-mono text-right', children: fmt(analytics.byok_usage_daily) }),
              jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'This Week' }),
              jsx('span', { className: 'font-mono text-right', children: fmt(analytics.byok_usage_weekly) }),
              jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'This Month' }),
              jsx('span', { className: 'font-mono text-right', children: fmt(analytics.byok_usage_monthly) }),
              jsx('span', { className: 'text-(--ui-text-quaternary) border-t border-(--ui-stroke-secondary) pt-2', children: 'All Time' }),
              jsx('span', { className: 'font-mono text-right border-t border-(--ui-stroke-secondary) pt-2', children: fmt(analytics.byok_usage) }),
            ]
          }),
        ]
      }),
      // Activity totals
      activityTotals && jsxs('div', {
        className: 'rounded-lg border border-(--ui-stroke-secondary) p-4',
        children: [
          jsx('div', { className: 'text-(--ui-text-quaternary) text-xs mb-3', children: 'Total Spend' }),
          jsxs('div', {
            className: 'grid grid-cols-4 gap-4 text-center',
            children: [
              jsxs('div', { children: [
                jsx('div', { className: 'text-[10px] text-(--ui-text-quaternary)', children: 'Today' }),
                jsx('div', { className: 'font-mono text-lg font-bold', children: fmt(activityTotals.today) }),
              ]}),
              jsxs('div', { children: [
                jsx('div', { className: 'text-[10px] text-(--ui-text-quaternary)', children: 'This Week' }),
                jsx('div', { className: 'font-mono text-lg font-bold', children: fmt(activityTotals.week) }),
              ]}),
              jsxs('div', { children: [
                jsx('div', { className: 'text-[10px] text-(--ui-text-quaternary)', children: 'This Month' }),
                jsx('div', { className: 'font-mono text-lg font-bold', children: fmt(activityTotals.month) }),
              ]}),
              jsxs('div', { children: [
                jsx('div', { className: 'text-[10px] text-(--ui-text-quaternary)', children: 'All Time' }),
                jsx('div', { className: 'font-mono text-lg font-bold', children: fmt(activityTotals.all) }),
              ]}),
            ]
          }),
        ]
      }),
      // Model usage breakdown
      activity.length > 0 ? jsxs('div', {
        className: 'rounded-lg border border-(--ui-stroke-secondary) p-4',
        children: [
          jsx('div', { className: 'text-(--ui-text-quaternary) text-xs mb-3', children: 'Usage by Model' }),
          jsxs('div', {
            className: 'space-y-2',
            children: activity.slice(0, 15).map((m, i) =>
              jsxs('div', {
                key: i,
                className: 'py-2 border-b border-(--ui-stroke-secondary) last:border-b-0',
                children: [
                  jsxs('div', {
                    className: 'flex items-center gap-2 mb-1',
                    children: [
                      jsx('span', { className: 'flex-1 min-w-0 truncate font-mono text-[12px]', title: m.model, children: m.model }),
                      m.provider && jsx('span', { className: 'text-[10px] text-(--ui-text-quaternary)', children: m.provider }),
                    ]
                  }),
                  jsxs('div', {
                    className: 'grid grid-cols-4 gap-2 text-center text-[11px]',
                    children: [
                      jsxs('div', { children: [
                        jsx('div', { className: 'text-[9px] text-(--ui-text-quaternary)', children: 'Today' }),
                        jsx('div', { className: 'font-mono', children: fmt(m.cost_today) }),
                      ]}),
                      jsxs('div', { children: [
                        jsx('div', { className: 'text-[9px] text-(--ui-text-quaternary)', children: 'Week' }),
                        jsx('div', { className: 'font-mono', children: fmt(m.cost_week) }),
                      ]}),
                      jsxs('div', { children: [
                        jsx('div', { className: 'text-[9px] text-(--ui-text-quaternary)', children: 'Month' }),
                        jsx('div', { className: 'font-mono', children: fmt(m.cost_month) }),
                      ]}),
                      jsxs('div', { children: [
                        jsx('div', { className: 'text-[9px] text-(--ui-text-quaternary)', children: 'All' }),
                        jsx('div', { className: 'font-mono', children: fmt(m.cost_all) }),
                      ]}),
                    ]
                  }),
                ]
              }, i)
            )
          }),
        ]
      }) : jsxs('div', {
        className: 'rounded-lg border border-(--ui-stroke-secondary) p-4',
        children: [
          jsx('div', { className: 'text-(--ui-text-quaternary) text-xs mb-2', children: 'Usage by Model' }),
          jsx('div', { className: 'text-xs text-(--ui-text-tertiary) mb-3', children: 'Requires a management key for per-model breakdown.' }),
          showKeyInput ? jsxs('div', {
            className: 'flex gap-2 items-center',
            children: [
              jsx('input', {
                type: 'password',
                value: mgmtKey,
                onChange: e => setMgmtKey(e.target.value),
                placeholder: 'sk-or-mgmt-...',
                className: 'flex-1 text-[12px] px-2 py-1 rounded border border-(--ui-stroke-secondary) bg-(--chrome-background) text-(--ui-text-primary) placeholder:text-(--ui-text-quaternary)',
                onKeyDown: e => { if (e.key === 'Enter') saveKey() }
              }),
              jsx('button', {
                className: 'text-xs px-2 py-1 rounded bg-(--ui-accent) text-white',
                onClick: saveKey,
                children: 'Save'
              }),
              jsx('button', {
                className: 'text-xs px-2 py-1 rounded text-(--ui-text-tertiary)',
                onClick: () => setShowKeyInput(false),
                children: 'Cancel'
              }),
            ]
          }) : jsxs('div', {
            className: 'flex gap-2 items-center justify-center',
            children: [
              jsx('button', {
                className: 'text-xs px-3 py-1.5 rounded border border-(--ui-stroke-secondary) text-(--ui-text-tertiary) hover:text-(--ui-text-primary) hover:bg-(--chrome-action-hover)',
                onClick: () => setShowKeyInput(true),
                children: mgmtKey ? '🔑 Change Key' : '🔑 Add Management Key'
              }),
              jsx('a', {
                href: 'https://openrouter.ai/settings/management-keys',
                target: '_blank',
                rel: 'noopener noreferrer',
                className: 'text-xs text-(--ui-accent, #60a5fa) hover:underline',
                children: 'Get one →'
              }),
            ]
          }),
        ]
      }),
    ]
  })
}

function BlogPage({ ctx }) {
  const [blogPosts, setBlogPosts] = useState([])
  const [loading, setLoading] = useState(true)

  const loadBlog = useCallback(async () => {
    try {
      const data = await api(ctx, 'GET', '/blog?limit=15')
      if (data && data.posts) {
        setBlogPosts(data.posts)
        // Mark as seen
        if (data.posts.length > 0) {
          try { localStorage.setItem('or-picker-blog-last', data.posts[0].link) } catch {}
        }
      }
    } catch {}
    setLoading(false)
  }, [ctx])

  useEffect(() => { loadBlog() }, [loadBlog])

  if (loading) return jsx('div', { className: 'flex items-center justify-center h-full text-(--ui-text-quaternary)', children: 'Loading news…' })

  return jsxs('div', {
    className: 'flex-1 overflow-y-auto p-4 space-y-3',
    children: blogPosts.length === 0
      ? jsx('div', { className: 'text-(--ui-text-quaternary) text-center py-8', children: 'No posts found' })
      : blogPosts.map((post, i) =>
          jsxs('div', {
            key: i,
            className: 'rounded-lg border border-(--ui-stroke-secondary) p-4 hover:bg-(--chrome-action-hover) transition-colors',
            children: [
              jsx('a', {
                href: post.link,
                target: '_blank',
                rel: 'noopener noreferrer',
                className: 'text-sm font-medium text-(--ui-accent, #60a5fa) hover:underline',
                children: post.title
              }),
              post.description && jsx('div', {
                className: 'text-xs text-(--ui-text-tertiary) leading-relaxed mt-1',
                children: post.description
              }),
              post.pubDate && jsx('div', {
                className: 'text-[10px] text-(--ui-text-quaternary) mt-2',
                children: post.pubDate.replace(/ \d{2}:\d{2}:\d{2} GMT/, '')
              })
            ]
          }, i)
        )
  })
}

export default {
  id: ID,
  name: 'OpenRouter Picker',
  defaultEnabled: true,
  register(ctx) {
    ctx.registerMany([
      {
        id: 'page',
        area: ROUTES_AREA,
        data: { path: PAGE },
        render: () => jsx(PickerPage, { ctx })
      },
      {
        id: 'nav',
        area: SIDEBAR_NAV_AREA,
        data: { path: PAGE, label: 'OR Picker', codicon: 'list-unordered' }
      },
      {
        id: 'open',
        area: PALETTE_AREA,
        data: {
          id: ID + '.open',
          label: 'Open OpenRouter Picker',
          keywords: ['openrouter', 'models', 'picker'],
          run: () => host.navigate(PAGE)
        }
      }
    ])
  }
}
