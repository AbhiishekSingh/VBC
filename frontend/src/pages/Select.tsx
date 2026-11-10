/**
 * Step 2 — choose what to check.
 *
 * Three things this screen must get right:
 *
 * 1. COST UNITS ARE NEVER SUMMED. Rupees, WhoisXML credits and screenshot
 *    credits are three separate budgets drawn from three separate pools.
 *    Adding them would produce a number that means nothing.
 *
 * 2. UNCONFIGURED CHECKS ARE NOT SHOWN HERE. They were, greyed out, so a
 *    gap in coverage could not pass for completeness. That argument holds
 *    for the DELIVERABLE, not for this screen: seven dead rows sat between
 *    the analyst and the checks that work. Coverage is accounted for in
 *    the client-facing report (Report.tsx), which is what has to stand on
 *    its own. Hiding a gap from a working screen is presentation; hiding
 *    it from the report would not be.
 *
 * 3. DESELECTION IS FREE AND UNWARNED. That is the client's explicit
 *    choice. Coverage is presented as a neutral readout — what this
 *    selection can and cannot fill — rather than as a nag.
 *
 * WHAT CHANGED IN THE UI PASS
 * ---------------------------
 * The catalogue holds 47 checks in 8 groups, all rendered at once, and
 * every tick was one click AND one round trip: selecting the eleven MCA
 * checks was eleven of each. Added here, all presentational:
 *
 *   - a tri-state checkbox per group, and Select all / Clear all / preset
 *     bundles for the page. Each performs ONE setSelection call with the
 *     whole array — the same endpoint the single toggle already used.
 *   - groups collapse, and a search + filter row narrows 47 rows to the
 *     ones you are actually deciding about.
 *   - the checkbox moves immediately and reverts if the write fails,
 *     instead of not moving until the server answers.
 *   - a failed toggle now says so. It used to throw unhandled and leave
 *     the box silently un-ticked.
 *   - the run shows progress rather than a disabled button.
 *
 * The API surface is untouched: same calls, same arguments, same order.
 */

import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '@/api'
import { errorMessage, errorTitle } from '@/api/http'
import { inputValue, missingInputs } from '@/api/mock'
import ParamField from '@/components/ParamField'
import { checkCostPaisa } from '@/lib/pricing'
import { blockingProblems } from '@/lib/validate'
import {
  CHECKS,
  CHECK_GROUPS,
  COMPANY_UNLOCK_PAISA,
  DIRECTOR_UNLOCK_PAISA,
  SCAN_PARAMETERS,
} from '@/catalog/generated'
import {
  Callout,
  ProgressBar,
  Tile,
  TriCheckbox,
  rupees,
} from '@/components/ui'
import { useToast } from '@/hooks/useToast'
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

/** Checks that would be orphaned if this one were switched off. */
function dependentsOf(checkId: string): string[] {
  return CHECKS.filter((c) => (c.requires as readonly string[]).includes(checkId)).map((c) => c.id)
}

/**
 * A selectable check is one with a provider wired up at all.
 *
 * A SOURCE CURRENTLY REFUSING US NO LONGER MAKES A CHECK UNSELECTABLE.
 *
 * It used to. `blocked` would drop the check out of every preset, every
 * group toggle and every count, and the tick could not be set. On
 * 7 Nov 2026 that cost a whole provider: Gridlines refused ONE of its
 * five products while three others answered 200 in the same second, and
 * the screen offered none of them.
 *
 * `blocked` is still read — the row still carries the source's own
 * sentence, so an analyst knows before they wait and somebody can go and
 * pay the invoice. It is information now, not a gate. The call goes out
 * regardless, because what a source said to somebody else a few minutes
 * ago is a PREDICTION, and a prediction must never stand in for asking.
 *
 * Still a parameter rather than module state: a stale copy of "what is
 * down" is worse than none.
 */
const isSelectable = (id: string, _blocked?: ReadonlyMap<string, string>): boolean => {
  const def = CHECKS.find((c) => c.id === id)
  return Boolean(def) && def!.state !== 'not_configured' && !def!.always
}

