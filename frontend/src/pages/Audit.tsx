/**
 * Governance — the audit trail.
 *
 * Append-only. Nothing here is ever updated or deleted; a correction is a
 * new entry. In an audit product the log is the evidence that the process
 * was followed, so its integrity matters more than its tidiness.
 */

import { useEffect, useState } from 'react'
import { api } from '@/api'
import { Card, SkeletonTable } from '@/components/ui'
import { csvRows, downloadBlob } from '@/lib/download'
import { useToast } from '@/hooks/useToast'
import type { AuditEntry } from '@/types/domain'

const ACTOR_TONE = (actor: string) => (actor === 'system' ? 'b-neutral' : 'b-accent')

const PAGE = 100

export default function Audit() {
  const toast = useToast()
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [filter, setFilter] = useState('')
  // The list started empty and rendered "0 entries" over a blank table
  // while the request was still in flight. In an append-only audit product
  // an unreachable log that reads as an empty log is a misreport, not an
  // untidy loading state.
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [shownCount, setShownCount] = useState(PAGE)

  useEffect(() => {
    let alive = true
    api
      .listAudit()
      .then((rows) => alive && setEntries(rows))
      .catch((e) => {
        if (!alive) return
        setFailed(true)
        toast.error(e, 'The audit trail could not be loaded.')
      })
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const shown = entries.filter(
    (e) =>
      !filter ||
      [e.action, e.detail, e.actor, e.vendorId ?? ''].join(' ').toLowerCase().includes(filter.toLowerCase()),
  )

  const csv = () => {
    const rows = [['Timestamp', 'Vendor', 'Actor', 'Action', 'Detail'], ...shown.map((e) => [e.ts, e.vendorId ?? '', e.actor, e.action, e.detail])]
    downloadBlob(csvRows(rows), 'vbc-audit-trail.csv', 'text/csv')
  }

  return (
    <div className="stack">
      <div>
        <div className="kicker">Governance</div>
        <h2 className="page-h">Audit trail</h2>
        <p className="page-sub">
          Every system and human action, append-only. Entries are never edited or removed — a
          correction is recorded as a new entry above the original.
        </p>
      </div>

      <Card
        title={loading ? 'Loading…' : `${shown.length} entries`}
        aside={
          <div className="row">
            <input
              className="input"
              style={{ width: 200 }}
              placeholder="Filter…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
            <button type="button" className="btn" onClick={csv}>Export CSV</button>
          </div>
        }
        tight
      >
        {/* The trail is unbounded. is-tall keeps the header in view while
            you scroll it, and the page button keeps the DOM finite. */}
        <div className="table-wrap is-tall">
          <table className="table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Vendor</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Detail</th>
              </tr>
            </thead>
            {loading ? (
              <SkeletonTable rows={8} cols={5} widths={['80%', '40%', '55%', '65%', '85%']} />
            ) : (
              <tbody>
                {shown.slice(0, shownCount).map((e, i) => (
                  <tr key={`${e.ts}-${i}`}>
                    <td className="mono muted" style={{ whiteSpace: 'nowrap' }}>{e.ts}</td>
                    <td className="mono">{e.vendorId ? `#${e.vendorId}` : '—'}</td>
                    <td><span className={`badge ${ACTOR_TONE(e.actor)}`}>{e.actor}</span></td>
                    <td className="mono small">{e.action}</td>
                    <td>{e.detail}</td>
                  </tr>
                ))}
              </tbody>
            )}
          </table>
        </div>

        {!loading && shown.length === 0 && (
          <div className="empty-inline">
            {failed ? (
              <>
                <span className="warn-text">The audit trail could not be loaded.</span>
                <span className="small muted">
                  This is not an empty log — nothing was read. Reload the page to try again.
                </span>
              </>
            ) : filter ? (
              <>
                <span>Nothing matches that filter.</span>
                <button type="button" className="btn sm" onClick={() => setFilter('')}>
                  Clear filter
                </button>
              </>
            ) : (
              <span className="muted">No entries recorded yet.</span>
            )}
          </div>
        )}

        {!loading && shown.length > shownCount && (
          <div className="list-foot row-between">
            <span className="small muted nums">
              Showing {shownCount} of {shown.length}
            </span>
            <button
              type="button"
              className="btn sm"
              onClick={() => setShownCount((n) => n + PAGE)}
            >
              Show {Math.min(PAGE, shown.length - shownCount)} more
            </button>
          </div>
        )}
      </Card>
    </div>
  )
}
