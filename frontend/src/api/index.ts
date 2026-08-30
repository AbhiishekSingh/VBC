/**
 * The data layer.
 *
 * Two adapters behind one interface. `mock` keeps the whole application
 * runnable in a browser with no backend — useful for design review and for
 * the client to click through — while `http` talks to FastAPI. Because both
 * satisfy the same interface, swapping them is a config change, and the
 * pages never learn which one they are talking to.
 *
 * Set VITE_API_MODE=http once the backend is up.
 */

import { mockApi } from './mock'
import { httpApi } from './http'
import type { VbcApi } from './contract'

const mode = import.meta.env.VITE_API_MODE ?? 'mock'

export const api: VbcApi = mode === 'http' ? httpApi : mockApi

export const API_MODE = mode as 'mock' | 'http'

export type { VbcApi } from './contract'
