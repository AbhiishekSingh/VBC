/**
 * Shared presentational pieces.
 *
 * The status vocabulary lives here and nowhere else. Every screen renders
 * a check outcome through `StatusBadge`, so "not configured" can never
 * accidentally be styled like "pass" on one page and not another — which
 * in this product would be a correctness bug, not a cosmetic one.
 */

import type { ReactNode } from 'react'
import type { CheckStatus, Rating, RuleState, SourceMode } from '@/types/domain'

/* ---- status vocabulary ----------------------------------------------- */

type Tone = 'pass' | 'warn' | 'adverse' | 'unchecked' | 'neutral' | 'accent'

const STATUS_TONE: Record<CheckStatus, Tone> = {
  pass: 'pass',
  warn: 'warn',
  fail: 'adverse',
  skip: 'unchecked',
  unavailable: 'unchecked',
  not_configured: 'unchecked',
  skipped_missing_input: 'unchecked',
}

const STATUS_LABEL: Record<CheckStatus, string> = {
  pass: 'Pass',
  warn: 'Attention',
  fail: 'Adverse',
  skip: 'Not applicable',
  unavailable: 'Unavailable',
  not_configured: 'Not configured',
  skipped_missing_input: 'Skipped — input missing',
}

/** Why a non-result happened. Shown wherever there is room for it. */
export const STATUS_EXPLANATION: Record<CheckStatus, string> = {
  pass: 'The check ran and found nothing adverse.',
  warn: 'The check ran and found something worth a look.',
  fail: 'The check ran and found an adverse finding.',
  skip: 'This check does not apply to this vendor.',
  unavailable: 'The provider could not be reached after retries. This is not a pass.',
  not_configured: 'No provider is wired up for this check. Nothing was examined.',
  skipped_missing_input: 'A required input was left blank, so the call was never made.',
}

export function StatusBadge({ status }: { status: CheckStatus }) {
  return (
    <span className={`badge b-${STATUS_TONE[status]}`} title={STATUS_EXPLANATION[status]}>
      {STATUS_LABEL[status]}
    </span>
  )
}

/**
 * A rating mark.
 *
 * This used to be a 7px circle whose ONLY differentiator was hue — green,
 * amber or red — and the `null` case rendered a grey circle with no
 * accessible name at all. In a product whose whole premise is that "not
 * applicable" must never read as "clean", that was the wrong place to lean
 * on colour alone. Each rating now carries a glyph as well as a hue, and
 * every state has a name.
 */
const RATING_GLYPH: Record<Rating, string> = { G: '✓', Y: '!', R: '✕' }
const RATING_LABEL: Record<Rating, string> = { G: 'Green', Y: 'Yellow', R: 'Red' }

export function RatingDot({ rating }: { rating: Rating | null }) {
  if (!rating) {
    return (
      <span className="dot" role="img" aria-label="Not applicable" title="Not applicable">
        –
      </span>
    )
  }
  const label = RATING_LABEL[rating]
  return (
    <span className={`dot d-${rating}`} role="img" aria-label={label} title={label}>
      {RATING_GLYPH[rating]}
    </span>
  )
}

export function SourceChip({ source, ran }: { source: SourceMode; ran?: boolean }) {
  if (source === 'AUTO' && ran === false) {
    return <span className="chip c-hook" title="This check was not run for this vendor">Not run</span>
  }
  const cls = { AUTO: 'c-auto', HUMAN: 'c-human', HOOK: 'c-hook' }[source]
  const title = {
    AUTO: 'Filled automatically by a configured check',
    HUMAN: 'Recorded by an analyst or from field work',
    HOOK: 'Would be automated by a check that has no provider yet',
  }[source]
  return <span className={`chip ${cls}`} title={title}>{source}</span>
}

export function RuleStateBadge({ state }: { state: RuleState }) {
  if (state === 'available') return null
  const label = state === 'not_configured' ? 'Not configured' : 'Not selected'
  const title =
    state === 'not_configured'
      ? 'No provider is wired up — this rule cannot participate'
      : 'The analyst did not select the check this rule reads'
  return <span className="badge b-unchecked" title={title}>{label}</span>
}

/* ---- layout primitives ----------------------------------------------- */

export function Card({
  title,
  subtitle,
  aside,
  children,
  tight,
}: {
  title?: ReactNode
  subtitle?: ReactNode
  aside?: ReactNode
  children: ReactNode
  tight?: boolean
}) {
  return (
    <section className="card">
      {(title || aside) && (
        <header className="card-head">
          <div>
            {title && <h3 className="section-h">{title}</h3>}
            {subtitle && <p className="small muted">{subtitle}</p>}
          </div>
          {aside}
        </header>
      )}
      <div className={`card-body${tight ? ' tight' : ''}`}>{children}</div>
    </section>
  )
}

export function Tile({
  n,
  label,
  note,
  tone = 'neutral',
}: {
  n: ReactNode
  label: string
  note?: string
  tone?: Tone
}) {
  return (
    <div className={`tile t-${tone}`}>
      <div className="tile-n nums">{n}</div>
      <div className="tile-label">{label}</div>
      {note && <div className="tile-note">{note}</div>}
    </div>
  )
}

