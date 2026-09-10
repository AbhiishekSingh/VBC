/**
 * Step 2 — choose what to check.
 *
 * Three things this screen must get right:
 *
 * 1. COST UNITS ARE NEVER SUMMED. Rupees, WhoisXML credits and screenshot
 *    credits are three separate budgets drawn from three separate pools.
 *    Adding them would produce a number that means nothing.
 *
 * 2. UNCONFIGURED CHECKS ARE SHOWN, NOT HIDDEN. All nine hooks appear,
 *    visibly disabled, so an analyst can see what this platform does not
 *    cover. Hiding them would let a gap in coverage pass for completeness.
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

import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '@/api'
import { errorMessage, errorTitle } from '@/api/http'
import { inputValue, missingInputs } from '@/api/mock'
import {
  CHECKS,
  CHECK_GROUPS,
  COMPANY_UNLOCK_PAISA,
  DIRECTOR_UNLOCK_PAISA,
  SCAN_PARAMETERS,
} from '@/catalog/generated'
import {
  Callout,
  Card,
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

  /** The page copy used to hard-code "thirty-two checks across eight
   *  groups". The catalogue holds 47, and it will move again. */
  const totals = useMemo(() => {
    const groups = CHECK_GROUPS.filter((g) => CHECKS.some((c) => c.group === g.id))
    return { checks: CHECKS.length, groups: groups.length }
  }, [])

  const run = async () => {
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
        <button type="button" className="btn primary" disabled={running || !selected.length} onClick={run}>
          {running && <span className="spinner" aria-hidden="true" />}
          {running ? 'Running checks…' : `Run ${selected.length} checks →`}
        </button>
      </>,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cost, running, selected.length, vendor])

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

      {missing.length > 0 && (
        <Callout kind="warn" title={`${missing.length} required input${missing.length > 1 ? 's' : ''} still blank`}>
          Each one skips a single check and is logged — the run itself is never blocked, and the
          skipped check appears on the findings page rather than vanishing.
          <ul style={{ margin: 'var(--space-2) 0 0', paddingLeft: 'var(--space-5)' }}>
            {missing.slice(0, 8).map((m) => (
              <li key={`${m.checkId}.${m.paramKey}`} className="small">
                <strong>{m.checkName}</strong> needs {m.paramLabel}
              </li>
            ))}
          </ul>
          {missing.length > 8 && (
            <div className="small muted" style={{ marginTop: 'var(--space-1)' }}>
              …and {missing.length - 8} more.
            </div>
          )}
        </Callout>
      )}

      {CHECK_GROUPS.map((group) => {
        const groupChecks = CHECKS.filter((c) => c.group === group.id)
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
              {group.configured && selectable.length > 0 ? (
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
                  <span className="small muted">{group.source}</span>
                </span>
              </button>

              {group.configured ? (
                <span className={`badge ${on ? 'b-accent' : 'b-neutral'} nums`}>
                  {on} of {groupChecks.length} selected
                </span>
              ) : (
                <span className="badge b-unchecked">No provider configured</span>
              )}
            </div>

            {isOpen && (
              <div className="card-body tight">
                <div className="stack-sm" style={{ padding: 'var(--space-2)' }}>
                  {visible.map((check) => {
                    const isOff = check.state === 'not_configured'
                    const isOn = selected.includes(check.id)
                    const isPending = pending.includes(check.id)
                    const params = check.params ?? []

                    return (
                      <div
                        key={check.id}
                        className={
                          'check-row' +
                          (isOn ? ' is-on' : '') +
                          (isOff ? ' is-off' : '') +
                          (isPending ? ' is-pending' : '')
                        }
                      >
                        <div className="check-main">
                          <label className="check-label">
                            <input
                              type="checkbox"
                              checked={isOn}
                              disabled={isOff || check.always || isPending}
                              onChange={() => void toggle(check.id)}
                            />
                            <span className="cell-strong">{check.name}</span>
                            {isPending && <span className="spinner" aria-hidden="true" />}
                            {check.always && <span className="chip">Always runs · free</span>}
                            {isOff && <span className="badge b-unchecked">Not configured</span>}
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

                          <span className="small muted">
                            {check.note || 'No provider selected for this check.'}
                          </span>
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
                          {check.costPaisa === 0 && !check.credits && !check.screenshots && !isOff && (
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

  return (
    <Field
      label={`${param.label}${param.required ? ' *' : ''}`}
      hint={
        suppliedByAnother
          ? `Supplied by the ${nameOf(param.fromResult!)} result`
          : isMissing
            ? 'Required — this check will be skipped without it'
            : undefined
      }
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
          className={`input${isMissing ? ' is-missing' : ''}`}
          type={param.type === 'number' ? 'number' : param.type === 'date' ? 'date' : 'text'}
          value={local}
          placeholder={param.placeholder}
          aria-invalid={isMissing || undefined}
          onFocus={() => {
            editing.current = true
          }}
          onBlur={() => {
            editing.current = false
          }}
          onChange={(e) => void write(e.target.value)}
        />
      )}
    </Field>
  )
}
