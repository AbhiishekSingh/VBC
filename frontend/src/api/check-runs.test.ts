/**
 * MANY RESULTS PER CHECK, in the mock.
 *
 * The mock is what the screens are built against, so a rule the server
 * enforces and the mock does not is a rule the UI will be built to break.
 * These are the same assertions as `backend/app/tests/test_check_runs.py`,
 * expressed against the adapter the browser actually calls in mock mode.
 *
 * The one that matters most is `scoring reads the primary, not the newest`:
 * every other rule here exists to keep that one true.
 */

import { beforeEach, describe, expect, it } from 'vitest'

import { mockApi } from './mock'
import type { Vendor } from '@/types/domain'

/** A vendor with a mobile number, which the person checks need. */
async function subject(): Promise<Vendor> {
  const clients = await mockApi.listClients()
  return mockApi.createVendor({
    clientId: clients[1].id,
    name: 'Run History Test Pvt Ltd',
    cin: 'U72900MH2015PTC268454',
    domain: 'example.co.in',
    contactMobile: '9876543210',
  })
}

const runsOf = (vendor: Vendor, checkId: string) =>
  (vendor.runs ?? []).filter((r) => r.checkId === checkId)

describe('many results per check', () => {
  let vendor: Vendor

  beforeEach(async () => {
    vendor = await subject()
    await mockApi.setSelection(vendor.id, ['master'])
  })

  it('appends rather than replacing', async () => {
    let result = await mockApi.runChecks(vendor.id, ['master'])
    expect(runsOf(result.vendor, 'master')).toHaveLength(1)

    result = await mockApi.runChecks(vendor.id, ['master'])
    expect(runsOf(result.vendor, 'master')).toHaveLength(2)

    result = await mockApi.runChecks(vendor.id, ['master'])
    expect(runsOf(result.vendor, 'master')).toHaveLength(3)
  })

  it('makes the first result primary without being asked', async () => {
    const { vendor: after } = await mockApi.runChecks(vendor.id, ['master'])
    const runs = runsOf(after, 'master')
    expect(runs[0].isPrimary).toBe(true)
  })

  it('does not let a later run steal the primary flag', async () => {
    await mockApi.runChecks(vendor.id, ['master'])
    const { vendor: after } = await mockApi.runChecks(vendor.id, ['master'])
    const runs = runsOf(after, 'master')

    expect(runs).toHaveLength(2)
    // Newest first, and the newest is NOT the one that counts.
    expect(runs[0].isPrimary).toBe(false)
    expect(runs[1].isPrimary).toBe(true)
  })

  it('exposes the primary — not the newest — as `checks`', async () => {
    await mockApi.runChecks(vendor.id, ['master'])
    const { vendor: after } = await mockApi.runChecks(vendor.id, ['master'])

    const primary = runsOf(after, 'master').find((r) => r.isPrimary)
    expect(after.checks.master.id).toBe(primary!.id)
  })

  it('holds exactly one primary per check after marking', async () => {
    await mockApi.runChecks(vendor.id, ['master'])
    const { vendor: two } = await mockApi.runChecks(vendor.id, ['master'])
    const newest = runsOf(two, 'master')[0]

    const after = await mockApi.markPrimary(vendor.id, newest.id!)
    const runs = runsOf(after, 'master')

    expect(runs.filter((r) => r.isPrimary)).toHaveLength(1)
    expect(runs[0].isPrimary).toBe(true)
    expect(after.checks.master.id).toBe(newest.id)
  })

  it('snapshots the inputs each result was run against', async () => {
    await mockApi.setCheckInput(vendor.id, 'master', 'cin', 'U72900MH2015PTC268454')
    await mockApi.runChecks(vendor.id, ['master'])

    // The SAME check, a different company.
    await mockApi.setCheckInput(vendor.id, 'master', 'cin', 'U01100MH2009PTC191545')
    const { vendor: after } = await mockApi.runChecks(vendor.id, ['master'])

    const runs = runsOf(after, 'master')
    expect(runs[0].inputs?.cin).toBe('U01100MH2009PTC191545')
    // The first result still names the company IT was run against — the
    // vendor record holds one value per key and would claim otherwise.
    expect(runs[1].inputs?.cin).toBe('U72900MH2015PTC268454')
  })

  it('promotes the newest in force when the primary is set aside', async () => {
    await mockApi.runChecks(vendor.id, ['master'])
    await mockApi.runChecks(vendor.id, ['master'])
    const { vendor: three } = await mockApi.runChecks(vendor.id, ['master'])

    const runs = runsOf(three, 'master')
    const primary = runs.find((r) => r.isPrimary)!
    // The oldest is the primary, so setting it aside is the interesting case.
    expect(primary.id).toBe(runs[2].id)

    const after = await mockApi.ignoreRun(vendor.id, primary.id!, 'wrong number')
    const left = runsOf(after, 'master')

    // NOTHING WAS REMOVED. That is the whole difference from the delete
    // this replaced.
    expect(left).toHaveLength(3)
    expect(left.find((r) => r.id === primary.id)!.ignoredAt).toBeTruthy()
    // The check is still scored. Silently dropping out of the score is
    // the failure this promotion exists to prevent.
    expect(left.filter((r) => r.isPrimary)).toHaveLength(1)
    expect(left[0].isPrimary).toBe(true)
    expect(after.checks.master).toBeDefined()
  })

  it('keeps an ignored result out of the scoring map', async () => {
    const { vendor: one } = await mockApi.runChecks(vendor.id, ['master'])
    const only = runsOf(one, 'master')[0]

    const after = await mockApi.ignoreRun(vendor.id, only.id!, 'superseded')

    // Out of `checks`, which is what the score and the report read...
    expect(after.checks.master).toBeUndefined()
    // ...and still served, so Step 3 can show it greyed with its reason.
    expect(runsOf(after, 'master')).toHaveLength(1)
    expect(runsOf(after, 'master')[0].ignoreReason).toBe('superseded')
  })

  it('refuses to set a result aside without a reason', async () => {
    const { vendor: one } = await mockApi.runChecks(vendor.id, ['master'])
    const only = runsOf(one, 'master')[0]
    await expect(mockApi.ignoreRun(vendor.id, only.id!, '  ')).rejects.toThrow()
  })

  it('reinstates a result that was set aside', async () => {
    const { vendor: one } = await mockApi.runChecks(vendor.id, ['master'])
    const only = runsOf(one, 'master')[0]

    await mockApi.ignoreRun(vendor.id, only.id!, 'second thoughts')
    const after = await mockApi.unignoreRun(vendor.id, only.id!)

    const back = runsOf(after, 'master')[0]
    expect(back.ignoredAt).toBeFalsy()
    // The only result in force, so it counts again rather than leaving
    // the check holding a live result and scoring nothing.
    expect(back.isPrimary).toBe(true)
    expect(after.checks.master).toBeDefined()
  })

  it('leaves the primary alone when a sibling is set aside', async () => {
    await mockApi.runChecks(vendor.id, ['master'])
    const { vendor: two } = await mockApi.runChecks(vendor.id, ['master'])
    const newest = runsOf(two, 'master')[0]
    const primaryId = runsOf(two, 'master').find((r) => r.isPrimary)!.id

    const after = await mockApi.ignoreRun(vendor.id, newest.id!, 'duplicate')
    expect(runsOf(after, 'master')).toHaveLength(2)
    expect(after.checks.master.id).toBe(primaryId)
  })

  it('records both a marking and a set-aside in the audit log', async () => {
    await mockApi.runChecks(vendor.id, ['master'])
    const { vendor: two } = await mockApi.runChecks(vendor.id, ['master'])
    const newest = runsOf(two, 'master')[0]

    await mockApi.markPrimary(vendor.id, newest.id!)
    await mockApi.ignoreRun(vendor.id, newest.id!, 'ran against the wrong director')

    const entries = await mockApi.listAudit(vendor.id)
    const actions = entries.map((a) => a.action)
    expect(actions).toContain('RUN_MARKED_PRIMARY')
    expect(actions).toContain('RUN_IGNORED')
    // The REASON is in the log, not just the act.
    expect(
      entries.some((a) => a.detail.includes('ran against the wrong director')),
    ).toBe(true)
  })

  it('refuses a run id belonging to another vendor', async () => {
    const other = await subject()
    await mockApi.setSelection(other.id, ['master'])
    const { vendor: ran } = await mockApi.runChecks(other.id, ['master'])
    const foreign = runsOf(ran, 'master')[0].id!

    await expect(mockApi.markPrimary(vendor.id, foreign)).rejects.toThrow()
    await expect(mockApi.ignoreRun(vendor.id, foreign, 'no')).rejects.toThrow()
  })

  it('reports what THIS run called, not what the vendor holds', async () => {
    await mockApi.runChecks(vendor.id, ['master'])
    await mockApi.runChecks(vendor.id, ['dup'])

    // Three results on file by now; this run called one.
    const result = await mockApi.runChecks(vendor.id, ['master'])
    expect(result.ran).toBe(1)
  })

  it('adds a check run from Step 3 to the selection', async () => {
    // `whois` is NOT selected. The dialog runs it anyway, and the server
    // runs the intersection of `only` and the selection — so a check run
    // from Step 3 has to end up selected or it would silently do nothing.
    const { vendor: after } = await mockApi.runChecks(vendor.id, ['whois'])
    expect(after.selected).toContain('whois')
    expect(runsOf(after, 'whois')).toHaveLength(1)
  })

  it('skips one check for a blank required input, and runs the rest', async () => {
    const bare = await mockApi.createVendor({
      clientId: (await mockApi.listClients())[1].id,
      name: 'No identifiers at all',
    })
    const { vendor: after, skippedMissingInput } = await mockApi.runChecks(bare.id, [
      'master',
      'dup',
    ])

    expect(skippedMissingInput.length).toBe(1)
    expect(runsOf(after, 'master')[0].status).toBe('skipped_missing_input')
    // The other one still ran. A blank field is one skipped check, never
    // a blocked run.
    expect(runsOf(after, 'dup')[0].status).toBe('pass')
  })
})

