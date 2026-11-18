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
 * THE SIDEBAR IS GONE (18 Nov 2026)
 * ---------------------------------
 * A 17rem card held four names, a column of ₹0 and two truncated
 * vendors. It filtered on two dimensions and cost the table the width
 * that forced the Cost column off the right edge in the first place.
 *
 * The same filtering is now a row of dropdowns, one per dimension, each
 * option carrying its own count — `ZEPTO LIMITED (25)` says more than a
 * sidebar entry did, in a quarter of the space. The table takes the rest,
 * which is why every column fits on a laptop without scrolling.
 *
 * `Cost` keeps `position: sticky; right: 0` anyway. It no longer triggers
 * at a normal width, and it is the difference between a narrow window
 * losing `When` and a narrow window losing the money.
 *
 * EVERY FILTER DEFAULTS TO EVERYTHING, and the line under the bar says
 * what is being shown — "78 of 78 calls", or "22 of 78" with the active
 * filters listed as removable chips. A filtered page that does not admit
 * it is filtered is how an invoice goes out short, which is the same
 * failure as the silent ₹0 and deserves the same treatment.
 *
 * WHY "unpriced" IS A HEADLINE FIGURE
 * -----------------------------------
 * `Finding.cost_paisa` defaults to zero and only the person-subject path
 * ever sets it, so most rows store nothing and the total under-reports.
 * A confident ₹0 across 78 calls is a gap wearing the clothes of a clean
 * result. Until the write path is fixed the page says how many calls it
 * could not price, which is both the honest total and the bug report.
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
import type { CheckStatus, HistoryRow, HistoryPage } from '@/types/domain'

/** YYYY-MM-DD, for the date inputs. */
const day = (d: Date): string => d.toISOString().slice(0, 10)

const SPAN = {
  '7': '7d',
  '30': '30d',
  '90': '90d',
  all: 'All',
} as const

type Span = keyof typeof SPAN

const SPAN_LABEL: Record<Span, string> = {
  '7': 'Last 7 days',
  '30': 'Last 30 days',
  '90': 'Last 90 days',
  all: 'Everything',
}

/** Provider colours, assigned by rank so the bar and the keys agree. */
const BURN_CLASSES = 6

/** The five dimensions the bar filters on. All default to everything. */
type FilterKey = 'client' | 'vendor' | 'provider' | 'check' | 'status'

const EMPTY: Record<FilterKey, string> = {
  client: '', vendor: '', provider: '', check: '', status: '',
}

const FILTER_NOUN: Record<FilterKey, string> = {
  client: 'Client',
  vendor: 'Vendor',
  provider: 'Provider',
  check: 'Check',
  status: 'Result',
}

/** How a row answers each dimension — one place, so the option lists,
 *  the filtering and the chips can never disagree about what a filter
 *  means. */
const VALUE_OF: Record<FilterKey, (r: HistoryRow) => string> = {
  client: (r) => r.clientId,
  vendor: (r) => r.vendorId,
  provider: (r) => r.provider || 'in-house',
  check: (r) => r.checkId,
  status: (r) => r.status,
}

const LABEL_OF: Record<FilterKey, (r: HistoryRow) => string> = {
  client: (r) => r.clientName,
  vendor: (r) => r.vendorName,
  provider: (r) => r.provider || 'in-house',
  check: (r) => r.checkName,
  status: (r) => STATUS_LABEL[r.status as CheckStatus] ?? r.status,
}

