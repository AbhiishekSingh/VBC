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
 */

import { useEffect, useMemo, useState } from 'react'
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
import { Callout, Card, Field, Tile, rupees } from '@/components/ui'
import { useToast } from '@/hooks/useToast'
import type { PageProps } from '@/App'

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

export default function Select({ vendor, setVendor, setPrimary }: PageProps) {
  const navigate = useNavigate()
  const toast = useToast()
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState<unknown>(null)
  const selected = vendor.selected

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
            `${orphaned.map((o) => CHECKS.find((c) => c.id === o)?.name).join(', ')}`,
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
    setVendor(await api.setSelection(vendor.id, next))
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
          {cost.shots > 0 && ` · ${cost.shots} screenshot`}
        </span>
        <button type="button" className="btn primary" disabled={running || !selected.length} onClick={run}>
          {running ? 'Running checks…' : `Run ${selected.length} checks →`}
        </button>
      </>,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cost, running, selected.length, vendor])

  return (
    <div className="stack">
      <div>
        <div className="kicker">Step 2 · Selection</div>
        <h2 className="page-h">Choose what to check</h2>
        <p className="page-sub">
          Thirty-two checks across eight groups. Tick what this vendor warrants — prerequisites
          are enabled for you, and anything you leave off is recorded as not examined.
        </p>
      </div>

      {runError != null && (
        <Callout kind="adverse" title={errorTitle(runError)}>
          {errorMessage(runError)}
          <div className="small muted" style={{ marginTop: 6 }}>
            Nothing was recorded against this vendor. Selections are unchanged — fix the cause
            and run again.
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

      {missing.length > 0 && (
        <Callout kind="warn" title={`${missing.length} required input${missing.length > 1 ? 's' : ''} still blank`}>
          Each one skips a single check and is logged — the run itself is never blocked, and the
          skipped check appears on the findings page rather than vanishing.
          <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
            {missing.map((m) => (
              <li key={`${m.checkId}.${m.paramKey}`} className="small">
                <strong>{m.checkName}</strong> needs {m.paramLabel}
              </li>
            ))}
          </ul>
        </Callout>
      )}

      {CHECK_GROUPS.map((group) => {
        const groupChecks = CHECKS.filter((c) => c.group === group.id)
        if (!groupChecks.length) return null
        const on = groupChecks.filter((c) => selected.includes(c.id)).length

        return (
          <Card
            key={group.id}
            title={group.name}
            subtitle={group.source}
            aside={
              group.configured ? (
                <span className="badge b-neutral">
                  {on} of {groupChecks.length} selected
                </span>
              ) : (
                <span className="badge b-unchecked">No provider configured</span>
              )
            }
            tight
          >
            <div className="stack-sm" style={{ padding: 4 }}>
              {groupChecks.map((check) => {
                const isOff = check.state === 'not_configured'
                const isOn = selected.includes(check.id)
                const params = check.params ?? []

                return (
                  <div
                    key={check.id}
                    style={{
                      padding: '10px 12px',
                      borderRadius: 'var(--radius-sm)',
                      background: isOn ? 'var(--accent-wash)' : 'transparent',
                      opacity: isOff ? 0.6 : 1,
                    }}
                  >
                    <div className="row-between" style={{ alignItems: 'flex-start' }}>
                      <label className="row" style={{ alignItems: 'flex-start', gap: 10, cursor: isOff ? 'default' : 'pointer' }}>
                        <input
                          type="checkbox"
                          checked={isOn}
                          disabled={isOff || check.always}
                          onChange={() => toggle(check.id)}
                          style={{ marginTop: 3 }}
                        />
                        <span>
                          <span style={{ fontWeight: 550 }}>{check.name}</span>
                          {check.always && <span className="chip" style={{ marginLeft: 8 }}>Always runs · free</span>}
                          {isOff && <span className="badge b-unchecked" style={{ marginLeft: 8 }}>Not configured</span>}
                          {check.requires.length > 0 && (
                            <span className="chip" style={{ marginLeft: 8 }}>
                              needs {check.requires.join(', ')}
                            </span>
                          )}
                          <span className="small muted" style={{ display: 'block' }}>
                            {check.note || 'No provider selected for this check.'}
                          </span>
                          <span className="small mono muted" style={{ display: 'block', marginTop: 2 }}>
                            {check.endpoint}
                          </span>
                        </span>
                      </label>

                      <div style={{ textAlign: 'right', flex: 'none' }}>
                        {check.costPaisa > 0 && <div className="small nums">{rupees(check.costPaisa)}</div>}
                        {check.credits > 0 && <div className="small nums">{check.credits} credits</div>}
                        {check.screenshots > 0 && <div className="small nums">{check.screenshots} of 10</div>}
                        {check.costPaisa === 0 && !check.credits && !check.screenshots && !isOff && (
                          <div className="small muted">free</div>
                        )}
                        {check.needsCompanyUnlock && !vendor.unlocked && (
                          <div className="small" style={{ color: 'var(--warn)' }}>
                            + {rupees(COMPANY_UNLOCK_PAISA)} unlock
                          </div>
                        )}
                        {check.feeds.length > 0 && (
                          <div className="chip c-auto" style={{ marginTop: 4 }}>
                            fills {check.feeds.join(', ')}
                          </div>
                        )}
                      </div>
                    </div>

                    {isOn && params.length > 0 && (
                      <div className="grid-3" style={{ marginTop: 10, paddingLeft: 26 }}>
                        {params.map((param) => {
                          const value = inputValue(vendor, check.id, param.key)
                          const suppliedByAnother =
                            param.fromResult && selected.includes(param.fromResult)
                          const isMissing = param.required && !suppliedByAnother && !value.trim()

                          return (
                            <Field
                              key={param.key}
                              label={`${param.label}${param.required ? ' *' : ''}`}
                              hint={
                                suppliedByAnother
                                  ? `Supplied by the ${param.fromResult} result`
                                  : isMissing
                                    ? 'Required — this check will be skipped without it'
                                    : undefined
                              }
                            >
                              {param.type === 'select' ? (
                                <select
                                  className="select"
                                  value={value}
                                  onChange={async (e) =>
                                    setVendor(await api.setCheckInput(vendor.id, check.id, param.key, e.target.value))
                                  }
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
                                  value={value}
                                  placeholder={param.placeholder}
                                  onChange={async (e) =>
                                    setVendor(await api.setCheckInput(vendor.id, check.id, param.key, e.target.value))
                                  }
                                />
                              )}
                            </Field>
                          )
                        })}
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
