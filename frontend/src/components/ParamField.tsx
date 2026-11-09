import { useEffect, useRef, useState } from 'react'

import { api } from '@/api'
import { inputValue } from '@/api/mock'
import { CHECKS } from '@/catalog/generated'
import { Field } from '@/components/ui'
import { useToast } from '@/hooks/useToast'
import { checkValue, detectIdType, ruleFor, splitSubjects } from '@/lib/validate'
import type { Vendor } from '@/types/domain'

/** Names rather than raw ids — "supplied by the master result" needs a name. */
const nameOf = (id: string): string => CHECKS.find((c) => c.id === id)?.name ?? id

/**
 * A single check-input field.
 *
 * SHARED BY STEP 2 AND THE STEP 3 "RUN MORE CHECKS" DIALOG, and that is the
 * reason it lives here rather than inside Step 2 where it was written.
 *
 * The dialog has to offer the same boxes Step 2 offers — an analyst who can
 * run a check from Step 3 but not type its input has to walk back two
 * screens anyway, which is the whole thing the dialog exists to avoid. A
 * second implementation of these boxes would mean two copies of the
 * fallback rule, the multi-value splitter and the format warnings, and two
 * copies of one rule is how this codebase has been bitten before.
 *
 * The value was read straight from `vendor` and written on every keystroke,
 * so a 21-character CIN fired 21 requests and whichever response landed
 * last won. Over real latency an earlier response arriving after a later
 * one rewrote the field with a shorter string and characters visibly
 * disappeared as you typed.
 *
 * The keystroke now updates a local value immediately, and the server's
 * copy is only allowed to take over once the field is no longer being
 * edited. The call itself is unchanged — same endpoint, same arguments,
 * same one-per-change cadence — so nothing about the integration moves.
 */
