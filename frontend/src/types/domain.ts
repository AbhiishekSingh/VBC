/**
 * Domain types, mirroring backend/app/domain/types.py.
 *
 * These are the shapes the API speaks. They are hand-written rather than
 * generated because they are structural (and small); the *data* — every
 * parameter, option string and weight — is generated, which is where drift
 * would actually hurt.
 */

export type Rating = 'G' | 'Y' | 'R'
export type PillarKey = 'S' | 'C' | 'A' | 'N'
export type SourceMode = 'AUTO' | 'HUMAN' | 'HOOK'
export type CheckState = 'active' | 'not_configured'

export type CheckStatus =
  | 'pass'
  | 'warn'
  | 'fail'
  | 'skip'
  | 'unavailable'
  | 'not_configured'
  | 'skipped_missing_input'

export type RuleState = 'available' | 'not_selected' | 'not_configured'

export type FieldTypeName = 'Yes / No' | 'Choice' | 'Text' | 'Number' | 'Date'

/** A check produced evidence — as opposed to being skipped or unavailable. */
export const WAS_EXAMINED: CheckStatus[] = ['pass', 'warn', 'fail']

export const IS_ADVERSE: CheckStatus[] = ['warn', 'fail']

/* ---- facts: the renderable tier between a result line and the payload --
 *
 * A check has always had two tiers — a one-line string, and `rawResponse`,
 * the exact provider bytes. Nothing sat between them, so this screen could
 * offer a sentence or twenty kilobytes of JSON and nothing in between.
 *
 * Everything here arrives PRE-FORMATTED. `₹7.69 Cr`, `02 Feb 2015` and
 * `Yes` are produced by the Python parser and travel as strings; the
 * renderer applies alignment and tone and nothing else. Two implementations
 * of Indian number formatting, one per language, is precisely the drift
 * `parity.test.ts` exists to catch for the catalog.
 */

export type FactShape =
  | 'detail'      // flat key-value
  | 'summary'     // headline statistics
  | 'table'       // repeating rows
  | 'document'    // files and long text
  | 'reference'   // operational metadata — NOT a finding about the vendor
  | 'none'        // nothing was parsed

export type FactTone = 'neutral' | 'good' | 'warn' | 'bad'
export type FactLevel = 'info' | 'warn' | 'bad'
export type FactFormat = 'text' | 'date' | 'money' | 'count' | 'url' | 'id' | 'bool'

export interface FactStat {
  label: string
  value: string
  tone?: FactTone
}

export interface FactField {
  label: string
  /** null means the provider returned nothing — rendered, not hidden. A
   *  field that disappears makes a partial response look complete. */
  value: string | null
  format?: FactFormat
  tone?: FactTone
  note?: string
}

export interface FactColumn {
  key: string
  label: string
  align?: 'left' | 'right'
  format?: FactFormat
}

export interface FactTable {
  columns: FactColumn[]
  rows: Record<string, string | number | null>[]
  /** The provider's count, which may exceed `rows.length` — 3209 filings
   *  arrive fifty at a time. */
  totalRows: number
  truncated: boolean
  /** What an empty table means AT THIS CHECK. "No charges registered" and
   *  "the search returned nothing" are different findings. */
  emptyNote?: string
}

export interface FactDocument {
  title: string
  kind: 'pdf' | 'image' | 'text'
  sizeBytes?: number
  href?: string
  excerpt?: string
  /** The excerpt is a sample, not the document. Set by the parser rather
   *  than guessed at here, so a short complete note is not rendered with a
   *  trailing ellipsis that makes it look cut off. */
  excerptTruncated?: boolean
}

/**
 * Something true of the RESPONSE, not of the vendor — a mismatch, a
 * staleness, an internal contradiction.
 *
 * Flags never carry or imply a status. A parser does not get to decide a
 * vendor is adverse because a certificate expired; it says so next to the
 * result and a person decides.
 */
