/**
 * The pipeline.
 *
 * Every vendor across every client, with the two scores side by side —
 * SCAN and the 0-100 point model. They are deliberately never merged into
 * one number: they measure different things and can legitimately disagree,
 * and hiding that disagreement behind a single figure would remove exactly
 * the signal an analyst needs.
 *
 * Below 860px the table becomes cards. A seven-column table on a phone is a
 * horizontal scrollbar, which is a table nobody reads.
 */

import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Card, EmptyState, Meter, Tile, toneForScan } from '@/components/ui'
import { useVendorList } from '@/hooks/useVendor'
import { DEFAULT_POLICY, applyPolicy, scoreRisk, scoreScan } from '@/scoring'
import type { Vendor } from '@/types/domain'

const STAGE_LABEL: Record<string, string> = {
  intake: 'Intake',
  select: 'Selecting checks',
  running: 'Checks running',
  manual: 'Manual entries',
  scoring: 'Scoring',
  report: 'Report',
  review: 'In review',
  decided: 'Decided',
}

type Filter = 'all' | 'open' | 'held' | 'decided'

const FILTERS: { key: Filter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'open', label: 'Awaiting a decision' },
  { key: 'held', label: 'Held for coverage' },
  { key: 'decided', label: 'Decided' },
]

/** Everything the row needs, computed once rather than per cell. */
function summarise(vendor: Vendor) {
  const scan = scoreScan(vendor.scan)
  const gate = applyPolicy(scan, DEFAULT_POLICY)
  const risk = scoreRisk(vendor.checks, vendor.selected)
  return { scan, gate, risk }
}

function VerdictBadge({ scan, gated }: { scan: ReturnType<typeof scoreScan>; gated: boolean }) {
  if (gated) return <span className="badge b-warn">Insufficient coverage</span>
  if (!scan.isScored) return <span className="badge b-unchecked">Not scored</span>
  return scan.passed ? (
    <span className="badge b-pass">Positive</span>
  ) : (
    <span className="badge b-adverse">Negative</span>
  )
}

function RiskBadge({ risk }: { risk: ReturnType<typeof scoreRisk> }) {
  const tone =
    risk.band.key === 'approve' ? 'pass' : risk.band.key === 'conditional' ? 'warn' : 'adverse'
  return (
    <span className={`badge b-${tone}`}>
      {risk.score} · {risk.band.label}
    </span>
  )
}

