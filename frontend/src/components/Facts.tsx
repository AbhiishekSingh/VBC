/**
 * Tier two — the renderable middle of a check result.
 *
 * A check used to offer exactly two things: a one-line string, and twenty
 * kilobytes of provider JSON behind "View response". Somebody who opened a
 * result wanting detail got a wall of `"cinHistory": [{"oldCin": …}]`, which
 * is evidence but is not an answer.
 *
 * Everything here arrives PRE-FORMATTED from the Python parser — `₹7.69 Cr`,
 * `02 Feb 2015`, `Yes`. This file applies alignment, tone and truncation and
 * performs no conversion of its own. Two implementations of Indian number
 * formatting, one per language, is exactly the drift `parity.test.ts` exists
 * to catch for the catalog.
 *
 * The raw panel is untouched and still sits below all of this. Facts are a
 * projection; the payload remains the evidence.
 */

import { useState } from 'react'

import { Callout } from '@/components/ui'
import type {
  CheckFacts,
  FactDocument,
  FactFlag,
  FactTable as FactTableShape,
  FactTone,
} from '@/types/domain'

/** How many rows of a long table are shown before asking. */
const ROW_PREVIEW = 8

const TONE_CLASS: Record<FactTone, string> = {
  neutral: '',
  good: 'f-good',
  warn: 'f-warn',
  bad: 'f-bad',
}

const FLAG_KIND: Record<FactFlag['level'], 'info' | 'warn' | 'adverse'> = {
  info: 'info',
  warn: 'warn',
  bad: 'adverse',
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

/* ---- flags ----------------------------------------------------------- */

/**
 * Problems with the RESPONSE, not with the vendor.
 *
 * These go FIRST, above every number, because each one is a reason not to
 * trust the numbers underneath it. A GSTIN that resolved to a different
 * company still renders a full, healthy, entirely real registration — and
 * the only thing standing between that and a client's report is this
 * paragraph.
 */
function Flags({ flags }: { flags: FactFlag[] }) {
  return (
    <div className="stack-sm fact-flags">
      {flags.map((flag, i) => (
        <Callout key={`${flag.label}-${i}`} kind={FLAG_KIND[flag.level]} title={flag.label}>
          {flag.detail}
        </Callout>
      ))}
    </div>
  )
}

/* ---- table ----------------------------------------------------------- */

export function FactTable({ table }: { table: FactTableShape }) {
  const [all, setAll] = useState(false)

  if (table.rows.length === 0) {
    return (
      <p className="small muted fact-empty">
        {/* Never a bare "no rows". "No charges registered against this
            company" is a finding; "no rows" is a shrug. */}
        {table.emptyNote ?? 'Nothing returned.'}
      </p>
    )
  }

  const rows = all ? table.rows : table.rows.slice(0, ROW_PREVIEW)
  const hidden = table.rows.length - rows.length

  return (
    <div className="fact-table">
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              {table.columns.map((col) => (
                <th key={col.key} className={col.align === 'right' ? 'num' : undefined}>
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {table.columns.map((col) => {
                  const cell = row[col.key]
                  const empty = cell === null || cell === undefined || cell === ''
                  return (
                    <td
                      key={col.key}
                      className={[
                        col.align === 'right' ? 'num' : '',
                        col.format === 'id' ? 'mono' : '',
                        empty ? 'is-empty' : '',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                    >
                      {empty ? '—' : String(cell)}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="fact-table-foot small muted">
        <span>
          Showing {rows.length} of {table.totalRows}
          {/* The distinction matters: a page limit is our doing, a provider
              cap is theirs, and neither is the same as "that is all there
              is". */}
          {table.truncated && rows.length === table.rows.length
            ? ' — the source returned a page, not the whole set'
            : ''}
        </span>
        {hidden > 0 && (
          <button type="button" className="btn sm ghost" onClick={() => setAll(true)}>
            Show {hidden} more
          </button>
        )}
        {all && table.rows.length > ROW_PREVIEW && (
          <button type="button" className="btn sm ghost" onClick={() => setAll(false)}>
            Show fewer
          </button>
        )}
      </div>
    </div>
  )
}

/* ---- documents ------------------------------------------------------- */

function Documents({ documents }: { documents: FactDocument[] }) {
  return (
    <ul className="fact-docs">
      {documents.map((doc, i) => (
        <li key={`${doc.title}-${i}`} className="fact-doc">
          <div className="fact-doc-head">
            <span className="badge b-neutral">{doc.kind.toUpperCase()}</span>
            {doc.href ? (
              <a href={doc.href} target="_blank" rel="noreferrer">
                {doc.title}
              </a>
            ) : (
              <span>{doc.title}</span>
            )}
            {typeof doc.sizeBytes === 'number' && (
              <span className="small muted nums">{formatBytes(doc.sizeBytes)}</span>
            )}
          </div>
          {doc.excerpt && <p className="small muted fact-excerpt">{doc.excerpt}…</p>}
        </li>
      ))}
    </ul>
  )
}

/* ---- the panel ------------------------------------------------------- */

export default function Facts({ facts }: { facts?: CheckFacts }) {
  // Absent on older rows, on anything unavailable, and on every check whose
  // parser is not written yet. The accordion falls back to the status line
  // and the raw panel, exactly as it behaved before this existed.
  if (!facts || facts.shape === 'none') return null

  const { stats, fields, table, documents, flags } = facts

  return (
    <div className="facts">
      {flags && flags.length > 0 && <Flags flags={flags} />}

      {facts.derivedFrom && (
        <p className="small muted fact-note">
          Read from the <strong>{facts.derivedFrom}</strong> response — this check
          made no call of its own, so the evidence sits under that result.
        </p>
      )}

      {facts.shape === 'reference' && facts.note && (
        <p className="small muted fact-note">{facts.note}</p>
      )}

      {stats && stats.length > 0 && (
        <div className="grid-4 fact-stats">
          {stats.map((s) => (
            <div key={s.label} className={`tile t-${toneTile(s.tone)}`}>
              <div className="tile-n nums">{s.value}</div>
              <div className="tile-label">{s.label}</div>
            </div>
          ))}
        </div>
      )}

      {fields && fields.length > 0 && (
        <dl className="io-list fact-fields">
          {fields.map((f) => (
            <div className="io-row" key={f.label}>
              <dt className="io-key">
                {f.label}
                {f.note && <span className="io-from" title={f.note}> ⓘ</span>}
              </dt>
              <dd
                className={[
                  'io-val',
                  f.value === null ? 'is-empty' : '',
                  f.format === 'id' ? 'mono' : '',
                  f.tone ? TONE_CLASS[f.tone] : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
              >
                {/* "not returned", never a blank. A field that renders as
                    nothing lets a partial response read as a complete one. */}
                {f.value ?? 'not returned'}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {table && <FactTable table={table} />}

      {documents && documents.length > 0 && <Documents documents={documents} />}

      {facts.shape !== 'reference' && facts.note && (
        <p className="small muted fact-note">{facts.note}</p>
      )}
    </div>
  )
}

function toneTile(tone?: FactTone): string {
  if (tone === 'good') return 'pass'
  if (tone === 'warn') return 'warn'
  if (tone === 'bad') return 'adverse'
  return 'neutral'
}
