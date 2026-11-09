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
import type { CheckStatus, Vendor } from '@/types/domain'

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
  /** Null when it can be run. Otherwise why not, in words.
   *  A source refusing us is NOT one of these — see `warning`. */
  blockedBy: string | null
  /** The source's own sentence, when it is currently refusing us.
   *  Shown on the row and nothing more: the check still runs. */
  warning: string | null
  /** The field to go and fill, when that is what is missing. */
  needsField: string | null
  costPaisa: number
  credits: number
  people: number
  /** Prerequisites not yet on file — run and charged with it. */
  alsoRuns: string[]
  /** This check already has a result. Re-running REPLACES it. */
  answered: boolean
  /** People on file from the last run, for a person check. */
  onFile: number
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
  const navigate = useNavigate()
  const toast = useToast()
  const [picked, setPicked] = useState<string[]>([])
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
        Object.values(vendor.checks)
          .filter((r) => ANSWERED.includes(r.status))
          .map((r) => r.checkId),
      ),
    [vendor.checks],
  )

  /*
    Everything the analyst could add, with the reason it cannot be added
    where there is one.

    `not_configured` checks are left out entirely, which is Step 2's
    stance and for Step 2's reason: a dead row between the analyst and a
    check that works is a cost on every visit. Coverage is accounted for
    in the client-facing report, which is what has to stand on its own.
  */
  const candidates = useMemo<Candidate[]>(() => {
    const assumed = Array.from(new Set([...vendor.selected, ...picked]))

    /**
     * Why this one check cannot run, ignoring what it depends on.
     *
     * `what` is the bare thing that is wrong — "CNR", or the source's own
     * sentence — kept apart from the finished phrasing so it can be
     * composed into a second one further down without being re-worded.
     * Lower-casing a finished sentence turned "CNR" into "cnr", which
     * reads as a field name we failed to translate.
     */
    const ownBlocker = (
      id: string,
    ): { why: string; what: string; field: string | null } | null => {
      // A SOURCE REFUSING US IS NO LONGER A REASON NOT TO RUN.
      //
      // It used to be: a blocked check sat in "Cannot run yet" and
      // could not be ticked. That is a prediction from what the source
      // said to somebody else, and on 7 Nov 2026 it cost four working
      // Gridlines checks over a refusal on a fifth. The analyst is
      // still told — `warning` below carries the source's own sentence
      // onto the row — but it does not stop them.
      //
      // A MISSING INPUT still stops a check, and the difference is
      // real: with no input there is no request to make, so the call
      // genuinely cannot happen. That is a fact about us, not a guess
      // about them.
      const gaps = inputGaps(vendor, id, assumed)
      if (!gaps.length) return null
      const what = gaps.map((g) => g.paramLabel).join(' and ')
      return { why: `Needs ${what}`, what, field: gaps[0].paramKey }
    }

    /*
      ALREADY-RUN CHECKS ARE OFFERED, NOT HIDDEN.

      They were excluded here, and listed at the bottom as names only.
      That broke the way this product is actually used:

          MCA gives you the director list
          -> the person checks give you each director's number
          -> those numbers drive employment history and digital
             footprint for the WHOLE BOARD

      Every step after the first is a re-run of a check that has already
      answered, with different numbers in the field. Hiding those rows
      made the loop impossible without going back to Step 2 and running
      everything again.

      Re-running costs money and REPLACES the previous result — one row
      per vendor per check — so the row says both, and nothing is
      pre-ticked.
    */
    return CHECKS.filter(
      (c) => c.state !== 'not_configured' && !c.always,
    ).map((c) => {
      const alsoRuns = withPrerequisites(c.id).filter(
        (id) => id !== c.id && !answered.has(id),
      )
      const own = ownBlocker(c.id)

      /*
        A CHECK IS ONLY AS RUNNABLE AS WHAT IT DEPENDS ON.

        Employment history chains off EPFO membership, which needs a
        contact number. Judged on its own the first looks ready, so it
        was offered as tickable while the thing it reads from sat in
        "cannot run yet" three rows below — a ticked box that could only
        produce a skipped check and a confused analyst.

        A prerequisite ALREADY ON FILE is not consulted: the server drops
        it rather than re-running it, so whatever is blocking it now is
        irrelevant to this run.
      */
      const upstream = alsoRuns.map((id) => ({ id, blocker: ownBlocker(id) }))
        .find((u) => u.blocker)

      return {
        id: c.id,
        name: c.name,
        group: c.group,
        blockedBy: own
          ? own.why
          : upstream
            ? `Needs ${upstream.blocker!.what}, for ${nameOf(upstream.id)}`
            : null,
        needsField: own ? own.field : (upstream?.blocker?.field ?? null),
        warning: blocked.get(c.id) ?? null,
        answered: answered.has(c.id),
        onFile: subjectsOnFile(vendor, c.id),
        costPaisa: (c.costPaisa || 0) * subjectCount(vendor, c.id),
        credits: c.credits || 0,
        people: subjectCount(vendor, c.id),
        alsoRuns,
      }
    })
  }, [vendor, answered, blocked, picked])

  const byId = useMemo(
    () => new Map(candidates.map((c) => [c.id, c])),
    [candidates],
  )

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

  const toggle = (id: string) =>
    setPicked((prev) => (prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]))

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
   */
  const confirm = async () => {
    if (!quote.ids.length) return
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

  // NOT YET RUN FIRST, within each group. A re-run is the deliberate
  // case and costs money twice; something never asked is the ordinary
  // one. Order is otherwise the catalog's, which is the screen order
  // everywhere else.
  const runnable = candidates
    .filter((c) => !c.blockedBy)
    .sort((a, b) => Number(a.answered) - Number(b.answered))
  const held = candidates.filter((c) => c.blockedBy)
  const done = candidates.filter((c) => c.answered)

  return (
    <Modal
      open={open}
      onClose={running ? () => undefined : onClose}
      wide
      title="Run more checks"
      sub={
        `Only what you tick is called. ` +
        (done.length
          ? `${done.length} already answered and can be run again with ` +
            `different inputs — those are charged again and replace what ` +
            `is on file.`
          : `Nothing on file is called or charged again.`)
      }
      footer={
        <>
          <span className="small muted nums">
            {picked.length === 0
              ? 'Nothing selected'
              : `${picked.length} check${picked.length === 1 ? '' : 's'}` +
                (quote.ids.length > picked.length
                  ? ` + ${quote.ids.length - picked.length} prerequisite`
                  : '') +
                ` · ${rupees(quote.paisa)}` +
                (quote.credits ? ` · ${quote.credits} credits` : '')}
          </span>
          <button
            type="button"
            className="btn primary"
            disabled={running || picked.length === 0}
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
        {runnable.length === 0 && held.length === 0 && (
          <p className="small muted">
            Every check with a source behind it has already answered for this
            vendor. There is nothing left to add.
          </p>
        )}

        {CHECK_GROUPS.map((group) => {
          const rows = runnable.filter((c) => c.group === group.id)
          if (!rows.length) return null
          return (
            <div key={group.id} className="runmore-group">
              <div className="runmore-group-h small">{group.name}</div>
              {rows.map((c) => (
                <label className="runmore-row" key={c.id}>
                  <input
                    type="checkbox"
                    checked={picked.includes(c.id)}
                    onChange={() => toggle(c.id)}
                  />
                  <span className="runmore-name">
                    {c.name}
                    {/* Said on the ROW, not only in the total: five
                        directors on one check is five paid calls, and the
                        row is where the analyst is deciding. */}
                    {c.people > 1 && (
                      <span className="small muted"> · {c.people} people</span>
                    )}
                    {c.alsoRuns.length > 0 && (
                      <span className="small muted">
                        {' '}
                        · also runs {c.alsoRuns.map(nameOf).join(', ')}
                      </span>
                    )}
                    {/* THE SOURCE'S OWN SENTENCE, on a row that is still
                        tickable. The analyst decides whether to spend the
                        round trip; the screen does not decide for them. */}
                    {c.warning && (
                      <span className="runmore-warn small">
                        {' '}
                        · last call was refused: {c.warning}
                      </span>
                    )}
                    {/* ALREADY ANSWERED. Offered, never pre-ticked, and
                        honest about both consequences: it is charged
                        again, and it REPLACES what is on file rather
                        than adding to it. An analyst running the board
                        one director at a time would otherwise lose the
                        first three. */}
                    {/* ALREADY ANSWERED. A SHORT marker, because the
                        consequence — charged again, replaces what is on
                        file — is stated once in the header and repeating
                        it on sixteen rows buried the check names it was
                        meant to qualify.

                        The people count is the part that is NOT in the
                        header and cannot be: "already run for 3 people"
                        against six numbers now in the field is exactly
                        the question an analyst working through a board
                        of directors is asking. */}
                    {c.answered && (
                      <span className="runmore-again small">
                        {' '}
                        · already run
                        {c.onFile > 0 && ` · ${c.onFile} ` +
                          (c.onFile === 1 ? 'person' : 'people') + ' on file'}
                      </span>
                    )}
                  </span>
                  <span className="runmore-cost small nums muted">
                    {c.costPaisa ? rupees(c.costPaisa) : 'free'}
                    {c.credits ? ` · ${c.credits} cr` : ''}
                  </span>
                </label>
              ))}
            </div>
          )
        })}

        {/* CANNOT RUN, AND WHY — not hidden, and not silently disabled.
            A missing input is the analyst's to fix and gets a link to the
            field; a source refusing our account is not, and gets the
            source's own sentence instead of an action it cannot offer. */}
        {held.length > 0 && (
          <div className="runmore-group">
            <div className="runmore-group-h small runmore-held-h">
              <span>Cannot run yet ({held.length})</span>
              {/* ONE action for the section, not one per row. Every one of
                  these buttons went to the same screen, and fourteen of
                  them down the right-hand side read as fourteen different
                  things to do. */}
              {held.some((c) => c.needsField) && (
                <button
                  type="button"
                  className="btn sm ghost"
                  onClick={() => {
                    onClose()
                    navigate(`/vendor/${vendor.id}/select`)
                  }}
                >
                  Fill inputs in on Step 2 →
                </button>
              )}
            </div>
            {held.map((c) => (
              <div className="runmore-row is-held" key={c.id}>
                <span className="runmore-name">{c.name}</span>
                <span className="small muted runmore-why">{c.blockedBy}</span>
              </div>
            ))}
          </div>
        )}

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
        const rows = CHECKS.filter(
          (c) => c.group === group.id && vendor.checks[c.id] && inScope(c.id),
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
                const result = vendor.checks[check.id]
                const isOpen = open.has(check.id)
                const panel = rawPanel(result, vendor)
                const inputs = inputsFor(check.id, vendor)

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
                        {/* <span className="small mono muted">{check.endpoint}</span> */}
                      </span>

                      <span className="acc-status">
                        <StatusBadge status={result.status} />
                      </span>

                      <span className="acc-result">
                        <span className="acc-value">{result.value || '—'}</span>
                        <span className="small muted">
                          {publicDetail(result.detail, { capitalise: true }) ||
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
                        {inputs.length > 0 && (
                          <div className="io-block">
                            <div className="io-label">What was asked</div>
                            <dl className="io-list">
                              {inputs.map((row) => (
                                <div className="io-row" key={`${row.label}-${row.from ?? ''}`}>
                                  <dt className="io-key">
                                    {row.label}
                                    {row.from && (
                                      <span className="io-from"> from {row.from}</span>
                                    )}
                                  </dt>
                                  <dd className={`io-val${row.value ? '' : ' is-empty'}`}>
                                    {row.value || (row.required ? 'not provided' : '—')}
                                  </dd>
                                </div>
                              ))}
                            </dl>
                          </div>
                        )}

                        {/* Tier two. Above the provenance line and the raw
                            panel, because this is what the reader came for;
                            the payload below it is what makes the reading
                            defensible, which is a different job. */}
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
                            {/* No size, no buttons when there is no payload.
                                The placeholder is a sentence saying nothing
                                was stored; offering "View JSON" on it, and a
                                byte count for our own apology text, invites
                                a click that can only disappoint. The warning
                                to its left is the whole message. */}
                            {panel.isReal && (
                              <>
                                <span>{formatBytes(panel.text)}</span>
                                {/* Copy does NOT require opening. Someone
                                    sending a payload to whoever maintains an
                                    adapter has no reason to read it first. */}
                                <button
                                  type="button"
                                  className="btn sm ghost"
                                  onClick={() => copy(check.id, panel.text)}
                                >
                                  {copied === check.id ? 'Copied' : 'Copy JSON'}
                                </button>
                                <button
                                  type="button"
                                  className="btn sm ghost"
                                  aria-expanded={rawOpen.has(check.id)}
                                  aria-controls={`raw-${check.id}`}
                                  onClick={() => toggleRaw(check.id)}
                                >
                                  {rawOpen.has(check.id) ? 'Hide JSON' : 'View JSON'}
                                </button>
                              </>
                            )}
                          </span>
                        </div>
                        {panel.isReal && rawOpen.has(check.id) && (
                          <pre className="raw raw-panel" id={`raw-${check.id}`}>
                            {panel.text}
                          </pre>
                        )}
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