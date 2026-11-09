/**
 * Every `fromVendor` must name a field that exists on a Vendor.
 *
 * It did not. `contact_mobile` and `legal_name` were emitted in the
 * Python module's snake_case, and the browser indexes the Vendor object
 * with them — `vendor['contact_mobile']` is `undefined`.
 *
 * The failure was SILENT, which is why it survived. An undefined lookup
 * returns a blank, and a blank is indistinguishable from "the analyst
 * left the box empty". So every person check reported "Needs Contact
 * mobile" and the litigation check reported "Needs Legal name to
 * search", however complete the vendor record was, and the Step 3
 * dialog filed all six under "Cannot run yet".
 *
 * A type cannot catch it: the lookup is `vendor[key as keyof Vendor]`,
 * and the cast is what makes an unknown key compile. So it is caught
 * here instead, against a real vendor object rather than a type.
 */

import { describe, expect, it } from 'vitest'

import { CHECKS } from '@/catalog/generated'
import { SEED_VENDORS } from '@/api/fixtures'

const vendor = SEED_VENDORS[0]

// `as const` in the generated catalog makes each check's `params` its
// own tuple type, so `flatMap` cannot unify them. The values are what
// is under test, not the types.
const fromVendorKeys = Array.from(
  new Set(
    (CHECKS as readonly { params: readonly { fromVendor: string | null }[] }[])
      .flatMap((c) => c.params.map((p) => p.fromVendor))
      .filter((k): k is string => Boolean(k)),
  ),
).sort()

describe('fromVendor names a real Vendor field', () => {
  it('finds at least one, or this suite is proving nothing', () => {
    expect(fromVendorKeys.length).toBeGreaterThan(0)
  })

  it.each(fromVendorKeys)('%s exists on a Vendor', (key) => {
    expect(Object.prototype.hasOwnProperty.call(vendor, key)).toBe(true)
  })

  it('is camelCase throughout — no snake_case leaks from Python', () => {
    const snake = fromVendorKeys.filter((k) => k.includes('_'))
    expect(snake).toEqual([])
  })

  it('resolves the two that were broken', () => {
    expect(fromVendorKeys).toContain('contactMobile')
    expect(fromVendorKeys).toContain('legalName')
  })
})
