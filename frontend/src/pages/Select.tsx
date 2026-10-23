import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '@/api'
import { errorMessage, errorTitle } from '@/api/http'
import { inputValue, missingInputs } from '@/api/mock'
import { blockingProblems, checkValue, detectIdType, ruleFor } from '@/lib/validate'
import {
  CHECKS,
  CHECK_GROUPS,
  COMPANY_UNLOCK_PAISA,
  DIRECTOR_UNLOCK_PAISA,
  SCAN_PARAMETERS,
} from '@/catalog/generated'
import {
  Callout,
  Field,
  ProgressBar,
  Tile,
  TriCheckbox,
  rupees,
} from '@/components/ui'
import { useToast } from '@/hooks/useToast'
import type { PageProps } from '@/App'
import type { Vendor } from '@/types/domain'

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

/** A selectable check is one with a provider behind it. */
const isSelectable = (id: string): boolean => {
  const def = CHECKS.find((c) => c.id === id)
  return !!def && def.state !== 'not_configured' && !def.always
}

/** Names rather than raw ids — "needs mca, dirs" told nobody anything. */
const nameOf = (id: string): string => CHECKS.find((c) => c.id === id)?.name ?? id
const labelOfParam = (id: string): string =>
  SCAN_PARAMETERS.find((p) => p.id === id)?.label ?? id

type Filter = 'all' | 'selected' | 'free' | 'configured'

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

    let next: string[]
    if (selected.includes(checkId)) {
      // Switching a check off takes its dependents with it — leaving them
      // selected would queue calls that cannot be made.
      const orphaned = dependentsOf(checkId).filter((d) => selected.includes(d))
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
    const ids = CHECKS.filter((c) => c.group === groupId && isSelectable(c.id)).map((c) => c.id)
    if (!ids.length) return

    let next: string[]
    if (on) {
      // Prerequisites travel with them, exactly as a single tick does.
      const additions = ids.flatMap((id) => withPrerequisites(id)).filter((id) => !selected.includes(id))
      next = [...selected, ...Array.from(new Set(additions))]
    } else {
      const orphaned = ids.flatMap(dependentsOf).filter((d) => selected.includes(d))
      const drop = new Set([...ids, ...orphaned])
      next = selected.filter((id) => !drop.has(id))
      if (orphaned.length) {
        toast(`${orphaned.length} dependent check(s) switched off too`)
      }
    }
    await commit(Array.from(new Set(next)), ids)
  }

  /** Presets. Each is a whole selection, applied in one write. */
  const applyPreset = async (preset: 'all' | 'none' | 'free' | 'essential') => {
    const selectable = CHECKS.filter((c) => isSelectable(c.id))
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

  /* ---- cost, kept in three separate currencies ---------------------- */
  const cost = useMemo(() => {
    const active = selected.map((id) => CHECKS.find((c) => c.id === id)).filter(Boolean)
    const reads = active.reduce((a, c) => a + (c!.costPaisa || 0), 0)
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
  }, [selected, vendor.unlocked])

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
      const result = await api.runChecks(vendor.id)
      setVendor(result.vendor)
      toast(
        `${result.ran} checks settled` +
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
        {/* DISABLED on a blocking input. The label says how many need
            fixing and the field itself carries the reason, so the button
            does not have to explain anything by being clickable. */}
        <button
          type="button"
          className="btn primary"
          disabled={running || !selected.length || badInputs.length > 0}
          onClick={run}
        >
          {running && <span className="spinner" aria-hidden="true" />}
          {running
            ? 'Running checks…'
            : missing.length
              ? `Fill ${missing.length} required input${missing.length > 1 ? 's' : ''} to run`
              : badInputs.length
                ? `Fix ${badInputs.length} input${badInputs.length > 1 ? 's' : ''} to run`
                : `Run ${selected.length} checks →`}
        </button>
      </>,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cost, running, selected.length, vendor, missing.length, badInputs.length])

  const matches = (check: (typeof CHECKS)[number]): boolean => {
    if (query.trim()) {
      const q = query.trim().toLowerCase()
      const hay = `${check.name} ${check.note ?? ''} ${check.id}`.toLowerCase()
      if (!hay.includes(q)) return false
    }
    if (filter === 'selected') return selected.includes(check.id)
    if (filter === 'configured') return check.state !== 'not_configured'
    if (filter === 'free') {
      return !check.costPaisa && !check.credits && !check.screenshots && !check.needsCompanyUnlock
    }
    return true
  }

  const selectableTotal = CHECKS.filter((c) => isSelectable(c.id)).length
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
        <Tile n={selected.length} label="Checks selected" tone="accent" />
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

      {/* One decision instead of forty-seven. */}
      <div className="sel-toolbar">
        <div className="sel-presets">
          <span className="small muted">Presets</span>
          <button type="button" className="btn sm" onClick={() => applyPreset('essential')}>
            Scored checks
          </button>
          <button type="button" className="btn sm" onClick={() => applyPreset('free')}>
            Free only
          </button>
          <button type="button" className="btn sm" onClick={() => applyPreset('all')}>
            Select all
          </button>
          <button type="button" className="btn sm" onClick={() => applyPreset('none')}>
            Clear all
          </button>
        </div>

        <div className="sel-spacer" />

        <span className="small muted nums">
          {selected.length} of {selectableTotal} selectable
        </span>
      </div>

      <div className="filter-row">
        <input
          className="input toolbar-search"
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
              ['configured', 'Configured'],
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
        <button
          type="button"
          className="btn sm ghost"
          onClick={() =>
            setCollapsed(collapsed.length ? [] : CHECK_GROUPS.map((g) => g.id))
          }
        >
          {collapsed.length ? 'Expand all' : 'Collapse all'}
        </button>
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

        const selectable = groupChecks.filter((c) => isSelectable(c.id))
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

                    return (
                      <div
                        key={check.id}
                        className={
                          'check-row' +
                          (isOn ? ' is-on' : '') +
                          (isPending ? ' is-pending' : '')
                        }
                      >
                        <div className="check-main">
                          <label className="check-label">
                            <input
                              type="checkbox"
                              checked={isOn}
                              disabled={check.always || isPending}
                              onChange={() => void toggle(check.id)}
                            />
                            <span className="cell-strong">{check.name}</span>
                            {isPending && <span className="spinner" aria-hidden="true" />}
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
                          {check.feeds.length > 0 && (
                            <span
                              className="chip c-auto"
                              title={`Fills: ${check.feeds.map(labelOfParam).join(', ')}`}
                            >
                              fills {check.feeds.join(', ')}
                            </span>
                          )}
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

/**
 * A single check-input field.
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
function ParamField({
  vendor,
  setVendor,
  checkId,
  param,
  selected,
}: {
  vendor: Vendor
  setVendor: (v: Vendor) => void
  checkId: string
  param: (typeof CHECKS)[number]['params'][number]
  selected: string[]
}) {
  const toast = useToast()
  const stored = inputValue(vendor, checkId, param.key)
  const [local, setLocal] = useState(stored)
  const editing = useRef(false)

  useEffect(() => {
    if (!editing.current) setLocal(stored)
  }, [stored])

  const suppliedByAnother = param.fromResult && selected.includes(param.fromResult)
  const isMissing = param.required && !suppliedByAnother && !local.trim()

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
                : rule?.example
                  ? `e.g. ${rule.example}`
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
          }}
          onChange={(e) => void write(e.target.value)}
        />
      )}
    </Field>
  )
}