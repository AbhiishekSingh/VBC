/**
 * Governance — the audit trail.
 *
 * Append-only. Nothing here is ever updated or deleted; a correction is a
 * new entry. In an audit product the log is the evidence that the process
 * was followed, so its integrity matters more than its tidiness.
 */

import { useEffect, useState } from 'react'
import { api } from '@/api'
import { Card } from '@/components/ui'
import type { AuditEntry } from '@/types/domain'

const ACTOR_TONE = (actor: string) => (actor === 'system' ? 'b-neutral' : 'b-accent')

export default function Audit() {
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [filter, setFilter] = useState('')

  useEffect(() => {
    api.listAudit().then(setEntries)
  }, [])

  const shown = entries.filter(
    (e) =>
      !filter ||
      [e.action, e.detail, e.actor, e.vendorId ?? ''].join(' ').toLowerCase().includes(filter.toLowerCase()),
  )

  const csv = () => {
    const rows = [['Timestamp', 'Vendor', 'Actor', 'Action', 'Detail'], ...shown.map((e) => [e.ts, e.vendorId ?? '', e.actor, e.action, e.detail])]
    const body = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n')
    const url = URL.createObjectURL(new Blob([body], { type: 'text/csv' }))
    const a = document.createElement('a')
    a.href = url
    a.download = 'vbc-audit-trail.csv'
    a.click()
    URL.revokeObjectURL(url)
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
        title={`${shown.length} entries`}
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
        <div className="table-wrap">
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
            <tbody>
              {shown.map((e, i) => (
                <tr key={`${e.ts}-${i}`}>
                  <td className="mono muted" style={{ whiteSpace: 'nowrap' }}>{e.ts}</td>
                  <td className="mono">{e.vendorId ? `#${e.vendorId}` : '—'}</td>
                  <td><span className={`badge ${ACTOR_TONE(e.actor)}`}>{e.actor}</span></td>
                  <td className="mono small">{e.action}</td>
                  <td>{e.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}
