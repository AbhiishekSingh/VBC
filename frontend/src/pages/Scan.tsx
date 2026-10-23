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
import {
  Callout,
  Card,
  InfoButton,
  Meter,
  RatingDot,
  SourceChip,
  Tile,
  toneForScan,
} from '@/components/ui'
import { useToast } from '@/hooks/useToast'
import { DEFAULT_POLICY, applyPolicy, scoreScan } from '@/scoring'
import type { PageProps } from '@/App'
import type { PillarKey, Rating, SourceMode } from '@/types/domain'

export default function Scan({ vendor, setVendor, setPrimary }: PageProps) {
  const navigate = useNavigate()
  const toast = useToast()

  const score = scoreScan(vendor.scan)
  const gate = applyPolicy(score, DEFAULT_POLICY)

  // Was the sentence "Automation can fill five of them — S1, S2, S3, A3 and
  // N3". The catalogue now marks ten parameters AUTO, and the Select page
  // computes its coverage tile from that same list, so the two screens
  // reported different automation coverage.
  const autoParams = SCAN_PARAMETERS.filter((p) => p.source === 'AUTO')

  /*
    READ, NEVER WRITTEN DOWN.

    The Assessment tile said "Weight 0.60 — the heaviest pillar" as a
    literal string while the pillar card directly beneath it rendered
    `w 0.4` from the catalog. One screen, one fact, two answers — and the
    hardcoded one had been wrong since the 5 Oct migration dropped A from
    0.6 to 0.4.

    Heaviest is computed too: if the weights are ever rebalanced again,
    this sentence follows instead of quietly becoming false.
  */
  const assessment = PILLARS.find((p) => p.key === 'A')!
  const heaviest = PILLARS.reduce((a, b) => (b.weight > a.weight ? b : a))

  // Best achievable with every parameter applicable. Was hardcoded "4.30",
  // which is right today only by coincidence — it is a function of the
  // weights and the parameter counts, both of which have moved once.
  const bestPossible = PILLARS.reduce(
    (sum, p) => sum + SCAN_PARAMETERS.filter((x) => x.pillar === p.key).length * p.weight,
    0,
  )

  useEffect(() => {
    setPrimary(
      <button type="button" className="btn primary" onClick={() => navigate(`/vendor/${vendor.id}/risk`)}>
        Risk score →
      </button>,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vendor.id])

  const setRating = async (paramId: string, value: string | null) => {
    // A rating that fails to save is the input to a binding decision. It
    // used to throw unhandled: the select snapped back and nothing said
    // why, so the analyst had no way to tell a saved rating from a lost one.
    try {
      setVendor(await api.setScanRating(vendor.id, paramId, value))
    } catch (e) {
      toast.error(e, 'That rating could not be saved.')
    }
  }

  return (
    <div className="stack">
      <div>
        <div className="kicker">Step 6 · Scoring</div>
        {/*
          The rules sit behind the ⓘ, not on the page.

          They are reference material: identical for every vendor, read
          once, then scrolled past forever. A card holding them cost a
          screenful on every visit to earn its keep on the first.

          Behind the glyph, not on a separate page — when a score is
          questioned, the paragraph that answers it has to be reachable
          from the number itself.
        */}
        <div className="row-head">
          <h2 className="page-h">SCAN scoring</h2>
          <InfoButton title="How this is calculated">
            {/*
              This read "Green + floor(Yellow ÷ 2) — an odd Yellow does not
              count", which was the DEFECT written down as if it were the
              rule. The workbook computes `=D8+(D9/2)` with no rounding, so
              one Yellow is worth half a Green. The code was fixed; this
              paragraph would have gone on teaching the old model.
            */}
            <p>
              <strong>positives</strong> = Green + (Yellow ÷ 2), per pillar. One Yellow is worth
              half a Green — not nothing.
            </p>
            <p>
              The <strong>{assessment.name}</strong> pillar is the exception: each of its{' '}
              {SCAN_PARAMETERS.filter((p) => p.pillar === 'A').length} dimensions carries its own
              share of the psychometric test rather than counting as one parameter, so its totals
              come out fractional.
            </p>
            <p>
              <strong>weighted</strong> = Σ (positives × pillar weight) ={' '}
              <span className="nums">{score.weighted.toFixed(2)}</span>
            </p>
            <p>
              <strong>best achievable</strong> = Σ (applicable × pillar weight) ={' '}
              <span className="nums">{score.best.toFixed(2)}</span>
            </p>
            {/*
              STRICTLY greater, and the 50% line is gone from here.

              "≥ 60%" was wrong twice over: the workbook asks `=IF(H16>D20)`,
              strictly, and the code now matches. The 50% watch line was
              mentioned only in this sentence and drawn nowhere — no tile, no
              marker on the meter. A threshold nobody can see is not a
              threshold, so it is now a mark ON the meter instead of a number
              in a paragraph.
            */}
            <p>
              Onboard when weighted is <strong>above</strong> 60% of best — here{' '}
              <span className="nums">{score.tolerance60.toFixed(2)}</span>. Landing exactly on the
              bar is Negative.
            </p>
            <p>
              With all {SCAN_PARAMETERS.length} parameters applicable the best achievable is{' '}
              <span className="nums">{bestPossible.toFixed(2)}</span>.
              Automation can fill {autoParams.length} of them — {autoParams.map((p) => p.id).join(', ')} —
              and the rest is human judgement and field work, by design.
            </p>
          </InfoButton>
        </div>
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
          n={`${score.pillars.A.applicable}/${
            SCAN_PARAMETERS.filter((p) => p.pillar === 'A').length
          }`}
          label="Assessment evaluated"
          note={
            `Weight ${assessment.weight}` +
            (heaviest.key === 'A' ? ' — the heaviest pillar' : '')
          }
          tone={score.pillars.A.applicable >= 2 ? 'pass' : 'warn'}
        />
      </div>

      <Card>
        <div className="stack-sm">
          <div className="row-between">
            <div>
              <div className="kicker">Verdict</div>
              <h3 className="stat-lg">{gate.verdict}</h3>
            </div>
            {/* Only when GATED. Ungated, this repeated the percentage and
                the applicable count from the tiles directly above it —
                three places for two facts. Gated, it is the one thing on
                the row the tiles cannot say. */}
            {gate.gated && (
              <span className="badge b-warn">{score.coverageNote}</span>
            )}
          </div>
          {/* The two thresholds, drawn where they actually sit. */}
          <Meter
            pct={score.pct}
            tone={toneForScan(score.pct, gate.gated)}
            marks={[
              { at: 50, label: `50% watch line — ${score.tolerance50.toFixed(2)}` },
              { at: 60, label: `60% pass mark — ${score.tolerance60.toFixed(2)}` },
            ]}
          />

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
              <div className="nums stat-lg" style={{ marginTop: 'var(--space-2)' }}>
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
            // No subtitle: the pillar TILE above already carries the
            // weight as a chip and this subtitle text verbatim. Repeating
            // both on the table heading made it the third rendering of the
            // same two facts on one screen.
            title={`${pillar.key} · ${pillar.name}`}
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

    </div>
  )
}