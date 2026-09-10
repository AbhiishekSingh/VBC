/**
 * Step 5 — site surveillance.
 *
 * Thirteen parameters recorded by someone who physically visited the
 * premises. Pass needs 60% positives on the 2Y=1G arithmetic, with one
 * override that matters more than the percentage: V1 EXISTENCE OF PREMISES
 * is a hard gate. You cannot have a satisfactory site visit to a site that
 * does not exist, so a Negative there forces the whole result Negative
 * however well the other twelve scored.
 *
 * The result writes A2 — the single heaviest-weighted parameter in SCAN.
 */

import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '@/api'
import { SURVEILLANCE_PARAMETERS } from '@/catalog/generated'
import { Callout, Card, Meter, RatingDot, Tile } from '@/components/ui'
import { useToast } from '@/hooks/useToast'
import { scoreSurveillance } from '@/scoring'
import type { PageProps } from '@/App'
import type { Rating } from '@/types/domain'

export default function Surveillance({ vendor, setVendor, setPrimary }: PageProps) {
  const navigate = useNavigate()
  const toast = useToast()

  // Live preview while editing; the server recomputes on completion.
  const score = scoreSurveillance(vendor.surveillance, true)
  const filed = vendor.surveillanceDone

  const setValue = async (paramId: string, value: string | null) => {
    try {
      setVendor(await api.setSurveillance(vendor.id, { [paramId]: value }))
    } catch (e) {
      toast.error(e, 'That field could not be saved.')
    }
  }

  const complete = async () => {
    let result
    try {
      result = await api.completeSurveillance(vendor.id)
    } catch (e) {
      // Filing is the step that writes A2. Failing it silently and then
      // navigating onward would leave the analyst believing it was filed.
      toast.error(e, 'The site visit could not be filed.')
      return
    }
    setVendor(result)
    toast(
      score.gateFailed
        ? 'Filed as Negative — premises could not be confirmed, which overrides the percentage'
        : `Filed as ${score.verdict} at ${score.pct}% · writes A2`,
    )
    navigate(`/vendor/${vendor.id}/scan`)
  }

  useEffect(() => {
    setPrimary(
      <>
        {!filed && (
          <button
            type="button"
            className="btn ghost"
            onClick={() => navigate(`/vendor/${vendor.id}/scan`)}
          >
            Skip — no visit conducted
          </button>
        )}
        <button
          type="button"
          className="btn primary"
          disabled={score.applicable === 0}
          onClick={filed ? () => navigate(`/vendor/${vendor.id}/scan`) : complete}
        >
          {filed ? 'SCAN scoring →' : 'File surveillance result →'}
        </button>
      </>,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vendor, score.applicable, filed])

  return (
    <div className="stack">
      <div>
        <div className="kicker">Step 5 · Field work</div>
        <h2 className="page-h">Site surveillance</h2>
        <p className="page-sub">
          Recorded by whoever visited the premises. The result writes SCAN parameter A2, which sits
          in the 0.60 Assessment pillar — the heaviest weighting in the framework.
        </p>
      </div>

      {!filed && score.applicable === 0 && (
        <Callout kind="info" title="Not conducted">
          If no visit takes place, leave this blank and skip. A2 then stays Not Applicable and drops
          out of the calculation entirely — it is never recorded as Negative on the strength of
          nobody having gone.
        </Callout>
      )}

      <div className="grid-4">
        <Tile n={score.applicable} label="Parameters recorded" note={`of ${SURVEILLANCE_PARAMETERS.length}`} />
        <Tile n={score.positives} label="Positives" note="2 Yellow = 1 Green" tone="pass" />
        <Tile
          n={`${score.pct}%`}
          label="Field score"
          note="60% required to pass"
          tone={score.pct >= 60 ? 'pass' : 'warn'}
        />
        <Tile
          n={score.verdict}
          label="Result"
          tone={score.passed ? 'pass' : 'adverse'}
          note={score.gateFailed ? 'Forced Negative by the premises gate' : undefined}
        />
      </div>

      {score.gateFailed && (
        <Callout kind="adverse" title="Hard gate triggered — existence of premises">
          The premises could not be confirmed, so the surveillance result is Negative regardless of
          the {score.pct}% otherwise achieved. Twelve satisfactory observations about a site nobody
          could find do not make a satisfactory site visit.
        </Callout>
      )}

      <Card title="Field parameters" subtitle="Leave anything not observed blank rather than guessing" tight>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th style={{ width: 40 }} />
                <th>Parameter</th>
                <th>Observation</th>
                <th style={{ width: 60 }}>Rating</th>
              </tr>
            </thead>
            <tbody>
              {SURVEILLANCE_PARAMETERS.map((param) => {
                const value = vendor.surveillance[param.id] ?? ''
                const rating =
                  (param.options.find((o) => o.value === value)?.rating as Rating | undefined) ?? null
                return (
                  <tr key={param.id}>
                    <td className="mono muted">{param.id}</td>
                    <td>
                      {param.label}
                      {param.hardGate && (
                        <span className="badge b-adverse" style={{ marginLeft: 8 }} title="A Negative here forces the entire result Negative">
                          Hard gate
                        </span>
                      )}
                    </td>
                    <td style={{ maxWidth: 260 }}>
                      <select
                        className="select"
                        value={value}
                        disabled={filed}
                        onChange={(e) => setValue(param.id, e.target.value || null)}
                      >
                        <option value="">Not observed</option>
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

      {score.applicable > 0 && (
        <Card title="Arithmetic">
          <div className="stack-sm">
            <div className="row-between">
              <span className="small muted">
                {score.G} Green + {score.Y} Yellow (÷2 = {Math.floor(score.Y / 2)}) ={' '}
                {score.positives} positives across {score.applicable} recorded
              </span>
              <strong className="nums">{score.pct}%</strong>
            </div>
            <Meter pct={score.pct} tone={score.passed ? 'pass' : 'adverse'} />
            <p className="small muted">
              An odd Yellow is not counted — two are needed to make one positive. The threshold is
              60% of what was actually observed, so recording fewer parameters does not lower the
              bar in your favour: it narrows the evidence the result rests on.
            </p>
          </div>
        </Card>
      )}
    </div>
  )
}
