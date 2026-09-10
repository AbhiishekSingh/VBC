/**
 * Step 4 — manual entries.
 *
 * Everything an API cannot answer. Two ways in: the organisation's field
 * library (so every vendor is asked the same questions and answers stay
 * comparable across audits), and an ad-hoc custom field for one-offs.
 *
 * ANALYST-STATED IS NOT VERIFIED. Every entry carries who recorded it and
 * when, and is rendered in its own block — never mixed into the sourced
 * findings, and never in the report's evidence sections. Nobody independent
 * confirmed any of it.
 */

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '@/api'
import { CURRENT_ANALYST } from '@/api/mock'
import { FIELD_CATEGORIES, MANUAL_TEMPLATES, SCAN_PARAMETERS } from '@/catalog/generated'
import { Callout, Card, Field } from '@/components/ui'
import { useToast } from '@/hooks/useToast'
import type { PageProps } from '@/App'
import type { FieldTypeName } from '@/types/domain'

const now = () => {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export default function Manual({ vendor, setVendor, setPrimary }: PageProps) {
  const navigate = useNavigate()
  const toast = useToast()

  const [templateId, setTemplateId] = useState<string>(MANUAL_TEMPLATES[0].id)
  const [value, setValue] = useState('')
  const [note, setNote] = useState('')

  const [customKey, setCustomKey] = useState('')
  const [customValue, setCustomValue] = useState('')
  const [customType, setCustomType] = useState<FieldTypeName>('Text')
  const [customNote, setCustomNote] = useState('')

  const template = MANUAL_TEMPLATES.find((t) => t.id === templateId)!
  const alreadyFiled = new Set(vendor.manual.map((e) => e.templateId).filter(Boolean))

  const mappingPreview = (() => {
    if (!template.mapsTo || !value) return null
    const target = (template.mapWhen as Record<string, string>)[value]
    return target ? `${template.mapsTo} → ${target}` : null
  })()

  const addFromTemplate = async () => {
    if (!value.trim()) return
    // A manual entry is an analyst asserting a fact that no provider
    // supplied, and several of them map straight onto a SCAN parameter.
    // Losing one silently is losing evidence.
    try {
      setVendor(
        await api.addManualEntry(vendor.id, {
          key: template.label,
          value,
          type: template.type as FieldTypeName,
          templateId: template.id,
          note,
          enteredBy: CURRENT_ANALYST,
          enteredAt: now(),
        }),
      )
    } catch (e) {
      toast.error(e, 'That entry could not be recorded.')
      return
    }
    toast(mappingPreview ? `Recorded — sets ${mappingPreview}` : 'Entry recorded')
    setValue('')
    setNote('')
  }

  const addCustom = async () => {
    if (!customKey.trim() || !customValue.trim()) return
    try {
      setVendor(
        await api.addManualEntry(vendor.id, {
          key: customKey,
          value: customValue,
          type: customType,
          templateId: null,
          note: customNote,
          enteredBy: CURRENT_ANALYST,
          enteredAt: now(),
        }),
      )
    } catch (e) {
      toast.error(e, 'That entry could not be recorded.')
      return
    }
    toast('Custom entry recorded')
    setCustomKey('')
    setCustomValue('')
    setCustomNote('')
  }

  useEffect(() => {
    setPrimary(
      <button type="button" className="btn primary" onClick={() => navigate(`/vendor/${vendor.id}/surveillance`)}>
        Site surveillance →
      </button>,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vendor.id])

  return (
    <div className="stack">
      <div>
        <div className="kicker">Step 4 · Analyst-stated</div>
        <h2 className="page-h">Manual entries</h2>
        <p className="page-sub">
          Everything no configured API can answer. Some of these fields write directly into the
          SCAN score — with GST unconfigured, a hand-checked suspension is the only way that fact
          reaches this system at all.
        </p>
      </div>

      <Callout kind="info" title="These are statements, not evidence">
        Every entry below is stamped with who recorded it and when, and appears in the report in
        its own block, clearly separated from anything a source returned. None of it has been
        independently confirmed.
      </Callout>

      <div className="grid-2">
        <Card title="From the field library" subtitle="Standard questions, asked of every vendor">
          <div className="stack-sm">
            <Field label="Field">
              <select
                className="select"
                value={templateId}
                onChange={(e) => {
                  setTemplateId(e.target.value)
                  setValue('')
                }}
              >
                {FIELD_CATEGORIES.filter((c) => c !== 'Custom').map((cat) => (
                  <optgroup key={cat} label={cat}>
                    {MANUAL_TEMPLATES.filter((t) => t.category === cat).map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.label}
                        {alreadyFiled.has(t.id) ? ' — already recorded' : ''}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </Field>

            <Field label="Value" hint={template.hint || undefined}>
              {template.options.length > 0 ? (
                <select className="select" value={value} onChange={(e) => setValue(e.target.value)}>
                  <option value="">Choose…</option>
                  {template.options.map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  className="input"
                  type={template.type === 'Number' ? 'number' : template.type === 'Date' ? 'date' : 'text'}
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                />
              )}
            </Field>

            {template.mapsTo && (
              <div className="callout k-info">
                <span className="small">
                  This field writes SCAN parameter <strong>{template.mapsTo}</strong>
                  {' — '}
                  {SCAN_PARAMETERS.find((p) => p.id === template.mapsTo)?.label}.
                  {mappingPreview && (
                    <>
                      {' '}
                      <span className="badge b-accent">SETS {mappingPreview}</span>
                    </>
                  )}
                </span>
              </div>
            )}

            <Field label="Note" hint="What you saw, and anything that qualifies the answer">
              <textarea className="textarea" value={note} onChange={(e) => setNote(e.target.value)} />
            </Field>

            <button type="button" className="btn primary" disabled={!value.trim()} onClick={addFromTemplate}>
              Record entry
            </button>
          </div>
        </Card>

        <Card title="Custom field" subtitle="One-off, for this vendor only">
          <div className="stack-sm">
            <Field label="Question">
              <input
                className="input"
                value={customKey}
                onChange={(e) => setCustomKey(e.target.value)}
                placeholder="Machine capacity (sheets/hour)"
              />
            </Field>
            <Field label="Type">
              <select
                className="select"
                value={customType}
                onChange={(e) => setCustomType(e.target.value as FieldTypeName)}
              >
                {(['Yes / No', 'Choice', 'Text', 'Number', 'Date'] as FieldTypeName[]).map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Value">
              <input
                className="input"
                type={customType === 'Number' ? 'number' : customType === 'Date' ? 'date' : 'text'}
                value={customValue}
                onChange={(e) => setCustomValue(e.target.value)}
              />
            </Field>
            <Field label="Note">
              <textarea className="textarea" value={customNote} onChange={(e) => setCustomNote(e.target.value)} />
            </Field>
            <button
              type="button"
              className="btn"
              disabled={!customKey.trim() || !customValue.trim()}
              onClick={addCustom}
            >
              Record custom entry
            </button>
            <p className="small muted">
              A custom field never writes a SCAN parameter. Only library templates carry mappings,
              so the score can never depend on ad-hoc wording.
            </p>
          </div>
        </Card>
      </div>

      <Card
        title={`Recorded for this vendor (${vendor.manual.length})`}
        subtitle="Analyst-stated · not independently verified"
        tight
      >
        {vendor.manual.length === 0 ? (
          <p className="muted" style={{ padding: 16 }}>
            Nothing recorded yet.
          </p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Value</th>
                  <th>Effect on score</th>
                  <th>Recorded</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {vendor.manual.map((entry) => {
                  const tpl = MANUAL_TEMPLATES.find((t) => t.id === entry.templateId)
                  const mapping = tpl?.mapsTo
                    ? (tpl.mapWhen as Record<string, string>)[entry.value]
                    : null
                  return (
                    <tr key={entry.id}>
                      <td>
                        <div className="cell-strong">{entry.key}</div>
                        {entry.note && <div className="small muted">{entry.note}</div>}
                      </td>
                      <td>
                        <strong>{entry.value}</strong>
                        <div className="small muted">{entry.type}</div>
                      </td>
                      <td>
                        {mapping ? (
                          <span className="badge b-accent">
                            SETS {tpl!.mapsTo} → {mapping}
                          </span>
                        ) : (
                          <span className="small muted">None — recorded for the file</span>
                        )}
                      </td>
                      <td className="small muted">
                        {entry.enteredBy}
                        <br />
                        {entry.enteredAt}
                      </td>
                      <td style={{ width: 1 }}>
                        <button
                          type="button"
                          className="btn sm ghost danger"
                          onClick={async () => {
                            try {
                              setVendor(await api.removeManualEntry(vendor.id, entry.id))
                            } catch (e) {
                              toast.error(e, 'That entry could not be removed.')
                              return
                            }
                            toast('Entry removed — any SCAN parameter it set has been cleared')
                          }}
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
