/**
 * Scoring — PREVIEW ONLY.
 *
 * ============================ READ THIS ============================
 * The backend is the authority on every score this platform records.
 * These functions exist so the SCAN page can recalculate instantly as an
 * analyst clicks through 18 parameters, without a network round-trip per
 * click. They are a mirror of backend/app/domain/scoring.py.
 *
 * Rules:
 *   1. A number produced here is never persisted. On save, the server
 *      recomputes and its answer wins.
 *   2. Any change to the Python engine must be reflected here in the same
 *      commit. The parity test in scoring/parity.test.ts runs both
 *      implementations over the shared fixtures and fails on divergence.
 *   3. If you find yourself wanting logic here that does not exist in
 *      Python, that is a sign the logic belongs in Python.
 *
 * Two implementations of the same rules is a real hazard, accepted here
 * for responsiveness and fenced by the parity test. It is not a licence
 * to let them drift.
 * ===================================================================
 */

import {
  PILLARS,
  RISK_BANDS,
  RISK_BASELINE,
  RISK_RULES,
  SCAN_PARAMETERS,
  SURVEILLANCE_PARAMETERS,
  SURVEILLANCE_THRESHOLD_PCT,
  CHECKS,
} from '@/catalog/generated'
import type {
  CheckResult,
  GatedVerdict,
  LedgerLine,
  PillarKey,
  PillarScore,
  Rating,
  RiskScore,
  ScanScore,
  SurveillanceScore,
  VerdictName,
} from '@/types/domain'
import { IS_ADVERSE } from '@/types/domain'

const TOLERANCE_PASS = 0.6
const TOLERANCE_WATCH = 0.5

/** Match Python's round-to-4 so floating point noise cannot diverge. */
const r4 = (n: number): number => Number(n.toFixed(4))

/**
 * Compare on letters and digits only — the backend's `ScanParameter._key`.
 *
 * "> 10 Years" and ">10 Years" are the same answer. This matters because
 * stored ratings carry whatever spelling was written at the time, and the
 * runner's own wording has changed: rows written before 5 Oct 2026 hold
 * "> 10 Years" where the catalog now says ">10 Years".
 */
const optionKey = (value: string): string =>
  value.toLowerCase().replace(/[^a-z0-9]/g, '')

/**
 * An option string to a colour, or null for "not applicable".
 *
 * This used to be `o.value === value`, an exact match, while the backend
 * compared on `_key`. So a stored spelling the catalog no longer uses
 * resolved there and returned null here — and a null drops the parameter
 * out of BOTH sides of the fraction, silently measuring the vendor against
 * a smaller bar.
 *
 * That is not a hypothetical: an unrecognised option is exactly how every
 * approved vendor once scored 100%. The same failure, in the copy of the
 * model that is actually on screen.
 */
const ratingOf = (
  options: readonly { readonly value: string; readonly rating: string }[],
  value: string | null | undefined,
): Rating | null => {
  if (value === null || value === undefined) return null
  const wanted = optionKey(value)
  const hit = options.find((o) => optionKey(o.value) === wanted)
  return hit ? (hit.rating as Rating) : null
}

/* ===================================================================
   SCAN
   =================================================================== */

