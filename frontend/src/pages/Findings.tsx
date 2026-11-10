/**
 * Step 3 — findings.
 *
 * The four tiles are the point of this screen, and the fourth is the one
 * that makes this product different from a generic KYC tool: NOT CHECKED
 * is given the same visual weight as passed, attention and adverse. It is
 * broken down by reason — skipped for a missing input, deselected by the
 * analyst, or not configured on the platform at all — because those three
 * mean very different things and none of them mean "clean".
 */

import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '@/api'
import { CHECKS, CHECK_GROUPS } from '@/catalog/generated'
import { inputGaps, inputValue } from '@/api/mock'
import Facts from '@/components/Facts'
import ParamField from '@/components/ParamField'
import {
  Card,
  EmptyState,
  Modal,
  STATUS_EXPLANATION,
  StatusBadge,
  Tile,
  rupees,
} from '@/components/ui'
import { useToast } from '@/hooks/useToast'
import { subjectCount, subjectsOnFile } from '@/lib/pricing'
import { publicDetail } from '@/lib/publicText'
import type { PageProps } from '@/App'
import type { CheckResult, CheckStatus, Vendor } from '@/types/domain'

/** A check plus everything it transitively needs. */
function withPrerequisites(checkId: string, acc: string[] = []): string[] {
  if (acc.includes(checkId)) return acc
  acc.push(checkId)
  const def = CHECKS.find((c) => c.id === checkId)
  for (const req of def?.requires ?? []) withPrerequisites(req, acc)
  return acc
}

/** Statuses that mean the check ANSWERED, and must not be bought again. */
const ANSWERED: CheckStatus[] = ['pass', 'warn', 'fail']

interface InputRow {
  label: string
  value: string
  /** The check the analyst actually typed it on, when not this one. */
  from?: string
  required: boolean
}

/**
 * What the ANALYST entered for this check.
 *
 * The panel showed only what came back. "7 directors" is not evidence
 * unless the screen also says which company was asked about — and that
 * value is something a person typed, so it is the part most likely to be
 * wrong and least likely to be questioned.
 *
 * Checks that carry no parameters of their own inherit them. "Directors
 * list" is read out of the company master response, so the CIN it used
 * was typed on Company master; showing nothing there would be accurate
 * but useless.
 */
function inputsFor(checkId: string, vendor: Vendor, seen = new Set<string>()): InputRow[] {
  if (seen.has(checkId)) return []
  seen.add(checkId)

  const def = CHECKS.find((c) => c.id === checkId)
  if (!def) return []

  const own: InputRow[] = def.params.map((param) => ({
    label: param.label,
    value: inputValue(vendor, checkId, param.key),
    required: param.required,
  }))

  // Inherit from prerequisites, marking where the value came from.
  const inherited: InputRow[] = []
  for (const requiredId of def.requires) {
    const parent = CHECKS.find((c) => c.id === requiredId)
    for (const row of inputsFor(requiredId, vendor, seen)) {
      if (own.some((o) => o.label === row.label)) continue
      inherited.push({ ...row, from: row.from ?? parent?.name ?? requiredId })
    }
  }

  return [...own, ...inherited]
}

/**
 * What was asked FOR ONE RESULT.
 *
 * `inputsFor` reads the vendor record, which holds one value per key — so
 * it shows whatever was typed LAST. Four runs of the same check against
 * four directors would all claim the fourth director's number, which is
 * the single most misleading thing this screen could do: every row would
 * name the same person and three of the four answers would be about
 * somebody else.
 *
 * So a result's own snapshot wins where it has one. A row written before
 * the snapshot existed falls back to the vendor record, which is the best
 * available answer and no worse than what was shown before.
 *
 * Inherited rows still come from the record: a prerequisite's inputs
 * belong to the prerequisite's own result, and that result is on this
 * screen too.
 */
function askedFor(
  checkId: string,
  vendor: Vendor,
  run: { inputs?: Record<string, string> },
): InputRow[] {
  const inherited = inputsFor(checkId, vendor).filter((row) => row.from)
  const def = CHECKS.find((c) => c.id === checkId)
  if (!def) return inherited

  const snap = run.inputs
  const own = def.params.map((param) => ({
    label: param.label,
    value: snap
      ? (snap[param.key] ?? '')
      : inputValue(vendor, checkId, param.key),
    required: param.required,
  }))
  return [...own, ...inherited]
}

/** The value that distinguishes one run of a check from another. */
function runSubject(checkId: string, run: { inputs?: Record<string, string> }): string {
  const def = CHECKS.find((c) => c.id === checkId)
  if (!def || !run.inputs) return ''
  for (const param of def.params) {
    const value = run.inputs[param.key]
    // A select with one sane default ("cin") distinguishes nothing.
    if (value && param.type !== 'select') return value
  }
  return ''
}

/* =====================================================================
   RUN MORE CHECKS
   =====================================================================

   Step 2 is where a selection is made, and until now it was the only
   place: an analyst reading Step 3 who realised they wanted one more
   check had to go back two screens, where the control that greets them
   is a 52-row catalogue and a Run button that re-runs EVERYTHING.

   That is the thing this dialog exists to avoid, and the reason it is a
   dialog rather than a link back to Step 2:

     - Step 2's Run has no notion of "only the new one". `run()` does not
       skip a check that already answered, so going back and pressing it
       re-calls and re-bills the whole selection. On a full MCA set that
       is upwards of ₹40 for one added check, and nothing on the screen
       says so.
     - Reading the findings is the context in which the decision is made.
       "The GST status is stale, so I want the returns check" is a
       thought you have with the GST result in front of you, and a
       navigation that throws that away costs the analyst their place.

   So: the delta only, priced before it is run, from the screen where the
   question arises. The findings underneath are not disturbed.

   Three rules this list follows, each the reason a row looks the way it
   does:

     1. A check that already answered is NOT offered. It is listed at the
        bottom, greyed, under its own heading — because an analyst who
        cannot find it needs to be told it is already done, not shown an
        empty list.
     2. A check that cannot run says SO, AND WHY, and is unselectable. A
        missing input and a source refusing our account need different
        people to act, so they do not share a message.
     3. The price is in the footer, pinned, and it counts people. Five
        directors on one person-level check is five paid calls.
*/

