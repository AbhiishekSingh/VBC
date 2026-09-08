/**
 * HTTP adapter — talks to FastAPI.
 *
 * Implements the same contract as the mock, so switching between them is a
 * config change and no page needs to know which is active. The endpoints
 * below are the contract the backend implements; they are not negotiable
 * from the frontend side once the backend is built against them.
 *
 * ERRORS
 * ------
 * The backend goes to real trouble to say WHY something did not happen —
 * 501 NotConfigured, 402 PaidCallRefused, 502 ProviderError each carry a
 * written explanation in `detail`. Collapsing those into "Request failed
 * (502)" throws away the only part an analyst can act on, and in an audit
 * product the reason a check did not run IS the finding.
 *
 * So every failure is turned into an ApiError carrying three things: the
 * provider's own sentence, a short label for what class of problem it is,
 * and whether retrying could plausibly help.
 */

import type { AuditEntry, Client, ManualEntry, User, Vendor } from '@/types/domain'
import type { ClientInput, DecisionInput, RunChecksResult, VbcApi } from './contract'

const BASE = import.meta.env.VITE_API_BASE ?? '/api'

/** What kind of problem this is — drives how a page presents it. */
export type ApiErrorKind =
  | 'offline' //      the request never reached the server
  | 'auth' //         401 — signed out, or the session expired
  | 'forbidden' //    403 — the role lacks this permission
  | 'not_found' //    404
  | 'refused' //      402 — the spend guard stopped a billable call
  | 'not_configured' //  501 — no provider wired up for that check
  | 'provider' //     502 — a provider answered badly
  | 'invalid' //      422 — the request body failed validation
  | 'conflict' //     409
  | 'server' //       500 and anything else unrecognised

class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly kind: ApiErrorKind,
    readonly detail?: unknown,
    /** True when the same request might succeed if repeated. */
    readonly retryable = false,
  ) {
    super(message)
    this.name = 'ApiError'
  }

  /** A short heading for a callout or toast, above the message. */
  get title(): string {
    switch (this.kind) {
      case 'offline':
        return 'Cannot reach the server'
      case 'auth':
        return 'Signed out'
      case 'forbidden':
        return 'Not permitted'
      case 'not_found':
        return 'Not found'
      case 'refused':
        return 'Paid call refused'
      case 'not_configured':
        return 'Provider not configured'
      case 'provider':
        return 'Provider error'
      case 'invalid':
        return 'Invalid request'
      case 'conflict':
        return 'Conflict'
      default:
        return 'Something went wrong'
    }
  }
}

function kindFor(status: number): ApiErrorKind {
  switch (status) {
    case 401:
      return 'auth'
    case 402:
      return 'refused'
    case 403:
      return 'forbidden'
    case 404:
      return 'not_found'
    case 409:
      return 'conflict'
    case 422:
      return 'invalid'
    case 501:
      return 'not_configured'
    case 502:
      return 'provider'
    default:
      return 'server'
  }
}

/**
 * Pull the human sentence out of whatever the server sent.
 *
 * FastAPI is not consistent about this by design: a raised HTTPException
 * gives `{detail: "..."}`, a validation failure gives `{detail: [{loc,
 * msg, type}, ...]}`, and an unhandled 500 or an nginx error page is not
 * JSON at all. All three have to end up as a readable line.
 */
function messageFrom(body: unknown, status: number, path: string): string {
  if (typeof body === 'string' && body.trim()) {
    // An HTML error page from nginx is not a message worth showing.
    if (/^\s*<(!doctype|html)/i.test(body)) return ''
    return body.trim().slice(0, 400)
  }

  if (body && typeof body === 'object') {
    const detail = (body as { detail?: unknown }).detail

    if (typeof detail === 'string' && detail.trim()) return detail.trim()

    // 422 — an array of per-field problems. Name the fields; "validation
    // error" alone leaves the analyst hunting for which box is wrong.
    if (Array.isArray(detail)) {
      const parts = detail
        .map((d) => {
          if (!d || typeof d !== 'object') return String(d)
          const loc = Array.isArray((d as { loc?: unknown[] }).loc)
            ? (d as { loc: unknown[] }).loc.filter((s) => s !== 'body').join('.')
            : ''
          const msg = String((d as { msg?: unknown }).msg ?? 'is invalid')
          return loc ? `${loc}: ${msg}` : msg
        })
        .filter(Boolean)
      if (parts.length) return parts.join(' · ')
    }

    // Some proxies answer {"message": "..."} rather than {"detail": ...}.
    const message = (body as { message?: unknown }).message
    if (typeof message === 'string' && message.trim()) return message.trim()
  }

  return `Request to ${path} failed (${status}).`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      // The session is an HttpOnly cookie — JS cannot read it, so it has to
      // be sent by the browser. Without this the API sees every request as
      // anonymous.
      credentials: 'include',
      ...init,
    })
  } catch (cause) {
    // fetch only rejects when the request never completed: the API is down,
    // DNS failed, the browser is offline, or CORS blocked it outright. This
    // is NOT a server error and must not be reported as one — "the API
    // returned an error" sends someone reading backend logs that contain
    // nothing, because the request never arrived.
    throw new ApiError(
      'The request did not reach the server. The API may be down, or this ' +
        'browser may be offline.',
      0,
      'offline',
      cause,
      true,
    )
  }

  if (!response.ok) {
    let body: unknown
    const raw = await response.text().catch(() => '')
    try {
      body = raw ? JSON.parse(raw) : undefined
    } catch {
      body = raw
    }

    const message = messageFrom(body, response.status, path) ||
      `Request to ${path} failed (${response.status}).`

    // 429 and 5xx can succeed on a second attempt; a 4xx is the server
    // telling you the request itself is wrong, and repeating it will not
    // change the answer.
    const retryable = response.status === 429 || response.status >= 500

    throw new ApiError(message, response.status, kindFor(response.status), body, retryable)
  }

  if (response.status === 204) return undefined as T

  try {
    return (await response.json()) as T
  } catch (cause) {
    // A 200 that is not JSON usually means something answered in front of
    // the API — an nginx page, or a login redirect from a proxy.
    throw new ApiError(
      `The server answered ${path} with a success code but not JSON. ` +
        'Something may be intercepting the request before it reaches the API.',
      response.status,
      'server',
      cause,
    )
  }
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined })

