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

  it('promotes the newest remaining when the primary is deleted', async () => {
    await mockApi.runChecks(vendor.id, ['master'])
    await mockApi.runChecks(vendor.id, ['master'])
    const { vendor: three } = await mockApi.runChecks(vendor.id, ['master'])

    const runs = runsOf(three, 'master')
    const primary = runs.find((r) => r.isPrimary)!
    // The oldest is the primary, so deleting it is the interesting case.
    expect(primary.id).toBe(runs[2].id)

    const after = await mockApi.deleteRun(vendor.id, primary.id!)
    const left = runsOf(after, 'master')

    expect(left).toHaveLength(2)
    // The check is still scored. Silently dropping out of the score is
    // the failure this promotion exists to prevent.
    expect(left.filter((r) => r.isPrimary)).toHaveLength(1)
    expect(left[0].isPrimary).toBe(true)
    expect(after.checks.master).toBeDefined()
  })

  it('leaves the primary alone when a sibling is deleted', async () => {
    await mockApi.runChecks(vendor.id, ['master'])
    const { vendor: two } = await mockApi.runChecks(vendor.id, ['master'])
    const newest = runsOf(two, 'master')[0]
    const primaryId = runsOf(two, 'master').find((r) => r.isPrimary)!.id

    const after = await mockApi.deleteRun(vendor.id, newest.id!)
    expect(runsOf(after, 'master')).toHaveLength(1)
    expect(after.checks.master.id).toBe(primaryId)
  })

  it('records both a marking and a deletion in the audit log', async () => {
    await mockApi.runChecks(vendor.id, ['master'])
    const { vendor: two } = await mockApi.runChecks(vendor.id, ['master'])
    const newest = runsOf(two, 'master')[0]

    await mockApi.markPrimary(vendor.id, newest.id!)
    await mockApi.deleteRun(vendor.id, newest.id!)

    const actions = (await mockApi.listAudit(vendor.id)).map((a) => a.action)
    expect(actions).toContain('RUN_MARKED_PRIMARY')
    expect(actions).toContain('RUN_DELETED')
  })

  it('refuses a run id belonging to another vendor', async () => {
    const other = await subject()
    await mockApi.setSelection(other.id, ['master'])
    const { vendor: ran } = await mockApi.runChecks(other.id, ['master'])
    const foreign = runsOf(ran, 'master')[0].id!

    await expect(mockApi.markPrimary(vendor.id, foreign)).rejects.toThrow()
    await expect(mockApi.deleteRun(vendor.id, foreign)).rejects.toThrow()
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
