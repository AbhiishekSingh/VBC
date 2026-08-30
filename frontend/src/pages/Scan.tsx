/**
 * Step 6 — SCAN scoring.
 *
 * All 18 parameters, live-editable, with the weighted maths recalculating
 * as you go. The recalculation is done locally (see src/scoring) purely for
 * responsiveness — the server is the authority and recomputes on save. The
 * parity suite proves the two agree.
 *
 * The coverage note beside the verdict is not decoration. Because N/A
 * parameters leave both sides of the fraction, 60% on six parameters and
 * 60% on eighteen render identically without it — and they mean very
 * different things.
 */

import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '@/api'
import { CHECKS, PILLARS, SCAN_PARAMETERS } from '@/catalog/generated'
import { Callout, Card, Meter, RatingDot, SourceChip, Tile, toneForScan } from '@/components/ui'
import { DEFAULT_POLICY, applyPolicy, scoreScan } from '@/scoring'
import type { PageProps } from '@/App'
import type { PillarKey, Rating, SourceMode } from '@/types/domain'

export default function Scan({ vendor, setVendor, setPrimary }: PageProps) {
  const navigate = useNavigate()

  const score = scoreScan(vendor.scan)
  const gate = applyPolicy(score, DEFAULT_POLICY)

  useEffect(() => {
    setPrimary(
      <button type="button" className="btn primary" onClick={() => navigate(`/vendor/${vendor.id}/risk`)}>
        Risk score →
      </button>,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vendor.id])

  const setRating = async (paramId: string, value: string | null) => {
    setVendor(await api.setScanRating(vendor.id, paramId, value))
  }

  return (
    <div className="stack">
      <div>
        <div className="kicker">Step 6 · Scoring</div>
        <h2 className="page-h">SCAN scoring</h2>
        <p className="page-sub">
          Eighteen parameters across four weighted pillars. Two Yellows make one Green; anything
          Not Applicable leaves both sides of the calculation, so the bar moves with coverage.
        </p>
      </div>

      <div className="grid-4">
        <Tile
          n={`${score.weighted.toFixed(2)} / ${score.best.toFixed(2)}`}
          label="Weighted / best achievable"
          tone="accent"
        />
        <Tile
          n={`${score.pct.toFixed(1)}%`}
          label="Achievement"
          note={
            gate.gated
              ? 'Threshold met, but held for coverage'
              : `60% tolerance is ${score.tolerance60.toFixed(2)}`
          }
          tone={toneForScan(score.pct, gate.gated)}
        />
        <Tile
          n={`${score.applicable}/${score.total}`}
          label="Parameters applicable"
          note="The rest are N/A and excluded"
        />
        <Tile
          n={score.pillars.A.applicable + '/4'}
          label="Assessment evaluated"
          note="Weight 0.60 — the heaviest pillar"
          tone={score.pillars.A.applicable >= 2 ? 'pass' : 'warn'}
        />
      </div>

      <Card>
        <div className="stack-sm">
          <div className="row-between">
            <div>
              <div className="kicker">Verdict</div>
              <h3 style={{ fontSize: 'var(--step-2)' }}>{gate.verdict}</h3>
            </div>
            <span
              className={`badge b-${
                gate.gated ? 'warn' : score.passed ? 'pass' : score.isScored ? 'adverse' : 'unchecked'
              }`}
            >
              {score.coverageNote}
            </span>
          </div>
          <Meter pct={score.pct} tone={toneForScan(score.pct, gate.gated)} />

          {gate.gated && (
            <Callout kind="warn" title="Held for coverage, not rejected">
              This vendor reached the 60% threshold, but on evidence too thin to support a positive
              recommendation. The score itself is unchanged and shown above; what is withheld is the
              claim.
              <ul style={{ margin: '8px 0 0', paddingLeft: 18 }}>
                {gate.reasons.map((r) => (
                  <li key={r} className="small">
                    {r}
                  </li>
                ))}
              </ul>
              <p className="small" style={{ marginTop: 8 }}>
                Coverage policy <strong>{gate.policyVersion}</strong>. Scores produced under
                different policy versions are not directly comparable.
              </p>
            </Callout>
          )}
        </div>
      </Card>

      <div className="grid-4">
        {PILLARS.map((pillar) => {
          const bucket = score.pillars[pillar.key as PillarKey]
          return (
            <div key={pillar.key} className="tile">
              <div className="row-between">
                <strong>{pillar.name}</strong>
                <span className="chip">w {pillar.weight}</span>
              </div>
              <div className="small muted">{pillar.subtitle}</div>
              <div className="nums" style={{ marginTop: 8, fontSize: 'var(--step-2)', fontWeight: 620 }}>
                {bucket.weighted.toFixed(2)} / {bucket.max.toFixed(2)}
              </div>
              <div className="small muted">
                {bucket.applicable} applicable · {bucket.G}G {bucket.Y}Y {bucket.R}R ·{' '}
                {bucket.positives} positive
              </div>
            </div>
          )
        })}
      </div>

      {PILLARS.map((pillar) => {
        const params = SCAN_PARAMETERS.filter((p) => p.pillar === pillar.key)
        return (
          <Card
            key={pillar.key}
            title={`${pillar.key} · ${pillar.name}`}
            subtitle={`${pillar.subtitle} · weight ${pillar.weight}`}
            tight
          >
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th style={{ width: 40 }} />
                    <th>Parameter</th>
                    <th style={{ width: 100 }}>Source</th>
                    <th>Value</th>
                    <th style={{ width: 60 }}>Rating</th>
                  </tr>
                </thead>
                <tbody>
                  {params.map((param) => {
                    const value = vendor.scan[param.id] ?? ''
                    const rating =
                      (param.options.find((o) => o.value === value)?.rating as Rating | undefined) ??
                      null
                    const feedingCheck = param.fedBy ? CHECKS.find((c) => c.id === param.fedBy) : null
                    const checkRan = param.fedBy ? !!vendor.checks[param.fedBy] : undefined
                    const isHook = feedingCheck?.state === 'not_configured'

                    return (
                      <tr key={param.id} className={value ? '' : 'is-dead'}>
                        <td className="mono muted">{param.id}</td>
                        <td>
                          <div>{param.label}</div>
                          <div className="small muted">{param.feed}</div>
                        </td>
                        <td>
                          <SourceChip
                            source={(isHook ? 'HOOK' : param.source) as SourceMode}
                            ran={param.source === 'AUTO' && !isHook ? checkRan : undefined}
                          />
                        </td>
                        <td>
                          <select
                            className="select"
                            value={value}
                            onChange={(e) => setRating(param.id, e.target.value || null)}
                          >
                            <option value="">Not applicable</option>
                            {param.options.map((o) => (
                              <option key={o.value} value={o.value}>
                                {o.value}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td>
                          <RatingDot rating={rating} />
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        )
      })}

      <Card title="How this is calculated">
        <div className="stack-sm small muted">
          <p>
            <strong>positives</strong> = Green + floor(Yellow ÷ 2), per pillar. An odd Yellow does
            not count.
          </p>
          <p>
            <strong>weighted</strong> = Σ (positives × pillar weight) ={' '}
            <span className="nums">{score.weighted.toFixed(2)}</span>
          </p>
          <p>
            <strong>best achievable</strong> = Σ (applicable × pillar weight) ={' '}
            <span className="nums">{score.best.toFixed(2)}</span>
          </p>
          <p>
            Onboard when weighted ≥ 60% of best, here{' '}
            <span className="nums">{score.tolerance60.toFixed(2)}</span>. The 50% watch line sits at{' '}
            <span className="nums">{score.tolerance50.toFixed(2)}</span>.
          </p>
          <p>
            With all 18 parameters applicable the best achievable is 4.30. Automation can fill five
            of them — S1, S2, S3, A3 and N3 — worth 1.30, about 34%. The rest is human judgement
            and field work, by design.
          </p>
        </div>
      </Card>
    </div>
  )
}