export function scoreScan(ratings: Record<string, string | null>): ScanScore {
  const pillars = {} as Record<PillarKey, PillarScore>
  for (const p of PILLARS) {
    pillars[p.key as PillarKey] = {
      key: p.key as PillarKey,
      name: p.name,
      subtitle: p.subtitle,
      weight: p.weight,
      applicable: 0,
      G: 0,
      Y: 0,
      R: 0,
      positives: 0,
      weighted: 0,
      max: 0,
    }
  }

  /*
    TWO PASSES, MIRRORING app/domain/scoring.py EXACTLY.

    This file is a SECOND implementation of the client's scoring model, and
    it is what every number on screen comes from — the backend's answer is
    stored, not displayed. It was left on the pre-migration model while the
    backend moved, so the two disagreed by up to 25 points on the same
    vendor, either side of a 60% pass mark. A screen that contradicts the
    database is worse than either being wrong on its own.

    Pass one counts what is applicable. Pass two fills the colour buckets,
    because the A pillar's share depends on how many A parameters were
    answered — which is not known until pass one finishes.
  */
  const rated: { param: (typeof SCAN_PARAMETERS)[number]; rating: Rating }[] = []
  for (const param of SCAN_PARAMETERS) {
    const rating = ratingOf(param.options, ratings[param.id])
    if (!rating) continue // not applicable — leaves both sides of the fraction
    pillars[param.pillar as PillarKey].applicable += 1
    rated.push({ param, rating })
  }

  /*
    The A pillar is a WEIGHTED BLEND, not a count.

    Every other pillar adds one whole parameter per rating. A adds a
    FRACTION — that dimension's share of the psychometric test, scaled by
    how many dimensions were answered:

        bucket += applicable_A_count × subWeight

    Integrity .5 · Business Acumen .3 · Risk Taking .1 · Problem Solving .1.
    So A totals come out fractional: Innovatiview, with four applicable,
    gives G=0.4 Y=1.6 R=2.0. A plain counter cannot reach those numbers,
    which is how the defect was found rather than argued about.
  */
  const aApplicable = pillars.A.applicable
  for (const { param, rating } of rated) {
    const bucket = pillars[param.pillar as PillarKey]
    const share =
      param.pillar === 'A' && param.subWeight ? aApplicable * param.subWeight : 1
    bucket[rating] += share
  }

  let weighted = 0
  let best = 0
  let applicable = 0

  for (const bucket of Object.values(pillars)) {
    /*
      HALF A GREEN, NOT NONE.

      This was `G + Math.floor(Y / 2)`. The workbook computes `=D8+(D9/2)`
      with no rounding at all, so one Yellow is worth half a Green. The
      floor is the tempting reading of "2 Yellow = 1 Green" and it is wrong
      in the direction that matters — it marks a vendor down for a middling
      answer instead of giving them the half they earned.

      `scoreSurveillance` below KEEPS its floor on purpose: the backend's
      `score_surveillance` floors too, and matching it is the point.
    */
    bucket.positives = r4(bucket.G + bucket.Y / 2)
    bucket.weighted = r4(bucket.positives * bucket.weight)
    bucket.max = r4(bucket.applicable * bucket.weight)
    weighted += bucket.weighted
    best += bucket.max
    applicable += bucket.applicable
  }

  weighted = r4(weighted)
  best = r4(best)

  const pct = best > 0 ? Number(((weighted / best) * 100).toFixed(1)) : 0
  const tolerance60 = r4(best * TOLERANCE_PASS)
  /*
    STRICTLY greater. The workbook asks `=IF(H16>D20, "Positive", ...)`.
    With `>=` a vendor landing exactly on the bar was Positive here and
    Negative there. No case on file lands exactly on it, which is precisely
    why it would have been found late and in front of a client.
  */
  const passed = best > 0 && weighted > tolerance60
  const total = SCAN_PARAMETERS.length

  return {
    pillars,
    weighted,
    best,
    tolerance60,
    tolerance50: r4(best * TOLERANCE_WATCH),
    applicable,
    total,
    pct,
    passed,
    verdict:
      best === 0
        ? 'Not Scored'
        : passed
          ? 'Positive for Onboarding'
          : 'Negative for Onboarding',
    assessmentEvaluated: pillars.A.applicable > 0,
    coverageNote: `${pct.toFixed(1)}% achieved, based on ${applicable} of ${total} parameters`,
    isScored: best > 0,
  }
}

/* ===================================================================
   Site surveillance
   =================================================================== */

