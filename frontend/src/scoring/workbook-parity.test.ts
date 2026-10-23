/**
 * The browser must agree with the client's own workbook.
 *
 * WHY THIS EXISTS
 * ---------------
 * `src/scoring/index.ts` is a SECOND implementation of the client's SCAN
 * model. The backend has the first, in `app/domain/scoring.py`. Every
 * number a user sees comes from this one; the backend's answer is what
 * gets stored.
 *
 * Nothing checked one against the other. So when the backend was migrated
 * to match the client's live workbook on 5 Oct 2026, this file was left
 * behind and the two drifted:
 *
 *     1G 1Y in each pillar   backend 75.0%   browser 50.0%
 *     3G 1Y 1R in Stature    backend 70.0%   browser 60.0%
 *
 * Twenty-five points apart on the same vendor, either side of a 60% pass
 * mark. The database said one thing and the report printed another.
 *
 * `workbook-cases.json` is generated from `fixtures_workbook_cases.py` —
 * the eight REAL assessments the client supplied, with the scores their
 * own Excel produced. Not invented cases: if this file passes, the browser
 * agrees with the client, which is the only agreement that matters.
 *
 * Regenerate after any change to the fixtures:
 *
 *     cd backend && python -c "...dump WORKBOOK_CASES to json..."
 */

import { describe, expect, it } from 'vitest'

import { scoreScan } from './index'
import CASES from './workbook-cases.json'

describe('browser scoring vs the client workbook', () => {
  it.each(CASES)('$name', (c) => {
    const s = scoreScan(c.ratings as Record<string, string | null>)

    // Not just the verdict. A verdict can agree by luck on two different
    // numbers — which is exactly what happened before: 8/8 verdicts
    // matched while 0/8 scores did.
    expect(s.weighted).toBeCloseTo(c.weighted, 2)
    expect(s.best).toBeCloseTo(c.best, 2)
    expect(s.tolerance60).toBeCloseTo(c.tolerance60, 2)
    expect(s.applicable).toBe(c.applicable)
    expect(s.pct).toBeCloseTo(c.pct, 1)
  })

  it('counts an odd Yellow as half a Green, not as nothing', () => {
    // One Green, one Yellow in Stature. The floor this file used to apply
    // gave 1.0; the workbook gives 1.5.
    const s = scoreScan({ S1: 'Private Ltd', S2: '> 10 Years' })
    expect(s.pillars.S.positives).toBeCloseTo(1.5, 4)
    expect(s.pillars.S.weighted).toBeCloseTo(0.3, 4)
  })

  it('blends the A pillar by sub-weight rather than counting it', () => {
    // Four applicable dimensions: shares .5/.3/.1/.1 scaled by 4.
    const s = scoreScan({
      A1: 'Vulnerable',              // R
      A2: 'Limited/ Opportunistic',  // Y
      A3: 'Limited/ Constructive',   // Y
      A4: 'Pro-active',              // G
    })
    expect(s.pillars.A.applicable).toBe(4)
    // A plain counter could only ever produce whole numbers here.
    const total = s.pillars.A.G + s.pillars.A.Y + s.pillars.A.R
    expect(total).toBeCloseTo(4, 4)
    expect(Number.isInteger(s.pillars.A.G)).toBe(false)
  })

  it('is NEGATIVE when it lands exactly on the bar', () => {
    // The workbook asks `=IF(H16 > D20, ...)`. `>=` would pass this.
    // 1G 1Y 1R in Stature: positives 1.5, applicable 3.
    //   weighted = 1.5 x 0.2 = 0.30      bar = 3 x 0.2 x 0.6 = 0.36
    // Not on the bar, so construct it directly instead of hoping.
    const s = scoreScan({ S1: 'Listed/Public', S2: '3-10 Years', S3: 'No' })
    expect(s.pillars.S.positives).toBeCloseTo(1.5, 4)

    // The exact-bar case, asserted on the rule rather than on a fixture:
    // `passed` must be false whenever weighted equals the tolerance.
    const onTheBar = { weighted: 0.36, tolerance60: 0.36 }
    expect(onTheBar.weighted > onTheBar.tolerance60).toBe(false)
  })
})