export default function ParamField({
  vendor,
  setVendor,
  checkId,
  param,
  selected,
  missingKeys,
}: {
  vendor: Vendor
  setVendor: (v: Vendor) => void
  checkId: string
  param: (typeof CHECKS)[number]['params'][number]
  selected: string[]
  /** Keys the PAGE considers blank — see the note at its definition. */
  missingKeys: Set<string>
}) {
  const toast = useToast()
  const stored = inputValue(vendor, checkId, param.key)
  const [local, setLocal] = useState(stored)
  const editing = useRef(false)

  /*
    THE BOX MUST SHOW WHAT THE RUN WILL SEND.

    `local` is what you see; `stored` — `inputValue()` — is what the gate
    reads and what the runner uses. They were allowed to disagree, and the
    case that broke was clearing a box that has a vendor-level fallback:

      vendor.domain = "aspiremgs.co.in", analyst clears the Domain field
        local  = ""                 -> box looks empty
        stored = "aspiremgs.co.in"  -> gate says nothing is missing

    So the field read blank with no red, the Run button stayed live, the
    call went out, and SSL came back `HTTP 400 — Input correct domain`.
    The analyst was shown one thing and the provider was sent another.

    This effect only fired when `stored` CHANGED, so after a clear-and-blur
    there was nothing to re-sync from. It now also fires when editing
    stops, so leaving a field always puts back whatever will actually be
    sent — including a value the analyst thought they had deleted.

    They CANNOT delete it: the backend applies the same fallback. A screen
    that implies otherwise is the thing that was wrong.
  */
  const [editCount, setEditCount] = useState(0)
  useEffect(() => {
    if (!editing.current) setLocal(stored)
  }, [stored, editCount])

  const suppliedByAnother = param.fromResult && selected.includes(param.fromResult)
  // Asked, not decided. The page owns this question; see `missingKeys`.
  const isMissing = missingKeys.has(`${checkId}.${param.key}`)

  /*
    WHEN TO SHOW A FORMAT ERROR — not what counts as one.

    A CIN is 21 characters, so checking on every keystroke paints the
    field red for the first twenty and clears it on the last. That trains
    an analyst to ignore the colour, which is the opposite of the point.
    So: stay quiet until the field has been left once, then stay live, so
    the error clears the moment it is corrected rather than on the next
    blur.

    `touched` starts TRUE when the field arrived WITH a value — typed at
    Step 1, or prefilled from the vendor record. Nobody is mid-word in
    that case, and staying quiet would be actively harmful now that a
    blocking error disables the Run button: the analyst would face a dead
    button, a count of inputs to fix, and no red field anywhere.

    None of this changes what blocks a run. `badInputs` is computed from
    the stored values, so an untouched bad field still stops it; this
    governs only when the message appears.
  */
  const [touched, setTouched] = useState(() => Boolean(stored))
  const found = checkValue(param.key, local)
  const problem = touched ? found : null
  const rule = ruleFor(param.key)

  /*
    ONE FIELD, MANY PEOPLE.

    The person-level checks take a list: a company with five directors is
    five lookups, and they belong on ONE check so that each answer stays
    tagged with the number it came from. Run as five separate checks the
    analyst gets five rows and no way to tell which answer was whose.

    A one-line input cannot show a list. It scrolls sideways, the analyst
    cannot see what they have entered, and the only affordance for "put
    several here" would be a sentence under the box.

    `multi` comes from the generated rule, so this is not a hardcoded list
    of field names — a field becomes multi-valued in
    `app/domain/validation.py` and the form follows.
  */
  const multi = Boolean(rule?.multi)
  const subjects = multi ? splitSubjects(local) : []

  /*
    THE IDENTIFIER TYPE FOLLOWS THE IDENTIFIER.

    This select used to carry an "Auto-detect" option, which existed
    because pinning it to "cin" made the provider apply CIN validation to
    every identifier — so an LLPIN came back 400 and an LLP could not be
    audited at all.

    Auto-detect is gone from the options, but the behaviour it protected
    is not: the value is derived from whatever was typed in the CIN box.
    Type a CIN and it reads "cin"; type an LLPIN and it reads "llpin".
    The analyst can still override. Nothing is pinned.
  */
  const derivedIdType =
    param.key === 'idType' ? detectIdType(inputValue(vendor, checkId, 'cin')) : null

  /*
    THE OVERRIDE IS HONOURED, AND THE RUNNER THROWS IT AWAY.

    Picking "fcin" against a CIN is allowed — MCA identifiers have more
    shapes than the documentation admits, and refusing to run on one we
    do not recognise is how LLPs became un-auditable before. So the
    runner does not refuse it either: where the choice contradicts the
    identifier it sends NO idType and lets the source detect, which is
    the behaviour that works.

    But until now the only trace was a line in the audit log. The screen
    said "fcin", "fcin" was not what got sent, and nothing said so. A
    control that reports something untrue about the call it is about to
    make is worse than one that is simply wrong.

    Not an error — nothing is broken and the run succeeds. Just the
    truth, stated under the field.
  */
  /*
    Shown under the CIN BOX, not under the select.

    It was under the select at first, which is where the overridden value
    lives — but the sentence is about the identifier, the select sits in a
    narrow column beside it, and a reader looking at the thing they typed
    found nothing there. Put it where the subject is.

    So it is computed from the CIN field's own side of the pair: what was
    typed here, against whatever the select currently holds.
  */
  const chosenIdType =
    param.key === 'cin' ? String(inputValue(vendor, checkId, 'idType') || '') : ''
  const idTypeIgnored =
    param.key === 'cin' &&
    local.trim() !== '' &&
    chosenIdType !== '' &&
    chosenIdType !== detectIdType(local)

  const write = async (value: string) => {
    setLocal(value)
    try {
      setVendor(await api.setCheckInput(vendor.id, checkId, param.key, value))
    } catch (e) {
      // A silently dropped input is the worst outcome here: the check is
      // skipped at run time and nobody knows why.
      toast.error(e, 'That value could not be saved.')
    }
  }

  /*
    Keep the select in step with the identifier. Declared AFTER `write`
    on purpose: it worked before only because an effect body runs after
    the component function has finished, which is a fact about React
    rather than anything this file should lean on.
  */
  useEffect(() => {
    if (!derivedIdType || editing.current) return
    if (local === derivedIdType) return
    void write(derivedIdType)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [derivedIdType])

  return (
    <Field
      label={`${param.label}${param.required ? ' *' : ''}`}
      hint={
        suppliedByAnother
          ? `Supplied by the ${nameOf(param.fromResult!)} result`
          : isMissing
            ? 'Required — fill this in, or deselect the check, before running'
            : problem
              ? problem.message
              : idTypeIgnored
                ? `Identifier type is set to "${chosenIdType}", but this looks ` +
                  `like a ${detectIdType(local).toUpperCase()}. The setting will be ` +
                  `ignored and the source asked to detect it.`
                : // THE COUNT REPLACES THE EXAMPLE once there is something
                  // to count. Five numbers in a box is five paid calls,
                  // and that is worth more than "e.g. 9876543210" under a
                  // field the analyst has evidently understood. Computed
                  // with the splitter the runner uses, so it is the number
                  // of calls that will be made, duplicates already gone.
                  subjects.length > 0
                  ? `${subjects.length} ${subjects.length === 1 ? 'person' : 'people'} — ` +
                    `this check is charged once per person`
                  : rule?.example
                    ? `e.g. ${rule.example}` +
                      (multi ? ' · one per line for several people' : '')
                    : undefined
      }
      tone={isMissing ? 'block' : problem?.level}
    >
      {param.type === 'select' ? (
        <select
          className="select"
          value={local}
          onChange={(e) => void write(e.target.value)}
        >
          {param.options.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      ) : multi ? (
        <textarea
          className={`input input-multi${isMissing ? ' is-invalid' : ''}${
            problem ? (problem.level === 'block' ? ' is-invalid' : ' is-warning') : ''
          }`}
          data-field={param.key}
          // Grows with the list, to a ceiling. A fixed height is either
          // three empty lines under one number or a scrollbar over five,
          // and the whole value of a textarea here is seeing the lot.
          rows={Math.min(6, Math.max(2, subjects.length + 1))}
          value={local}
          placeholder={param.placeholder || 'One per line'}
          aria-invalid={isMissing || problem?.level === 'block' || undefined}
          onFocus={() => {
            editing.current = true
          }}
          onBlur={() => {
            editing.current = false
            setTouched(true)
            setEditCount((n) => n + 1)
          }}
          onChange={(e) => void write(e.target.value)}
        />
      ) : (
        <input
          // RED, not amber. It used to be amber because a blank required
          // field only meant "this one check will be skipped". It now
          // stops the run, so it gets the colour that means stop.
          className={`input${isMissing ? ' is-invalid' : ''}${
            problem ? (problem.level === 'block' ? ' is-invalid' : ' is-warning') : ''
          }`}
          data-field={param.key}
          type={param.type === 'number' ? 'number' : param.type === 'date' ? 'date' : 'text'}
          value={local}
          placeholder={param.placeholder}
          aria-invalid={isMissing || problem?.level === 'block' || undefined}
          onFocus={() => {
            editing.current = true
          }}
          onBlur={() => {
            editing.current = false
            setTouched(true)
            // Re-sync even when `stored` did not change — see above.
            setEditCount((n) => n + 1)
          }}
          onChange={(e) => void write(e.target.value)}
        />
      )}
    </Field>
  )
}
