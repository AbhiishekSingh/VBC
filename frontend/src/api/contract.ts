/**
 * The API contract.
 *
 * Written here first, deliberately: the prototype is the specification for
 * the screens, so the shapes the screens need are known before FastAPI
 * exists. The backend implements this; it does not get to invent a
 * different one.
 */

import type { AuditEntry, Client, ManualEntry, User, Vendor } from '@/types/domain'

export interface RunChecksResult {
  vendor: Vendor
  ran: number
  skippedMissingInput: string[]
  costPaisa: number
  credits: number
}

export interface DecisionInput {
  decision: 'Approved' | 'Conditional' | 'Rejected'
  remarks: string
  /**
   * NO decidedBy. The actor comes from the session on the server. It used
   * to be sent from here, which meant anyone could record a binding
   * approval under a colleague's name.
   */
  overrideReason?: string
}

/**
 * One data source, and whether it can be called right now.
 *
 * `configured` and `blocked` are DIFFERENT QUESTIONS and the screen must
 * not merge them. `configured` says a key is set; it is decided by the
 * server's environment and does not change while the app is open.
 * `blocked` says the source is refusing our account at this moment — an
 * empty prepaid balance, a revoked key, an IP that is not allowlisted.
 * A source can be perfectly configured and blocked, which is the normal
 * shape of a prepaid account that has run out.
 *
 * `blockedReason` is the SOURCE'S OWN SENTENCE, passed through untouched.
 * One provider returns an empty balance, a bad key and a blocked IP under
 * a single status code, and each needs a different person to act, so a
 * message of our own invention would be wrong most of the time.
 */
export interface ProviderStatus {
  provider: string
  configured: boolean
  sandbox?: boolean
  note?: string
  blocked?: boolean
  blockedReason?: string
  blockedSince?: string | null
  blockedStatus?: number | null
}

export interface ClientInput {
  name: string
  legalName?: string
  industry?: string
  spoc?: string
  email?: string
  phone?: string
  notes?: string
}

export interface VbcApi {
  login(email: string, password: string): Promise<User>
  logout(): Promise<void>
  me(): Promise<User | null>

  listClients(includeInactive?: boolean): Promise<Client[]>
  getClient(id: string): Promise<Client | null>
  createClient(input: ClientInput): Promise<Client>
  updateClient(id: string, patch: Partial<ClientInput> & { active?: boolean }): Promise<Client>
  deactivateClient(id: string): Promise<Client>

  /** Every vendor, or one client's vendors. */
  listVendors(clientId?: string): Promise<Vendor[]>
  getVendor(id: string): Promise<Vendor | null>
  createVendor(draft: Partial<Vendor>): Promise<Vendor>
  updateVendor(id: string, patch: Partial<Vendor>): Promise<Vendor>

  setSelection(id: string, selected: string[]): Promise<Vendor>
  setCheckInput(id: string, checkId: string, key: string, value: string): Promise<Vendor>
  runChecks(id: string): Promise<RunChecksResult>

  addManualEntry(id: string, entry: Omit<ManualEntry, 'id'>): Promise<Vendor>
  removeManualEntry(id: string, entryId: string): Promise<Vendor>

  setSurveillance(id: string, values: Record<string, string | null>): Promise<Vendor>
  completeSurveillance(id: string): Promise<Vendor>

  setScanRating(id: string, paramId: string, value: string | null): Promise<Vendor>

  recordDecision(id: string, input: DecisionInput): Promise<Vendor>

  listAudit(vendorId?: string): Promise<AuditEntry[]>
  listCostReference(): Promise<
    readonly { group: string; item: string; unit: string; source: string }[]
  >

  /** Which sources are live, and which are refusing our account. */
  listProviderStatus(): Promise<readonly ProviderStatus[]>
}
