/**
 * One client, and its vendors.
 *
 * The vendor list here is scoped server-side by clientId — not filtered in
 * the browser from a full list. Filtering client-side would mean every
 * client's vendors travelled to the browser and only the display was
 * narrowed.
 */

import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { api } from '@/api'
import {
  Card,
  EmptyState,
  LoadingBlock,
  Meter,
  SkeletonTiles,
  Tile,
  toneForScan,
} from '@/components/ui'
import { useClient } from '@/hooks/useClients'
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

export default function ClientDetail() {
  const { clientId } = useParams<{ clientId: string }>()
  const { client, loading, error } = useClient(clientId)
  const [vendors, setVendors] = useState<Vendor[]>([])
  const [loadingVendors, setLoadingVendors] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    if (!clientId) return
    let alive = true
    setLoadingVendors(true)
    api
      .listVendors(clientId)
      .then((rows) => alive && setVendors(rows))
      .finally(() => alive && setLoadingVendors(false))
    return () => {
      alive = false
    }
  }, [clientId])

  if (loading) {
    return (
      <div className="stack">
        <LoadingBlock label="Loading client…" />
        <SkeletonTiles />
      </div>
    )
  }
  if (error || !client) return <div className="callout k-adverse">{error ?? 'Client not found.'}</div>

  const decided = vendors.filter((v) => v.decision)
  const gated = vendors.filter((v) => applyPolicy(scoreScan(v.scan), DEFAULT_POLICY).gated)

  return (
    <div className="stack">
      <div className="client-header">
        <span className="client-avatar lg" aria-hidden="true">
          {client.name.slice(0, 2).toUpperCase()}
        </span>
        <div className="client-header-text">
          <div className="kicker">Client · {client.id}</div>
          <h2 className="page-h">{client.name}</h2>
          <p className="page-sub">
            {[client.legalName !== client.name ? client.legalName : null, client.industry]
              .filter(Boolean)
              .join(' · ') || 'No further details recorded'}
          </p>
        </div>
        <button
          type="button"
          className="btn primary"
          onClick={() => navigate(`/vendor/new?clientId=${client.id}`)}
        >
          Add a vendor
        </button>
      </div>

      {(client.spoc || client.email || client.phone) && (
        <div className="meta-row small muted">
          {client.spoc && <span>Contact: {client.spoc}</span>}
          {client.email && <span>{client.email}</span>}
          {client.phone && <span>{client.phone}</span>}
        </div>
      )}

      <div className="grid-4">
        <Tile n={vendors.length} label="Vendors" tone="accent" />
        <Tile n={vendors.length - decided.length} label="Awaiting a decision" />
        <Tile
          n={gated.length}
          label="Held for coverage"
          note="Reached the threshold on too little evidence"
          tone={gated.length ? 'warn' : 'neutral'}
        />
        <Tile n={decided.length} label="Decided" tone="pass" />
      </div>

      <Card title="Vendors" subtitle={`Under ${client.name}`} tight>
        {loadingVendors ? (
          <LoadingBlock label="Loading vendors…" />
        ) : vendors.length === 0 ? (
          <EmptyState
            title={`No vendors for ${client.name} yet`}
            body="Add the first company this client wants assessed."
            action={
              <button
                type="button"
                className="btn primary"
                onClick={() => navigate(`/vendor/new?clientId=${client.id}`)}
              >
                Add a vendor
              </button>
            }
          />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Vendor</th>
                  <th>Stage</th>
                  <th>Coverage</th>
                  <th>Verdict</th>
                  <th className="num">Risk</th>
                  <th>Decision</th>
                </tr>
              </thead>
              <tbody>
                {vendors.map((v) => {
                  const scan = scoreScan(v.scan)
                  const gate = applyPolicy(scan, DEFAULT_POLICY)
                  const risk = scoreRisk(v.checks, v.selected)
                  return (
                    // A pointer cursor and an onClick and nothing else:
                    // there was no keyboard path at all from a client to
                    // its vendors. Dashboard does this correctly.
                    <tr
                      key={v.id}
                      className="row-link"
                      role="link"
                      tabIndex={0}
                      aria-label={`Open ${v.name}`}
                      onClick={() => navigate(`/vendor/${v.id}/findings`)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          navigate(`/vendor/${v.id}/findings`)
                        }
                      }}
                    >
                      <td>
                        <div className="cell-strong">{v.name}</div>
                        <div className="small muted mono">#{v.id}</div>
                      </td>
                      <td>
                        <span className="badge b-neutral">{STAGE_LABEL[v.stage] ?? v.stage}</span>
                      </td>
                      <td className="col-coverage">
                        {scan.isScored ? (
                          <>
                            <div className="small nums">{scan.pct.toFixed(1)}%</div>
                            <Meter pct={scan.pct} tone={toneForScan(scan.pct, gate.gated)} />
                          </>
                        ) : (
                          <span className="small muted">Not scored</span>
                        )}
                      </td>
                      <td>
                        {gate.gated ? (
                          <span className="badge b-warn">Insufficient coverage</span>
                        ) : scan.passed ? (
                          <span className="badge b-pass">Positive</span>
                        ) : scan.isScored ? (
                          <span className="badge b-adverse">Negative</span>
                        ) : (
                          <span className="badge b-unchecked">Not scored</span>
                        )}
                      </td>
                      <td className="num nums">{scan.isScored ? risk.score : '—'}</td>
                      <td>
                        {v.decision ? (
                          // Every non-null decision used to render as a
                          // green "pass" badge, so a REJECTED vendor read
                          // as approved on the client's own page.
                          <span
                            className={`badge ${
                              v.decision === 'Rejected'
                                ? 'b-adverse'
                                : v.decision === 'Approved'
                                  ? 'b-pass'
                                  : 'b-warn'
                            }`}
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
        )}
      </Card>
    </div>
  )
}