export function Callout({
  kind = 'info',
  title,
  children,
}: {
  kind?: 'info' | 'warn' | 'adverse' | 'pass'
  title?: string
  children: ReactNode
}) {
  return (
    <div className={`callout k-${kind}`}>
      {title && <div className="callout-h">{title}</div>}
      <div className="muted">{children}</div>
    </div>
  )
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string
  body: string
  action?: ReactNode
}) {
  return (
    <div className="empty">
      <h3 className="empty-h">{title}</h3>
      <p className="empty-p">{body}</p>
      {action}
    </div>
  )
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: ReactNode
  children: ReactNode
}) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  )
}

export function Meter({ pct, tone = 'accent' }: { pct: number; tone?: Tone }) {
  const colour = {
    pass: 'var(--pass)',
    warn: 'var(--warn)',
    adverse: 'var(--adverse)',
    unchecked: 'var(--unchecked)',
    neutral: 'var(--ink-4)',
    accent: 'var(--accent)',
  }[tone]
  return (
    <div className="meter" role="presentation">
      <div
        className="meter-fill"
        style={{ width: `${Math.max(0, Math.min(100, pct))}%`, background: colour }}
      />
    </div>
  )
}

/* ---- loading ---------------------------------------------------------
   There was not one spinner or skeleton in the app. Nine screens showed a
   bare "Loading…" paragraph that REPLACED the whole page, so the layout
   jumped when the data landed, and two screens (Audit, Costs) showed an
   empty table — an audit trail reading "0 entries" while it is still
   loading is misleading, not merely plain.

   These are presentational only: they render while a caller's existing
   loading flag is true. No fetch behaviour changes.
   --------------------------------------------------------------------- */

export function Skeleton({
  w = '100%',
  h = 12,
  radius,
}: {
  w?: number | string
  h?: number | string
  radius?: number | string
}) {
  return (
    <span
      className="skeleton"
      aria-hidden="true"
      style={{ width: w, height: h, borderRadius: radius }}
    />
  )
}

/** Placeholder rows that match the real table's shape, so nothing shifts. */
export function SkeletonTable({
  rows = 6,
  cols = 4,
  widths,
}: {
  rows?: number
  cols?: number
  widths?: (number | string)[]
}) {
  return (
    <tbody aria-hidden="true">
      {Array.from({ length: rows }, (_, r) => (
        <tr key={r}>
          {Array.from({ length: cols }, (_, c) => (
            <td key={c}>
              <Skeleton w={widths?.[c] ?? (c === 0 ? '70%' : '45%')} />
            </td>
          ))}
        </tr>
      ))}
    </tbody>
  )
}

/** Placeholder for the four-tile row that opens seven of the pages. */
export function SkeletonTiles({ n = 4 }: { n?: number }) {
  return (
    <div className="grid-4" aria-hidden="true">
      {Array.from({ length: n }, (_, i) => (
        <div className="tile" key={i}>
          <Skeleton w="55%" h={26} />
          <div style={{ marginTop: 'var(--space-3)' }}>
            <Skeleton w="75%" h={10} />
          </div>
        </div>
      ))}
    </div>
  )
}

export function Spinner({ lg }: { lg?: boolean }) {
  return <span className={`spinner${lg ? ' lg' : ''}`} aria-hidden="true" />
}

/** A polite, centred block for a whole-panel load. */
export function LoadingBlock({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="empty-inline" role="status" aria-live="polite">
      <Spinner lg />
      <span className="small muted">{label}</span>
    </div>
  )
}

/** An indeterminate bar, for an operation with no progress to report. */
export function ProgressBar({ label }: { label?: string }) {
  return (
    <div role="status" aria-live="polite">
      <div className="progress" />
      {label && (
        <div className="small muted" style={{ marginTop: 'var(--space-2)' }}>
          {label}
        </div>
      )}
    </div>
  )
}

/**
 * A checkbox with a third, indeterminate state — "some of this group".
 *
 * `indeterminate` is a DOM property, not an attribute, so React cannot set
 * it through JSX; it has to be written on the node.
 */
export function TriCheckbox({
  checked,
  indeterminate,
  onChange,
  label,
  disabled,
}: {
  checked: boolean
  indeterminate: boolean
  onChange: () => void
  label: string
  disabled?: boolean
}) {
  return (
    <input
      type="checkbox"
      checked={checked}
      disabled={disabled}
      aria-label={label}
      title={label}
      onChange={onChange}
      ref={(el) => {
        if (el) el.indeterminate = !checked && indeterminate
      }}
    />
  )
}

/* ---- formatting ------------------------------------------------------ */

export const rupees = (paisa: number): string => {
  const value = paisa / 100
  return `₹${Number.isInteger(value) ? value.toLocaleString('en-IN') : value.toFixed(2)}`
}

/**
 * Colour for a SCAN result.
 *
 * Takes the GATE, not just the percentage. A vendor held for insufficient
 * coverage must never render in the same green as a clean pass — that is
 * precisely the misreading this product exists to prevent. Azahan reaches
 * 60.0% on six of eighteen parameters; the number is real, but it is not a
 * pass, and the colour has to say so.
 */
export const toneForScan = (pct: number, gated = false): Tone => {
  if (gated) return 'warn'
  return pct >= 60 ? 'pass' : pct >= 50 ? 'warn' : 'adverse'
}
