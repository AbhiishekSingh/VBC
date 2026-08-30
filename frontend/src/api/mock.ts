/**
 * In-memory adapter.
 *
 * Keeps the app fully clickable with no backend. It is not a stub: check
 * running, prerequisite expansion, missing-input skipping and manual-field
 * mapping all behave as specified, because the point of this adapter is to
 * let the client walk the real flow and to let the pages be built against
 * realistic behaviour rather than empty promises.
 *
 * State lives in module scope and resets on reload. Nothing is persisted —
 * that is the backend's job.
 */

import { CHECKS, MANUAL_TEMPLATES, SCAN_PARAMETERS } from '@/catalog/generated'
import { scoreSurveillance } from '@/scoring'
import { SEED_AUDIT, SEED_VENDORS, COST_REFERENCE } from './fixtures'
import type { AuditEntry, CheckResult, Client, ManualEntry, User, Vendor } from '@/types/domain'
import type { DecisionInput, VbcApi } from './contract'

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v))

let vendors: Vendor[] = clone(SEED_VENDORS)
let audit: AuditEntry[] = clone(SEED_AUDIT)
let nextId = 234481

const latency = <T>(value: T, ms = 90): Promise<T> =>
  new Promise((resolve) => setTimeout(() => resolve(value), ms))

const stamp = (): string => {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

export const CURRENT_ANALYST = 'a.mehta'

function log(vendorId: string | null, action: string, detail: string, actor = CURRENT_ANALYST) {
  audit = [{ ts: stamp(), vendorId, actor, action, detail }, ...audit]
}

const find = (id: string): Vendor => {
  const v = vendors.find((x) => x.id === id)
  if (!v) throw new Error(`Unknown vendor: ${id}`)
  return v
}

const checkDef = (id: string) => CHECKS.find((c) => c.id === id)

/**
 * Apply a manual entry's SCAN mapping, if it has one.
 *
 * Runs on load as well as on edit, so a filed entry and the score it
 * justifies can never drift apart.
 */
export function applyManualMapping(vendor: Vendor, entry: ManualEntry): string | null {
  if (!entry.templateId) return null
  const tpl = MANUAL_TEMPLATES.find((t) => t.id === entry.templateId)
  if (!tpl?.mapsTo) return null
  const target = (tpl.mapWhen as Record<string, string>)[entry.value]
  if (!target) return null
  vendor.scan[tpl.mapsTo] = target
  return `${tpl.mapsTo} → ${target}`
}

/** Resolve a check's input value: analyst entry, then vendor prefill, then default. */
export function inputValue(vendor: Vendor, checkId: string, paramKey: string): string {
  const stored = vendor.inputs?.[checkId]?.[paramKey]
  if (stored !== undefined) return stored

  const def = checkDef(checkId)
  const param = def?.params.find((p) => p.key === paramKey)
  if (!param) return ''

  if (param.fromVendor) {
    const fromVendor = vendor[param.fromVendor as keyof Vendor]
    if (typeof fromVendor === 'string' && fromVendor) return fromVendor
  }
  return param.default ?? ''
}

/** Required inputs still blank across the current selection. */
export function missingInputs(
  vendor: Vendor,
): { checkId: string; checkName: string; paramKey: string; paramLabel: string }[] {
  const out: ReturnType<typeof missingInputs> = []
  for (const checkId of vendor.selected) {
    const def = checkDef(checkId)
    if (!def) continue
    for (const param of def.params) {
      if (!param.required) continue
      // A value another check supplies is not the analyst's problem.
      if (param.fromResult && vendor.selected.includes(param.fromResult)) continue
      if (!inputValue(vendor, checkId, param.key).trim()) {
        out.push({
          checkId,
          checkName: def.name,
          paramKey: param.key,
          paramLabel: param.label,
        })
      }
    }
  }
  return out
}

/**
 * Simulated check outcomes, keyed off what the vendor record actually says.
 *
 * The rules are crude by design — the real adapters replace them entirely.
 * What matters is that the *shape* of the outcome is right: a check with no
 * usable identifier fails rather than passing, and a missing required input
 * skips one check rather than blocking the run.
 */
function simulate(vendor: Vendor, checkId: string): CheckResult {
  const seeded = SEED_VENDORS.find((v) => v.id === vendor.id)?.checks?.[checkId]
  if (seeded) return clone(seeded)

  const base = { checkId, value: '', detail: '' }
  const def = checkDef(checkId)

  if (def?.state === 'not_configured') {
    return { ...base, status: 'not_configured', value: 'No provider', detail: 'This check has no provider wired up.' }
  }

  const needsCin = ['master', 'dirs', 'charges', 'filings', 'fin', 'ustatus', 'refresh']
  const needsDomain = ['whois', 'reput', 'ssl', 'rwhois', 'avail', 'cdx', 'shot']

  if (needsCin.includes(checkId) && !vendor.cin) {
    return { ...base, status: 'fail', value: 'No CIN on record', detail: 'MCA holds no record without a CIN — consistent with an unincorporated entity.' }
  }
  if (needsDomain.includes(checkId) && !vendor.domain) {
    return { ...base, status: 'fail', value: 'No domain', detail: 'No registered domain traced to this entity.' }
  }
  if (checkId === 'dup') {
    return { ...base, status: 'pass', value: 'No duplicate', detail: 'No matching GST/PAN in the vendor master.' }
  }
  if (checkId === 'conflict') {
    return { ...base, status: 'pass', value: 'No conflict', detail: 'No overlap with employee records.' }
  }
  return { ...base, status: 'pass', value: 'Retrieved', detail: 'Check completed against the provider.' }
}

// ---------------------------------------------------------------------
// Mock clients. Vendors carry clientId; anything without one lands in
// the same holding client the migration creates.
// ---------------------------------------------------------------------

const HOLDING = 'CL000000'

const clients: Client[] = [
  { id: HOLDING, name: 'Unassigned', legalName: 'Unassigned', industry: '',
    spoc: '', email: '', phone: '', notes: 'Vendors that predate the client layer.',
    active: true, createdAt: '2026-07-01T09:00:00Z', vendorCount: 0, decidedCount: 0 },
  { id: 'CL000001', name: 'Reliance Industries', legalName: 'Reliance Industries Limited',
    industry: 'Conglomerate', spoc: 'R Shah', email: 'procurement@ril.example',
    phone: '+91 22 3555 5000', notes: '', active: true,
    createdAt: '2026-07-14T09:00:00Z', vendorCount: 0, decidedCount: 0 },
  { id: 'CL000002', name: 'Tata Steel', legalName: 'Tata Steel Limited',
    industry: 'Steel', spoc: 'P Iyer', email: 'vendors@tatasteel.example',
    phone: '+91 657 664 5000', notes: '', active: true,
    createdAt: '2026-08-02T09:00:00Z', vendorCount: 0, decidedCount: 0 },
]

const MOCK_USER: User = {
  id: 'US000001', email: 'a.mehta@q1ssl.com', name: 'A Mehta',
  role: 'approver',
  permissions: ['decide', 'rate', 'read', 'record_manual', 'run_checks'],
}

let signedIn = false

function withCounts(client: Client): Client {
  const mine = vendors.filter((v) => v.clientId === client.id)
  return {
    ...client,
    vendorCount: mine.length,
    decidedCount: mine.filter((v) => v.decision).length,
  }
}

export const mockApi: VbcApi = {
  // --- auth ---------------------------------------------------------
  // Mock mode accepts any password: it exists to demo screens without a
  // backend, and a fake credential check would only teach the wrong habit.
  async login(email) {
    signedIn = true
    return latency({ ...MOCK_USER, email: email || MOCK_USER.email })
  },

  async logout() {
    signedIn = false
    return latency(undefined)
  },

  async me() {
    return latency(signedIn ? { ...MOCK_USER } : null)
  },

  // --- clients ------------------------------------------------------
  async listClients(includeInactive = false) {
    const rows = clients.filter((c) => includeInactive || c.active).map(withCounts)
    return latency(clone(rows))
  },

  async getClient(id) {
    const found = clients.find((c) => c.id === id)
    return latency(found ? clone(withCounts(found)) : null)
  },

  async createClient(input) {
    const used = clients.map((c) => Number(c.id.replace(/\D/g, '')) || 0)
    const client: Client = {
      id: `CL${String(Math.max(0, ...used) + 1).padStart(6, '0')}`,
      name: input.name,
      legalName: input.legalName || input.name,
      industry: input.industry ?? '',
      spoc: input.spoc ?? '',
      email: input.email ?? '',
      phone: input.phone ?? '',
      notes: input.notes ?? '',
      active: true,
      createdAt: new Date().toISOString(),
      vendorCount: 0,
      decidedCount: 0,
    }
    clients.push(client)
    return latency(clone(client))
  },

  async updateClient(id, body) {
    const found = clients.find((c) => c.id === id)
    if (!found) throw new Error(`No client ${id}`)
    Object.assign(found, body)
    return latency(clone(withCounts(found)))
  },

  async deactivateClient(id) {
    const found = clients.find((c) => c.id === id)
    if (!found) throw new Error(`No client ${id}`)
    found.active = false
    return latency(clone(withCounts(found)))
  },

  // --- vendors ------------------------------------------------------
  async listVendors(clientId) {
    // Mappings are re-applied on read so a filed entry and its score agree.
    for (const v of vendors) for (const e of v.manual) applyManualMapping(v, e)
    const rows = clientId ? vendors.filter((v) => v.clientId === clientId) : vendors
    return latency(clone(rows))
  },

  async getVendor(id) {
    const v = vendors.find((x) => x.id === id)
    if (!v) return latency(null)
    for (const e of v.manual) applyManualMapping(v, e)
    return latency(clone(v))
  },

  async createVendor(draft) {
    const id = String(nextId++)
    const clientId = draft.clientId ?? HOLDING
    const vendor: Vendor = {
      id,
      clientId,
      clientName: clients.find((c) => c.id === clientId)?.name ?? '',
      name: draft.name ?? 'Unnamed vendor',
      legalName: draft.legalName || (draft.name ?? '').toUpperCase(),
      address: draft.address ?? '',
      material: draft.material ?? '',
      spoc: draft.spoc ?? '',
      designation: draft.designation ?? '',
      gst: draft.gst || null,
      pan: draft.pan || null,
      cin: draft.cin || null,
      domain: draft.domain || null,
      website: draft.website || null,
      stage: 'select',
      decision: null,
      unlocked: false,
      submitted: stamp().slice(0, 16),
      selected: [],
      inputs: {},
      checks: {},
      scan: Object.fromEntries(SCAN_PARAMETERS.map((p) => [p.id, null])),
      manual: [],
      surveillance: {},
      surveillanceDone: false,
    }
    vendors = [vendor, ...vendors]
    log(id, 'VENDOR_SUBMITTED', `${vendor.name} submitted via intake form`)
    return latency(clone(vendor))
  },

  async updateVendor(id, patch) {
    const v = find(id)
    Object.assign(v, patch)
    return latency(clone(v))
  },

  async setSelection(id, selected) {
    const v = find(id)
    v.selected = selected
    return latency(clone(v))
  },

  async setCheckInput(id, checkId, key, value) {
    const v = find(id)
    v.inputs[checkId] = { ...(v.inputs[checkId] ?? {}), [key]: value }
    return latency(clone(v), 0)
  },

  async runChecks(id) {
    const v = find(id)
    const missing = new Set(missingInputs(v).map((m) => m.checkId))
    let costPaisa = 0
    let credits = 0
    const skipped: string[] = []

    v.checks = {}
    for (const checkId of v.selected) {
      const def = checkDef(checkId)
      if (!def) continue

      // A blank required input skips ONE check and is logged. It never
      // blocks the run, and it never disappears from the findings page.
      if (missing.has(checkId)) {
        v.checks[checkId] = {
          checkId,
          status: 'skipped_missing_input',
          value: 'Not run',
          detail: 'A required input was left blank, so this check could not be called.',
        }
        skipped.push(def.name)
        continue
      }

      v.checks[checkId] = simulate(v, checkId)
      costPaisa += def.costPaisa
      credits += def.credits
    }

    if (v.selected.some((c) => checkDef(c)?.needsCompanyUnlock) && !v.unlocked) {
      v.unlocked = true
      costPaisa += 22000
      log(id, 'COMPANY_UNLOCKED', 'Company unlocked for one year · ₹220')
    }

    v.stage = 'manual'
    const settled = Object.values(v.checks)
    log(
      id,
      'CHECKS_COMPLETE',
      `${settled.length} checks settled · ` +
        `${settled.filter((c) => c.status === 'pass').length} pass · ` +
        `${settled.filter((c) => c.status === 'warn').length} warn · ` +
        `${settled.filter((c) => c.status === 'fail').length} fail` +
        (skipped.length ? ` · ${skipped.length} skipped for missing input` : ''),
      'system',
    )

    return latency({ vendor: clone(v), ran: settled.length, skippedMissingInput: skipped, costPaisa, credits }, 700)
  },

  async addManualEntry(id, entry) {
    const v = find(id)
    const full: ManualEntry = { ...entry, id: `e${Date.now()}` }
    v.manual = [...v.manual, full]
    const mapping = applyManualMapping(v, full)
    log(
      id,
      'MANUAL_FIELD_ADDED',
      `${full.key} = ${full.value}${mapping ? ` · sets ${mapping}` : ''}`,
      full.enteredBy,
    )
    return latency(clone(v))
  },

  async removeManualEntry(id, entryId) {
    const v = find(id)
    const gone = v.manual.find((e) => e.id === entryId)
    v.manual = v.manual.filter((e) => e.id !== entryId)
    if (gone) {
      // The SCAN parameter the entry justified must go with it.
      const tpl = MANUAL_TEMPLATES.find((t) => t.id === gone.templateId)
      if (tpl?.mapsTo) v.scan[tpl.mapsTo] = null
      log(id, 'MANUAL_FIELD_REMOVED', `${gone.key} removed`)
    }
    return latency(clone(v))
  },

  async setSurveillance(id, values) {
    const v = find(id)
    v.surveillance = { ...v.surveillance, ...values }
    return latency(clone(v), 0)
  },

  async completeSurveillance(id) {
    const v = find(id)
    v.surveillanceDone = true
    const result = scoreSurveillance(v.surveillance, true)
    v.scan.A2 = result.scanValue
    log(
      id,
      'SURVEILLANCE_FILED',
      `Site surveillance completed · ${result.verdict} · ${result.pct}%` +
        (result.gateFailed ? ' · forced Negative by the premises hard gate' : ''),
    )
    return latency(clone(v))
  },

  async setScanRating(id, paramId, value) {
    const v = find(id)
    v.scan[paramId] = value
    return latency(clone(v), 0)
  },

  async recordDecision(id, input: DecisionInput) {
    const v = find(id)
    v.decision = input.decision
    v.decisionRemarks = input.remarks
    v.decidedBy = MOCK_USER.email
    v.stage = 'decided'
    log(
      id,
      'DECISION_RECORDED',
      `${input.decision.toUpperCase()} — ${input.remarks}` +
        (input.overrideReason ? ` · OVERRIDE: ${input.overrideReason}` : ''),
      MOCK_USER.email,
    )
    return latency(clone(v))
  },

  async listAudit(vendorId) {
    const rows = vendorId ? audit.filter((a) => a.vendorId === vendorId) : audit
    return latency(clone(rows))
  },

  async listCostReference() {
    return latency(COST_REFERENCE)
  },
}
