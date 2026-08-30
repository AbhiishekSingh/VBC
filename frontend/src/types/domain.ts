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

export interface CheckResult {
  checkId: string
  status: CheckStatus
  value: string
  detail: string
  rawResponse?: unknown
  costPaisa?: number
  fetchedAt?: string
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
  stage: VendorStage
  decision: string | null
  decisionRemarks?: string
  decidedBy?: string
  unlocked: boolean
  submitted: string
  selected: string[]
  inputs: Record<string, Record<string, string>>
  checks: Record<string, CheckResult>
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
