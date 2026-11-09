/**
 * What a check will actually cost, for this vendor, right now.
 *
 * `CHECKS[].costPaisa` is the price of ONE call, and for most of the
 * catalogue that is the whole story. It is not for the person-level checks:
 * those take a LIST — five directors' numbers in one field — and are
 * charged per person. A screen that quotes the flat figure understates the
 * price by a factor of five on exactly the checks where the analyst has
 * least chance of working it out for themselves.
 *
 * So the quote is computed from the field, with the same splitter the
 * runner uses. Nothing here invents a price: it multiplies the catalogue's
 * own figure by the number of calls that will actually be made.
 *
 * Credits and screenshots are NOT multiplied, and that is not an oversight
 * — no person-level check draws on either pool. If one ever does, this is
 * the single place that has to learn about it.
 */

import { inputValue } from '@/api/mock'
import { CHECKS } from '@/catalog/generated'
import { ruleFor, splitSubjects } from '@/lib/validate'
import type { Vendor } from '@/types/domain'

/**
 * How many people a check will be run against. 1 for all but the
 * person-level checks, and never 0 — an empty field is a missing input,
 * which is a different screen's problem, and quoting ₹0 for it would read
 * as "this one is free".
 */
export function subjectCount(vendor: Vendor, checkId: string): number {
  const def = CHECKS.find((c) => c.id === checkId)
  // Driven off the generated rule, not a list of field names kept here:
  // a field becomes multi-valued in `app/domain/validation.py` and this
  // follows, rather than needing to be remembered.
  const multi = (def?.params ?? []).filter((p) => ruleFor(p.key)?.multi)
  if (!multi.length) return 1
  const counts = multi.map((p) => splitSubjects(inputValue(vendor, checkId, p.key)).length)
  return Math.max(1, ...counts)
}

/** One check's rupee cost for this vendor, people counted. */
export function checkCostPaisa(vendor: Vendor, checkId: string): number {
  const def = CHECKS.find((c) => c.id === checkId)
  if (!def?.costPaisa) return 0
  return def.costPaisa * subjectCount(vendor, checkId)
}

/**
 * How many people a check ALREADY has results for.
 *
 * The person checks store one row per vendor with every subject inside
 * it — `{"subjects": [...]}` — so this reads the stored payload rather
 * than the input box. Put beside `subjectCount`, which reads the box,
 * it answers the question an analyst actually has when they come back
 * to re-run one: "I have three directors on file and six numbers typed
 * — what happens if I press this?"
 *
 * 0 when the check has not run, or stored something older than the
 * per-subject shape.
 */
export function subjectsOnFile(vendor: Vendor, checkId: string): number {
  const raw = vendor.checks?.[checkId]?.rawResponse as
    | { subjects?: unknown[] }
    | undefined
  return Array.isArray(raw?.subjects) ? raw!.subjects!.length : 0
}
