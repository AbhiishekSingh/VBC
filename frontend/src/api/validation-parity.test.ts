/**
 * The format rules are implemented TWICE, and this proves the two agree.
 *
 * `app/domain/validation.py` is the definition; `src/lib/validate.ts` is a
 * copy with no independent life. The patterns themselves come across by
 * codegen and cannot drift. The rest can:
 *
 *   - the GSTIN check character is computed in both languages;
 *   - `mobile` and `uan` hold a LIST, and their normalisation — a pasted
 *     `+91`, a leading `0`, spaces, duplicates — is procedural rather than
 *     expressible in the shared pattern.
 *
 * That second one is why this file exists. When the field and the runner
 * disagree about what a value means, the analyst is shown one thing and
 * the provider is sent another — the exact defect that had SSL asked
 * about a domain the screen showed as deleted.
 *
 * `parity-expected.json` is written by `scripts/emit_parity.py` running
 * the PYTHON implementation. If this suite fails, the browser is
 * validating differently from the API and the build must not pass.
 */

import { describe, expect, it } from 'vitest'

import expected from '@/scoring/parity-expected.json'
import { checkValue, splitSubjects } from '@/lib/validate'

const { checkValue: valueCases, splitSubjects: subjectCases } =
  expected.validation as {
    checkValue: {
      key: string
      value: string
      expected: { level: string; message: string } | null
    }[]
    splitSubjects: { value: string; expected: string[] }[]
  }

describe('checkValue matches the Python definition', () => {
  it.each(valueCases)('$key = $value', ({ key, value, expected: want }) => {
    const got = checkValue(key, value)
    if (want === null) {
      expect(got).toBeNull()
      return
    }
    expect(got).not.toBeNull()
    // Level AND message. A copy that blocks the right values with the
    // wrong sentence sends the analyst looking for the wrong mistake,
    // which on a ten-digit number is most of the cost of being wrong.
    expect(got!.level).toBe(want.level)
    expect(got!.message).toBe(want.message)
  })
})

describe('splitSubjects matches the Python definition', () => {
  it.each(subjectCases)('splits %j', ({ value, expected: want }) => {
    expect(splitSubjects(value)).toEqual(want)
  })
})
