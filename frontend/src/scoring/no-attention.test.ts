/**
 * The risk rules read FACTS, not statuses.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * "Attention" (status `warn`) was removed on 17 Nov 2026. It asserted
 * that something a provider returned was CONCERNING — a domain under
 * two years old, a reputation score under 80, a negative net worth, a
 * pending case — on thresholds this codebase chose. None came from a
 * client or a standard, and judging a vendor on them was never VBC's
 * job.
 *
 * THE TRAP. Four rules award points for a GOOD outcome and tested it
 * with `didPass(check)`, which worked only while the check reported
 * something other than 'pass' for the BAD outcome:
 *
 *     r1 +20  MCA registered and active        pass unless struck off
 *     r2 +10  Filings current                  pass unless none returned
 *     r3 +15  positive net worth               pass unless negative
 *     r5 +10  continuous presence, no outages  pass unless outages
 *
 * Once those checks reported 'pass' either way, r1 would have awarded
 * +20 to a struck-off company and r3 +15 for a loss. A gap reading as
 * clean is this product's cardinal failure; adverse reading as POSITIVE
 * is the same failure worth more points.
 *
 * These assertions are the mirror of `test_no_attention.py`. The two
 * scoring implementations have drifted before, which is why
 * parity.test.ts exists; this covers the part of the rule table that
 * fixture parity alone does not reach.
 */

import { describe, expect, it } from 'vitest'

import { scoreRisk } from '@/scoring'
import type { CheckResult, CheckStatus } from '@/types/domain'

const result = (
  checkId: string,
  status: CheckStatus,
  rawResponse?: unknown,
): CheckResult => ({ checkId, status, value: 'x', detail: '', rawResponse })

/** Did the named rule fire, with only these checks selected? */
const fired = (id: string, checks: Record<string, CheckResult>): boolean => {
  const score = scoreRisk(checks, Object.keys(checks))
  return score.ledger.find((l) => l.id === id)?.applied === true
}

describe('a positive rule reads the fact, not the status', () => {
  const cases: Array<[string, string, unknown, unknown]> = [
    ['r1', 'master', { facts: { status: 'ACTIVE' } }, { facts: { status: 'STRUCK OFF' } }],
    ['r2', 'filings', { rows: [{ formId: 'AOC-4' }] }, { rows: [] }],
    ['r3', 'fin', { facts: { positive_net_worth: true } }, { facts: { positive_net_worth: false } }],
    ['r5', 'cdx', { continuous: true }, { continuous: false }],
  ]

  it.each(cases)('%s fires on the good fact only', (rule, check, good, bad) => {
    expect(fired(rule, { [check]: result(check, 'pass', good) })).toBe(true)
    expect(fired(rule, { [check]: result(check, 'pass', bad) })).toBe(false)
  })
})

describe('an open charge still costs points', () => {
  it('fires on the payload now that charges reports pass', () => {
    expect(fired('r7', {
      charges: result('charges', 'pass', { open: [{ holder: 'HDFC' }], closed: [] }),
    })).toBe(true)
  })

  it('does not fire when every charge is satisfied', () => {
    expect(fired('r7', {
      charges: result('charges', 'pass', { open: [], closed: [{ holder: 'SBI' }] }),
    })).toBe(false)
  })
})

describe('a result with no payload falls back to its status', () => {
  /*
    A MANUALLY RECORDED result carries no provider payload at all, and
    neither does a row stored before the check kept its raw response.
    Reading "no payload" as "the fact is false" would silently stop
    r1, r2, r3, r5 and r7 scoring for every one of them.
  */
  it.each([['r1', 'master'], ['r2', 'filings'], ['r3', 'fin'], ['r5', 'cdx']])(
    '%s still fires on a bare pass',
    (rule, check) => {
      expect(fired(rule, { [check]: result(check, 'pass') })).toBe(true)
    },
  )

  it.each([['r1', 'master'], ['r2', 'filings'], ['r3', 'fin'], ['r5', 'cdx']])(
    '%s does not fire on a bare needs_confirmation',
    (rule, check) => {
      expect(fired(rule, { [check]: result(check, 'needs_confirmation') })).toBe(false)
    },
  )

  it('a legacy warn on charges still costs points', () => {
    expect(fired('r7', { charges: result('charges', 'warn') })).toBe(true)
  })
})

describe('needs_confirmation is adverse, so r8 and r9 are unchanged', () => {
  it('a duplicate vendor still scores', () => {
    expect(fired('r8', { dup: result('dup', 'needs_confirmation') })).toBe(true)
  })

  it('a related party still scores', () => {
    expect(fired('r9', { rp: result('rp', 'needs_confirmation') })).toBe(true)
  })
})