/**
 * Checks that have ANSWERED and are therefore locked on.
 *
 * ONLY pass / warn / fail count. A check whose results are all
 * `unavailable`, `not_configured` or `skipped_missing_input` produced no
 * evidence — nothing was examined, so there is nothing to protect and it
 * stays unlocked and re-runnable. This is the runner's own definition of
 * "already on file", deliberately, so the screen and the server cannot
 * disagree about what a second Run would charge for.
 *
 * Read from `checks`, not `runs`: `checks` holds the results in force, so
 * a check whose every result was SET ASIDE unlocks again — which is
 * right, because the analyst has said the evidence does not stand and
 * running it again is how they replace it.
 */
const ANSWERED: CheckStatus[] = ['pass', 'warn', 'fail']

function answeredChecks(vendor: Vendor): Set<string> {
  return new Set(
    Object.values(vendor.checks)
      .filter((r) => ANSWERED.includes(r.status))
      .map((r) => r.checkId),
  )
}

/** Names rather than raw ids — "needs mca, dirs" told nobody anything. */
const nameOf = (id: string): string => CHECKS.find((c) => c.id === id)?.name ?? id

/*
  No 'configured' any more. Unconfigured checks are not rendered at all,
  so the filter matched every visible row and did nothing.
*/
type Filter = 'all' | 'selected' | 'free'

