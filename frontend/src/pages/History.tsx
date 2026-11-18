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
 *
 * WHAT CHANGED ON 18 NOV 2026, AND WHY
 * ------------------------------------
 *
 * THE COST COLUMN WAS OFF-SCREEN. Two column min-widths plus the client
 * sidebar pushed the table past the viewport, and the one column this
 * page exists for sat behind the horizontal scrollbar. It is now
 * `position: sticky; right: 0` — narrow the window and you lose When and
 * Vendor, never the money.
 *
 * FOUR EQUAL TILES SAID FOUR EQUAL THINGS, and these four are not equal:
 * one is the answer and three are context. The total leads; calls,
 * credits and set-aside sit beside it at a quarter of the weight.
 *
 * A FOURTH FIGURE, "unpriced", COUNTS CALLS THAT RECORDED NO PRICE.
 * `Finding.cost_paisa` defaults to zero and only the person-subject path
 * ever sets it, so most rows store nothing and the total under-reports.
 * A confident ₹0 across 78 calls is the failure this product refuses
 * everywhere else — a gap wearing the clothes of a clean result. Until
 * the write path is fixed the page says how many it could not price,
 * which is both the honest total and the bug report.
 *
 * THE SIDEBAR SHOWS CALLS AS WELL AS RUPEES, for the same reason: with
 * prices unwritten every line read "₹0" and the list looked broken
 * rather than unpriced. A call count is always true.
 *
 * ROWS ARE GROUPED BY DAY with a daily subtotal, which stops the date
 * repeating on every row and is how a ledger is read anyway.
 */

import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '@/api'
import {
  Callout,
  EmptyState,
  STATUS_LABEL,
  STATUS_TONE,
  rupees,
} from '@/components/ui'
import { useToast } from '@/hooks/useToast'
import type { HistoryRow, HistoryPage } from '@/types/domain'

/** YYYY-MM-DD, for the date inputs. */
const day = (d: Date): string => d.toISOString().slice(0, 10)

const SPAN = {
  '7': 'Last 7 days',
  '30': 'Last 30 days',
  '90': 'Last 90 days',
  all: 'Everything',
} as const

type Span = keyof typeof SPAN

/** Provider colours, assigned by rank so the bar and the keys agree. */
const BURN_CLASSES = 6