export interface FactFlag {
  level: FactLevel
  label: string
  detail: string
}

export interface CheckFacts {
  shape: FactShape
  parserVersion: string
  stats?: FactStat[]
  fields?: FactField[]
  table?: FactTable
  documents?: FactDocument[]
  flags?: FactFlag[]
  /** Set when this check made no call of its own — the directors list is
   *  read out of the company master payload. The screen then says where the
   *  evidence is, instead of showing a "no payload stored" placeholder that
   *  is true of this row and misleading about the finding. */
  derivedFrom?: string
  /** Standing prose printed ABOVE the data, where `note` is printed below
   *  it. The difference is not cosmetic: the person-level checks return a
   *  named individual's PAN, date of birth and home address, and "this is
   *  personal data about a person, not a company record" has to be read
   *  BEFORE the table rather than after it. */
  lede?: string
  note?: string
}

export interface CheckResult {
  /** The row id. A check holds several results now, and "mark this one"
   *  and "delete this one" need to name which. Absent on anything
   *  constructed rather than read. */
  id?: number
  checkId: string
  status: CheckStatus
  value: string
  detail: string
  /** Derived from `rawResponse` and rebuildable from it. Absent on older
   *  rows and on anything unavailable, so every renderer must degrade to
   *  `value`/`detail` without it. */
  facts?: CheckFacts
  rawResponse?: unknown
  costPaisa?: number
  fetchedAt?: string
  /** The one result of this check that SCAN, the risk score and the
   *  report read. Exactly one per check. */
  isPrimary?: boolean
  /** What was asked, for THIS result, snapshotted when it ran.
   *  `vendor.inputs` holds one value per key, so it shows whatever was
   *  typed LAST — four runs against four directors would otherwise all
   *  claim the fourth director's number. */
  inputs?: Record<string, string>

  /* ---- set aside by a person -------------------------------------
   *
   * Null/absent means the result is IN FORCE. Set means somebody took
   * it out of the score deliberately, and said why.
   *
   * The row is kept whole either way: payload, facts and cost. History
   * still counts it, because it was still a call that was paid for.
   * This replaced a delete, which took all three away to achieve the
   * one thing the analyst actually wanted.
   */
  ignoredAt?: string | null
  ignoredBy?: string | null
  ignoreReason?: string | null
}

export interface ManualEntry {
  id: string
  key: string
  value: string
  type: FieldTypeName
  templateId: string | null
  note: string
  enteredBy: string
  enteredAt: string
}

export type VendorStage =
  | 'intake'
  | 'select'
  | 'running'
  | 'manual'
  | 'scoring'
  | 'report'
  | 'review'
  | 'decided'

export interface Client {
  id: string
  name: string
  legalName: string
  industry: string
  spoc: string
  email: string
  phone: string
  notes: string
  active: boolean
  createdAt: string
  /** Rolled up server-side so the client list needs one call, not N. */
  vendorCount: number
  decidedCount: number
}

export type Role = 'analyst' | 'approver' | 'admin'

export interface User {
  id: string
  email: string
  name: string
  role: Role
  /** What this role may do. The UI hides what the API would refuse. */
  permissions: string[]
}

export interface Vendor {
  id: string
  /** Every vendor belongs to exactly one client. */
  clientId: string
  clientName: string
  name: string
  legalName: string
  address: string
  material: string
  spoc: string
  designation: string
  /** Every identifier is nullable — nothing is compulsory at intake. */
  gst: string | null
  pan: string | null
  cin: string | null
  domain: string | null
  website: string | null
  /**
   * The vendor's own contact number, for the five person-level checks.
   *
   * Worth knowing when reading this beside `gst` and `cin`: this one
   * resolves to a PERSON. Even a company switchboard number belongs to
   * whoever holds the SIM, and what comes back is that individual's PAN,
   * date of birth and home address — not a company record.
   */
  contactMobile: string | null
  stage: VendorStage
  decision: string | null
  decisionRemarks?: string
  decidedBy?: string
  unlocked: boolean
  submitted: string
  selected: string[]
  inputs: Record<string, Record<string, string>>
  /** The PRIMARY result per check — what counts, and what the score
   *  and the report read. */
  checks: Record<string, CheckResult>
  /** EVERY result, newest first, including the ones that do not count.
   *  A check used to hold one and a re-run overwrote it. */
  runs?: CheckResult[]
  scan: Record<string, string | null>
  manual: ManualEntry[]
  surveillance: Record<string, string | null>
  surveillanceDone: boolean
}

