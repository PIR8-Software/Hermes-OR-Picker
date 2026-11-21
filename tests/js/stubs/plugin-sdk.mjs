/**
 * Stub for '@hermes/plugin-sdk': only what catalog/desktop/plugin.js imports.
 * Components render as plain host elements so the behavior harness can find and
 * click them like any other node. queryClient.invalidateQueries is recorded so
 * tests can prove the accepted live composer invalidation still happens.
 */
import { jsx } from '../runtime.mjs'

export const composerInvalidations = []

export function cn(...args) {
  return args.filter(Boolean).join(' ')
}

export const host = {
  navigations: [],
  navigate(path) { host.navigations.push(path) },
}

export const ROUTES_AREA = 'routes'
export const SIDEBAR_NAV_AREA = 'sidebar-nav'
export const PALETTE_AREA = 'palette'

export function Checkbox(props) {
  return jsx('checkbox-mock', props)
}
export function Select(props) {
  return jsx('select-mock', props)
}
export function SelectContent(props) {
  return jsx('select-content-mock', props)
}
export function SelectItem(props) {
  return jsx('select-item-mock', props)
}
export function SelectTrigger(props) {
  return jsx('select-trigger-mock', props)
}
export function SelectValue(props) {
  return jsx('select-value-mock', props)
}

export const queryClient = {
  invalidateQueries(args) {
    composerInvalidations.push(args)
  },
}
