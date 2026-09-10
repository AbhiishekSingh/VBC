/**
 * Step 8 — the verification report.
 *
 * NO LLM. Fixed sentence templates selected by branching on check status
 * and filled from findings. The same inputs always produce the same text,
 * nothing is invented, and any sentence can be traced to the finding that
 * produced it.
 *
 * Section 6 (coverage) is MANDATORY and never omitted. With nine checks
 * unconfigured, a report that quietly leaves out sanctions screening
 * implies a screening that never happened.
 */

import { useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'

import { CHECKS, MANUAL_TEMPLATES } from '@/catalog/generated'
import { Callout, EmptyState } from '@/components/ui'
import { DEFAULT_POLICY, applyPolicy, scoreRisk, scoreScan, scoreSurveillance } from '@/scoring'
import { downloadBlob } from '@/lib/download'
import type { PageProps } from '@/App'
import type { Vendor } from '@/types/domain'

interface Section {
  heading: string
  paragraphs: string[]
}

interface Flag {
  level: 'high' | 'medium' | 'low'
  text: string
}

export function buildReport(vendor: Vendor) {
  const checks = vendor.checks
  const selected = new Set(vendor.selected)
  const ran = (id: string) => selected.has(id) && !!checks[id]
  const get = (id: string) => checks[id] ?? { status: 'skip' as const, value: '—', detail: 'not run' }
  const passed = (id: string) => ran(id) && get(id).status === 'pass'

  const scan = scoreScan(vendor.scan)
  const gate = applyPolicy(scan, DEFAULT_POLICY)
  const risk = scoreRisk(checks, vendor.selected)
  const sv = scoreSurveillance(vendor.surveillance, vendor.surveillanceDone)

  const sections: Section[] = []

  /* 1 · identity and constitution */
  // Optional fields are OMITTED, never rendered as an empty slot. This
  // used to read "submitted on 2026-08-30 for ." when no material was
  // entered — a punctuation artefact in a document a client reads.
  const forWhat = vendor.material.trim()
    ? ` for ${vendor.material.trim().toLowerCase()}`
    : ''
  const onBehalf = vendor.clientName ? ` on behalf of ${vendor.clientName}` : ''
  let identity =
    `${vendor.legalName} was submitted on ${vendor.submitted}${onBehalf}${forWhat}. `
  if (passed('master')) {
    identity += `MCA records confirm an active registered entity — ${get('master').detail}. `
  } else if (ran('master')) {
    identity += `MCA screening did not return an active company record: ${get('master').detail}. This limits what can be independently corroborated about the entity's standing. `
  } else {
    identity += `Company registry screening was not run for this vendor, so incorporation status is unverified. `
  }
  if (passed('dirs')) identity += `${get('dirs').detail}. `
  sections.push({ heading: 'Identity and constitution', paragraphs: [identity] })

  /* 2 · corporate standing */
  const standing: string[] = []
  if (ran('charges')) {
    standing.push(
      get('charges').status === 'pass'
        ? `No open charges are recorded against the company.`
        : `A charge remains open: ${get('charges').value} — ${get('charges').detail} An unsatisfied charge means a lender still holds security over company assets and should be stated in any onboarding note.`,
    )
  }
  if (ran('filings')) standing.push(`Statutory filings: ${get('filings').detail}.`)
  if (ran('fin')) {
    standing.push(
      `Filed financials (${get('fin').value}) come from the company's own AOC-4 return: ${get('fin').detail}. These are government-filed figures, not estimates.`,
    )
  }
  if (standing.length) {
    sections.push({ heading: 'Corporate standing and financials', paragraphs: [standing.join(' ')] })
  }

  /* 3 · web presence */
  const web: string[] = []
  if (ran('whois')) {
    web.push(
      passed('whois')
        ? `the domain checks out (${get('whois').value.toLowerCase()})`
        : `domain ownership raised a point for attention — ${get('whois').detail}`,
    )
  }
  if (ran('reput')) web.push(`the domain trust score is ${get('reput').value.replace(/^Trust score /, '')}`)
  if (ran('ssl')) web.push(passed('ssl') ? 'SSL is valid' : 'the SSL certificate is not from a trusted authority')
  if (ran('cdx')) web.push(`archive history shows ${get('cdx').value.toLowerCase()}`)
  if (ran('rwhois')) web.push(`the registrant's wider portfolio shows ${get('rwhois').value.toLowerCase()}`)
  if (web.length) {
    let text = `Open-source screening: ${web.join('; ')}. `
    if (ran('cdx') && get('cdx').status !== 'pass') text += `${get('cdx').detail}. `
    if (ran('rwhois')) {
      text += `A varied portfolio under one registrant is consistent with an agency or developer managing client domains; near-identical variations of one brand would instead suggest typosquatting.`
    }
    sections.push({ heading: 'Web presence and domain ownership', paragraphs: [text] })
  }

  /* 4 · internal risk */
  const internal: string[] = []
  if (ran('dup') && get('dup').status !== 'pass') internal.push(`a possible duplicate registration (${get('dup').detail})`)
  if (ran('rp') && get('rp').status !== 'pass') internal.push(`related-party exposure (${get('rp').detail})`)
  if (ran('conflict') && get('conflict').status !== 'pass') internal.push(`an employee conflict of interest (${get('conflict').detail})`)
  sections.push({
    heading: 'Internal risk',
    paragraphs: [
      internal.length
        ? `Checks against the vendor master surfaced ${internal.join(', and ')}. Where this reflects a genuine business relationship it should be recorded as a disclosure rather than treated as disqualifying.`
        : `Checks against the vendor master found no duplicate registration, related-party overlap or employee conflict of interest.`,
    ],
  })

  /* 5 · surveillance */
  sections.push({
    heading: 'Site surveillance',
    paragraphs: [
      sv.done
        ? `Surveillance returned ${sv.verdict}, with ${sv.positives} positives across ${sv.applicable} assessed parameters (${sv.pct}%). ` +
          (sv.gateFailed
            ? `Existence of premises could not be confirmed, which forces the overall field result Negative irrespective of the percentage achieved.`
            : `The 60% field threshold was ${sv.passed ? 'met' : 'not met'}.`)
        : `Site surveillance has not been conducted. SCAN parameter A2 therefore remains Not Applicable and drops out of the weighted calculation, materially reducing coverage of the Assessment pillar — the heaviest at 0.60.`,
    ],
  })

  /* 6 · coverage — MANDATORY, never omitted */
  const notSelected = CHECKS.filter((c) => !c.admin && c.state === 'active' && !selected.has(c.id))
  const hooks = CHECKS.filter((c) => c.state === 'not_configured')
  const skipped = Object.values(checks).filter((c) => c.status === 'skipped_missing_input')
  const coverage =
    `${Object.keys(checks).length} checks were run for this vendor. ` +
    (skipped.length
      ? `${skipped.length} selected ${skipped.length === 1 ? 'check was' : 'checks were'} skipped because a required input was not provided: ${skipped.map((s) => CHECKS.find((c) => c.id === s.checkId)?.name).join(', ')}. `
      : '') +
    (notSelected.length
      ? `${notSelected.length} available checks were not selected: ${notSelected.map((c) => c.name).join(', ')}. `
      : '') +
    (hooks.length
      ? `A further ${hooks.length} checks are not configured on this platform at all: ${hooks.map((c) => c.name).join(', ')}. `
      : '') +
    `Nothing in this report should be read as clearance on any of the above — they were not examined.`
  sections.push({ heading: 'Coverage — what was not checked', paragraphs: [coverage] })

  /* 7 · scoring */
  sections.push({
    heading: 'Scoring',
    paragraphs: [
      `Under the SCAN framework, ${scan.applicable} of ${scan.total} parameters were applicable, producing a weighted score of ${scan.weighted.toFixed(2)} against a best achievable of ${scan.best.toFixed(2)}. The 60% tolerance is ${scan.tolerance60.toFixed(2)}, giving ${scan.pct.toFixed(1)}% achievement. ` +
        (gate.gated
          ? `Under coverage policy ${gate.policyVersion} this does not support a positive recommendation: ${gate.reasons.join(' ')} `
          : '') +
        `The separate 0–100 point model scores ${risk.score}, placing the vendor in the ${risk.band.label} band — ${risk.band.note} ${risk.dead} of its ${risk.ledger.length} rules have no configured data source and did not participate.`,
    ],
  })

  /* 8 · analyst-recorded — kept structurally separate */
  if (vendor.manual.length) {
    sections.push({
      heading: 'Analyst-recorded information (stated, not verified)',
      paragraphs: [
        `The following was recorded by an analyst and has not been independently confirmed by any source. It is presented separately from the findings above for that reason.`,
        ...vendor.manual.map((entry) => {
          const tpl = MANUAL_TEMPLATES.find((t) => t.id === entry.templateId)
          const mapping = tpl?.mapsTo ? (tpl.mapWhen as Record<string, string>)[entry.value] : null
          return (
            `${entry.key}: ${entry.value}. Recorded by ${entry.enteredBy} on ${entry.enteredAt}.` +
            (entry.note ? ` ${entry.note}` : '') +
            (mapping ? ` This entry sets SCAN parameter ${tpl!.mapsTo} to ${mapping}.` : '')
          )
        }),
      ],
    })
  }

  /* flags */
  const flags: Flag[] = []
  for (const [id, result] of Object.entries(checks)) {
    if (!selected.has(id) || result.status !== 'fail') continue
    flags.push({ level: 'high', text: `${CHECKS.find((c) => c.id === id)?.name}: ${result.value} — ${result.detail}` })
  }
  for (const [id, result] of Object.entries(checks)) {
    if (!selected.has(id) || result.status !== 'warn') continue
    flags.push({ level: 'medium', text: `${CHECKS.find((c) => c.id === id)?.name}: ${result.value} — ${result.detail}` })
  }
  if (!sv.done) {
    flags.push({ level: 'medium', text: 'Site surveillance not conducted — Assessment pillar (weight 0.60) largely unevaluated' })
  }
  if (gate.gated) {
    flags.push({ level: 'high', text: `Verdict held for coverage under policy ${gate.policyVersion} — ${gate.reasons.length} condition(s) unmet` })
  }
  if (hooks.length) {
    flags.push({ level: 'low', text: `${hooks.length} checks not configured on this platform, including GST and sanctions screening` })
  }

  return { sections, flags, scan, gate, risk, sv, recommendation: gate.verdict }
}

const STATUS_LABEL: Record<string, string> = {
  pass: 'Passed',
  warn: 'Attention',
  fail: 'Adverse',
  skip: 'N/A',
  unavailable: 'Not examined',
  not_configured: 'No provider',
  skipped_missing_input: 'Not run',
}

const STATUS_TONE: Record<string, string> = {
  pass: 'low',
  warn: 'medium',
  fail: 'high',
  skip: 'none',
  unavailable: 'none',
  not_configured: 'none',
  skipped_missing_input: 'none',
}

export default function Report({ vendor, setPrimary }: PageProps) {
  const navigate = useNavigate()
  const report = useMemo(() => buildReport(vendor), [vendor])

  const generatedAt = useMemo(
    () =>
      new Date().toLocaleString(undefined, {
        day: '2-digit', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
      }),
    [],
  )

  const verdictTone = report.gate.gated
    ? 'held'
    : report.scan.passed
      ? 'positive'
      : 'negative'

  const examined = Object.values(vendor.checks).filter((c) =>
    ['pass', 'warn', 'fail'].includes(c.status),
  ).length

  /** Every check that ran, in catalogue order, for the evidence index. */
  const evidence = useMemo(
    () =>
      CHECKS.filter((c) => vendor.checks[c.id]).map((c) => {
        const result = vendor.checks[c.id]
        return {
          id: c.id,
          name: c.name,
          provider: c.provider,
          statusLabel: STATUS_LABEL[result.status] ?? result.status,
          tone: STATUS_TONE[result.status] ?? 'none',
          value: result.value || result.detail || '—',
        }
      }),
    [vendor.checks],
  )

  const exportText = () => {
    const lines = [
      `VERIFICATION REPORT — ${vendor.legalName}`,
      `Vendor #${vendor.id} · submitted ${vendor.submitted}`,
      // The header on screen renders local time and the export used to
      // write UTC, so one report carried two generation times up to twelve
      // hours apart. One clock, one value.
      `Generated ${generatedAt}`,
      '',
      'This report is assembled from fixed templates selected by check outcome.',
      'It contains no generated prose. The recommendation is advisory; the binding',
      'decision is recorded by a named analyst.',
      '',
      ...report.sections.flatMap((s) => [
        s.heading.toUpperCase(),
        '─'.repeat(s.heading.length),
        ...s.paragraphs,
        '',
      ]),
      'RISK FLAGS',
      '──────────',
      ...report.flags.map((f) => `[${f.level.toUpperCase()}] ${f.text}`),
      '',
      `RECOMMENDATION: ${report.recommendation}`,
      `Coverage: ${report.scan.coverageNote}`,
      'Recommendation only — not a binding decision.',
    ]
    downloadBlob(lines.join('\n'), `VBC-${vendor.id}-report.txt`, 'text/plain')
  }

  useEffect(() => {
    setPrimary(
      <>
        <button type="button" className="btn" onClick={exportText}>
          Export TXT
        </button>
        {/* The browser's own print-to-PDF. One renderer, so the PDF cannot
            drift from what is on screen. */}
        <button type="button" className="btn" onClick={() => window.print()}>
          Download PDF
        </button>
        <button type="button" className="btn primary" onClick={() => navigate(`/vendor/${vendor.id}/decision`)}>
          Record the decision →
        </button>
      </>,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vendor])

  if (Object.keys(vendor.checks).length === 0) {
    return (
      <EmptyState
        title="Nothing to report on yet"
        body="The report assembles from check findings. Run the checks and it builds itself."
        action={
          <button type="button" className="btn primary" onClick={() => navigate(`/vendor/${vendor.id}/select`)}>
            Choose what to check
          </button>
        }
      />
    )
  }

  return (
    <div className="stack">
      {/* Screen-only chrome. The printed document starts at .doc below. */}
      <div className="no-print">
        <div className="kicker">Step 8 · Output</div>
        <h2 className="page-h">Verification report</h2>
        <p className="page-sub">
          Assembled from fixed templates selected by check outcome. No language model is involved
          anywhere — the same findings always produce the same words.
        </p>
      </div>

      <div className="no-print">
        <Callout kind="info" title="Recommendation only">
          This document recommends; it does not decide. The binding approve or reject is recorded by
          a named analyst on the next screen, with reasons.
        </Callout>
      </div>

      {/*
        THE DOCUMENT.
        Everything below prints; everything above does not. Save as PDF from
        the browser produces this and nothing else — no sidebar, no buttons,
        no navigation. A separate PDF generator would be a second renderer to
        keep in step with this one, and the two would drift.
      */}
      <article className="doc">
        <header className="doc-head">
          <div className="doc-brand">
            <span className="doc-mark">VBC</span>
            <div>
              <div className="doc-org">Q1SSL · Vendor Intelligence</div>
              <div className="doc-kind">Vendor verification report</div>
            </div>
          </div>
          <div className="doc-ref">
            <div className="doc-ref-row">
              <span>Report ref</span>
              <b>VBC-{vendor.id}</b>
            </div>
            <div className="doc-ref-row">
              <span>Generated</span>
              <b>{generatedAt}</b>
            </div>
          </div>
        </header>

        <h1 className="doc-title">{vendor.legalName}</h1>
        <dl className="doc-facts">
          <div><dt>Client</dt><dd>{vendor.clientName || '—'}</dd></div>
          <div><dt>Vendor ref</dt><dd className="mono">#{vendor.id}</dd></div>
          <div><dt>CIN</dt><dd className="mono">{vendor.cin ?? 'Not provided'}</dd></div>
          <div><dt>GST</dt><dd className="mono">{vendor.gst ?? 'Not provided'}</dd></div>
          <div><dt>PAN</dt><dd className="mono">{vendor.pan ?? 'Not provided'}</dd></div>
          <div><dt>Domain</dt><dd className="mono">{vendor.domain ?? 'Not provided'}</dd></div>
          <div><dt>Submitted</dt><dd>{vendor.submitted}</dd></div>
          <div><dt>Material</dt><dd>{vendor.material || 'Not recorded'}</dd></div>
        </dl>

        {/* The verdict, once, at the top — the first thing a reader wants. */}
        <section className={`doc-verdict v-${verdictTone}`}>
          <div className="doc-verdict-main">
            <div className="doc-verdict-label">Recommendation</div>
            <div className="doc-verdict-value">{report.recommendation}</div>
            <p className="doc-verdict-note">{report.scan.coverageNote}</p>
          </div>
          <div className="doc-verdict-figures">
            <div>
              <div className="doc-fig">{report.scan.pct.toFixed(1)}%</div>
              <div className="doc-fig-label">
                SCAN · {report.scan.applicable}/{report.scan.total} params
              </div>
            </div>
            <div>
              <div className="doc-fig">{report.risk.score}</div>
              <div className="doc-fig-label">Risk · {report.risk.band.label}</div>
            </div>
            <div>
              <div className="doc-fig">{examined}</div>
              <div className="doc-fig-label">Checks examined</div>
            </div>
          </div>
        </section>

        <div className="doc-banner">
          Recommendation only. This document does not decide. The binding approve or reject is
          recorded separately by a named analyst, with reasons.
        </div>

        {report.sections.map((section, i) => (
          <section className="doc-section" key={section.heading}>
            <h2 className="doc-h2">
              <span className="doc-num">{i + 1}</span>
              {section.heading}
            </h2>
            {section.paragraphs.map((p, j) => (
              <p className="doc-p" key={j}>
                {p}
              </p>
            ))}
          </section>
        ))}

        <section className="doc-section">
          <h2 className="doc-h2">
            <span className="doc-num">{report.sections.length + 1}</span>
            Risk flags
          </h2>
          {report.flags.length === 0 ? (
            <p className="doc-p">
              No adverse findings and no coverage gaps were raised by the checks that were run.
            </p>
          ) : (
            <table className="doc-table">
              <thead>
                <tr>
                  <th style={{ width: 82 }}>Level</th>
                  <th>Finding</th>
                </tr>
              </thead>
              <tbody>
                {report.flags.map((flag, i) => (
                  <tr key={i}>
                    <td>
                      <span className={`doc-flag f-${flag.level}`}>{flag.level}</span>
                    </td>
                    <td>{flag.text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        {/* Evidence index: which source produced which finding, and when. */}
        <section className="doc-section">
          <h2 className="doc-h2">
            <span className="doc-num">{report.sections.length + 2}</span>
            Evidence index
          </h2>
          <p className="doc-p">
            Every check that ran, with the outcome recorded against it. Rows marked
            <em> not examined</em> produced no evidence and must not be read as clean.
          </p>
          <table className="doc-table">
            <thead>
              <tr>
                <th>Check</th>
                <th>Source</th>
                <th style={{ width: 96 }}>Outcome</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {evidence.map((row) => (
                <tr key={row.id}>
                  <td>{row.name}</td>
                  <td className="mono small">{row.provider}</td>
                  <td>
                    <span className={`doc-flag f-${row.tone}`}>{row.statusLabel}</span>
                  </td>
                  <td>{row.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <footer className="doc-foot">
          <p>
            The system automates the data layer. The analyst retains the decision layer. This report
            gathers, scores, drafts and flags; it never issues a binding approve or reject.
          </p>
          {/* No page number here. CSS cannot count pages in Chrome, so a
              hardcoded "page 1" would print on every page and be a lie in a
              document whose whole point is not overstating things. Enable
              "Headers and footers" in the print dialog for real numbering. */}
          <p className="doc-foot-ref">
            VBC-{vendor.id} · {vendor.legalName} · generated {generatedAt}
          </p>
        </footer>
      </article>
    </div>
  )
}