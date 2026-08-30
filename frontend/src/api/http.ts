/**
 * HTTP adapter — talks to FastAPI.
 *
 * Implements the same contract as the mock, so switching between them is a
 * config change and no page needs to know which is active. The endpoints
 * below are the contract the backend implements; they are not negotiable
 * from the frontend side once the backend is built against them.
 */

import type { AuditEntry, Client, ManualEntry, User, Vendor } from '@/types/domain'
import type { ClientInput, DecisionInput, RunChecksResult, VbcApi } from './contract'

const BASE = import.meta.env.VITE_API_BASE ?? '/api'

class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    // The session is an HttpOnly cookie — JS cannot read it, so it has to
    // be sent by the browser. Without this the API sees every request as
    // anonymous.
    credentials: 'include',
    ...init,
  })

  if (!response.ok) {
    let detail: unknown
    try {
      detail = await response.json()
    } catch {
      detail = await response.text().catch(() => undefined)
    }
    // Surface something an analyst can act on, not just a status code.
    const message =
      typeof detail === 'object' && detail && 'detail' in detail
        ? String((detail as { detail: unknown }).detail)
        : `Request to ${path} failed (${response.status})`
    throw new ApiError(message, response.status, detail)
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined })

const patch = <T>(path: string, body: unknown) =>
  request<T>(path, { method: 'PATCH', body: JSON.stringify(body) })

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
