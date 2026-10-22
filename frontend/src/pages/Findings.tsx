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

import { CHECKS, CHECK_GROUPS } from '@/catalog/generated'
import { inputValue } from '@/api/mock'
import Facts from '@/components/Facts'
import { Card, EmptyState, STATUS_EXPLANATION, StatusBadge, Tile } from '@/components/ui'
import { publicDetail } from '@/lib/publicText'
import type { PageProps } from '@/App'
import type { CheckStatus, Vendor } from '@/types/domain'

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

export default function Findings({ vendor, setPrimary }: PageProps) {
  const navigate = useNavigate()

  // A SET, not a single id. Previously only one payload could be open at a
  // time and opening a second silently closed the first, which made
  // comparing two sources against each other impossible — the single most
  // common thing an analyst actually does with this screen.
  const [open, setOpen] = useState<Set<string>>(() => new Set())
  const [copied, setCopied] = useState<string | null>(null)

  const toggleOne = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const toggleGroup = (ids: string[], expand: boolean) =>
    setOpen((prev) => {
      const next = new Set(prev)
      ids.forEach((id) => (expand ? next.add(id) : next.delete(id)))
      return next
    })

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
      <button type="button" className="btn primary" onClick={() => navigate(`/vendor/${vendor.id}/manual`)}>
        Record manual entries →
      </button>,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vendor.id])

  if (results.length === 0) {
    return (
      <EmptyState
        title="No checks have run yet"
        body="Select the checks this vendor warrants and run them. Findings, scoring and the report all build from what comes back."
        action={
          <button type="button" className="btn primary" onClick={() => navigate(`/vendor/${vendor.id}/select`)}>
            Choose what to check
          </button>
        }
      />
    )
  }

  return (
    <div className="stack">
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
                            <span>{formatBytes(panel.text)}</span>
                            <button
                              type="button"
                              className="btn sm ghost"
                              onClick={() => copy(check.id, panel.text)}
                            >
                              {copied === check.id ? 'Copied' : 'Copy JSON'}
                            </button>
                          </span>
                        </div>
                        <pre className="raw raw-panel">{panel.text}</pre>
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