/**
 * Module hooks for the OR Picker JS behavior harness.
 *
 * Maps the shipped plugin's ONLY allowed bare imports (react, react/jsx-runtime,
 * @hermes/plugin-sdk) to the test stubs in tests/js/stubs/, and forces
 * catalog/desktop/plugin.js to load as an ES module so the real shipped file is
 * what the tests execute (installed-artifact path, not a copy).
 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'

const STUBS = {
  'react/jsx-runtime': new URL('./stubs/jsx-runtime.mjs', import.meta.url).href,
  'react': new URL('./stubs/react.mjs', import.meta.url).href,
  '@hermes/plugin-sdk': new URL('./stubs/plugin-sdk.mjs', import.meta.url).href,
}

export function resolve(specifier, context, nextResolve) {
  if (STUBS[specifier]) {
    return { url: STUBS[specifier], shortCircuit: true }
  }
  return nextResolve(specifier, context)
}

export function load(url, context, nextLoad) {
  if (url.endsWith('/catalog/desktop/plugin.js')) {
    // No package.json marks this repo as ESM; force the shipped file to parse
    // as the ES module it is, byte-for-byte from its installed artifact path.
    return {
      format: 'module',
      source: fs.readFileSync(fileURLToPath(url), 'utf8'),
      shortCircuit: true,
    }
  }
  return nextLoad(url, context)
}
