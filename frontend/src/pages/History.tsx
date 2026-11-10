/**
 * API call history — the ledger.
 *
 * DISTINCT FROM THE AUDIT TRAIL, and the distinction is the reason this
 * screen exists rather than another filter on that one.
 *
 * The audit trail answers "what happened and who did it", in sentences:
 * eleven checks ran, a result was set aside because the number belonged
 * to a different director, an approval was recorded. Sentences are the
 * right shape for that and the wrong shape for this, because prose
 * cannot be added up. "What has this client cost us" is a question about
 * money, and it is answered by putting numbers in a column.
 *
 * So: one row per call, joined to the vendor and the client it was spent
 * on, with the price as a figure.
 *
 * THREE THINGS THIS SCREEN REFUSES TO DO
 * --------------------------------------
 *
 * 1. Hide a call because its result no longer counts. A result set aside
 *    was still a call that was paid for, and leaving it out would make
 *    this page under-report the bill — silently, which is the worst way
 *    to be wrong about money. Ignored rows are listed and marked.
 *
 * 2. Compute its totals separately from its rows. Both come from the
 *    same filtered set, summed in one pass, so the figure at the top and
 *    the list beneath it cannot drift apart. Two queries against one
 *    question is how a page ends up arguing with itself.
 *
 * 3. Round. Prices are integers in paisa everywhere they travel and are
 *    turned into rupees once, at the edge, for display.
 */

import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '@/api'
import { Callout, EmptyState, StatusBadge, rupees } from '@/components/ui'
import { useToast } from '@/hooks/useToast'
import type { HistoryPage, HistoryRow } from '@/types/domain'

/** YYYY-MM-DD, for the date inputs. */
const day = (d: Date): string => d.toISOString().slice(0, 10)

const SPAN = {
  '7': 'Last 7 days',
  '30': 'Last 30 days',
  '90': 'Last 90 days',
  all: 'Everything',
} as const

type Span = keyof typeof SPAN