interface DayGroupData {
  key: string
  label: string
  rows: HistoryRow[]
  paisa: number
}

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
      /* Calls that recorded no price at all. NOT the same as free: a
         free check and a check whose cost was never written both store
         zero, and only one of them should reassure anybody. */
      unpriced: rows.filter((r) => !r.costPaisa && !r.credits).length,
    }),
    [rows],
  )

  /** Where the money went, by provider. The spend-watching half. */
  const burn = useMemo(() => {
    const acc = new Map<string, { name: string; calls: number; paisa: number }>()
    for (const r of rows) {
      const name = r.provider || 'in-house'
      const at = acc.get(name) ?? { name, calls: 0, paisa: 0 }
      at.calls += 1
      at.paisa += r.costPaisa
      acc.set(name, at)
    }
    return [...acc.values()].sort(
      (a, b) =>
        b.paisa - a.paisa || b.calls - a.calls || a.name.localeCompare(b.name),
    )
  }, [rows])

  /** Clients down the left, with what each has cost in this range. */
  const clients = useMemo(() => {
    const acc = new Map<
      string,
      { id: string; name: string; calls: number; paisa: number }
    >()
    for (const r of page?.rows ?? []) {
      const at = acc.get(r.clientId) ?? {
        id: r.clientId,
        name: r.clientName,
        calls: 0,
        paisa: 0,
      }
      at.calls += 1
      at.paisa += r.costPaisa
      acc.set(r.clientId, at)
    }
    return [...acc.values()].sort(
      (a, b) => b.paisa - a.paisa || b.calls - a.calls || a.name.localeCompare(b.name),
    )
  }, [page])

  /** Vendors of the chosen client — or of everyone, when none is chosen. */
  const vendors = useMemo(() => {
    const acc = new Map<
      string,
      { id: string; name: string; calls: number; paisa: number }
    >()
    for (const r of page?.rows ?? []) {
      if (client && r.clientId !== client) continue
      const at = acc.get(r.vendorId) ?? {
        id: r.vendorId,
        name: r.vendorName,
        calls: 0,
        paisa: 0,
      }
      at.calls += 1
      at.paisa += r.costPaisa
      acc.set(r.vendorId, at)
    }
    return [...acc.values()].sort(
      (a, b) => b.paisa - a.paisa || b.calls - a.calls || a.name.localeCompare(b.name),
    )
  }, [page, client])

  /** Rows cut into days, newest first, each with its own subtotal. */
  const days = useMemo(() => {
    const acc: DayGroupData[] = []
    for (const r of rows) {
      const at = new Date(r.fetchedAt)
      const key = day(at)
      let group = acc[acc.length - 1]
      if (!group || group.key !== key) {
        group = {
          key,
          label: at.toLocaleDateString(undefined, {
            weekday: 'long',
            day: 'numeric',
            month: 'long',
          }),
          rows: [],
          paisa: 0,
        }
        acc.push(group)
      }
      group.rows.push(r)
      group.paisa += r.costPaisa
    }
    return acc
  }, [rows])

  const scope = client
    ? clients.find((c) => c.id === client)?.name ?? 'This client'
    : 'All clients'

  /*
    EXPORT WHAT IS ON SCREEN, not what the server last sent.

    An invoice is prepared from a filtered view — one client, one month —
    and a CSV that quietly carried the unfiltered set would be wrong in
    the direction nobody checks.
  */
  function exportCsv() {
    const header = [
      'When', 'Client', 'Vendor', 'Check', 'Provider', 'Asked',
      'Result', 'Set aside', 'Reason', 'Cost (INR)', 'Credits',
    ]
    const cell = (v: unknown) => {
      const text = String(v ?? '')
      return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
    }
    const lines = [
      header.join(','),
      ...rows.map((r) =>
        [
          new Date(r.fetchedAt).toISOString(),
          r.clientName,
          r.vendorName,
          r.checkName,
          r.provider,
          Object.values(r.inputs).filter(Boolean).join(' · '),
          STATUS_LABEL[r.status] ?? r.status,
          r.ignoredAt ? 'yes' : '',
          r.ignoreReason ?? '',
          // Paisa to rupees once, at the edge, exactly as the screen does.
          (r.costPaisa / 100).toFixed(2),
          r.credits || '',
        ]
          .map(cell)
          .join(','),
      ),
    ]
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `vbc-api-history-${day(new Date())}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

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

  const burnTotal = burn.reduce((n, b) => n + b.paisa, 0)

  return (
    <div className="stack">
      {/* THE FIGURE FIRST, and at the size of an answer. The question
          this page answers is "how much"; the rest is context and is
          sized like context. */}
      <section className="stmt">
        <div className="stmt-lead">
          <div className="stmt-who">
            {scope} · {SPAN[span]}
          </div>
          <div className="stmt-total nums">{rupees(totals.paisa)}</div>
          <div className="stmt-sub">
            {totals.calls} call{totals.calls === 1 ? '' : 's'} across{' '}
            {burn.length} provider{burn.length === 1 ? '' : 's'}
            {vendor
              ? ''
              : ` · ${vendors.length} vendor${vendors.length === 1 ? '' : 's'}`}
          </div>
        </div>

        <div className="stmt-figs">
          <div className="stmt-fig">
            <div className="fig-n nums">{totals.calls}</div>
            <div className="fig-l">Calls</div>
          </div>
          <div className="stmt-fig">
            <div className="fig-n nums">{totals.credits}</div>
            <div className="fig-l">Credits</div>
          </div>
          <div className="stmt-fig">
            <div className="fig-n nums">{totals.aside}</div>
            <div className="fig-l" title="Still billed, still listed">
              Set aside
            </div>
          </div>
          {/* SAID OUT LOUD. A total that silently omits unpriced calls is
              wrong in the direction nobody checks. */}
          <div className={`stmt-fig${totals.unpriced ? ' is-flagged' : ''}`}>
            <div className="fig-n nums">{totals.unpriced}</div>
            <div
              className="fig-l"
              title="Calls that recorded no price. Not the same as free — the total does not include them."
            >
              Unpriced
            </div>
          </div>
        </div>
      </section>

      {burnTotal > 0 && (
        <section className="burn" aria-label="Spend by provider">
          <div className="burn-bar">
            {burn
              .filter((b) => b.paisa > 0)
              .map((b, i) => (
                <div
                  key={b.name}
                  className={`burn-seg burn-c${i % BURN_CLASSES}`}
                  style={{ width: `${(b.paisa / burnTotal) * 100}%` }}
                  title={`${b.name} — ${rupees(b.paisa)} over ${b.calls} calls`}
                />
              ))}
          </div>
          <div className="burn-keys">
            {burn.map((b, i) => (
              <span key={b.name} className="burn-key">
                <i className={`burn-dot burn-c${i % BURN_CLASSES}`} />
                {b.name} <b className="nums">{rupees(b.paisa)}</b>
                <span className="muted"> · {b.calls}</span>
              </span>
            ))}
          </div>
        </section>
      )}

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
        <button
          type="button"
          className="btn"
          onClick={exportCsv}
          disabled={!rows.length}
          title="Downloads exactly the rows shown, with the filters applied"
        >
          Export CSV
        </button>
      </div>

      <div className="hist-split">
        <aside className="hist-side">
          <div className="hist-side-h small">Clients</div>
          <Pick
            on={client === ''}
            name="All clients"
            paisa={page?.totalCostPaisa ?? 0}
            calls={page?.totalCalls ?? 0}
            onClick={() => {
              setClient('')
              setVendor('')
            }}
          />
          {clients.map((c) => (
            <Pick
              key={c.id}
              on={client === c.id}
              name={c.name}
              paisa={c.paisa}
              calls={c.calls}
              onClick={() => {
                setClient(c.id)
                setVendor('')
              }}
            />
          ))}

          <div className="hist-side-h small">
            {client ? 'Vendors of this client' : 'Vendors'}
          </div>
          {vendors.map((v) => (
            <Pick
              key={v.id}
              on={vendor === v.id}
              name={v.name}
              paisa={v.paisa}
              calls={v.calls}
              onClick={() => setVendor(vendor === v.id ? '' : v.id)}
            />
          ))}
        </aside>

        <div className="hist-main">
          {rows.length === 0 ? (
            <Callout kind="info" title="Nothing matches those filters">
              Clear the search, or pick a different client.
            </Callout>
          ) : (
            <div className="hist-scroll">
              <table className="hist-table">
                <thead>
                  <tr>
                    <th className="c-when">When</th>
                    {!vendor && <th className="c-vendor">Vendor</th>}
                    <th className="c-check">Check</th>
                    <th className="c-asked">Asked</th>
                    <th className="c-res">Result</th>
                    <th className="c-cost">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {days.map((group) => (
                    <DayGroup
                      key={group.key}
                      group={group}
                      showVendor={!vendor}
                      onVendor={(id) => navigate(`/vendor/${id}/findings`)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/** One client or vendor in the left-hand list. */
function Pick({
  on,
  name,
  paisa,
  calls,
  onClick,
}: {
  on: boolean
  name: string
  paisa: number
  calls: number
  onClick: () => void
}) {
  return (
    <button
      type="button"
      className={`hist-pick${on ? ' is-on' : ''}`}
      onClick={onClick}
      title={name}
    >
      <span className="hist-pick-name">{name}</span>
      <span className="hist-pick-meta">
        {/* The rupee figure can legitimately be ₹0 while prices are
            unwritten, so the call count carries the line. */}
        <span className="hist-pick-cost nums">{rupees(paisa)}</span>
        <span className="hist-pick-calls nums">{calls} calls</span>
      </span>
    </button>
  )
}

function DayGroup({
  group,
  showVendor,
  onVendor,
}: {
  group: DayGroupData
  showVendor: boolean
  onVendor: (vendorId: string) => void
}) {
  return (
    <>
      <tr className="day-row">
        <td colSpan={showVendor ? 6 : 5}>
          {group.label}
          <span className="day-sum nums">
            {group.rows.length} call{group.rows.length === 1 ? '' : 's'} ·{' '}
            {rupees(group.paisa)}
          </span>
        </td>
      </tr>
      {group.rows.map((r) => (
        <Row
          key={r.runId}
          row={r}
          showVendor={showVendor}
          onVendor={() => onVendor(r.vendorId)}
        />
      ))}
    </>
  )
}

function Row({
  row,
  showVendor,
  onVendor,
}: {
  row: HistoryRow
  showVendor: boolean
  onVendor: () => void
}) {
  /* The values this call was made against. On a check run once per
     director this is the only thing telling the rows apart, and on an
     invoice it is what a client would query. */
  const asked = Object.values(row.inputs).filter(Boolean).join(' · ')
  const priced = row.costPaisa > 0 || row.credits > 0

  return (
    <tr className={row.ignoredAt ? 'is-aside' : undefined}>
      <td className="c-when nums">
        {new Date(row.fetchedAt).toLocaleTimeString(undefined, {
          hour: '2-digit',
          minute: '2-digit',
        })}
      </td>
      {showVendor && (
        <td className="c-vendor">
          <div className="cell-main">
            <button type="button" className="linklike" onClick={onVendor}>
              {row.vendorName}
            </button>
          </div>
          <div className="cell-sub">{row.clientName}</div>
        </td>
      )}
      <td className="c-check">
        <div className="cell-main">{row.checkName}</div>
        <div className="cell-sub">{row.provider || '—'}</div>
      </td>
      <td className="c-asked">
        <span className="asked-val">{asked || '—'}</span>
      </td>
      <td className="c-res">
        {/* A dot and a word rather than a filled badge. This is a list
            read for numbers, and a column of saturated chips competes
            with the figures beside it. */}
        <span
          className={`res res-${STATUS_TONE[row.status]}`}
          title={STATUS_LABEL[row.status]}
        >
          <i className="res-dot" />
          {STATUS_LABEL[row.status]}
        </span>
        {/* WHY IT WAS SET ASIDE, in the ledger as well as on Step 3. The
            row stays because the money was spent; the reason stays
            because "why is this call on my invoice" is the question it
            will be read with. */}
        {row.ignoredAt && (
          <div className="aside-why">Set aside — {row.ignoreReason}</div>
        )}
      </td>
      <td className="c-cost">
        {priced ? (
          <>
            <div className="cost-val nums">{rupees(row.costPaisa)}</div>
            {row.credits > 0 && (
              <div className="cost-cr nums">{row.credits} cr</div>
            )}
          </>
        ) : (
          /* NOT "₹0". A call with no recorded price is not a free call,
             and the two must not render the same. */
          <div
            className="cost-val cost-none"
            title="No price was recorded for this call"
          >
            not priced
          </div>
        )}
      </td>
    </tr>
  )
}