interface Candidate {
  id: string
  name: string
  group: string
  /** Required inputs still blank, in words — "Mobile number and UAN". */
  needs: string | null
  /** The source's own sentence, when it is currently refusing us.
   *  Shown on the row and nothing more: the check still runs. */
  warning: string | null
  costPaisa: number
  credits: number
  people: number
  /** Prerequisites not yet on file — run and charged with it. */
  alsoRuns: string[]
  /** This check already has at least one result on file. */
  answered: boolean
  /** How many results are on file, across every run of it. */
  onFileRuns: number
  /** People on file from the runs so far, for a person check. */
  onFile: number
  /** The fields this check asks for, rendered inline. */
  params: (typeof CHECKS)[number]['params']
}

function RunMoreDialog({
  vendor,
  setVendor,
  open,
  onClose,
}: {
  vendor: Vendor
  setVendor: (v: Vendor) => void
  open: boolean
  onClose: () => void
}) {
  const toast = useToast()
  const [picked, setPicked] = useState<string[]>([])
  const [opened, setOpened] = useState<string[]>([])
  const [query, setQuery] = useState('')
  const [running, setRunning] = useState(false)

  /*
    WHICH SOURCES ARE REFUSING OUR ACCOUNT RIGHT NOW.

    Same map, same reasoning and the same safe failure as Step 2: the
    server resolves which CHECK IDS each outage covers, because providers
    do not all bill the same way, and a load failure leaves the map empty
    rather than hiding checks that work.

    Fetched when the dialog OPENS rather than on mount. An outage that
    started while the analyst was reading is exactly the case this has to
    get right, and the whole point of the dialog is that it is opened
    some time after the page was loaded.
  */
  const [blocked, setBlocked] = useState<ReadonlyMap<string, string>>(new Map())

  useEffect(() => {
    if (!open) return
    let live = true
    api
      .listProviderStatus()
      .then((rows) => {
        if (!live) return
        const next = new Map<string, string>()
        for (const row of rows) {
          for (const [checkId, reason] of Object.entries(row.blockedChecks ?? {})) {
            next.set(checkId, reason || 'No reason was returned.')
          }
        }
        setBlocked(next)
      })
      .catch(() => {
        /* an empty map is the safe failure — see above */
      })
    return () => {
      live = false
    }
  }, [open])

  const answered = useMemo(
    () =>
      new Set(
        (vendor.runs ?? Object.values(vendor.checks))
          .filter((r) => ANSWERED.includes(r.status))
          .map((r) => r.checkId),
      ),
    [vendor.runs, vendor.checks],
  )

  /*
    EVERY CHECK, WITH ITS OWN INPUT BOXES. NOTHING WITHHELD.

    What this list used to do, and why none of it survived:

      - it hid checks that had already answered, then listed them at the
        bottom as names only. That broke the way the product is actually
        used. MCA gives you the director list; the person checks give you
        each director's number; those numbers drive employment history and
        digital footprint for the WHOLE BOARD. Every step after the first
        is a re-run of a check that has already answered with a different
        number in the field, and a hidden row made the loop impossible.

      - it put a check with a blank required input in a "Cannot run yet"
        bucket, unselectable, with a button back to Step 2. The dialog
        exists so that nobody has to go back to Step 2. A row that can
        only tell you to leave is worse than no row.

    So every check Step 2 offers is offered here, in Step 2's group order,
    each carrying the same input fields Step 2 carries — the same
    component, so the fallback rule, the multi-value splitter and the
    format warnings cannot drift between the two screens. Fill the field
    on the row, tick it, run it.

    `not_configured` checks are still left out, which is Step 2's stance
    and for Step 2's reason: a dead row between the analyst and a check
    that works is a cost on every visit. Coverage is accounted for in the
    client-facing report, which is what has to stand on its own.
  */
  const candidates = useMemo<Candidate[]>(() => {
    const assumed = Array.from(new Set([...vendor.selected, ...picked]))
    const runs = vendor.runs ?? Object.values(vendor.checks)

    return CHECKS.filter((c) => c.state !== 'not_configured' && !c.always).map((c) => {
      const alsoRuns = withPrerequisites(c.id).filter(
        (id) => id !== c.id && !answered.has(id),
      )
      const gaps = inputGaps(vendor, c.id, assumed)

      return {
        id: c.id,
        name: c.name,
        group: c.group,
        needs: gaps.length ? gaps.map((g) => g.paramLabel).join(' and ') : null,
        warning: blocked.get(c.id) ?? null,
        answered: answered.has(c.id),
        onFileRuns: runs.filter((r) => r.checkId === c.id).length,
        onFile: subjectsOnFile(vendor, c.id),
        costPaisa: (c.costPaisa || 0) * subjectCount(vendor, c.id),
        credits: c.credits || 0,
        people: subjectCount(vendor, c.id),
        alsoRuns,
        params: c.params,
      }
    })
  }, [vendor, answered, blocked, picked])

  const byId = useMemo(() => new Map(candidates.map((c) => [c.id, c])), [candidates])

  /*
    THE PRICE OF WHAT IS TICKED, INCLUDING WHAT IT DRAGS IN.

    A new check may need a prerequisite. One already on file is dropped by
    the server rather than re-bought, so it must not be counted here
    either — quoting a price that includes it and then charging less is
    the same class of mistake as the reverse, and it teaches the analyst
    to distrust the number.
  */
  const quote = useMemo(() => {
    const ids = new Set<string>()
    for (const id of picked) {
      ids.add(id)
      for (const dep of byId.get(id)?.alsoRuns ?? []) ids.add(dep)
    }
    let paisa = 0
    let credits = 0
    for (const id of ids) {
      const def = CHECKS.find((c) => c.id === id)
      if (!def) continue
      paisa += (def.costPaisa || 0) * subjectCount(vendor, id)
      credits += def.credits || 0
    }
    return { ids: Array.from(ids), paisa, credits }
  }, [picked, byId, vendor])

  /*
    TICKED, AND STILL MISSING SOMETHING IT CANNOT RUN WITHOUT.

    With no input there is no request to make, so the server skips the
    check and logs it. That is honest behaviour but a pointless click, and
    the box to fix it is on the row — so the run waits until it is filled
    and the footer says which ones.

    Only what is TICKED counts. A blank field three groups down is not a
    reason to stop a run of something else, which is exactly what the old
    "Cannot run yet" bucket amounted to.
  */
  const blockedTicks = quote.ids
    .map((id) => byId.get(id))
    .filter((c): c is Candidate => Boolean(c?.needs))

  const toggle = (id: string) =>
    setPicked((prev) => {
      const next = prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]
      // Ticking opens the fields. The commonest reason to tick a check is
      // to run it against a value you are about to type.
      if (!prev.includes(id)) setOpened((o) => (o.includes(id) ? o : [...o, id]))
      return next
    })

  /**
   * Add to the selection, then run ONLY the delta.
   *
   * Two calls, in this order, and both are needed. The server runs the
   * intersection of `only` and the vendor's SELECTION — the selection is
   * the record of what this vendor is being charged for, and it is what
   * the report's coverage section reads — so a check that is run has to
   * be selected. Running without selecting first would silently do
   * nothing, which is the worst available outcome for a button that is
   * about to spend money.
   *
   * The INPUTS need no call of their own: every field writes itself as it
   * is typed, through the same endpoint Step 2 uses. A "save then run"
   * button would be a second way for the value on the screen and the
   * value in the request to disagree.
   */
  const confirm = async () => {
    if (!quote.ids.length || blockedTicks.length) return
    setRunning(true)
    try {
      const next = Array.from(new Set([...vendor.selected, ...quote.ids]))
      if (next.length !== vendor.selected.length) {
        setVendor(await api.setSelection(vendor.id, next))
      }
      const result = await api.runChecks(vendor.id, quote.ids)
      setVendor(result.vendor)
      toast(
        `${result.ran} more check${result.ran === 1 ? '' : 's'} settled` +
          (result.costPaisa ? ` · ${rupees(result.costPaisa)}` : ''),
      )
      setPicked([])
      onClose()
    } catch (e) {
      // It stays OPEN on failure, with the ticks intact. Closing would
      // leave the analyst guessing whether anything ran.
      toast.error(e, 'Those checks could not be run.')
    } finally {
      setRunning(false)
    }
  }

  /*
    A SEARCH BOX, because this list is now the whole catalogue.

    Forty-odd rows was a reason to hide things, and hiding things is what
    broke it. A filter narrows the list without deciding anything on the
    analyst's behalf, and a ticked row is never filtered away — losing
    sight of something you have agreed to pay for is not a trade worth
    making for a shorter list.
  */
  const term = query.trim().toLowerCase()
  const matches = (c: Candidate) =>
    !term ||
    picked.includes(c.id) ||
    c.name.toLowerCase().includes(term) ||
    c.id.toLowerCase().includes(term) ||
    (CHECK_GROUPS.find((g) => g.id === c.group)?.name ?? '').toLowerCase().includes(term)

  const shown = candidates.filter(matches)
  const rerunCount = candidates.filter((c) => c.answered).length

  return (
    <Modal
      open={open}
      onClose={running ? () => undefined : onClose}
      wide
      title="Run checks"
      sub={
        'Every check, with its inputs — nothing here needs a trip back to ' +
        'Step 2. Only what you tick is called, and a result already on file ' +
        'is kept: a re-run is added beside it, not over it.'
      }
      footer={
        <>
          <span className="small muted nums">
            {blockedTicks.length > 0 ? (
              <span className="runmore-why">
                {blockedTicks.length === 1
                  ? `${blockedTicks[0].name} needs ${blockedTicks[0].needs}`
                  : `${blockedTicks.length} ticked checks still need an input`}
              </span>
            ) : picked.length === 0 ? (
              'Nothing ticked'
            ) : (
              `${picked.length} check${picked.length === 1 ? '' : 's'}` +
              (quote.ids.length > picked.length
                ? ` + ${quote.ids.length - picked.length} prerequisite`
                : '') +
              ` · ${rupees(quote.paisa)}` +
              (quote.credits ? ` · ${quote.credits} credits` : '')
            )}
          </span>
          <button
            type="button"
            className="btn primary"
            disabled={running || picked.length === 0 || blockedTicks.length > 0}
            onClick={confirm}
          >
            {running && <span className="spinner" aria-hidden="true" />}
            {running
              ? 'Running…'
              : `Run ${quote.ids.length || ''} check${quote.ids.length === 1 ? '' : 's'}`.trim()}
          </button>
        </>
      }
    >
      <div className="stack">
        <div className="runmore-search">
          <input
            className="input"
            type="search"
            value={query}
            placeholder="Filter by check or group — e.g. director, GST, footprint"
            onChange={(e) => setQuery(e.target.value)}
          />
          <span className="small muted nums">
            {shown.length} of {candidates.length}
            {rerunCount > 0 && ` · ${rerunCount} already have a result`}
          </span>
        </div>

        {shown.length === 0 && (
          <p className="small muted">No check matches that filter.</p>
        )}

        {CHECK_GROUPS.map((group) => {
          const rows = shown.filter((c) => c.group === group.id)
          if (!rows.length) return null
          return (
            <div key={group.id} className="runmore-group">
              <div className="runmore-group-h small">{group.name}</div>
              {rows.map((c) => {
                const isPicked = picked.includes(c.id)
                const fieldsOpen = isPicked || opened.includes(c.id)
                return (
                  <div
                    className={`runmore-row-wrap${isPicked ? ' is-picked' : ''}`}
                    key={c.id}
                  >
                    <div className="runmore-row">
                      <label className="runmore-tick">
                        <input
                          type="checkbox"
                          checked={isPicked}
                          onChange={() => toggle(c.id)}
                        />
                        <span className="runmore-name">
                          {c.name}
                          {/* Said on the ROW, not only in the total: five
                              directors on one check is five paid calls, and
                              the row is where the analyst is deciding. */}
                          {c.people > 1 && (
                            <span className="small muted"> · {c.people} people</span>
                          )}
                          {c.alsoRuns.length > 0 && (
                            <span className="small muted">
                              {' '}
                              · also runs {c.alsoRuns.map(nameOf).join(', ')}
                            </span>
                          )}
                          {/* THE SOURCE'S OWN SENTENCE, on a row that is
                              still tickable. The analyst decides whether to
                              spend the round trip; the screen does not
                              decide for them. */}
                          {c.warning && (
                            <span className="runmore-warn small">
                              {' '}
                              · last call was refused: {c.warning}
                            </span>
                          )}
                          {/* A RESULT ON FILE IS A FACT, NOT A WARNING.
                              Running it again adds a result beside the
                              ones already there and the analyst chooses
                              which one counts, so there is nothing here to
                              caution against — only the count, which is
                              the thing somebody working through a board of
                              directors is actually asking about. */}
                          {c.answered && (
                            <span className="runmore-again small">
                              {' '}
                              · {c.onFileRuns} on file
                              {c.onFile > 0 &&
                                ` · ${c.onFile} ` +
                                  (c.onFile === 1 ? 'person' : 'people')}
                            </span>
                          )}
                          {/* WHAT IS MISSING, next to the box that fills
                              it. Not a reason the row cannot be used. */}
                          {c.needs && (
                            <span className="runmore-why small"> · needs {c.needs}</span>
                          )}
                        </span>
                      </label>
                      <span className="runmore-cost small nums muted">
                        {c.costPaisa ? rupees(c.costPaisa) : 'free'}
                        {c.credits ? ` · ${c.credits} cr` : ''}
                      </span>
                      {c.params.length > 0 && (
                        <button
                          type="button"
                          className="btn sm ghost runmore-fields-btn"
                          aria-expanded={fieldsOpen}
                          onClick={() =>
                            setOpened((o) =>
                              o.includes(c.id)
                                ? o.filter((x) => x !== c.id)
                                : [...o, c.id],
                            )
                          }
                        >
                          {fieldsOpen ? 'Hide inputs' : `Inputs (${c.params.length})`}
                        </button>
                      )}
                    </div>

                    {/* THE SAME FIELDS STEP 2 SHOWS, on this row.
                        Prefilled from the vendor record, editable, and each
                        one saves itself as it is typed — so what the screen
                        shows is what the run will send. */}
                    {fieldsOpen && c.params.length > 0 && (
                      <div className="runmore-inputs">
                        {c.params.map((param) => (
                          <ParamField
                            key={param.key}
                            vendor={vendor}
                            setVendor={setVendor}
                            checkId={c.id}
                            param={param}
                            selected={Array.from(
                              new Set([...vendor.selected, ...picked]),
                            )}
                            /* The dialog does not paint a field red for
                               being blank until the check is ticked:
                               nothing is being run, so nothing is yet
                               wrong. Once it is ticked the field is the
                               thing standing between the analyst and the
                               run, and it says so. */
                            missingKeys={
                              new Set(
                                isPicked
                                  ? inputGaps(vendor, c.id, [
                                      ...vendor.selected,
                                      ...picked,
                                    ]).map((g) => `${c.id}.${g.paramKey}`)
                                  : [],
                              )
                            }
                          />
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )
        })}
      </div>
    </Modal>
  )
}

/** Names rather than raw ids — "needs mca, dirs" told nobody anything. */
const nameOf = (id: string): string => CHECKS.find((c) => c.id === id)?.name ?? id

/**
 * The raw payload panel.
 *
 * This used to ALWAYS render a hardcoded placeholder describing what the
 * panel would show "in production", ignoring `result.rawResponse` even when
 * the backend had sent the real payload. So a live run that genuinely
 * called the provider still displayed a stub, which made a correct result
 * look fabricated — the opposite of what an evidence panel is for.
 *
 * The real payload is now shown whenever one exists. The placeholder
 * survives only for the case it was written for: a check that never
 * produced a payload, where it must be OBVIOUS that this is not evidence.
 */
const rawPanel = (
  result: { checkId: string; rawResponse?: unknown },
  vendor: { cin: string | null; domain: string | null },
): { text: string; isReal: boolean } => {
  const raw = result.rawResponse
  const present = raw !== undefined && raw !== null && !(typeof raw === 'object' && Object.keys(raw as object).length === 0)

  if (present) {
    return { text: JSON.stringify(raw, null, 2), isReal: true }
  }
  return {
    text: JSON.stringify(
      {
        _note:
          'No payload was stored for this check, so there is nothing to show. ' +
          'This is a placeholder, NOT provider evidence.',
        checkId: result.checkId,
        request: { cin: vendor.cin, domain: vendor.domain },
      },
      null,
      2,
    ),
    isReal: false,
  }
}

/**
 * Size of a payload, in bytes.
 *
 * This was called with `panel.text.length` — a count of UTF-16 code units,
 * not bytes — and labelled the result "B". Any non-ASCII payload, which is
 * most Indian address data, under-reported its own size.
 */
function formatBytes(text: string): string {
  const n =
    typeof TextEncoder === 'undefined' ? text.length : new TextEncoder().encode(text).length
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

/**
 * ONE RESULT, in full.
 *
 * Pulled out of the accordion because a check no longer holds one result.
 * The person-level checks are run once per director, so a check can hold
 * six, each about a different human being — and every one of them needs
 * the same three tiers underneath it: what was asked, what the parser
 * made of the answer, and the stored bytes.
 *
 * Keyed by RUN rather than by check, so opening the payload of the third
 * director does not open the other five.
 */
function ResultBody({
  vendor,
  checkId,
  result,
  keyId,
  rawOpen,
  toggleRaw,
  copied,
  copy,
}: {
  vendor: Vendor
  checkId: string
  result: CheckResult
  keyId: string
  rawOpen: ReadonlySet<string>
  toggleRaw: (id: string) => void
  copied: string | null
  copy: (id: string, text: string) => void
}) {
  const panel = rawPanel(result, vendor)
  const inputs = askedFor(checkId, vendor, result)

  return (
    <>
      {inputs.length > 0 && (
        <div className="io-block">
          <div className="io-label">What was asked</div>
          <dl className="io-list">
            {inputs.map((row) => (
              <div className="io-row" key={`${row.label}-${row.from ?? ''}`}>
                <dt className="io-key">
                  {row.label}
                  {row.from && <span className="io-from"> from {row.from}</span>}
                </dt>
                <dd className={`io-val${row.value ? '' : ' is-empty'}`}>
                  {row.value || (row.required ? 'not provided' : '—')}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {/* Tier two. Above the provenance line and the raw panel, because
          this is what the reader came for; the payload below it is what
          makes the reading defensible, which is a different job. */}
      <Facts facts={result.facts} />

      <div className="acc-meta">
        <span className={`small ${panel.isReal ? 'muted' : 'warn-text'}`}>
          {panel.isReal
            ? 'Stored provider response — the exact bytes this result was computed from.'
            : 'No stored payload for this check. This is a placeholder, not evidence.'}
        </span>
        <span className="acc-meta-right small muted">
          {result.fetchedAt && <span>{new Date(result.fetchedAt).toLocaleString()}</span>}
          {typeof result.costPaisa === 'number' && result.costPaisa > 0 && (
            <span>₹{(result.costPaisa / 100).toFixed(2)}</span>
          )}
          {/* No size, no buttons when there is no payload. The placeholder
              is a sentence saying nothing was stored; offering "View JSON"
              on it, and a byte count for our own apology text, invites a
              click that can only disappoint. The warning to its left is
              the whole message. */}
          {panel.isReal && (
            <>
              <span>{formatBytes(panel.text)}</span>
              {/* Copy does NOT require opening. Someone sending a payload
                  to whoever maintains an adapter has no reason to read it
                  first. */}
              <button
                type="button"
                className="btn sm ghost"
                onClick={() => copy(keyId, panel.text)}
              >
                {copied === keyId ? 'Copied' : 'Copy JSON'}
              </button>
              <button
                type="button"
                className="btn sm ghost"
                aria-expanded={rawOpen.has(keyId)}
                aria-controls={`raw-${keyId}`}
                onClick={() => toggleRaw(keyId)}
              >
                {rawOpen.has(keyId) ? 'Hide JSON' : 'View JSON'}
              </button>
            </>
          )}
        </span>
      </div>
      {panel.isReal && rawOpen.has(keyId) && (
        <pre className="raw raw-panel" id={`raw-${keyId}`}>
          {panel.text}
        </pre>
      )}
    </>
  )
}

/* =====================================================================
   THE RESULTS OF ONE CHECK
   =====================================================================

   A check used to hold exactly one result and a re-run overwrote it. That
   was wrong in a way that cost real evidence: the five person-level checks
   are run once per director, so running the second director erased the
   first, and the screen gave no sign that anything had been there.

   Every result is now kept, and ONE of them is primary — the one SCAN, the
   risk score and the report read. The rest sit beside it, each tagged with
   the input it was run against, each deletable, and any of them promotable.

   Two rules this list follows, and both are about not lying by layout:

     1. THE PRIMARY IS NAMED, not implied by position. "Newest at the top"
        is how the number would be guessed wrong — the analyst who marked
        the second result is exactly the person for whom position means
        nothing.
     2. DELETING ASKS FIRST, and says what happens to the score. Deleting
        the primary promotes the newest remaining rather than leaving the
        check unscored, and an analyst who does not know that will think
        they have removed a finding when they have swapped it.
*/
function RunList({
  vendor,
  setVendor,
  checkId,
  runs,
  rawOpen,
  toggleRaw,
  copied,
  copy,
}: {
  vendor: Vendor
  setVendor: (v: Vendor) => void
  checkId: string
  runs: CheckResult[]
  rawOpen: ReadonlySet<string>
  toggleRaw: (id: string) => void
  copied: string | null
  copy: (id: string, text: string) => void
}) {
  const toast = useToast()
  const [busy, setBusy] = useState<number | null>(null)
  const [asking, setAsking] = useState<number | null>(null)
  const [reason, setReason] = useState('')

  /*
    ONE RESULT IS QUIETER, NOT BARE.

    The header used to be suppressed entirely for a check that had run
    once: nothing to choose between, and a "Counts" tag on a list of one
    is noise that teaches the reader to ignore the tag on the lists where
    it matters. Both still true — so the ORDINAL and the primary controls
    are what a single result does without.

    The header itself stays, because it now carries Ignore, and a result
    that cannot be set aside because it happens to be the only one is a
    control that disappears exactly when it is first needed. A check run
    once and run wrong is the ordinary case, not an edge one.

    `single` therefore means "do not clutter", never "do not offer".
  */
  const single = runs.length === 1 && !runs[0]?.ignoredAt

  const mark = async (runId: number) => {
    setBusy(runId)
    try {
      setVendor(await api.markPrimary(vendor.id, runId))
      toast('The score and the report now read this result.')
    } catch (e) {
      toast.error(e, 'That result could not be marked.')
    } finally {
      setBusy(null)
    }
  }

  /*
    SET ASIDE, NOT DELETED.

    There was a Delete here. It did what the analyst wanted — take a
    result out of the score — by destroying the evidence and the spend
    record to get there, which put two of this product's commitments
    against each other and resolved them the wrong way.

    The row now stays whole. Only the score stops reading it, and the
    reason is kept beside it, because a file that cannot say why a
    finding was set aside is not one anybody can defend a year later.
  */
  const ignore = async (runId: number) => {
    if (!reason.trim()) return
    setBusy(runId)
    try {
      setVendor(await api.ignoreRun(vendor.id, runId, reason.trim()))
      setAsking(null)
      setReason('')
      toast('Set aside. It is kept, and still counted as spend.')
    } catch (e) {
      toast.error(e, 'That result could not be set aside.')
    } finally {
      setBusy(null)
    }
  }

  const reinstate = async (runId: number) => {
    setBusy(runId)
    try {
      setVendor(await api.unignoreRun(vendor.id, runId))
      toast('Back in force.')
    } catch (e) {
      toast.error(e, 'That result could not be reinstated.')
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      {runs.map((run, index) => {
        const keyId = run.id === undefined ? checkId : `${checkId}#${run.id}`
        const subject = runSubject(checkId, run)

        return (
          <div
            className={
              `run-item${run.isPrimary && !single ? ' is-primary' : ''}` +
              (run.ignoredAt ? ' is-aside' : '')
            }
            key={keyId}
          >
            {(
              <div className={`run-head${single ? ' is-lone' : ''}`}>
                {!single && (
                  <span className="run-ord small nums muted">
                    #{runs.length - index}
                  </span>
                )}
                {!single && <StatusBadge status={run.status} />}
                <span className="run-sum">
                  {!single && <span className="run-value">{run.value || '—'}</span>}
                  {/* THE INPUT IS THE IDENTITY of a result on a check that
                      was run several times. Without it the list reads as
                      four answers to one question. */}
                  {!single && subject && (
                    <span className="small mono muted"> · {subject}</span>
                  )}
                  {!single && run.fetchedAt && (
                    <span className="small muted">
                      {' '}
                      · {new Date(run.fetchedAt).toLocaleString()}
                    </span>
                  )}
                </span>

                {/* SET ASIDE: the tag says so, and says WHY on the row
                    rather than in a tooltip. A result that quietly stops
                    counting is the one thing this must never produce. */}
                {run.ignoredAt ? (
                  <>
                    <span className="run-aside-tag" title={run.ignoreReason ?? ''}>
                      Set aside
                    </span>
                    <span className="run-aside-why small">
                      {run.ignoreReason}
                      {run.ignoredBy && (
                        <span className="muted"> · {run.ignoredBy}</span>
                      )}
                    </span>
                    <button
                      type="button"
                      className="btn sm ghost"
                      disabled={busy !== null || run.id === undefined}
                      onClick={() => run.id !== undefined && void reinstate(run.id)}
                    >
                      Reinstate
                    </button>
                  </>
                ) : (
                  <>
                    {/* The primary controls are the part a list of one
                        does without: there is nothing to choose between. */}
                    {single ? null : run.isPrimary ? (
                      <span
                        className="run-tag"
                        title="The score and the report read this result"
                      >
                        Counts
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="btn sm ghost"
                        disabled={busy !== null || run.id === undefined}
                        onClick={() => run.id !== undefined && void mark(run.id)}
                      >
                        Use this
                      </button>
                    )}

                    {/* ASKS FOR A REASON, in place, and will not proceed
                        without one. Ignoring moves a client-facing number;
                        the server refuses a blank reason and so does this,
                        rather than letting the analyst discover the rule
                        from an error. */}
                    {asking === run.id ? (
                      <span className="run-confirm small">
                        <input
                          className="input run-reason"
                          autoFocus
                          value={reason}
                          placeholder={
                            run.isPrimary
                              ? 'Why? The newest result still in force takes over.'
                              : 'Why is this being set aside?'
                          }
                          onChange={(e) => setReason(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && run.id !== undefined) {
                              void ignore(run.id)
                            }
                            if (e.key === 'Escape') {
                              setAsking(null)
                              setReason('')
                            }
                          }}
                        />
                        <button
                          type="button"
                          className="btn sm primary"
                          disabled={busy !== null || !reason.trim()}
                          onClick={() => run.id !== undefined && void ignore(run.id)}
                        >
                          Set aside
                        </button>
                        <button
                          type="button"
                          className="btn sm ghost"
                          onClick={() => {
                            setAsking(null)
                            setReason('')
                          }}
                        >
                          Cancel
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="btn sm ghost run-del"
                        disabled={busy !== null || run.id === undefined}
                        onClick={() => {
                          setReason('')
                          if (run.id !== undefined) setAsking(run.id)
                        }}
                      >
                        Ignore
                      </button>
                    )}
                  </>
                )}
              </div>
            )}

            <ResultBody
              vendor={vendor}
              checkId={checkId}
              result={run}
              keyId={keyId}
              rawOpen={rawOpen}
              toggleRaw={toggleRaw}
              copied={copied}
              copy={copy}
            />
          </div>
        )
      })}
    </>
  )
}

export default function Findings({ vendor, setVendor, setPrimary }: PageProps) {
  const navigate = useNavigate()
  const [runMore, setRunMore] = useState(false)

  // A SET, not a single id. Previously only one payload could be open at a
  // time and opening a second silently closed the first, which made
  // comparing two sources against each other impossible — the single most
  // common thing an analyst actually does with this screen.
  const [open, setOpen] = useState<Set<string>>(() => new Set())
  const [copied, setCopied] = useState<string | null>(null)

  /*
    THE RAW PAYLOAD IS COLLAPSED BY DEFAULT.

    It used to print the moment a check was expanded — sixteen kilobytes
    of provider JSON under a readable six-row summary, so the facts the
    analyst came for scrolled off the top the instant they opened
    anything, and a screen that reads as professional turned into a
    terminal dump.

    Collapsing it is a presentation choice, NOT a disclosure one. The
    provenance line above stays visible on every check, "Copy JSON" still
    works without opening anything, and the button says plainly that the
    bytes are there. The evidence is one click away rather than in your
    face — which is the right order, because the summary is what is read
    and the payload is what makes the reading defensible. Those are
    different jobs and they do not deserve equal space.

    Separate from `open`: a reader comparing two sources wants both
    summaries side by side, and almost never wants both raw dumps.
  */
  const [rawOpen, setRawOpen] = useState<Set<string>>(() => new Set())

  const toggleRaw = (id: string) =>
    setRawOpen((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const toggleOne = (id: string) => {
    // Closing a check also closes its payload, so reopening starts on the
    // summary rather than halfway down a JSON dump left open ten minutes
    // ago.
    setRawOpen((prev) => {
      if (!prev.has(id)) return prev
      const next = new Set(prev)
      next.delete(id)
      return next
    })
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleGroup = (ids: string[], expand: boolean) => {
    if (!expand) setRawOpen(() => new Set())
    setOpen((prev) => {
      const next = new Set(prev)
      ids.forEach((id) => (expand ? next.add(id) : next.delete(id)))
      return next
    })
  }

  const copy = (id: string, text: string) => {
    void navigator.clipboard?.writeText(text).then(
      () => {
        setCopied(id)
        window.setTimeout(() => setCopied((c) => (c === id ? null : c)), 1500)
      },
      () => setCopied(null),
    )
  }

  /*
    ONLY WHAT IS CURRENTLY SELECTED.
    -------------------------------
    Results are stored per check and never wiped, so a vendor whose
    selection changed between runs still HOLDS results for checks that are
    no longer in scope. Showing those made this screen disagree with Step 2
    and put a stale answer beside a live one with nothing marking which.

    `vendor.selected` is the server's EXPANDED selection — prerequisites
    folded in by expand_selection() — so a check pulled in because
    something else needed it still appears. It ran, it cost money, and it
    fed another row here.

    Nothing is deleted: re-selecting a check in Step 2 brings its row
    straight back without re-running it.
  */
  const inScope = (checkId: string) => vendor.selected.includes(checkId)

  const results = Object.values(vendor.checks).filter((r) => inScope(r.checkId))

  const counts = useMemo(() => {
    const by = (s: CheckStatus) => results.filter((r) => r.status === s).length
    const skippedInput = by('skipped_missing_input')
    const notApplicable = by('skip')
    const unavailable = by('unavailable')

    return {
      pass: by('pass'),
      warn: by('warn'),
      fail: by('fail'),
      skippedInput,
      notApplicable,
      unavailable,
      notChecked: skippedInput + notApplicable + unavailable,
    }
  }, [results, vendor.selected])

  useEffect(() => {
    setPrimary(
      <>
        {/* SECONDARY, beside the step's own action and not instead of it.
            Adding a check is a detour; moving on is the path. A primary
            button here would compete with the one that advances the file. */}
        <button type="button" className="btn ghost" onClick={() => setRunMore(true)}>
          Run more checks
        </button>
        <button type="button" className="btn primary" onClick={() => navigate(`/vendor/${vendor.id}/manual`)}>
          Record manual entries →
        </button>
      </>,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vendor.id])

  const dialog = (
    <RunMoreDialog
      vendor={vendor}
      setVendor={setVendor}
      open={runMore}
      onClose={() => setRunMore(false)}
    />
  )

  if (results.length === 0) {
    return (
      <>
        {dialog}
        <EmptyState
          title="No checks have run yet"
          body="Select the checks this vendor warrants and run them. Findings, scoring and the report all build from what comes back."
          action={
            <button type="button" className="btn primary" onClick={() => navigate(`/vendor/${vendor.id}/select`)}>
              Choose what to check
            </button>
          }
        />
      </>
    )
  }

  return (
    <div className="stack">
      {dialog}

      <div>
        <div className="kicker">Step 3 · Evidence</div>
        <h2 className="page-h">Findings</h2>
        <p className="page-sub">
          Every check that ran, with the exact response it was computed from.
        </p>
      </div>

      <div className="grid-4">
        <Tile n={counts.pass} label="Passed" tone="pass" />
        <Tile n={counts.warn} label="Needs attention" tone="warn" />
        <Tile n={counts.fail} label="Adverse" tone="adverse" />
        <Tile
          n={counts.notChecked}
          label="Not checked"
          tone="unchecked"
          note={
            [
              counts.skippedInput && `${counts.skippedInput} missing input`,
              counts.notApplicable && `${counts.notApplicable} not applicable`,
              counts.unavailable && `${counts.unavailable} unavailable`,
            ]
              .filter(Boolean)
              .join(' · ') || undefined
          }
        />
      </div>

      {CHECK_GROUPS.map((group) => {
        /*
          A CHECK WHOSE EVERY RESULT WAS SET ASIDE STAYS ON THIS SCREEN.

          This read `vendor.checks[c.id]`, which holds only results in
          force — so setting aside the last result of a check made the
          whole row disappear. Three things wrong with that, and the
          third is the one that bites: it looks deleted, when the point
          of Ignore is that nothing is; the reader cannot see that a
          finding was taken out, which is the opposite of what an audit
          file is for; and the Reinstate button goes with it, so the act
          becomes irreversible through the screen that performed it.
        */
        const rows = CHECKS.filter(
          (c) =>
            c.group === group.id &&
            inScope(c.id) &&
            (vendor.checks[c.id] ||
              (vendor.runs ?? []).some((r) => r.checkId === c.id)),
        )
        if (!rows.length) return null

        const ids = rows.map((c) => c.id)
        const openHere = ids.filter((id) => open.has(id)).length

        return (
          <Card
            key={group.id}
            title={group.name}
            tight
            aside={
              <button
                type="button"
                className="btn sm ghost"
                onClick={() => toggleGroup(ids, openHere !== ids.length)}
              >
                {openHere === ids.length ? 'Collapse all' : 'Expand all'}
              </button>
            }
          >
            <div className="acc">
              {rows.map((check) => {
                const isOpen = open.has(check.id)
                /*
                  EVERY RESULT OF THIS CHECK, newest first, with the
                  primary among them — not just the one that counts.

                  `vendor.checks` is the primary per check and is what the
                  header reads, because the header is the summary and the
                  summary has to be the number the report will carry.
                  `vendor.runs` is the lot. An older payload with no `runs`
                  degrades to the single result it has, which is exactly
                  what it used to show.
                */
                const runs = (vendor.runs ?? []).filter((r) => r.checkId === check.id)
                const inForce = vendor.checks[check.id]
                const theseRuns = runs.length ? runs : inForce ? [inForce] : []

                /*
                  The header summarises what COUNTS. With nothing in
                  force there is no such thing, so it summarises the
                  state instead — "set aside", with the reason — rather
                  than borrowing the first ignored result's words and
                  presenting a withdrawn finding as the finding.
                */
                const aside = !inForce
                const reasons = aside
                  ? Array.from(
                      new Set(
                        theseRuns
                          .map((r) => r.ignoreReason)
                          .filter(Boolean) as string[],
                      ),
                    )
                  : []
                const result = inForce ?? theseRuns[0]
                if (!result) return null

                return (
                  <div className={`acc-item${isOpen ? ' is-open' : ''}`} key={check.id}>
                    <button
                      type="button"
                      className="acc-head"
                      onClick={() => toggleOne(check.id)}
                      aria-expanded={isOpen}
                      aria-controls={`panel-${check.id}`}
                    >
                      <span className="acc-chev" aria-hidden="true">
                        ›
                      </span>

                      <span className="acc-check">
                        <span className="acc-name">{check.name}</span>
                        {/* SAID ON THE CLOSED ROW, under the name rather
                            than in a column of its own: the header is a
                            fixed grid and a sixth child only appears on
                            some rows, which would misalign every row
                            around it. A check holding six results, five of
                            them about other directors, must not read as
                            one finding to somebody who never opens it. */}
                        {theseRuns.length > 1 && (
                          <span className="acc-runs small nums">
                            {theseRuns.length} results · one counts
                          </span>
                        )}
                      </span>

                      <span className="acc-status">
                        {aside ? (
                          <span className="run-aside-tag">Set aside</span>
                        ) : (
                          <StatusBadge status={result.status} />
                        )}
                      </span>

                      <span className="acc-result">
                        <span className="acc-value">
                          {aside
                            ? `${theseRuns.length} result${
                                theseRuns.length === 1 ? '' : 's'
                              } set aside`
                            : result.value || '—'}
                        </span>
                        <span className="small muted">
                          {aside
                            ? reasons.join('; ') ||
                              'Kept as evidence; not read by the score.'
                            : publicDetail(result.detail, { capitalise: true }) ||
                              STATUS_EXPLANATION[result.status]}
                        </span>
                      </span>


                      {/* "View response" was accurate and unhelpful: what
                          opened was a JSON dump. It now opens a readable
                          breakdown for any check whose parser is written,
                          with the payload still underneath. */}
                      <span className="acc-cta small">
                        {isOpen ? 'Hide' : 'View'} {result.facts ? 'details' : 'response'}
                      </span>
                    </button>

                    {isOpen && (
                      <div className="acc-body" id={`panel-${check.id}`}>
                        <RunList
                          vendor={vendor}
                          setVendor={setVendor}
                          checkId={check.id}
                          runs={theseRuns}
                          rawOpen={rawOpen}
                          toggleRaw={toggleRaw}
                          copied={copied}
                          copy={copy}
                        />
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </Card>
        )
      })}

    </div>
  )
}