export default function History() {
  const navigate = useNavigate()
  const toast = useToast()

  const [page, setPage] = useState<HistoryPage | null>(null)
  const [loading, setLoading] = useState(true)
  const [span, setSpan] = useState<Span>('30')
  const [client, setClient] = useState<string>('')
  const [vendor, setVendor] = useState<string>('')
  const [query, setQuery] = useState('')

  /*
    THE WHOLE SET IS FETCHED ONCE PER DATE RANGE, and narrowing by client
    or vendor happens here.

    A round trip per click would make the left-hand list feel like a
    series of page loads, and the totals it shows are already in hand —
    they are sums over rows this screen is holding. The date range is the
    one filter that genuinely changes what the server must read, so it is
    the one that refetches.
  */
  useEffect(() => {
    let live = true
    setLoading(true)
    const from =
      span === 'all'
        ? undefined
        : day(new Date(Date.now() - Number(span) * 86_400_000))
    api
      .listHistory({ from })
      .then((result) => {
        if (live) setPage(result)
      })
      .catch((e) => {
        if (live) toast.error(e, 'The history could not be loaded.')
      })
      .finally(() => {
        if (live) setLoading(false)
      })
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [span])

  const rows = useMemo(() => {
    const all = page?.rows ?? []
    const term = query.trim().toLowerCase()
    return all.filter((r) => {
      if (client && r.clientId !== client) return false
      if (vendor && r.vendorId !== vendor) return false
      if (!term) return true
      return (
        r.checkName.toLowerCase().includes(term) ||
        r.vendorName.toLowerCase().includes(term) ||
        r.clientName.toLowerCase().includes(term) ||
        r.provider.toLowerCase().includes(term) ||
        Object.values(r.inputs).some((v) => v.toLowerCase().includes(term))
      )
    })
  }, [page, client, vendor, query])

  /** Summed from the rows ON SCREEN — see the note at the top. */
  const totals = useMemo(
    () => ({
      calls: rows.length,
      paisa: rows.reduce((n, r) => n + r.costPaisa, 0),
      credits: rows.reduce((n, r) => n + r.credits, 0),
      aside: rows.filter((r) => r.ignoredAt).length,
    }),
    [rows],
  )

  /** Clients down the left, with what each has cost in this range. */
  const clients = useMemo(() => {
    const acc = new Map<string, { id: string; name: string; calls: number; paisa: number }>()
    for (const r of page?.rows ?? []) {
      const at = acc.get(r.clientId) ?? {
        id: r.clientId, name: r.clientName, calls: 0, paisa: 0,
      }
      at.calls += 1
      at.paisa += r.costPaisa
      acc.set(r.clientId, at)
    }
    return [...acc.values()].sort((a, b) => b.paisa - a.paisa || a.name.localeCompare(b.name))
  }, [page])

  /** Vendors of the chosen client — or of everyone, when none is chosen. */
  const vendors = useMemo(() => {
    const acc = new Map<string, { id: string; name: string; calls: number; paisa: number }>()
    for (const r of page?.rows ?? []) {
      if (client && r.clientId !== client) continue
      const at = acc.get(r.vendorId) ?? {
        id: r.vendorId, name: r.vendorName, calls: 0, paisa: 0,
      }
      at.calls += 1
      at.paisa += r.costPaisa
      acc.set(r.vendorId, at)
    }
    return [...acc.values()].sort((a, b) => b.paisa - a.paisa || a.name.localeCompare(b.name))
  }, [page, client])

  if (loading && !page) {
    return <p className="small muted">Loading the ledger…</p>
  }

  if (page && page.rows.length === 0) {
    return (
      <EmptyState
        title="No API calls in this period"
        body="Every check that calls a provider is recorded here, with what it cost. Widen the date range, or run some checks."
        action={
          <button type="button" className="btn" onClick={() => setSpan('all')}>
            Show everything
          </button>
        }
      />
    )
  }

  return (
    <div className="stack">
      {/* THE FIGURE FIRST. The question this page answers is "how much",
          and an answer that requires scrolling is not an answer. */}
      <div className="grid-4">
        <div className="tile">
          <div className="tile-n nums">{rupees(totals.paisa)}</div>
          <div className="tile-label">Spent</div>
        </div>
        <div className="tile">
          <div className="tile-n nums">{totals.calls}</div>
          <div className="tile-label">API calls</div>
        </div>
        <div className="tile">
          <div className="tile-n nums">{totals.credits}</div>
          <div className="tile-label">Credits</div>
        </div>
        <div className="tile">
          <div className="tile-n nums">{totals.aside}</div>
          <div className="tile-label">Set aside</div>
          {/* SAID HERE, not left to be inferred from the rows. A reader
              checking an invoice has to know these are included. */}
          <div className="tile-note small muted">still billed, still listed</div>
        </div>
      </div>

      <div className="hist-bar">
        <div className="seg">
          {(Object.keys(SPAN) as Span[]).map((key) => (
            <button
              key={key}
              type="button"
              className={`seg-btn${span === key ? ' is-on' : ''}`}
              onClick={() => setSpan(key)}
            >
              {SPAN[key]}
            </button>
          ))}
        </div>
        <input
          className="input"
          type="search"
          value={query}
          placeholder="Filter by check, vendor, provider or the value it was run against"
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      <div className="hist-split">
        <aside className="hist-side">
          <div className="hist-side-h small">Clients</div>
          <button
            type="button"
            className={`hist-pick${client === '' ? ' is-on' : ''}`}
            onClick={() => {
              setClient('')
              setVendor('')
            }}
          >
            <span className="hist-pick-name">All clients</span>
            <span className="small nums muted">{rupees(page?.totalCostPaisa ?? 0)}</span>
          </button>
          {clients.map((c) => (
            <button
              key={c.id}
              type="button"
              className={`hist-pick${client === c.id ? ' is-on' : ''}`}
              onClick={() => {
                setClient(c.id)
                setVendor('')
              }}
            >
              <span className="hist-pick-name">{c.name}</span>
              <span className="small nums muted">{rupees(c.paisa)}</span>
            </button>
          ))}

          <div className="hist-side-h small">
            {client ? 'Vendors of this client' : 'Vendors'}
          </div>
          {vendors.map((v) => (
            <button
              key={v.id}
              type="button"
              className={`hist-pick${vendor === v.id ? ' is-on' : ''}`}
              onClick={() => setVendor(vendor === v.id ? '' : v.id)}
            >
              <span className="hist-pick-name">{v.name}</span>
              <span className="small nums muted">{rupees(v.paisa)}</span>
            </button>
          ))}
        </aside>

        <div className="hist-main">
          {rows.length === 0 ? (
            <Callout kind="info" title="Nothing matches those filters">
              Clear the search, or pick a different client.
            </Callout>
          ) : (
            <table className="table hist-table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Vendor</th>
                  <th>Check</th>
                  <th>Asked</th>
                  <th>Result</th>
                  <th className="num">Cost</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <Row key={r.runId} row={r} onVendor={() => navigate(`/vendor/${r.vendorId}/findings`)} />
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

function Row({ row, onVendor }: { row: HistoryRow; onVendor: () => void }) {
  /* The values this call was made against. On a check run once per
     director this is the only thing telling the rows apart, and on an
     invoice it is what a client would query. */
  const asked = Object.values(row.inputs).filter(Boolean).join(' · ')

  return (
    <tr className={row.ignoredAt ? 'is-aside' : undefined}>
      <td className="small nums muted">
        {new Date(row.fetchedAt).toLocaleString(undefined, {
          day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
        })}
      </td>
      <td>
        <button type="button" className="linklike" onClick={onVendor}>
          {row.vendorName}
        </button>
        <div className="small muted">{row.clientName}</div>
      </td>
      <td>
        {row.checkName}
        <div className="small muted">{row.provider || '—'}</div>
      </td>
      <td className="small mono">{asked || '—'}</td>
      <td>
        <StatusBadge status={row.status} />
        {/* WHY IT WAS SET ASIDE, in the ledger as well as on Step 3. The
            row stays because the money was spent; the reason stays
            because "why is this call on my invoice" is the question it
            will be read with. */}
        {row.ignoredAt && (
          <span className="small hist-aside"> set aside — {row.ignoreReason}</span>
        )}
      </td>
      <td className="num nums">
        {row.costPaisa ? rupees(row.costPaisa) : '—'}
        {row.credits > 0 && <div className="small muted">{row.credits} cr</div>}
      </td>
    </tr>
  )
}
