/**
 * Stub for the 'react' bare import: re-exports the real hook runtime so the
 * shipped plugin's hooks execute genuine per-instance state/effect semantics.
 */
export { useState, useEffect, useCallback, useMemo, useRef } from '../runtime.mjs'
