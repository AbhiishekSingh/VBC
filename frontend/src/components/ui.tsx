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

export function RatingDot({ rating }: { rating: Rating | null }) {
  if (!rating) return <span className="dot" title="Not applicable" />
  const label = { G: 'Green', Y: 'Yellow', R: 'Red' }[rating]
  return <span className={`dot d-${rating}`} title={label} aria-label={label} />
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
