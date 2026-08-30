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
}
