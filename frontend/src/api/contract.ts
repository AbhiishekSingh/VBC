/**
 * The API contract.
 *
 * Written here first, deliberately: the prototype is the specification for
 * the screens, so the shapes the screens need are known before FastAPI
 * exists. The backend implements this; it does not get to invent a
 * different one.
 */

import type {
  AuditEntry,
  Client,
  HistoryPage,
  ManualEntry,
  User,
  Vendor,
} from '@/types/domain'

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

  /**
   * The CHECK IDS this provider's outages cover, each with the source's
   * own reason. Resolved on the SERVER, because providers do not all
   * bill the same way: one of them charges its products from separate
   * pools, so a refusal on one says nothing about the others, while the
   * rest draw on a single wallet where a refusal really is account-wide.
   *
   * Working that out here would mean a second copy of the rule living in
   * the browser, and two copies of one rule is how the scoring engine
   * once ended up 25 points apart from itself. This screen only asks
   * "is my check id in here".
   */
  blockedChecks?: Record<string, string>
  blockedSince?: string | null
  blockedStatus?: number | null
}

export interface HistoryFilter {
  clientId?: string
  vendorId?: string
  /** YYYY-MM-DD, inclusive at both ends. `to` names a DAY, so a call
   *  stamped 17:40 on it belongs to it. */
  from?: string
  to?: string
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
  /**
   * Run the vendor's selection, or ONLY the checks named in `only`.
   *
   * `only` exists because re-running costs money. The server does not skip
   * a check that already answered — it runs what it is given — so a "run
   * more checks" control that re-posted the whole selection would silently
   * re-call and re-bill every check the analyst had already paid for.
   * Passing the delta is what makes that control safe, and the server
   * drops any prerequisite already on file rather than buying it twice.
   */
  runChecks(id: string, only?: string[]): Promise<RunChecksResult>

  /** Choose which result of a check the score and the report read.
   *  MOVES A CLIENT-FACING NUMBER, so the server writes it to the audit
   *  log with a name and a timestamp. */
  markPrimary(vendorId: string, runId: number): Promise<Vendor>

  /**
   * Set one result aside. It is KEPT; it stops counting.
   *
   * THIS REPLACED A DELETE. Deleting did what the analyst wanted — take
   * a result out of the score — by destroying the evidence and the
   * spend record to get there. Two commitments were in conflict and it
   * resolved them the wrong way: a result is evidence and evidence is
   * kept, and a call that cost money stays in the ledger whatever
   * anybody later decides about its answer.
   *
   * `reason` is required by the server. Ignoring moves a client-facing
   * number, so the file has to say why.
   *
   * Ignoring the result that counts promotes the newest one still in
   * force. Ignoring the last one leaves the check unscored and SAID to
   * be set aside, never silently and never as "not checked".
   */
  ignoreRun(vendorId: string, runId: number, reason: string): Promise<Vendor>

  /** Put a result back in force. Reversible because the judgement it
   *  records is a person's, and people reconsider. Both directions are
   *  audited. */
  unignoreRun(vendorId: string, runId: number): Promise<Vendor>

  addManualEntry(id: string, entry: Omit<ManualEntry, 'id'>): Promise<Vendor>
  removeManualEntry(id: string, entryId: string): Promise<Vendor>

  setSurveillance(id: string, values: Record<string, string | null>): Promise<Vendor>
  completeSurveillance(id: string): Promise<Vendor>

  setScanRating(id: string, paramId: string, value: string | null): Promise<Vendor>

  recordDecision(id: string, input: DecisionInput): Promise<Vendor>

  listAudit(vendorId?: string): Promise<AuditEntry[]>

  /**
   * Every API call made, with what it cost, for whom.
   *
   * THE LEDGER, as distinct from the audit log above. The audit log
   * answers "what happened and who did it", in sentences; prose cannot
   * be summed. This answers "what has been spent, on which vendor, for
   * which client", which is a question about money and therefore about
   * numbers that add up.
   *
   * Ignored results are included and marked: a result taken out of the
   * score was still a call that was paid for.
   */
  listHistory(filter?: HistoryFilter): Promise<HistoryPage>
  listCostReference(): Promise<
    readonly { group: string; item: string; unit: string; source: string }[]
  >

  /** Which sources are live, and which are refusing our account. */
  listProviderStatus(): Promise<readonly ProviderStatus[]>
}
