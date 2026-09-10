/**
 * Step 7 — the 0-100 point ledger.
 *
 * Independent of SCAN, and it can disagree with it. That disagreement is
 * surfaced rather than smoothed over: two scores that differ are telling
 * the analyst something, and the UI says which one binds.
 *
 * Dead rules stay in the ledger with the reason they did not participate.
 * A rule that scores nothing because nobody wired up a provider must never
 * look like a rule that scored nothing because the vendor is clean.
 */

import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

import { Callout, Card, EmptyState, Meter, RuleStateBadge, Tile } from '@/components/ui'
import { DEFAULT_POLICY, applyPolicy, scoreRisk, scoreScan } from '@/scoring'
import type { PageProps } from '@/App'

export default function Risk({ vendor, setPrimary }: PageProps) {
  const navigate = useNavigate()
  const risk = scoreRisk(vendor.checks, vendor.selected)
  const scan = scoreScan(vendor.scan)
  const gate = applyPolicy(scan, DEFAULT_POLICY)

  // The swing used to be the literal `Math.abs(-25 - 50 - 15) + 40`, printed
  // as 130 whatever had actually sat out. Summed from the ledger's own dead
  // lines instead, so the sentence stays true when the catalogue moves.
  const deadSwing = risk.ledger
    .filter((line) => line.state !== 'available')
    .reduce((total, line) => total + Math.abs(line.points), 0)

  useEffect(() => {
    setPrimary(
      <button type="button" className="btn primary" onClick={() => navigate(`/vendor/${vendor.id}/report`)}>
        Build the report →
      </button>,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vendor.id])

  if (Object.keys(vendor.checks).length === 0) {
    return (
      <EmptyState
        title="No checks have run"
        body="The point ledger reads check results. Run the checks first and this fills in."
        action={
          <button type="button" className="btn primary" onClick={() => navigate(`/vendor/${vendor.id}/select`)}>
            Choose what to check
          </button>
        }
      />
    )
  }

  const bandTone =
    risk.band.key === 'approve' ? 'pass' : risk.band.key === 'conditional' ? 'warn' : 'adverse'

  // SCAN and the ledger are independent and can point different ways.
  const disagree =
    scan.isScored && ((scan.passed && risk.score < 60) || (!scan.passed && risk.score >= 80))

  return (
    <div className="stack">
      <div>
        <div className="kicker">Step 7 · Scoring</div>
        <h2 className="page-h">Risk score</h2>
        <p className="page-sub">
          A transparent point ledger running alongside SCAN, starting from a neutral 50. Every rule
          names the check it reads and reports why it did or did not participate.
        </p>
      </div>

      <div className="grid-4">
        <Tile n={risk.score} label="Risk score" note={`Baseline ${risk.baseline}`} tone={bandTone} />
        <Tile n={risk.band.label} label="Band" note={risk.band.note} tone={bandTone} />
        <Tile n={`+${risk.gained}`} label="Points gained" tone="pass" />
        <Tile n={risk.lost} label="Points lost" tone={risk.lost < 0 ? 'adverse' : 'neutral'} />
      </div>

      <Card>
        <div className="stack-sm">
          <div className="row-between">
            <span className="small muted">
              {risk.baseline} baseline {risk.raw >= 0 ? '+' : '−'} {Math.abs(risk.raw)} from{' '}
              {risk.participating} participating rules
            </span>
            <strong className="nums stat-lg">
              {risk.score}
            </strong>
          </div>
          <Meter pct={risk.score} tone={bandTone} />
        </div>
      </Card>

      {risk.dead > 0 && (
        <Callout kind="warn" title={`${risk.dead} of ${risk.ledger.length} rules did not participate`}>
          The ledger is incomplete for this vendor. The rules that did not participate carry{' '}
          {deadSwing} points of potential swing between them, and none of it was applied in either
          direction. A score of {risk.score} here is not the same as a score of {risk.score} from a
          complete ledger.
        </Callout>
      )}

      {disagree && (
        <Callout kind="warn" title="The two models disagree">
          SCAN reports <strong>{gate.verdict}</strong> while the point ledger places this vendor in{' '}
          <strong>{risk.band.label}</strong>. SCAN mirrors the client's workbook and is the binding
          score; the point ledger is a triage signal that ranks vendors by how much attention they
          need. Where they diverge, the divergence is itself worth recording in the decision.
        </Callout>
      )}

      <Card title="The ledger" subtitle="Every rule, whether or not it fired" tight>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th style={{ width: 40 }} />
                <th>Rule</th>
                <th>Reads</th>
                <th>Outcome</th>
                <th className="num">Points</th>
              </tr>
            </thead>
            <tbody>
              {risk.ledger.map((line) => (
                <tr key={line.id} className={line.state !== 'available' ? 'is-dead' : ''}>
                  <td className="mono muted">{line.id}</td>
                  <td>{line.label}</td>
                  {/* <td className="small mono muted">{line.needs.join(', ')}</td> */}
                  <td>
                    {line.state === 'available' ? (
                      <span className={`badge b-${line.applied ? (line.points > 0 ? 'pass' : 'adverse') : 'neutral'}`}>
                        {line.applied ? 'Applied' : 'Not met'}
                      </span>
                    ) : (
                      <RuleStateBadge state={line.state} />
                    )}
                    <div className="small muted">{line.explanation}</div>
                  </td>
                  <td className="num nums">
                    {line.state === 'available' ? (
                      <>
                        <span style={{ opacity: line.applied ? 1 : 0.35 }}>
                          {line.points > 0 ? '+' : ''}
                          {line.points}
                        </span>
                        {line.applied && <strong style={{ marginLeft: 6 }}>✓</strong>}
                      </>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Why the scale starts at 50">
        <p className="small muted">
          With GST and sanctions unconfigured, the rules available in this build total +70 of
          positives against −45 of negatives. A scale starting at zero could never reach its own
          upper bands, and every vendor would read as high-risk for reasons that have nothing to do
          with the vendor. The neutral 50 baseline makes the score reflect what was found rather
          than what has not been built yet.
        </p>
      </Card>
    </div>
  )
}
