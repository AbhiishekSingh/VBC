/**
 * What the analyst sees must be what the run sends.
 *
 * Two values describe one field:
 *
 *   inputValue()    what the gate reads and the runner uses
 *   ParamField.local  what is rendered in the box
 *
 * They were allowed to drift. Clearing a box that has a vendor-level
 * fallback left `local` empty while `inputValue` still returned the
 * vendor's value, so the field read blank, nothing turned red, the Run
 * button stayed live, and SSL went out and came back
 * `HTTP 400 — Input correct domain`.
 *
 * `ParamField` now re-syncs on blur. These tests pin the data half of the
 * invariant: a field is reported missing EXACTLY when the value that would
 * be sent is blank — never on what was typed and discarded.
 */

import { describe, expect, it } from 'vitest'

import { inputValue, missingInputs } from './mock'
import { CHECKS } from '@/catalog/generated'
import type { Vendor } from '@/types/domain'

const vendor = (over: Record<string, unknown> = {}): Vendor =>
  ({
    id: '1', selected: [], inputs: {}, checks: {}, scan: {}, manual: [],
    surveillance: {}, surveillanceDone: false,
    cin: null, domain: null, gst: null, pan: null, website: null,
    ...over,
  } as unknown as Vendor)

describe('the input gate', () => {
  it('flags a required field exactly when what would be SENT is blank', () => {
    for (const check of CHECKS) {
      if (check.state === 'not_configured') continue
      for (const param of check.params) {
        if (!param.required || param.fromResult) continue

        const blank = vendor({ selected: [check.id] })
        expect(
          missingInputs(blank).some((m) => m.checkId === check.id && m.paramKey === param.key),
          `${check.id}.${param.key} is blank and was not flagged`,
        ).toBe(true)
      }
    }
  })

  it('does NOT flag a field the vendor record fills', () => {
    const v = vendor({ selected: ['ssl'], domain: 'aspiremgs.co.in' })
    expect(inputValue(v, 'ssl', 'domainName')).toBe('aspiremgs.co.in')
    expect(missingInputs(v)).toHaveLength(0)
  })

  it('a cleared box still sends the vendor value — so it is not "missing"', () => {
    // The case that broke. The analyst CANNOT delete a vendor-level value:
    // the backend applies the same fallback. What was wrong was the screen
    // implying they had.
    const v = vendor({
      selected: ['ssl'], domain: 'aspiremgs.co.in',
      inputs: { ssl: { domainName: '' } },
    })
    expect(inputValue(v, 'ssl', 'domainName')).toBe('aspiremgs.co.in')
    expect(missingInputs(v)).toHaveLength(0)
  })

  it('whitespace is blank', () => {
    const v = vendor({ selected: ['ssl'], domain: '   ' })
    expect(missingInputs(v).length).toBeGreaterThan(0)
  })
})