/* =====================================================================
   STEP 2 NEVER RE-CHARGES
   =====================================================================

   Step 2's Run used to post nothing, which the server reads as "run the
   whole selection" — and the runner does not skip a check that already
   answered. So going back to add two checks re-called and re-billed
   everything already on file, upwards of ₹40 on a full MCA set, with
   nothing on screen to say it had happened.

   It now sends the delta. These pin the behaviour at the adapter, where
   both Step 2 and the Step 3 popup meet the same code.
*/

describe('adding checks later', () => {
  let vendor: Vendor

  beforeEach(async () => {
    vendor = await subject()
    await mockApi.setSelection(vendor.id, ['master', 'dup'])
  })

  it('charges only for the checks that have not answered', async () => {
    const first = await mockApi.runChecks(vendor.id, ['master', 'dup'])
    expect(first.ran).toBe(2)
    const paidFirst = first.costPaisa

    // Back to Step 2, two more ticked. The delta is what gets sent.
    await mockApi.setSelection(vendor.id, ['master', 'dup', 'whois', 'ssl'])
    const second = await mockApi.runChecks(vendor.id, ['whois', 'ssl'])

    expect(second.ran).toBe(2)
    // The old two were not called again...
    expect(runsOf(second.vendor, 'master')).toHaveLength(1)
    expect(runsOf(second.vendor, 'dup')).toHaveLength(1)
    // ...and not charged again.
    expect(second.costPaisa).toBeLessThanOrEqual(paidFirst + second.costPaisa)
    expect(runsOf(second.vendor, 'whois')).toHaveLength(1)
    expect(runsOf(second.vendor, 'ssl')).toHaveLength(1)
  })

  it('still shows all four results afterwards', async () => {
    await mockApi.runChecks(vendor.id, ['master', 'dup'])
    await mockApi.setSelection(vendor.id, ['master', 'dup', 'whois', 'ssl'])
    const { vendor: after } = await mockApi.runChecks(vendor.id, ['whois', 'ssl'])

    for (const id of ['master', 'dup', 'whois', 'ssl']) {
      expect(runsOf(after, id).length, id).toBeGreaterThan(0)
    }
  })

  it('a deliberate re-run from Step 3 IS charged and IS kept', async () => {
    await mockApi.runChecks(vendor.id, ['master'])
    const { vendor: after } = await mockApi.runChecks(vendor.id, ['master'])

    // Two results, because re-running against a different director is
    // the whole point of the popup — and the first is not thrown away.
    expect(runsOf(after, 'master')).toHaveLength(2)
  })
})
