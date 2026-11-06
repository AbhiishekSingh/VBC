/**
 * Input validation, from the generated rules.
 *
 * The patterns, levels and hints all come from `INPUT_RULES` in the
 * generated catalog, which is emitted from `app/domain/validation.py`.
 * Nothing here invents a rule — if a format is wrong, it is wrong in the
 * Python module and both sides are wrong together, which is the point.
 *
 * WHY VALIDATE HERE AT ALL, GIVEN THE API ALSO DOES
 * -------------------------------------------------
 * Because this is the only place it can be caught before the money is
 * spent AND in front of someone who can fix it. A mistyped GSTIN rejected
 * by the API is a 422 after the analyst has committed to a run; rejected
 * here it is a red field and a corrected character.
 *
 * BLOCK versus WARN is the generated rule's call, not this file's.
 */

import { INPUT_RULES } from '@/catalog/generated'

export type Level = 'block' | 'warn'

export interface Problem {
  key: string
  level: Level
  message: string
}

type RuleShape = {
  pattern: string
  level: string
  hint: string
  example: string
  normalise: boolean
  /** ONE FIELD, MANY VALUES — see `cleanSubject` below. */
  multi?: boolean
}

const RULES = INPUT_RULES as unknown as Record<string, RuleShape>

export function ruleFor(key: string): RuleShape | undefined {
  return RULES[key]
}

/**
 * One entry of a multi-value field, as the runner will send it.
 *
 * Mirrors `clean_subject` in `app/domain/validation.py`. Digits only, with
 * a pasted `+91` or leading `0` dropped — both are the commonest paste off
 * a contact sheet rather than a mistake.
 *
 * The two copies must agree, and the reason is the one Select.tsx is full
 * of: if this box accepts a value the runner would send differently, the
 * analyst is shown one thing and the provider receives another.
 */
export function cleanSubject(entry: string): string {
  const digits = (entry || '').replace(/\D/g, '')
  if (digits.length === 12 && digits.startsWith('91')) return digits.slice(2)
  if (digits.length === 11 && digits.startsWith('0')) return digits.slice(1)
  return digits
}

/**
 * A multi-value field as the list the runner will loop over.
 *
 * Order preserved, duplicates dropped. Two directors sharing a number is a
 * real thing; paying twice for one answer is not.
 */
export function splitSubjects(text: string | null | undefined): string[] {
  const raw = (text || '').trim()
  if (!raw) return []
  const out: string[] = []
  for (const part of raw.replace(/[,;]/g, '\n').split('\n')) {
    const value = cleanSubject(part)
    if (value && !out.includes(value)) out.push(value)
  }
  return out
}

const GSTIN_ALPHABET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'

/**
 * Verify a GSTIN's 15th character.
 *
 * Catches what a length check cannot: one mistyped digit inside an
 * otherwise well-formed GSTIN, which is the usual way this field is
 * wrong. Each of the first 14 characters is weighted alternately 1 and 2,
 * each product reduced by base-36 digit sum, and the check character is
 * whatever brings the total to a multiple of 36.
 *
 * Returns true when the input is not GSTIN-shaped at all — shape is the
 * pattern's job, and "bad checksum" on a 4-character string would send
 * someone hunting for the wrong mistake.
 */
export function gstinChecksumOk(value: string): boolean {
  const v = (value || '').trim().toUpperCase()
  if (v.length !== 15) return true
  if ([...v].some((ch) => !GSTIN_ALPHABET.includes(ch))) return true

  let total = 0
  for (let i = 0; i < 14; i += 1) {
    const digit = GSTIN_ALPHABET.indexOf(v[i])
    const product = digit * (i % 2 ? 2 : 1)
    total += Math.floor(product / 36) + (product % 36)
  }
  return GSTIN_ALPHABET[(36 - (total % 36)) % 36] === v[14]
}

/**
 * Which MCA identifier this is: 'cin', 'llpin' or 'fcin'.
 *
 * Mirrors `detect_id_type` in the Python module. Falls back to 'cin' for
 * an empty box or an unrecognised shape, which is what lets the dropdown
 * drop its "Auto-detect" option without pinning LLPs to CIN validation —
 * typing an LLPIN selects llpin by itself.
 */
export function detectIdType(value: string | null | undefined): string {
  const text = (value || '').trim().toUpperCase().replace(/\s/g, '')
  if (/^[A-Z]{3}-?\d{4}$/.test(text)) return 'llpin'
  if (/^(F|FLLPIN)\d{4,6}$/.test(text)) return 'fcin'
  return 'cin'
}

/**
 * Validate one field. `null` means nothing to report.
 *
 * An EMPTY value is never a problem here. Whether a field is required is
 * the catalog's business, and "wrong format" on a box nobody filled in
 * points at the wrong thing.
 */
export function checkValue(key: string, value: string | null | undefined): Problem | null {
  const rule = RULES[key]
  if (!rule) return null

  const raw = (value || '').trim()
  if (!raw) return null

  if (rule.multi) {
    // Each entry on its own, and the message NAMES the bad one. "Ten
    // digits starting 6-9" against a box holding five numbers does not
    // tell the analyst which of the five to look at.
    for (const entry of raw.replace(/[,;]/g, '\n').split('\n')) {
      if (!entry.trim()) continue
      if (!new RegExp(rule.pattern).test(cleanSubject(entry))) {
        return { key, level: rule.level as Level, message: `“${entry.trim()}” is not usable. ${rule.hint}` }
      }
    }
    if (splitSubjects(raw).length === 0) {
      return { key, level: rule.level as Level, message: rule.hint }
    }
    return null
  }

  const candidate = rule.normalise ? raw.toUpperCase() : raw
  if (!new RegExp(rule.pattern).test(candidate)) {
    return { key, level: rule.level as Level, message: rule.hint }
  }

  if (key === 'gstin' && !gstinChecksumOk(candidate)) {
    return {
      key,
      level: 'block',
      message:
        'The check character does not match the rest of the GSTIN — usually ' +
        'one mistyped digit. Compare it against the source document.',
    }
  }
  return null
}

/** Every problem across a set of inputs, blocking ones first. */
export function checkAll(values: Record<string, string | null | undefined>): Problem[] {
  const found: Problem[] = []
  for (const [key, value] of Object.entries(values)) {
    const problem = checkValue(key, value)
    if (problem) found.push(problem)
  }
  // All of them, not the first: someone who mistyped two fields should fix
  // two fields in one pass, not find the second after correcting the first.
  return found.sort((a, b) => (a.level === b.level ? 0 : a.level === 'block' ? -1 : 1))
}

export function blockingProblems(
  values: Record<string, string | null | undefined>,
): Problem[] {
  return checkAll(values).filter((p) => p.level === 'block')
}