export function scoreSurveillance(
  values: Record<string, string | null>,
  done = true,
): SurveillanceScore {
  if (!done) {
    return {
      done: false,
      applicable: 0,
      G: 0,
      Y: 0,
      R: 0,
      positives: 0,
      pct: 0,
      gateFailed: false,
      passed: false,
      verdict: 'Not conducted',
      scanValue: null,
    }
  }

  let applicable = 0
  let G = 0
  let Y = 0
  let R = 0
  let gateFailed = false

  for (const param of SURVEILLANCE_PARAMETERS) {
    const rating = ratingOf(param.options, values[param.id])
    if (!rating) continue
    applicable += 1
    if (rating === 'G') G += 1
    else if (rating === 'Y') Y += 1
    else {
      R += 1
      // The hard gate: no premises, no positive result, whatever the rest say.
      if (param.hardGate) gateFailed = true
    }
  }

  const positives = G + Math.floor(Y / 2)
  const pct = applicable ? Number(((positives / applicable) * 100).toFixed(1)) : 0
  const passed = !gateFailed && pct >= SURVEILLANCE_THRESHOLD_PCT

  return {
    done: true,
    applicable,
    G,
    Y,
    R,
    positives,
    pct,
    gateFailed,
    passed,
    verdict: passed ? 'Positive' : 'Negative',
    scanValue: passed ? 'Positive' : 'Negative',
  }
}

/* ===================================================================
   0-100 risk ledger
   =================================================================== */

const checkById = (id: string) => CHECKS.find((c) => c.id === id)
const isConfigured = (id: string) => checkById(id)?.state === 'active'

const statusOf = (checks: Record<string, CheckResult>, id: string) =>
  checks[id]?.status ?? null

const didPass = (checks: Record<string, CheckResult>, id: string) =>
  statusOf(checks, id) === 'pass'

const isAdverse = (checks: Record<string, CheckResult>, id: string) => {
  const status = statusOf(checks, id)
  return status !== null && IS_ADVERSE.includes(status)
}

const domainOlderThan2y = (checks: Record<string, CheckResult>): boolean => {
  const result = checks['whois']
  if (!result || result.status !== 'pass') return false
  const match = /(\d+)\s*yrs?/i.exec(String(result.value ?? ''))
  return !!match && Number(match[1]) >= 2
}

const RULE_TESTS: Record<string, (c: Record<string, CheckResult>) => boolean> = {
  r1: (c) => didPass(c, 'master'),
  r2: (c) => didPass(c, 'filings'),
  r3: (c) => didPass(c, 'fin'),
  r4: domainOlderThan2y,
  r5: (c) => didPass(c, 'cdx'),
  r6: (c) => didPass(c, 'ssl'),
  r7: (c) => isAdverse(c, 'charges'),
  r8: (c) => isAdverse(c, 'dup'),
  r9: (c) => isAdverse(c, 'rp'),
  r10: () => false,
  r11: () => false,
  r12: () => false,
  r13: () => false,
}