export default function Dashboard() {
  const { vendors, loading } = useVendorList()
  const navigate = useNavigate()

  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<Filter>('all')

  const counts = useMemo(() => {
    const decided = vendors.filter((v) => v.decision).length
    const held = vendors.filter((v) => summarise(v).gate.gated).length
    return { total: vendors.length, decided, held, open: vendors.length - decided }
  }, [vendors])

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return vendors.filter((v) => {
      if (filter === 'open' && v.decision) return false
      if (filter === 'decided' && !v.decision) return false
      if (filter === 'held' && !summarise(v).gate.gated) return false
      if (!needle) return true
      // Search what an analyst actually has to hand: a name, a reference,
      // a CIN from an email, or the client who asked.
      return [v.name, v.legalName, v.id, v.cin, v.clientName]
        .filter(Boolean)
        .some((field) => String(field).toLowerCase().includes(needle))
    })
  }, [vendors, query, filter])

  if (loading) return <p className="muted">Loading vendors…</p>

  const open = (id: string) => navigate(`/vendor/${id}/findings`)

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="kicker">Overview</div>
          <h2 className="page-h">Vendor pipeline</h2>
        </div>
        <button type="button" className="btn primary" onClick={() => navigate('/vendor/new')}>
          Add a vendor
        </button>
      </div>

      <div className="grid-4">
        <Tile n={counts.total} label="Vendors on file" tone="accent" />
        <Tile n={counts.open} label="Awaiting a decision" />
        <Tile
          n={counts.held}
          label="Held for coverage"
          note="Reached the threshold on too little evidence"
          tone={counts.held ? 'warn' : 'neutral'}
        />
        <Tile n={counts.decided} label="Decided" tone="pass" />
      </div>

      {vendors.length === 0 ? (
        <Card tight>
          <EmptyState
            title="No vendors yet"
            body="Add a client first, then the vendors they want assessed. Everything else builds from what the checks return."
            action={
              <button type="button" className="btn primary" onClick={() => navigate('/clients')}>
                Go to clients
              </button>
            }
          />
        </Card>
      ) : (
        <Card
          title="Vendors"
          subtitle="SCAN verdict and the 0–100 point model, side by side"
          tight
        >
          <div className="toolbar">
            <input
              className="input toolbar-search"
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search name, reference, CIN or client…"
              aria-label="Search vendors"
            />
            <div className="seg" role="group" aria-label="Filter vendors">
              {FILTERS.map((f) => (
                <button
                  key={f.key}
                  type="button"
                  className={`seg-btn${filter === f.key ? ' is-on' : ''}`}
                  onClick={() => setFilter(f.key)}
                  aria-pressed={filter === f.key}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </div>

          {shown.length === 0 ? (
            <div className="empty-inline">
              <p>No vendors match that search.</p>
              <button
                type="button"
                className="btn sm ghost"
                onClick={() => {
                  setQuery('')
                  setFilter('all')
                }}
              >
                Clear filters
              </button>
            </div>
          ) : (
            <>
              {/* Table on desktop. */}
              <div className="table-wrap only-wide">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Vendor</th>
                      <th>Client</th>
                      <th>Stage</th>
                      <th>Coverage</th>
                      <th>Verdict</th>
                      <th>Risk</th>
                      <th>Decision</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((v) => {
                      const { scan, gate, risk } = summarise(v)
                      return (
                        <tr
                          key={v.id}
                          className="row-link"
                          tabIndex={0}
                          role="link"
                          aria-label={`Open ${v.name}`}
                          onClick={() => open(v.id)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault()
                              open(v.id)
                            }
                          }}
                        >
                          <td>
                            <div className="cell-strong">{v.name}</div>
                            <div className="small muted mono cell-ref">
                              #{v.id} · {v.cin ?? 'no CIN'}
                            </div>
                          </td>
                          <td className="small cell-client">{v.clientName || '—'}</td>
                          <td>
                            <span className="badge b-neutral">
                              {STAGE_LABEL[v.stage] ?? v.stage}
                            </span>
                          </td>
                          <td style={{ minWidth: 140 }}>
                            {scan.isScored ? (
                              <>
                                <div className="small nums">
                                  {scan.pct.toFixed(1)}% · {scan.applicable}/{scan.total}
                                </div>
                                <Meter pct={scan.pct} tone={toneForScan(scan.pct, gate.gated)} />
                              </>
                            ) : (
                              <span className="small muted">Not scored</span>
                            )}
                          </td>
                          <td title={gate.gated ? gate.reasons.join(' ') : undefined}>
                            <VerdictBadge scan={scan} gated={gate.gated} />
                          </td>
                          <td>
                            {scan.isScored ? (
                              <RiskBadge risk={risk} />
                            ) : (
                              <span className="small muted">—</span>
                            )}
                          </td>
                          <td>
                            {v.decision ? (
                              <span
                                className={`badge b-${v.decision === 'Rejected' ? 'adverse' : 'pass'}`}
                              >
                                {v.decision}
                              </span>
                            ) : (
                              <span className="small muted">Open</span>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {/* Cards on narrow screens — a seven-column table on a phone
                  is a horizontal scrollbar, which nobody reads. */}
              <div className="v-cards only-narrow">
                {shown.map((v) => {
                  const { scan, gate, risk } = summarise(v)
                  return (
                    <button key={v.id} type="button" className="v-card" onClick={() => open(v.id)}>
                      <div className="v-card-top">
                        <div className="cell-strong">{v.name}</div>
                        {v.decision ? (
                          <span
                            className={`badge b-${v.decision === 'Rejected' ? 'adverse' : 'pass'}`}
                          >
                            {v.decision}
                          </span>
                        ) : (
                          <span className="badge b-neutral">
                            {STAGE_LABEL[v.stage] ?? v.stage}
                          </span>
                        )}
                      </div>

                      <div className="small muted mono">
                        #{v.id} · {v.cin ?? 'no CIN'}
                      </div>
                      {v.clientName && <div className="small muted">{v.clientName}</div>}

                      {scan.isScored && (
                        <div className="v-card-meter">
                          <div className="small nums">
                            SCAN {scan.pct.toFixed(1)}% · {scan.applicable}/{scan.total} params
                          </div>
                          <Meter pct={scan.pct} tone={toneForScan(scan.pct, gate.gated)} />
                        </div>
                      )}

                      <div className="v-card-badges">
                        <VerdictBadge scan={scan} gated={gate.gated} />
                        {scan.isScored && <RiskBadge risk={risk} />}
                      </div>
                    </button>
                  )
                })}
              </div>
            </>
          )}

          {shown.length > 0 && shown.length !== vendors.length && (
            <div className="list-foot small muted">
              Showing {shown.length} of {vendors.length} vendors
            </div>
          )}
        </Card>
      )}
    </div>
  )
}