interface Option { value: string; label: string; count: number }

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
  const [filters, setFilters] = useState<Record<FilterKey, string>>(EMPTY)
  const [query, setQuery] = useState('')

  /*
    THE WHOLE SET IS FETCHED ONCE PER DATE RANGE, and every other filter
    is applied here.

    A round trip per dropdown would make the bar feel like a series of
    page loads, and the counts beside each option are sums over rows
    this screen is already holding. The date range is the one filter
    that genuinely changes what the server must read, so it is the one
    that refetches.
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

  const all = useMemo(() => page?.rows ?? [], [page])

  const matches = useMemo(() => {
    const term = query.trim().toLowerCase()
    return (r: HistoryRow): boolean => {
      for (const key of Object.keys(filters) as FilterKey[]) {
        const want = filters[key]
        if (want && VALUE_OF[key](r) !== want) return false
      }
      if (!term) return true
      return (
        r.checkName.toLowerCase().includes(term) ||
        r.vendorName.toLowerCase().includes(term) ||
        r.clientName.toLowerCase().includes(term) ||
        r.provider.toLowerCase().includes(term) ||
        Object.values(r.inputs).some((v) => v.toLowerCase().includes(term))
      )
    }
  }, [filters, query])

  const rows = useMemo(() => all.filter(matches), [all, matches])

  /*
    OPTION COUNTS ARE MEASURED WITH THAT DIMENSION'S OWN FILTER LIFTED.

    Counted against the fully filtered set, picking "ZEPTO LIMITED"
    would leave every other vendor reading (0) — the list would tell you
    only what you had already chosen, and look broken doing it. Lifting
    just this dimension answers the question actually being asked: "how
    many would I get if I switched to that one".
  */
  const options = useMemo(() => {
    const out = {} as Record<FilterKey, Option[]>
    for (const key of Object.keys(EMPTY) as FilterKey[]) {
      const others = { ...filters, [key]: '' }
      const pool = all.filter((r) => {
        for (const k of Object.keys(others) as FilterKey[]) {
          const want = others[k]
          if (want && VALUE_OF[k](r) !== want) return false
        }
        return true
      })
      const acc = new Map<string, Option>()
      for (const r of pool) {
        const value = VALUE_OF[key](r)
        const at = acc.get(value) ?? { value, label: LABEL_OF[key](r), count: 0 }
        at.count += 1
        acc.set(value, at)
      }
      out[key] = [...acc.values()].sort(
        (a, b) => b.count - a.count || a.label.localeCompare(b.label),
      )
    }
    return out
  }, [all, filters])

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
      vendors: new Set(rows.map((r) => r.vendorId)).size,
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

  const active = (Object.keys(filters) as FilterKey[]).filter((k) => filters[k])

  /** What the header says it is showing. */
  const scope = useMemo(() => {
    const parts = (['client', 'vendor'] as FilterKey[]).map((key) => {
      const chosen = filters[key]
      if (!chosen) return key === 'client' ? 'All clients' : 'All vendors'
      return options[key].find((o) => o.value === chosen)?.label ?? chosen
    })
    return `${parts[0]} · ${parts[1]} · ${SPAN_LABEL[span]}`
  }, [filters, options, span])

  const set = (key: FilterKey, value: string) =>
    setFilters((f) => ({ ...f, [key]: value }))

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
          STATUS_LABEL[r.status as CheckStatus] ?? r.status,
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
          <div className="stmt-who">{scope}</div>
          <div className="stmt-total nums">{rupees(totals.paisa)}</div>
          <div className="stmt-sub">
            {totals.calls} call{totals.calls === 1 ? '' : 's'} across{' '}
            {burn.length} provider{burn.length === 1 ? '' : 's'} ·{' '}
            {totals.vendors} vendor{totals.vendors === 1 ? '' : 's'}
            {totals.unpriced === totals.calls && totals.calls > 0
              ? ' · no prices recorded yet'
              : ''}
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

      <section className="filters">
        {(Object.keys(EMPTY) as FilterKey[]).map((key) => (
          <Picker
            key={key}
            id={`f-${key}`}
            label={FILTER_NOUN[key]}
            value={filters[key]}
            options={options[key]}
            onChange={(v) => set(key, v)}
          />
        ))}

        <div className="f">
          <span className="f-l">Period</span>
          <div className="seg">
            {(Object.keys(SPAN) as Span[]).map((key) => (
              <button
                key={key}
                type="button"
                className={`seg-btn${span === key ? ' is-on' : ''}`}
                onClick={() => setSpan(key)}
                title={SPAN_LABEL[key]}
              >
                {SPAN[key]}
              </button>
            ))}
          </div>
        </div>

        <div className="f f-grow">
          <label className="f-l" htmlFor="f-search">Search</label>
          <input
            className="input"
            id="f-search"
            type="search"
            value={query}
            placeholder="Check, vendor, provider, or the value it was run against"
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>

        <div className="f-actions">
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
      </section>

      {/* WHAT IS BEING SHOWN, ALWAYS. A page that has quietly narrowed
          itself is how an invoice goes out short. */}
      <div className="chips">
        <span className="chips-l">Showing</span>
        {active.length === 0 && !query ? (
          <span className="chip-f"><b>Everything</b></span>
        ) : (
          <>
            {active.map((key) => (
              <span key={key} className="chip-f">
                {FILTER_NOUN[key]}{' '}
                <b>
                  {options[key].find((o) => o.value === filters[key])?.label ??
                    filters[key]}
                </b>
                <button
                  type="button"
                  className="chip-x"
                  onClick={() => set(key, '')}
                  aria-label={`Clear the ${FILTER_NOUN[key]} filter`}
                >
                  ×
                </button>
              </span>
            ))}
            {query && (
              <span className="chip-f">
                Search <b>{query}</b>
                <button
                  type="button"
                  className="chip-x"
                  onClick={() => setQuery('')}
                  aria-label="Clear the search"
                >
                  ×
                </button>
              </span>
            )}
            <button
              type="button"
              className="chip-clear"
              onClick={() => {
                setFilters(EMPTY)
                setQuery('')
              }}
            >
              Clear all
            </button>
          </>
        )}
        <span className="chips-count">
          — {rows.length} of {all.length} calls
        </span>
      </div>

      {rows.length === 0 ? (
        <Callout kind="info" title="Nothing matches those filters">
          Clear a filter, or widen the period.
        </Callout>
      ) : (
        <div className="hist-scroll">
          <table className="hist-table">
            <thead>
              <tr>
                <th className="c-when">When</th>
                <th className="c-vendor">Vendor</th>
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
                  onVendor={(id) => navigate(`/vendor/${id}/findings`)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/** One dropdown.
 *
 *  The options carried their row counts until 18 Nov 2026 —
 *  `ZEPTO LIMITED (17)`. Dropped: with five filters side by side the
 *  bar became a wall of parenthesised numbers, and the two that
 *  matter are already on the page — the total in the header and
 *  "17 of 31 calls" under the bar. A count repeated five times in the
 *  closed state of a control is noise, not information.
 *
 *  `Option.count` is still carried, because the list is ORDERED by it:
 *  the vendor you have spent most on is the one you are most likely to
 *  want, and it sits at the top without having to say why. */
function Picker({
  id, label, value, options, onChange,
}: {
  id: string
  label: string
  value: string
  options: Option[]
  onChange: (value: string) => void
}) {
  return (
    <div className="f">
      <label className="f-l" htmlFor={id}>{label}</label>
      <select
        className="select"
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">All {label.toLowerCase()}s</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  )
}

function DayGroup({
  group, onVendor,
}: {
  group: DayGroupData
  onVendor: (vendorId: string) => void
}) {
  return (
    <>
      <tr className="day-row">
        <td colSpan={6}>
          {group.label}
          <span className="day-sum nums">
            {group.rows.length} call{group.rows.length === 1 ? '' : 's'} ·{' '}
            {rupees(group.paisa)}
          </span>
        </td>
      </tr>
      {group.rows.map((r) => (
        <Row key={r.runId} row={r} onVendor={() => onVendor(r.vendorId)} />
      ))}
    </>
  )
}

function Row({ row, onVendor }: { row: HistoryRow; onVendor: () => void }) {
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
      <td className="c-vendor">
        <div className="cell-main">
          <button type="button" className="linklike" onClick={onVendor}>
            {row.vendorName}
          </button>
        </div>
        <div className="cell-sub">{row.clientName}</div>
      </td>
      <td className="c-check">
        <div className="cell-main">{row.checkName}</div>
        {/* The provider, under the check rather than in a column of its
            own. It repeats down the page and rarely varies within a
            vendor, so it does not earn the width — but it is still what
            a reader checks when a cost looks wrong. */}
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
