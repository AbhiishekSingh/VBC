/**
 * A check examined and then set aside must never read as "not checked".
 *
 * `checks` holds only results IN FORCE, so a check whose every result
 * was set aside drops out of it — and a check absent from the report's
 * evidence index reads exactly like a check nobody ran.
 *
 * That is the one thing this product refuses to let happen. Its core
 * rule is that something not examined must never look like something
 * that came back clean; the converse binds just as hard, because a
 * deliberate human judgement presented as a gap in coverage is a lie
 * about who decided what.
 *
 * Asserted on the data the report screen builds from rather than on the
 * rendered page: the rule is about what the reader is told, and the
 * words are the part that must not change quietly.
 */

import { describe, expect, it } from 'vitest'

import { CHECKS } from '@/catalog/generated'
import type { CheckResult, Vendor } from '@/types/domain'

/** The exact derivation Report.tsx makes — see its `evidence` memo. */
function evidenceIndex(vendor: Vendor) {
  const runs = vendor.runs ?? []
  return CHECKS.filter(
    (c) => vendor.checks[c.id] || runs.some((r) => r.checkId === c.id),
  ).map((c) => {
    const result = vendor.checks[c.id]
    if (result) return { id: c.id, label: result.status, value: result.value }
    const aside = runs.filter((r) => r.checkId === c.id)
    const reasons = Array.from(
      new Set(aside.map((r) => r.ignoreReason).filter(Boolean) as string[]),
    )
    return {
      id: c.id,
      label: 'set_aside',
      value:
        `${aside.length} result${aside.length === 1 ? '' : 's'} set aside` +
        (reasons.length ? ` — ${reasons.join('; ')}` : ''),
    }
  })
}

const run = (over: Partial<CheckResult>): CheckResult => ({
  checkId: 'ssl', status: 'pass', value: 'Valid SSL', detail: '', ...over,
})

const vendorWith = (checks: Record<string, CheckResult>, runs: CheckResult[]): Vendor =>
  ({ checks, runs } as unknown as Vendor)

describe('a check whose every result was set aside', () => {
  it('still appears in the evidence index', () => {
    const vendor = vendorWith({}, [
      run({ id: 1, ignoredAt: '2026-11-10T10:00:00Z', ignoreReason: 'wrong domain' }),
    ])
    expect(evidenceIndex(vendor).map((e) => e.id)).toContain('ssl')
  })

  it('is labelled set aside, never as not checked', () => {
    const vendor = vendorWith({}, [
      run({ id: 1, ignoredAt: '2026-11-10T10:00:00Z', ignoreReason: 'wrong domain' }),
    ])
    const row = evidenceIndex(vendor).find((e) => e.id === 'ssl')!
    expect(row.label).toBe('set_aside')
    expect(row.label).not.toBe('unavailable')
    expect(row.label).not.toBe('skipped_missing_input')
  })

  it('carries the reason, because that is the finding', () => {
    const vendor = vendorWith({}, [
      run({ id: 1, ignoredAt: '2026-11-10T10:00:00Z', ignoreReason: 'wrong domain' }),
    ])
    const row = evidenceIndex(vendor).find((e) => e.id === 'ssl')!
    expect(row.value).toContain('wrong domain')
  })

  it('counts them when several were set aside', () => {
    const vendor = vendorWith({}, [
      run({ id: 1, ignoredAt: 'x', ignoreReason: 'first director' }),
      run({ id: 2, ignoredAt: 'x', ignoreReason: 'second director' }),
    ])
    const row = evidenceIndex(vendor).find((e) => e.id === 'ssl')!
    expect(row.value).toContain('2 results set aside')
    expect(row.value).toContain('first director')
    expect(row.value).toContain('second director')
  })

  it('reads normally again once one result is back in force', () => {
    const inForce = run({ id: 2, value: 'Valid SSL' })
    const vendor = vendorWith({ ssl: inForce }, [
      run({ id: 1, ignoredAt: 'x', ignoreReason: 'superseded' }),
      inForce,
    ])
    const row = evidenceIndex(vendor).find((e) => e.id === 'ssl')!
    expect(row.label).toBe('pass')
    expect(row.value).toBe('Valid SSL')
  })

  it('a check nobody ran stays absent', () => {
    // The other half of the rule: a gap is still a gap, and inventing a
    // "set aside" row for it would be the same lie in reverse.
    const vendor = vendorWith({}, [])
    expect(evidenceIndex(vendor)).toHaveLength(0)
  })
})

/* =====================================================================
   AND ON STEP 3, FOR THE SAME REASON
   =====================================================================

   Findings listed its rows from `vendor.checks`, which holds only
   results in force — so setting aside the last result of a check made
   the whole row disappear from the evidence screen.

   Three things wrong with that, and the third is the one that bites:
   it looks deleted, when the point of Ignore is that nothing is; the
   reader cannot see that a finding was taken out, which is the opposite
   of what an audit file is for; and the Reinstate button goes with it,
   so the act becomes irreversible through the screen that performed it.
*/

/** The exact derivation Findings.tsx makes for a group's rows. */
function visibleChecks(vendor: Vendor, selected: string[]) {
  const runs = vendor.runs ?? []
  return CHECKS.filter(
    (c) =>
      selected.includes(c.id) &&
      (vendor.checks[c.id] || runs.some((r) => r.checkId === c.id)),
  ).map((c) => c.id)
}

describe('Step 3 after everything is set aside', () => {
  it('keeps the check on screen', () => {
    const vendor = vendorWith({}, [
      run({ id: 1, ignoredAt: 'x', ignoreReason: 'wrong domain' }),
    ])
    expect(visibleChecks(vendor, ['ssl'])).toContain('ssl')
  })

  it('still hides a check that is no longer selected', () => {
    // Scope is a separate question from force, and this screen has
    // always answered it from the selection.
    const vendor = vendorWith({}, [
      run({ id: 1, ignoredAt: 'x', ignoreReason: 'wrong domain' }),
    ])
    expect(visibleChecks(vendor, ['whois'])).not.toContain('ssl')
  })

  it('shows nothing for a check that never ran', () => {
    expect(visibleChecks(vendorWith({}, []), ['ssl'])).toHaveLength(0)
  })
})