const patch = <T>(path: string, body: unknown) =>
  request<T>(path, { method: 'PATCH', body: JSON.stringify(body) })

/**
 * The message to show a person, from any thrown value.
 *
 * Use this in a catch rather than `e.message` — an ApiError carries the
 * provider's own sentence, and a non-Error throw would otherwise render
 * as "[object Object]".
 */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error && error.message) return error.message
  if (typeof error === 'string' && error.trim()) return error
  return 'Something went wrong, and no reason was given.'
}

/** The heading to pair with `errorMessage`. */
export function errorTitle(error: unknown): string {
  return error instanceof ApiError ? error.title : 'Something went wrong'
}

export const httpApi: VbcApi = {
  // --- auth ---------------------------------------------------------
  login: (email, password) => post<User>('/auth/login', { email, password }),

  logout: () => post<void>('/auth/logout'),

  // 401 here is the normal "not signed in" answer, not an error.
  me: () =>
    request<User>('/auth/me').catch((e: ApiError) =>
      e.status === 401 ? null : Promise.reject(e),
    ),

  // --- clients ------------------------------------------------------
  listClients: (includeInactive = false) =>
    request<Client[]>(`/clients${includeInactive ? '?includeInactive=true' : ''}`),

  getClient: (id) =>
    request<Client>(`/clients/${id}`).catch((e: ApiError) =>
      e.status === 404 ? null : Promise.reject(e),
    ),

  createClient: (input: ClientInput) => post<Client>('/clients', input),

  updateClient: (id, body) => patch<Client>(`/clients/${id}`, body),

  deactivateClient: (id) => post<Client>(`/clients/${id}/deactivate`),

  // --- vendors ------------------------------------------------------
  listVendors: (clientId) =>
    request<Vendor[]>(`/vendors${clientId ? `?clientId=${clientId}` : ''}`),

  getVendor: (id) =>
    request<Vendor>(`/vendors/${id}`).catch((e: ApiError) =>
      e.status === 404 ? null : Promise.reject(e),
    ),

  createVendor: (draft) => post<Vendor>('/vendors', draft),

  updateVendor: (id, body) => patch<Vendor>(`/vendors/${id}`, body),

  setSelection: (id, selected) => post<Vendor>(`/vendors/${id}/selection`, { selected }),

  setCheckInput: (id, checkId, key, value) =>
    post<Vendor>(`/vendors/${id}/inputs`, { checkId, key, value }),

  runChecks: (id) => post<RunChecksResult>(`/vendors/${id}/run`),

  addManualEntry: (id, entry: Omit<ManualEntry, 'id'>) =>
    post<Vendor>(`/vendors/${id}/manual`, entry),

  removeManualEntry: (id, entryId) =>
    request<Vendor>(`/vendors/${id}/manual/${entryId}`, { method: 'DELETE' }),

  setSurveillance: (id, values) => post<Vendor>(`/vendors/${id}/surveillance`, { values }),

  completeSurveillance: (id) => post<Vendor>(`/vendors/${id}/surveillance/complete`),

  setScanRating: (id, paramId, value) =>
    post<Vendor>(`/vendors/${id}/scan`, { paramId, value }),

  recordDecision: (id, input: DecisionInput) => post<Vendor>(`/vendors/${id}/decision`, input),

  listAudit: (vendorId) =>
    request<AuditEntry[]>(`/audit${vendorId ? `?vendorId=${vendorId}` : ''}`),

  listCostReference: () =>
    request<{ group: string; item: string; unit: string; source: string }[]>('/cost-reference'),
}

export { ApiError }