export function scoreRisk(
  checks: Record<string, CheckResult>,
  selected: string[] = [],
): RiskScore {
  const selection = new Set(selected)
  const ledger: LedgerLine[] = RISK_RULES.map((rule) => {
    const unconfigured = rule.needs.filter((n) => !isConfigured(n))

    /*
      A rule is AVAILABLE only if something it reads actually RAN.

      Counting the exclusions separately is not enough. A rule reading two
      checks — one with no provider, one the analyst deselected — matched
      neither "all unconfigured" nor "all unselected", so it reported
      AVAILABLE and contributed zero points. Zero from a rule that looked
      and zero from a rule that never looked are the same number and mean
      opposite things.

      r13 (adverse news + court records) hit exactly this the moment court
      gained a provider: news is still a hook, court is real but often
      unticked, so the rule claimed to be participating while reading
      nothing. The backend was fixed; this copy was not, and the two have
      disagreed on every vendor since.
    */
    const ran = rule.needs.filter((n) => isConfigured(n) && selection.has(n))

    let state: LedgerLine['state'] = 'available'
    let applied = false

    if (unconfigured.length === rule.needs.length) {
      state = 'not_configured'
    } else if (ran.length === 0) {
      // Something exists, but none of it ran.
      state = 'not_selected'
    } else {
      try {
        applied = !!RULE_TESTS[rule.id](checks)
      } catch {
        // A malformed payload must never break scoring.
        applied = false
      }
    }

    const explanation =
      state === 'not_configured'
        ? 'source not configured'
        : state === 'not_selected'
          ? 'check not selected for this vendor'
          : applied
            ? 'applied'
            : 'condition not met'

    return {
      id: rule.id,
      label: rule.label,
      points: rule.points,
      needs: [...rule.needs],
      state,
      applied,
      contribution: applied ? rule.points : 0,
      explanation,
    }
  })

  const raw = ledger.reduce((a, l) => a + l.contribution, 0)
  const score = Math.max(0, Math.min(100, RISK_BASELINE + raw))
  const band =
    RISK_BANDS.find((b) => score >= b.min && score <= b.max) ??
    RISK_BANDS[RISK_BANDS.length - 1]
  const dead = ledger.filter((l) => l.state !== 'available').length

  return {
    score,
    raw,
    baseline: RISK_BASELINE,
    ledger,
    band: { ...band },
    gained: ledger.filter((l) => l.applied && l.points > 0).reduce((a, l) => a + l.points, 0),
    lost: ledger.filter((l) => l.applied && l.points < 0).reduce((a, l) => a + l.points, 0),
    dead,
    participating: ledger.length - dead,
  }
}

/* ===================================================================
   Coverage policy (§18.1)
   =================================================================== */

export interface CoveragePolicy {
  version: string
  minAssessmentParameters: number
  minApplicableParameters: number
  requireGstEvidence: boolean
}

export const DEFAULT_POLICY: CoveragePolicy = {
  version: '1.0',
  minAssessmentParameters: 2,
  minApplicableParameters: 8,
  requireGstEvidence: false,
}

export const PROTOTYPE_POLICY: CoveragePolicy = {
  version: '0.0-prototype',
  minAssessmentParameters: 0,
  minApplicableParameters: 0,
  requireGstEvidence: false,
}

export function applyPolicy(
  scan: ScanScore,
  policy: CoveragePolicy = DEFAULT_POLICY,
  hasGstEvidence = false,
): GatedVerdict {
  const raw: VerdictName = !scan.isScored
    ? 'Not Scored'
    : scan.passed
      ? 'Positive for Onboarding'
      : 'Negative for Onboarding'

  const reasons: string[] = []

  // Only a would-be Positive is gated. Thin evidence must never manufacture
  // a rejection.
  if (raw === 'Positive for Onboarding') {
    const assessed = scan.pillars.A.applicable
    if (assessed < policy.minAssessmentParameters) {
      reasons.push(
        `Only ${assessed} of 4 Assessment parameters were evaluated, below the ` +
          `floor of ${policy.minAssessmentParameters}. Assessment carries weight ` +
          `0.60 — the heaviest in the framework — and site surveillance, market ` +
          `references and the psychometric result are the substantive checks in it.`,
      )
    }
    if (scan.applicable < policy.minApplicableParameters) {
      reasons.push(
        `Only ${scan.applicable} of ${scan.total} parameters were applicable, ` +
          `below the floor of ${policy.minApplicableParameters} required for a ` +
          `positive recommendation.`,
      )
    }
    if (policy.requireGstEvidence && !hasGstEvidence) {
      reasons.push(
        'No GST evidence on file. While the GST API is unconfigured this must ' +
          'be recorded manually before a positive verdict.',
      )
    }
  }

  const gated = reasons.length > 0
  const verdict: VerdictName = gated ? 'Insufficient Coverage — Senior Review' : raw

  return {
    verdict,
    rawVerdict: raw,
    policyVersion: policy.version,
    gated,
    reasons,
    headline: `${verdict} — ${scan.coverageNote}`,
  }
}