export default function Select({ vendor, setVendor, setPrimary }: PageProps) {
  const navigate = useNavigate()
  const toast = useToast()
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState<unknown>(null)
  const [pending, setPending] = useState<string[]>([])
  const [collapsed, setCollapsed] = useState<string[]>([])
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const selected = vendor.selected

  /*
    LOCKED ON: a check that has already answered.

    Deselecting used to be how an analyst took a result out of the score,
    and it had two faults. It hid the result rather than recording a
    judgement about it — on the screen it became indistinguishable from a
    check nobody ever ran — and the next Run then re-called and re-billed
    everything still ticked anyway.

    So the tick is now a record of what has been bought, and it cannot be
    taken back. Taking a RESULT out of the score is Ignore, on Step 3,
    which keeps the evidence, keeps the spend, and asks why.
  */
  const locked = useMemo(() => answeredChecks(vendor), [vendor.checks])

  /*
    WHICH SOURCES ARE REFUSING OUR ACCOUNT RIGHT NOW.

    We buy these checks on prepaid accounts. When one runs out, every
    check against it fails the same way — and without this, each analyst
    learns that separately: the first from a failed run, and so does the
    tenth, each having waited on a call that could not succeed with a
    client on the other side of it.

    The server records the first refusal and reports it here. The reason
    shown is the SOURCE'S OWN SENTENCE, never ours: one of them returns
    an empty balance, a revoked key and a blocked IP under a single
    status code, so a message we wrote would send the wrong person to
    the wrong place most of the time.

    A failure to load this is silent and leaves the map EMPTY. Not
    knowing which sources are down must never hide checks that work —
    worst case the analyst meets the error the old way, which is where
    this screen started.
  */
  const [blocked, setBlocked] = useState<ReadonlyMap<string, string>>(new Map())

  useEffect(() => {
    let live = true
    api
      .listProviderStatus()
      .then((rows) => {
        if (!live) return
        // One flat map of check id -> the source's own words. The
        // server has already resolved which checks each outage covers,
        // so a provider that bills per product takes down only the
        // checks on the dead pool.
        const next = new Map<string, string>()
        for (const row of rows) {
          for (const [checkId, reason] of Object.entries(row.blockedChecks ?? {})) {
            next.set(checkId, reason || 'No reason was returned.')
          }
        }
        setBlocked(next)
      })
      .catch(() => {
        /* see above: an empty map is the safe failure */
      })
    return () => {
      live = false
    }
  }, [])

  /*
    The DISTINCT reasons behind the blocked checks.

    A provider that bills per product can have one pool down and the
    others fine, so the number of blocked checks and the number of actual
    faults are different numbers. The headline uses this one.
  */
  const reasons = useMemo(
    () => Array.from(new Set(blocked.values())),
    [blocked],
  )

  /** The source's own words for why this check cannot run, or null. */
  const blockedReason = (checkId: string): string | null =>
    blocked.get(checkId) ?? null

  /**
   * One write for any selection change, whether it came from a single
   * checkbox, a group header or a preset.
   *
   * The checkbox moves first and is put back if the write fails. It used to
   * wait for the response before moving, which reads as a broken control on
   * anything slower than localhost — and a rejected write threw unhandled
   * and said nothing at all.
   */
  const commit = async (next: string[], touched: string[]) => {
    const before = vendor
    setPending((p) => [...p, ...touched])
    setVendor({ ...vendor, selected: next })
    try {
      setVendor(await api.setSelection(vendor.id, next))
    } catch (e) {
      setVendor(before)
      toast.error(e, 'The selection could not be saved.')
    } finally {
      setPending((p) => p.filter((id) => !touched.includes(id)))
    }
  }

  const toggle = async (checkId: string) => {
    const def = CHECKS.find((c) => c.id === checkId)
    if (!def || def.state === 'not_configured' || def.always) return
    // Unreachable from the box, which is disabled — but `toggle` is also
    // called by the group tick and by the presets, and a lock that only
    // one caller honours is not a lock.
    if (locked.has(checkId) && selected.includes(checkId)) return
    // A BLOCKED CHECK CAN BE TICKED ON. It used to be refused here, on
    // the grounds that the call could not be made — but that is a
    // prediction from what the source told somebody else earlier, and
    // the only way anyone ever learns it is wrong is by asking again.
    // The row still shows the source's own sentence; it just does not
    // stop the analyst.

    let next: string[]
    if (selected.includes(checkId)) {
      // Switching a check off takes its dependents with it — leaving them
      // selected would queue calls that cannot be made.
      // A dependent that has ANSWERED is not switched off with its
      // parent: it holds evidence that was paid for, and the parent's
      // result is on file too, so nothing it needs has gone away.
      const orphaned = dependentsOf(checkId)
        .filter((d) => selected.includes(d) && !locked.has(d))
      next = selected.filter((id) => id !== checkId && !orphaned.includes(id))
      if (orphaned.length) {
        toast(
          `${orphaned.length} dependent check${orphaned.length > 1 ? 's' : ''} switched off too — ` +
            `${orphaned.map(nameOf).join(', ')}`,
        )
      }
    } else {
      // Ticking a check auto-enables what it needs.
      const additions = withPrerequisites(checkId).filter((id) => !selected.includes(id))
      next = [...selected, ...additions]
      if (additions.length > 1) {
        toast(`${additions.length - 1} prerequisite check(s) enabled automatically`)
      }
    }
    await commit(next, [checkId])
  }

  /** Every check in a group, on or off, in one write. */
  const toggleGroup = async (groupId: string, on: boolean) => {
    const ids = CHECKS.filter((c) => c.group === groupId && isSelectable(c.id, blocked)).map((c) => c.id)
    if (!ids.length) return

    let next: string[]
    if (on) {
      // Prerequisites travel with them, exactly as a single tick does.
      const additions = ids.flatMap((id) => withPrerequisites(id)).filter((id) => !selected.includes(id))
      next = [...selected, ...Array.from(new Set(additions))]
    } else {
      const orphaned = ids.flatMap(dependentsOf).filter((d) => selected.includes(d))
      const drop = new Set(
        [...ids, ...orphaned].filter((id) => !locked.has(id)),
      )
      next = selected.filter((id) => !drop.has(id))
      if (orphaned.length) {
        toast(`${orphaned.length} dependent check(s) switched off too`)
      }
    }
    await commit(Array.from(new Set(next)), ids)
  }

  /** Presets. Each is a whole selection, applied in one write. */
  const applyPreset = async (preset: 'all' | 'none' | 'free' | 'essential') => {
    const selectable = CHECKS.filter((c) => isSelectable(c.id, blocked))
    let ids: string[] = []
    if (preset === 'all') ids = selectable.map((c) => c.id)
    if (preset === 'none') ids = []
    if (preset === 'free') {
      ids = selectable
        .filter((c) => !c.costPaisa && !c.credits && !c.screenshots && !c.needsCompanyUnlock)
        .map((c) => c.id)
    }
    if (preset === 'essential') {
      // The checks that feed a SCAN parameter or a risk rule — the ones
      // whose absence leaves a hole in the score rather than in the detail.
      ids = selectable.filter((c) => c.feeds.length > 0).map((c) => c.id)
    }
    const withDeps = Array.from(new Set(ids.flatMap((id) => withPrerequisites(id))))
    await commit(withDeps, withDeps)
  }

  /**
   * What this Run will actually call.
   *
   * NOT the selection. A check already on file is not re-called and not
   * re-charged, so quoting the whole selection would name a price three
   * times what the button is about to spend — and an estimate the
   * analyst learns to distrust is worse than none at all.
   */
  const toRun = useMemo(
    () => selected.filter((id) => !locked.has(id)),
    [selected, locked],
  )

  /* ---- cost, kept in three separate currencies ---------------------- */
  const cost = useMemo(() => {
    const active = toRun.map((id) => CHECKS.find((c) => c.id === id)).filter(Boolean)
    // PEOPLE COUNTED, not calls assumed. The person-level checks take a
    // list — five directors in one field — and are charged per person, so
    // the flat catalogue price would quote a fifth of the real figure on
    // exactly the checks the analyst cannot price by eye.
    const reads = active.reduce((a, c) => a + checkCostPaisa(vendor, c!.id), 0)
    const credits = active.reduce((a, c) => a + (c!.credits || 0), 0)
    const shots = active.reduce((a, c) => a + (c!.screenshots || 0), 0)
    const needsUnlock = active.some((c) => c!.needsCompanyUnlock) && !vendor.unlocked
    const needsDirectorUnlock = active.some((c) => c!.needsDirectorUnlock)
    return {
      reads,
      credits,
      shots,
      needsUnlock,
      needsDirectorUnlock,
      rupeesTotal:
        reads +
        (needsUnlock ? COMPANY_UNLOCK_PAISA : 0) +
        (needsDirectorUnlock ? DIRECTOR_UNLOCK_PAISA : 0),
    }
    // `vendor` whole, not just `vendor.unlocked`: the person-level prices
    // are read off the check inputs, so typing a fourth number has to move
    // the figure the Run button is standing next to.
  }, [toRun, vendor])

  /* ---- which SCAN parameters this selection can fill ---------------- */
  const coverage = useMemo(() => {
    const fillable = new Set<string>()
    for (const id of selected) {
      const def = CHECKS.find((c) => c.id === id)
      for (const p of def?.feeds ?? []) fillable.add(p)
    }
    const autoParams = SCAN_PARAMETERS.filter((p) => p.source === 'AUTO')
    return {
      fillable,
      autoTotal: autoParams.length,
      autoFilled: autoParams.filter((p) => fillable.has(p.id)).length,
    }
  }, [selected])

  const missing = useMemo(() => missingInputs(vendor), [vendor])

  /*
    ONE DEFINITION OF "BLANK", NOT TWO.

    The page asked `missingInputs(vendor)` and the field asked
    `!local.trim()` — two implementations of the same question, reading
    different state. They drifted the moment a field was typed into and
    cleared: the box went red and said "Required" while the button still
    read "Run 1 checks", because only one of them thought anything was
    wrong. The run then went ahead.

    The field now asks this set instead of deciding for itself.
  */
  const missingKeys = useMemo(
    () => new Set(missing.map((m) => `${m.checkId}.${m.paramKey}`)),
    [missing],
  )

  /** Scroll a field into view and put the cursor in it. */
  const focusField = (paramKey: string) => {
    const el = document.querySelector<HTMLElement>(`[data-field="${paramKey}"]`)
    el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el?.focus()
  }

  /*
    BLOCKING FORMAT ERRORS ACROSS EVERY SELECTED CHECK.

    Only inputs belonging to checks actually selected count. A malformed
    GSTIN on a check nobody chose is not a reason to stop a run that will
    never read it.
  */
  const badInputs = useMemo(() => {
    const values: Record<string, string> = {}
    for (const id of selected) {
      const def = CHECKS.find((c) => c.id === id)
      for (const p of def?.params ?? []) {
        values[p.key] = inputValue(vendor, id, p.key)
      }
    }
    return blockingProblems(values)
  }, [vendor, selected])

  const run = async () => {
    /*
      NOTHING RUNS UNTIL EVERY REQUIRED FIELD IS FILLED.

      This used to let the run proceed and record the check as
      `skipped_missing_input` — a gap honestly filed rather than hidden,
      which is the right instinct and was the wrong behaviour here.

      It was also, in one case, not even true. `inputValue` returned a
      stored empty string instead of falling back to the vendor record,
      while the runner DID fall back — so a check the screen promised
      would be skipped made its call anyway and burnt 50 WhoisXML credits
      on a 403. That divergence is fixed in api/mock.ts; this is the
      guard that should have been here regardless.

      Clicking Run with a blank required field now takes the analyst to
      that field instead of running. Each click moves to the next one, so
      the only ways forward are to fill it or to deselect the check —
      which is the real choice, and is still free to make.

      No toast and no banner: the field itself turns red and says why.
    */
    const firstGap = missing[0]
    if (firstGap) {
      focusField(firstGap.paramKey)
      return
    }

    // Format errors. Unreachable from the button, which is disabled while
    // this is non-empty, but `run` is a function and a later caller must
    // not get past it.
    if (badInputs.length > 0) return

    setRunning(true)
    setRunError(null)
    try {
      /*
        THE DELTA, NEVER THE WHOLE SELECTION.

        This posted nothing, which the server reads as "run everything
        selected" — and the runner does not skip a check that already
        answered. So coming back to Step 2 to add two checks re-called
        and re-billed every check already on file, upwards of ₹40 on a
        full MCA set, with nothing on screen to say it had happened.

        `only` is what makes the trip back safe. Re-running a check on
        purpose is still possible and still charged; it is done from the
        Step 3 popup, where it is one deliberate tick rather than a side
        effect of pressing Run again.
      */
      const result = await api.runChecks(vendor.id, toRun)
      setVendor(result.vendor)
      const kept = selected.length - toRun.length
      toast(
        `${result.ran} checks settled` +
          (kept ? ` · ${kept} already on file, not re-run or re-charged` : '') +
          (result.skippedMissingInput.length
            ? ` · ${result.skippedMissingInput.length} skipped for missing input`
            : ''),
      )
      navigate(`/vendor/${vendor.id}/findings`)
    } catch (e) {
      // This used to be a bare try/finally. A run that failed — a spend
      // guard refusing a paid call, a provider down, the session expired
      // mid-run — left the button un-spinning and said nothing at all,
      // and the analyst had no way to tell a refusal from a success with
      // no findings. The reason has to reach the screen.
      //
      // It is shown twice on purpose: a toast for someone watching, and a
      // callout that stays on the page for someone who looked away during
      // a run that can take a minute.
      setRunError(e)
      toast.error(e)
    } finally {
      setRunning(false)
    }
  }

  useEffect(() => {
    setPrimary(
      <>
        <span className="small muted nums">
          {rupees(cost.rupeesTotal)}
          {cost.credits > 0 && ` · ${cost.credits} credits`}
          {cost.shots > 0 && ` · ${cost.shots} screenshot${cost.shots > 1 ? 's' : ''}`}
        </span>
        {/* DEAD while anything is blank or malformed. The label says how
            many need attention and the field carries the reason, so the
            button does not have to explain itself by being clickable. */}
        <button
          type="button"
          className="btn primary"
          disabled={
            running || !toRun.length || missing.length > 0 || badInputs.length > 0
          }
          onClick={run}
        >
          {running && <span className="spinner" aria-hidden="true" />}
          {running
            ? 'Running checks…'
            : missing.length
              ? `Fill ${missing.length} required input${missing.length > 1 ? 's' : ''} to run`
              : badInputs.length
                ? `Fix ${badInputs.length} input${badInputs.length > 1 ? 's' : ''} to run`
                : /* COUNTS WHAT WILL BE CALLED. "Run 11 checks" over a
                     selection of eleven where eight are already on file
                     promises eight calls that will not happen and a
                     price that will not be charged. */
                  !toRun.length
                  ? 'Everything selected is already on file'
                  : `Run ${toRun.length} check${toRun.length === 1 ? '' : 's'} →`}
        </button>
      </>,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cost, running, toRun.length, selected.length, vendor, missing.length, badInputs.length])

  const matches = (check: (typeof CHECKS)[number]): boolean => {
    if (query.trim()) {
      const q = query.trim().toLowerCase()
      const hay = `${check.name} ${check.note ?? ''} ${check.id}`.toLowerCase()
      if (!hay.includes(q)) return false
    }
    if (filter === 'selected') return selected.includes(check.id)
    if (filter === 'free') {
      return !check.costPaisa && !check.credits && !check.screenshots && !check.needsCompanyUnlock
    }
    return true
  }

  const selectableTotal = CHECKS.filter((c) => isSelectable(c.id, blocked)).length
  const filtering = query.trim() !== '' || filter !== 'all'

  return (
    <div className="stack">
      <div>
        <div className="kicker">Step 2 · Selection</div>
        <h2 className="page-h">Choose what to check</h2>
        {/* <p className="page-sub">
          {totals.checks} checks across {totals.groups} groups. Tick what this vendor warrants —
          prerequisites are enabled for you, and anything you leave off is recorded as not examined.
        </p> */}
      </div>

      {runError != null && (
        <Callout kind="adverse" title={errorTitle(runError)}>
          {errorMessage(runError)}
          <div className="small muted" style={{ marginTop: 'var(--space-2)' }}>
            Nothing was recorded against this vendor. Selections are unchanged — fix the cause
            and run again.
          </div>
        </Callout>
      )}

      {/*
        One line at the top, so nobody has to scroll eight groups to find
        out why a familiar check is greyed out.

        COUNTED BY FAULT, NOT BY CHECK. "11 checks unavailable" reads as
        eleven separate problems when it is one account that needs
        paying, and a reader who thinks eleven things are broken reaches
        for the wrong response. Distinct reasons is the honest count: one
        empty wallet is one line however many checks it stops.
      */}
      {reasons.length > 0 && (
        <Callout
          kind="warn"
          title={
            reasons.length === 1
              ? 'One data source is not answering'
              : `${reasons.length} data sources are not answering`
          }
        >
          {blocked.size === 1
            ? 'One check is switched off below and will not be charged for.'
            : `${blocked.size} checks are switched off below and will not be charged for.`}{' '}
          What the source said:
          <ul style={{ margin: 'var(--space-2) 0 0', paddingLeft: '1.1rem' }}>
            {reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </Callout>
      )}

      {running && (
        <Callout kind="info" title="Running the selected checks">
          <div style={{ marginTop: 'var(--space-2)' }}>
            <ProgressBar
              label={`${selected.length} checks queued. Providers are called in waves; this can take a minute.`}
            />
          </div>
        </Callout>
      )}

      <div className="grid-4">
        {/* SELECTED and TO BE RUN are different numbers now, and the
            tile says both. Sixteen selected beside a button reading "Run
            1 check" is a discrepancy the analyst has to resolve on their
            own otherwise, and the resolution — fifteen are already paid
            for — is the reassuring half. */}
        <Tile
          n={selected.length}
          label="Checks selected"
          tone="accent"
          note={
            selected.length - toRun.length
              ? `${selected.length - toRun.length} already on file · ` +
                `${toRun.length || 'none'} to run`
              : undefined
          }
        />
        <Tile
          n={rupees(cost.rupeesTotal)}
          label="FileSure spend"
          note={cost.needsUnlock ? `Includes the ${rupees(COMPANY_UNLOCK_PAISA)} company unlock` : 'Company already unlocked'}
        />
        <Tile n={cost.credits} label="WhoisXML credits" note="A separate pool — never added to rupees" />
        <Tile
          n={`${coverage.autoFilled}/${coverage.autoTotal}`}
          label="Automatable SCAN parameters"
          note="The rest are human judgement or field work"
          tone="neutral"
        />
      </div>

      {/*
        ONE TOOLBAR, NOT TWO.

        Searching, filtering and selecting are the same decision — what am
        I running — and they were split across two stacked rows, with the
        count stranded beside a row of presets it did not describe.

        "Configured" is gone from the filter: unconfigured checks are no
        longer rendered at all, so it filtered nothing. The preset bundles
        are gone with it, leaving the two that do the work on forty rows.
      */}
      <div className="sel-bar">
        <input
          className="input sel-search"
          type="search"
          placeholder="Search checks…"
          value={query}
          aria-label="Search checks"
          onChange={(e) => setQuery(e.target.value)}
        />

        <div className="seg" role="group" aria-label="Filter checks">
          {(
            [
              ['all', 'All'],
              ['selected', 'Selected'],
              ['free', 'Free'],
            ] as [Filter, string][]
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={`seg-btn${filter === value ? ' is-on' : ''}`}
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>

        <span className="sel-sep" aria-hidden="true" />

        <div className="sel-actions">
          <button
            type="button"
            className="btn sm ghost"
            onClick={() =>
              setCollapsed(collapsed.length ? [] : CHECK_GROUPS.map((g) => g.id))
            }
          >
            {collapsed.length ? 'Expand all' : 'Collapse all'}
          </button>
          <button type="button" className="btn sm" onClick={() => applyPreset('all')}>
            Select all
          </button>
          <button type="button" className="btn sm" onClick={() => applyPreset('none')}>
            Clear all
          </button>
        </div>

        {/* Pushed right by its own margin rather than a spacer div, so it
            stays put when the row wraps on a narrow screen. */}
        <span className="sel-count nums">
          <strong>{selected.length}</strong> of {selectableTotal} selectable
        </span>
      </div>

      {/*
        The "N required inputs still blank" callout was here. It is gone
        because the Run button now refuses and jumps to the field, so the
        same fact was being stated in two places — and the panel was the
        one you scroll past.
      */}

      {CHECK_GROUPS.map((group) => {
        /*
          NOT-CONFIGURED CHECKS ARE NOT SHOWN HERE AT ALL.

          They used to appear greyed out with a "No provider configured"
          badge. That is a list of things this platform cannot do,
          rendered on the screen where someone is deciding what to do —
          seven rows of noise between them and the checks that work.

          This is a presentation choice, not a disclosure one. The
          client-facing report still accounts for coverage; see
          Report.tsx. Hiding a gap from the analyst's working screen is
          fine. Hiding it from the deliverable would not be.
        */
        const groupChecks = CHECKS.filter(
          (c) => c.group === group.id && c.state !== 'not_configured',
        )
        if (!groupChecks.length) return null

        const visible = groupChecks.filter(matches)
        // While filtering, a group with no matches is noise.
        if (filtering && !visible.length) return null

        const selectable = groupChecks.filter((c) => isSelectable(c.id, blocked))
        const on = groupChecks.filter((c) => selected.includes(c.id)).length
        const allOn = selectable.length > 0 && selectable.every((c) => selected.includes(c.id))
        const someOn = on > 0 && !allOn
        const isOpen = !collapsed.includes(group.id)

        return (
          <div className={`card group${isOpen ? ' is-open' : ''}`} key={group.id}>
            {/* One row: select-all, disclosure, title, count. The
                checkbox used to wrap onto its own line above the group
                name, where it read as belonging to nothing. */}
            <div className="group-row">
              {selectable.length > 0 ? (
                <span className="group-select">
                  <TriCheckbox
                    checked={allOn}
                    indeterminate={someOn}
                    onChange={() => void toggleGroup(group.id, !allOn)}
                    label={`${allOn ? 'Clear' : 'Select'} all ${group.name} checks`}
                  />
                </span>
              ) : (
                <span className="group-select-spacer" aria-hidden="true" />
              )}

              <button
                type="button"
                className="group-head"
                aria-expanded={isOpen}
                onClick={() =>
                  setCollapsed((c) =>
                    c.includes(group.id) ? c.filter((g) => g !== group.id) : [...c, group.id],
                  )
                }
              >
                <span className="group-chev" aria-hidden="true">›</span>
                <span className="group-titles">
                  <span className="group-title">{group.name}</span>
                </span>
              </button>

              {/* Counted against the checks actually shown. A group with
                  a provider on some checks and not others — tax, rep —
                  now reads "2 of 2", not "2 of 3". */}
              <span className={`badge ${on ? 'b-accent' : 'b-neutral'} nums`}>
                {on} of {groupChecks.length} selected
              </span>
            </div>

            {isOpen && (
              <div className="card-body tight">
                <div className="stack-sm" style={{ padding: 'var(--space-2)' }}>
                  {visible.map((check) => {
                    const isOn = selected.includes(check.id)
                    const isPending = pending.includes(check.id)
                    const params = check.params ?? []
                    const unavailable = blockedReason(check.id)

                    return (
                      <div
                        key={check.id}
                        className={
                          'check-row' +
                          (isOn ? ' is-on' : '') +
                          (isPending ? ' is-pending' : '') +
                          (unavailable ? ' is-unavailable' : '')
                        }
                      >
                        <div className="check-main">
                          <label className="check-label">
                            <input
                              type="checkbox"
                              checked={isOn}
                              // A blocked check already selected stays
                              // tickable, so it can be switched OFF. Only
                              // turning one ON is refused, by `toggle`.
                              disabled={
                                check.always ||
                                isPending ||
                                (!!unavailable && !isOn) ||
                                // ALREADY ANSWERED. The tick records what
                                // has been bought and cannot be taken
                                // back; Ignore on Step 3 is how a result
                                // stops counting.
                                locked.has(check.id)
                              }
                              onChange={() => void toggle(check.id)}
                            />
                            <span className="cell-strong">{check.name}</span>
                            {isPending && <span className="spinner" aria-hidden="true" />}
                            {locked.has(check.id) && (
                              <span
                                className="chip c-done"
                                title={
                                  'This check has a result on file. It is not ' +
                                  're-run or re-charged. To stop a result ' +
                                  'counting, set it aside on the findings screen.'
                                }
                              >
                                already run · not re-charged
                              </span>
                            )}
                            {unavailable && <span className="chip c-warn">Unavailable</span>}
                            {check.always && <span className="chip">Always runs · free</span>}
                            {check.requires.length > 0 && (
                              <span
                                className="chip"
                                title={`Requires: ${check.requires.map(nameOf).join(', ')}`}
                              >
                                {/* Was printing raw check ids. */}
                                needs {check.requires.map(nameOf).join(', ')}
                              </span>
                            )}
                          </label>

                          <span className="small muted">{check.note}</span>
                          {/* <span className="small mono muted">{check.endpoint}</span> */}

                          {/*
                            THE SOURCE'S OWN SENTENCE, verbatim. Not a
                            rewrite of it, and not a generic "temporarily
                            unavailable" — the whole value of this line
                            is that it says which of several quite
                            different things has gone wrong, so whoever
                            reads it knows who has to fix it.
                          */}
                          {unavailable && (
                            <span className="small warn-text">
                              Not running: {unavailable}
                            </span>
                          )}

                          {isOn && params.length > 0 && (
                            <div className="check-params">
                              <div className="grid-3">
                                {params.map((param) => (
                                  <ParamField
                                    key={param.key}
                                    vendor={vendor}
                                    setVendor={setVendor}
                                    checkId={check.id}
                                    param={param}
                                    selected={selected}
                                    missingKeys={missingKeys}
                                  />
                                ))}
                              </div>
                            </div>
                          )}
                        </div>

                        <div className="check-cost">
                          {check.costPaisa > 0 && <span className="small nums">{rupees(check.costPaisa)}</span>}
                          {check.credits > 0 && <span className="small nums">{check.credits} credits</span>}
                          {check.screenshots > 0 && <span className="small nums">{check.screenshots} of 10</span>}
                          {check.costPaisa === 0 && !check.credits && !check.screenshots && (
                            <span className="small muted">free</span>
                          )}
                          {check.needsCompanyUnlock && !vendor.unlocked && (
                            <span className="small warn-text">
                              + {rupees(COMPANY_UNLOCK_PAISA)} unlock
                            </span>
                          )}
                          {/* The "fills S1, S2" chip was here. Raw SCAN
                              parameter ids on a selection screen are our
                              internal numbering, not a fact about the
                              check — and an analyst choosing what to buy
                              does not decide by them. Which parameters a
                              result feeds is shown where it matters, on
                              the SCAN screen itself. */}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        )
      })}

      {filtering && !CHECK_GROUPS.some((g) => CHECKS.some((c) => c.group === g.id && matches(c))) && (
        <div className="empty-inline">
          <span>No check matches that filter.</span>
          <button
            type="button"
            className="btn sm"
            onClick={() => {
              setQuery('')
              setFilter('all')
            }}
          >
            Clear filters
          </button>
        </div>
      )}
    </div>
  )
}