export interface AuditEntry {
  ts: string
  vendorId: string | null
  actor: string
  action: string
  detail: string
}

/* ---- scoring results, mirroring the Python dataclasses ---------------- */

export interface PillarScore {
  key: PillarKey
  name: string
  subtitle: string
  weight: number
  applicable: number
  G: number
  Y: number
  R: number
  positives: number
  weighted: number
  max: number
}

export interface ScanScore {
  pillars: Record<PillarKey, PillarScore>
  weighted: number
  best: number
  tolerance60: number
  tolerance50: number
  applicable: number
  total: number
  pct: number
  passed: boolean
  verdict: string
  assessmentEvaluated: boolean
  coverageNote: string
  isScored: boolean
}

export interface SurveillanceScore {
  done: boolean
  applicable: number
  G: number
  Y: number
  R: number
  positives: number
  pct: number
  gateFailed: boolean
  passed: boolean
  verdict: string
  scanValue: string | null
}

export interface LedgerLine {
  id: string
  label: string
  points: number
  needs: string[]
  state: RuleState
  applied: boolean
  contribution: number
  explanation: string
}

export interface RiskBandInfo {
  key: string
  label: string
  note: string
  min: number
  max: number
}

export interface RiskScore {
  score: number
  raw: number
  baseline: number
  ledger: LedgerLine[]
  band: RiskBandInfo
  gained: number
  lost: number
  dead: number
  participating: number
}

export type VerdictName =
  | 'Positive for Onboarding'
  | 'Negative for Onboarding'
  | 'Not Scored'
  | 'Insufficient Coverage — Senior Review'

export interface GatedVerdict {
  verdict: VerdictName
  rawVerdict: VerdictName
  policyVersion: string
  gated: boolean
  reasons: string[]
  headline: string
}

/* ---- API call history -------------------------------------------------
 *
 * One row per call ever made for a vendor, with what it cost. Read by the
 * History screen and by nothing that computes a finding.
 *
 * Separate from `AuditEntry` on purpose. The audit log records ACTIONS —
 * who approved what, who set a result aside — in prose, and prose cannot
 * be summed. This is the ledger: one row, one call, one price, joined up
 * to the vendor and the client it was spent on.
 */

export interface HistoryRow {
  runId: number
  clientId: string
  clientName: string
  vendorId: string
  vendorName: string
  checkId: string
  checkName: string
  provider: string
  status: CheckStatus
  value: string
  /** What was asked, snapshotted at run time. */
  inputs: Record<string, string>
  costPaisa: number
  credits: number
  /** How many times this check had been attempted when this row ran. */
  attempts: number
  fetchedAt: string
  /** The result SCAN, the risk score and the report read. */
  isPrimary: boolean
  /** Set aside by a person — still billed, still listed. */
  ignoredAt?: string | null
  ignoredBy?: string | null
  ignoreReason?: string | null
}

export interface HistoryTotal {
  id: string
  name: string
  calls: number
  costPaisa: number
  credits: number
}

export interface HistoryPage {
  rows: HistoryRow[]
  /** Spend rolled up per client and per vendor, over the SAME filter the
   *  rows were drawn with — so the totals and the list always agree. */
  byClient: HistoryTotal[]
  byVendor: HistoryTotal[]
  totalCalls: number
  totalCostPaisa: number
  totalCredits: number
}
