/**
 * Step 9 — record the decision.
 *
 * The one screen where the system stops advising and a person commits. The
 * product principle that runs through everything else lands here: the
 * platform gathered, scored, drafted and flagged, and now a named human
 * takes responsibility for the outcome.
 *
 * Remarks are mandatory. Contradicting the recommendation additionally
 * requires a stated reason — not to discourage the override (Azahan was
 * overridden and the human was right) but so that the file records why.
 */

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '@/api'
import { Callout, Card, Field } from '@/components/ui'
import { useToast } from '@/hooks/useToast'
import { DEFAULT_POLICY, applyPolicy, scoreRisk, scoreScan } from '@/scoring'
import type { PageProps } from '@/App'

type DecisionValue = 'Approved' | 'Conditional' | 'Rejected'

export default function Decision({ vendor, setVendor, setPrimary }: PageProps) {
  const navigate = useNavigate()
  const toast = useToast()

  const scan = scoreScan(vendor.scan)
  const gate = applyPolicy(scan, DEFAULT_POLICY)
  const risk = scoreRisk(vendor.checks, vendor.selected)

  const [decision, setDecision] = useState<DecisionValue | ''>((vendor.decision as DecisionValue) ?? '')
  const [remarks, setRemarks] = useState(vendor.decisionRemarks ?? '')
  const [overrideReason, setOverrideReason] = useState('')
  const [saving, setSaving] = useState(false)

  // The system recommends onboarding only on an ungated positive.
  const systemPositive = gate.verdict === 'Positive for Onboarding'
  const isOverride =
    (decision === 'Approved' && !systemPositive) || (decision === 'Rejected' && systemPositive)

  const canSubmit =
    !!decision && remarks.trim().length >= 10 && (!isOverride || overrideReason.trim().length >= 10)

  const submit = async () => {
    if (!canSubmit) return
    setSaving(true)
    try {
      setVendor(
        await api.recordDecision(vendor.id, {
          decision: decision as DecisionValue,
          remarks,
          overrideReason: isOverride ? overrideReason : undefined,
        }),
      )
      toast(`Decision recorded — ${decision}`)
      navigate('/')
    } finally {
      setSaving(false)
    }
  }

  useEffect(() => {
    setPrimary(
      <button type="button" className="btn primary" disabled={!canSubmit || saving} onClick={submit}>
        {saving ? 'Recording…' : 'Record decision'}
      </button>,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canSubmit, saving, decision, remarks, overrideReason])

  if (vendor.decision) {
    return (
      <div className="stack">
        <div>
          <div className="kicker">Step 9 · Decided</div>
          <h2 className="page-h">Decision recorded</h2>
        </div>
        <Card>
          <div className="stack-sm">
            <div className="row-between">
              <span className={`badge b-${vendor.decision === 'Rejected' ? 'adverse' : 'pass'}`}>
                {vendor.decision}
              </span>
              <span className="small muted">
                {vendor.decidedBy} · {vendor.submitted}
              </span>
            </div>
            <p>{vendor.decisionRemarks}</p>
          </div>
        </Card>
        <Callout kind="info" title="This is the binding record">
          The decision above, not the score, is what this platform holds as the outcome. It is in
          the audit trail with the analyst's name against it and cannot be edited — a change would
          be recorded as a new entry.
        </Callout>
      </div>
    )
  }

  return (
    <div className="stack">
      <div>
        <div className="kicker">Step 9 · The decision layer</div>
        <h2 className="page-h">Record the decision</h2>
        <p className="page-sub">
          The system has gathered, scored, drafted and flagged. What it will not do is decide. That
          is recorded here, by name, with reasons.
        </p>
      </div>

      <Card title="What the system found">
        <div className="grid-3">
          <div>
            <div className="kicker">SCAN</div>
            <div className="nums" style={{ fontSize: 'var(--step-2)', fontWeight: 620 }}>
              {scan.weighted.toFixed(2)} / {scan.best.toFixed(2)}
            </div>
            <div className="small muted">{scan.coverageNote}</div>
          </div>
          <div>
            <div className="kicker">Point model</div>
            <div className="nums" style={{ fontSize: 'var(--step-2)', fontWeight: 620 }}>
              {risk.score}
            </div>
            <div className="small muted">
              {risk.band.label} · {risk.dead} rules had no source
            </div>
          </div>
          <div>
            <div className="kicker">Recommendation</div>
            <div style={{ fontSize: 'var(--step-1)', fontWeight: 620 }}>{gate.verdict}</div>
            <div className="small muted">Advisory only</div>
          </div>
        </div>

        {gate.gated && (
          <div style={{ marginTop: 12 }}>
            <Callout kind="warn" title="Held for coverage">
              <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                {gate.reasons.map((r) => (
                  <li key={r} className="small">
                    {r}
                  </li>
                ))}
              </ul>
            </Callout>
          </div>
        )}
      </Card>

      <Card title="Your decision">
        <div className="stack-sm">
          <div className="row">
            {(['Approved', 'Conditional', 'Rejected'] as DecisionValue[]).map((option) => (
              <button
                key={option}
                type="button"
                className={`btn${decision === option ? ' primary' : ''}`}
                onClick={() => setDecision(option)}
              >
                {option}
              </button>
            ))}
          </div>

          <Field
            label="Remarks (required)"
            hint="What decided it. This is the record a colleague reads in a year's time."
          >
            <textarea
              className="textarea"
              value={remarks}
              onChange={(e) => setRemarks(e.target.value)}
              placeholder="Approved on the strength of filed financials and a confirmed site visit. Open HDFC charge noted and disclosed."
            />
          </Field>

          {isOverride && (
            <>
              <Callout kind="warn" title="This contradicts the recommendation">
                The system recommends <strong>{gate.verdict}</strong> and you are recording{' '}
                <strong>{decision}</strong>. Overrides are expected and often correct — the file
                simply needs to say why.
              </Callout>
              <Field label="Reason for the override (required)">
                <textarea
                  className="textarea"
                  value={overrideReason}
                  onChange={(e) => setOverrideReason(e.target.value)}
                  placeholder="Entity is an unincorporated proprietorship with no premises and no web presence. The 60% reflects six applicable parameters, not a strong result."
                />
              </Field>
            </>
          )}

          {!canSubmit && (
            <p className="small muted">
              {!decision
                ? 'Choose an outcome.'
                : remarks.trim().length < 10
                  ? 'Remarks are required.'
                  : 'A reason for the override is required.'}
            </p>
          )}
        </div>
      </Card>
    </div>
  )
}
