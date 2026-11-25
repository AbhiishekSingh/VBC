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

      {/* These four are the ROLL-UP, and they are what a client reads
          first — so each carries its own working, the same way the
          pillar tiles below do. Every figure is read from `score` and
          `gate`; none is written down a second time. */}
      <div className="grid-4">
        <Tile
          n={`${score.weighted.toFixed(2)} / ${score.best.toFixed(2)}`}
          label="Weighted / best achievable"
          tone="accent"
          info={
            <>
              <p>Both sides are the four pillar tiles below, added up.</p>
              <table className="table">
                <thead>
                  <tr>
                    <th>Pillar</th>
                    <th className="num">Weighted</th>
                    <th className="num">Best</th>
                  </tr>
                </thead>
                <tbody>
                  {PILLARS.map((pillar) => {
                    const b = score.pillars[pillar.key as PillarKey]
                    return (
                      <tr key={pillar.key}>
                        <td>
                          {pillar.name} <span className="muted">· w {pillar.weight}</span>
                        </td>
                        <td className="num nums">{b.weighted.toFixed(2)}</td>
                        <td className="num nums">{b.max.toFixed(2)}</td>
                      </tr>
                    )
                  })}
                  <tr>
                    <td>
                      <strong>Total</strong>
                    </td>
                    <td className="num nums">
                      <strong>{score.weighted.toFixed(2)}</strong>
                    </td>
                    <td className="num nums">
                      <strong>{score.best.toFixed(2)}</strong>
                    </td>
                  </tr>
                </tbody>
              </table>
              <p>
                <strong>Weighted</strong> is what this vendor earned.{' '}
                <strong>Best achievable</strong> is what the questions that were actually answered
                could have been worth, had every one come back Green.
              </p>
              <p>
                With all {score.total} parameters applicable the best achievable would be{' '}
                <span className="nums">
                  {PILLARS.reduce(
                    (sum, p) =>
                      sum +
                      SCAN_PARAMETERS.filter((q) => q.pillar === p.key).length * p.weight,
                    0,
                  ).toFixed(2)}
                </span>
                . It is{' '}
                <span className="nums">{score.best.toFixed(2)}</span> here because{' '}
                {score.total - score.applicable} were marked Not applicable and left both sides.
              </p>
            </>
          }
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
          info={
            <>
              <p className="nums">
                <strong>
                  {score.weighted.toFixed(2)} ÷ {score.best.toFixed(2)} ={' '}
                  {score.pct.toFixed(1)}%
                </strong>
              </p>
              <p>
                The pass mark is <strong>60% of best achievable</strong> — here{' '}
                <span className="nums">{score.tolerance60.toFixed(2)}</span>. The 50% watch line is{' '}
                <span className="nums">{score.tolerance50.toFixed(2)}</span>; both are drawn on the
                meter below rather than left as numbers in a sentence.
              </p>
              <p>
                Onboarding needs weighted <strong>above</strong> the pass mark, strictly. Landing
                exactly on the bar is Negative — the client&rsquo;s workbook asks{' '}
                <span className="mono">=IF(H16&gt;D20, …)</span> and this matches it.
              </p>
              <p>
                {score.weighted > score.tolerance60 ? (
                  <>
                    <span className="nums">{score.weighted.toFixed(2)}</span> is above{' '}
                    <span className="nums">{score.tolerance60.toFixed(2)}</span>, so the arithmetic
                    says <strong>{gate.rawVerdict}</strong>.
                  </>
                ) : (
                  <>
                    <span className="nums">{score.weighted.toFixed(2)}</span> does not clear{' '}
                    <span className="nums">{score.tolerance60.toFixed(2)}</span>, so the arithmetic
                    says <strong>{gate.rawVerdict}</strong>.
                  </>
                )}
                {gate.gated && (
                  <>
                    {' '}
                    The verdict shown is <strong>{gate.verdict}</strong> instead, because the
                    evidence behind that percentage is too thin to stand behind — see the verdict
                    card below.
                  </>
                )}
              </p>
              <p>
                A percentage is only as good as the number of questions under it. This one rests on{' '}
                {score.applicable} of {score.total}.
              </p>
            </>
          }
        />
        <Tile
          n={`${score.applicable}/${score.total}`}
          label="Parameters applicable"
          note="The rest are N/A and excluded"
          info={
            <>
              <p>
                {score.applicable} of {score.total} questions were answered.{' '}
                {score.total - score.applicable} are set to Not applicable.
              </p>
              <table className="table">
                <tbody>
                  {PILLARS.map((pillar) => {
                    const b = score.pillars[pillar.key as PillarKey]
                    const of = SCAN_PARAMETERS.filter((p) => p.pillar === pillar.key).length
                    return (
                      <tr key={pillar.key}>
                        <td>{pillar.name}</td>
                        <td className="num nums">
                          {b.applicable} / {of}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              <p>
                <strong>Not applicable leaves both sides of the calculation.</strong> A vendor is
                never marked down for a question that could not apply to them — a sole proprietor
                has no board, so board questions are struck off the paper rather than failed.
              </p>
              <p>
                The consequence is that the bar moves with coverage. Answer fewer questions and both
                the score and the pass mark shrink together, so a high percentage on a handful of
                answers is not the same achievement as the same percentage on all{' '}
                {score.total}. That is what the coverage floors exist to catch.
              </p>
            </>
          }
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
          info={
            <>
              <p>
                How many of the {SCAN_PARAMETERS.filter((p) => p.pillar === 'A').length} Assessment
                questions have a result. They come from the psychometric test, and all four are
                entered by a person — nothing fills them automatically.
              </p>
              <p>
                This pillar carries weight <strong>{assessment.weight}</strong>
                {heaviest.key === 'A' && ', the heaviest of the four'}, so a verdict reached without
                it is a statement about paperwork rather than about a vendor.
              </p>
              <p>
                A positive recommendation needs at least{' '}
                <strong>{DEFAULT_POLICY.minAssessmentParameters} of them answered</strong>. Below
                that the score still stands and is still shown, but the verdict is held for senior
                review.
              </p>
              <p>
                It is a count rather than a yes/no on purpose. A floor of one could be met by the
                cheapest check in the catalog; a floor of{' '}
                {DEFAULT_POLICY.minAssessmentParameters} forces real work.
              </p>
            </>
          }
        />
      </div>

      <Card>
        <div className="stack-sm">
          <div className="row-between">
            <div>
              <div className="kicker">Verdict</div>
              <h3 className="stat-lg">{gate.verdict}</h3>
            </div>
            {/* THE BADGE IS GONE.
                It read "94.4% achieved, based on 14 of 18 parameters" —
                and the Achievement tile two inches above already says
                94.4%, while the one beside it says 14/18. The earlier
                note here claimed it was "the one thing on the row the
                tiles cannot say"; it was not, in either state. Three
                renderings of two facts, on the screen whose job is to
                make the arithmetic followable. */}
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

      {/*
        AN `ⓘ` PER PILLAR, not one for the page.

        The question a client asks is never "how does SCAN work" in the
        abstract — it is "why does THAT tile say 0.90 / 1.00". A general
        formula at the top of the page does not answer it; the reader has
        to carry four numbers from a paragraph down to a tile and do the
        arithmetic themselves. So each tile shows its own working, with
        this vendor's own figures, substituted in and named.

        Every number below is read from the same `bucket` the tile prints.
        Nothing is written down twice, so the explanation cannot drift
        from the number it explains — which is exactly how the verdict
        card came to claim Assessment weighed 0.60 for seven weeks after
        it stopped.
      */}
      <div className="grid-4">
        {PILLARS.map((pillar) => {
          const bucket = score.pillars[pillar.key as PillarKey]
          const params = SCAN_PARAMETERS.filter((p) => p.pillar === pillar.key)
          const rated = params.filter((p) => vendor.scan[p.id])
          const isA = pillar.key === 'A'
          return (
            <div key={pillar.key} className="tile">
              <div className="row-between">
                <strong>{pillar.name}</strong>
                <span className="row-head">
                  <span className="chip">w {pillar.weight}</span>
                  <InfoButton
                    title={`${pillar.name} — how this tile is calculated`}
                    label={`How ${pillar.name} is calculated`}
                  >
                    {bucket.applicable === 0 ? (
                      <>
                        <p>
                          Nothing in this pillar has been answered yet, so it contributes{' '}
                          <strong>nothing to either side</strong> of the score.
                        </p>
                        <p>
                          <strong>0.00 / 0.00 does not mean the vendor scored zero.</strong> It
                          means the questions were never put. A zero score would read 0.00 /{' '}
                          <span className="nums">{(params.length * pillar.weight).toFixed(2)}</span>{' '}
                          — asked and failed. Not asking is a different answer from asking and
                          finding nothing wrong, and this product refuses to blur the two.
                        </p>
                        <p>
                          Its {params.length} questions are {params.map((p) => p.id).join(', ')}.
                          Answer any of them in the table below and both sides of this tile start
                          moving.
                        </p>
                      </>
                    ) : (
                      <>
                        <p>
                          <strong>{bucket.applicable}</strong> of this pillar&rsquo;s{' '}
                          {params.length} questions were answered
                          {params.length - bucket.applicable > 0 && (
                            <>
                              {' '}
                              — {params.length - bucket.applicable} left Not applicable, which
                              leaves <em>both</em> sides of the calculation
                            </>
                          )}
                          .
                        </p>

                        <table className="table">
                          <tbody>
                            {rated.map((p) => {
                              const value = vendor.scan[p.id]
                              const rating = p.options.find((o) => o.value === value)?.rating
                              const worth =
                                rating === 'G' ? '1' : rating === 'Y' ? '½' : '0'
                              return (
                                <tr key={p.id}>
                                  <td className="mono muted">{p.id}</td>
                                  <td>{value}</td>
                                  <td>
                                    <RatingDot rating={(rating as Rating) ?? null} />
                                  </td>
                                  <td className="num nums">{worth}</td>
                                </tr>
                              )
                            })}
                          </tbody>
                        </table>

                        <p>
                          Green is worth 1, Yellow <strong>½</strong> — not nothing — and Red 0.
                        </p>
                        {/* Its own paragraph. Run on after the sentence above it
                            read "…and Red 0. 4 + (1 ÷ 2) = 4.5 positives", where
                            the Red's zero and the Green count collide into "0. 4". */}
                        {bucket.Y > 0 && (
                          <p className="nums">
                            {bucket.G} Green + ({bucket.Y} Yellow ÷ 2) = {bucket.positives}{' '}
                            positives
                          </p>
                        )}

                        {isA && (
                          <p>
                            This pillar is the exception: each of its {params.length} dimensions
                            carries its own share of the psychometric test —{' '}
                            {params
                              .map((p) => `${p.label} ${(p.subWeight ?? 0) * 100}%`)
                              .join(', ')}{' '}
                            — rather than counting as one parameter each, so its totals come out
                            fractional.
                          </p>
                        )}

                        <p className="nums">
                          <strong>
                            {bucket.positives} positives × {pillar.weight} weight ={' '}
                            {bucket.weighted.toFixed(2)}
                          </strong>
                          <br />
                          <strong>
                            {bucket.applicable} answered × {pillar.weight} weight ={' '}
                            {bucket.max.toFixed(2)}
                          </strong>
                        </p>
                        <p>
                          The right-hand number only ever moves when a question is answered or set
                          back to Not applicable. The colours move the left-hand number alone.
                        </p>
                      </>
                    )}
                  </InfoButton>
                </span>
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