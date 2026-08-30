/**
 * Step 1 — intake.
 *
 * NOTHING IS COMPULSORY HERE. That is a locked scope decision, and the form
 * enforces it: format checks are advice, never a barrier. An analyst who has
 * only a name and a phone number can still file the vendor and move on;
 * whatever is missing gets collected on the Select Checks screen, where it is
 * clear which API needs it and why.
 */

import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { api } from '@/api'
import { Callout, Card, Field } from '@/components/ui'
import { useToast } from '@/hooks/useToast'
import { useClients } from '@/hooks/useClients'
import type { Vendor } from '@/types/domain'

const GST_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/
const PAN_RE = /^[A-Z]{5}[0-9]{4}[A-Z]$/
const CIN_RE = /^[LUu][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$/

/** Parse a domain out of whatever the analyst pasted into the website field. */
export function domainFromUrl(input: string): string | null {
  const trimmed = input.trim()
  if (!trimmed) return null
  try {
    const url = new URL(trimmed.includes('://') ? trimmed : `https://${trimmed}`)
    return url.hostname.replace(/^www\./, '') || null
  } catch {
    return null
  }
}

interface Props {
  vendor: Vendor | null
  setVendor: (v: Vendor) => void
  setPrimary: (node: React.ReactNode) => void
}

export default function Submit({ vendor, setPrimary }: Props) {
  const navigate = useNavigate()
  const toast = useToast()
  const [params] = useSearchParams()
  const { clients, loading: loadingClients } = useClients()
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Pre-selected when arriving from a client page, which is the normal
  // route in. Landing here from the sidebar leaves it to be chosen.
  const [clientId, setClientId] = useState(params.get('clientId') ?? '')

  const [form, setForm] = useState({
    name: vendor?.name ?? '',
    legalName: vendor?.legalName ?? '',
    address: vendor?.address ?? '',
    material: vendor?.material ?? '',
    spoc: vendor?.spoc ?? '',
    designation: vendor?.designation ?? '',
    gst: vendor?.gst ?? '',
    pan: vendor?.pan ?? '',
    cin: vendor?.cin ?? '',
    website: vendor?.website ?? '',
  })

  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }))

  const domain = domainFromUrl(form.website)

  // Advice, never a barrier — see the module docstring.
  const advice: string[] = []
  if (form.gst && !GST_RE.test(form.gst.toUpperCase())) advice.push('GSTIN does not match the standard 15-character format.')
  if (form.pan && !PAN_RE.test(form.pan.toUpperCase())) advice.push('PAN does not match the standard 10-character format.')
  if (form.cin && !CIN_RE.test(form.cin.toUpperCase())) advice.push('CIN does not match the standard 21-character format.')
  if (form.website && !domain) advice.push('That website could not be parsed into a domain, so domain checks will need it entered by hand.')

  const submit = async () => {
    if (!clientId) {
      setError('Choose which client this vendor belongs to.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const created = await api.createVendor({
        ...form,
        clientId,
        gst: form.gst || null,
        pan: form.pan || null,
        cin: form.cin || null,
        website: form.website || null,
        domain,
      })
      toast(`${created.name} filed as #${created.id}`)
      navigate(`/vendor/${created.id}/select`)
    } catch (e) {
      // A duplicate CIN for this client is a 409 with a message worth
      // showing verbatim — it names the vendor already on file.
      setError(e instanceof Error ? e.message : 'Could not file the vendor.')
    } finally {
      setSaving(false)
    }
  }

  useEffect(() => {
    setPrimary(
      <button
        type="button"
        className="btn primary"
        disabled={saving || !form.name.trim() || !clientId}
        onClick={submit}
      >
        {saving ? 'Filing…' : 'File vendor and choose checks →'}
      </button>,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saving, form, domain, clientId])

  if (vendor) {
    return (
      <div className="stack">
        <div>
          <div className="kicker">Step 1 · Intake</div>
          <h2 className="page-h">{vendor.name}</h2>
          <p className="page-sub">Filed {vendor.submitted}. Identifiers as submitted.</p>
        </div>
        <Card title="Vendor record">
          <dl className="grid-2" style={{ margin: 0 }}>
            {[
              ['Legal name', vendor.legalName],
              ['Material / service', vendor.material],
              ['Contact', `${vendor.spoc} · ${vendor.designation}`],
              ['GSTIN', vendor.gst ?? '—'],
              ['PAN', vendor.pan ?? '—'],
              ['CIN', vendor.cin ?? '—'],
              ['Domain', vendor.domain ?? '—'],
              ['Address', vendor.address],
            ].map(([label, value]) => (
              <div key={label}>
                <dt className="small muted">{label}</dt>
                <dd style={{ margin: 0, whiteSpace: 'pre-line' }}>{value || '—'}</dd>
              </div>
            ))}
          </dl>
        </Card>
      </div>
    )
  }

  return (
    <div className="stack">
      <div>
        <div className="kicker">Step 1 · Intake</div>
        <h2 className="page-h">Add a vendor</h2>
        <p className="page-sub">
          Enter whatever is known. No field is compulsory — anything an API needs later is
          collected on the next screen, where it is clear which check is asking and why.
        </p>
      </div>

      {error && <div className="callout k-adverse">{error}</div>}

      <Card
        title="Client"
        subtitle="Which client is this vendor being onboarded for"
      >
        {loadingClients ? (
          <p className="muted">Loading clients…</p>
        ) : clients.length === 0 ? (
          <div className="callout k-warn">
            <div className="callout-h">No clients on file</div>
            <p className="small muted">
              A vendor belongs to a client. Add the client first, then come back.
            </p>
            <button
              type="button"
              className="btn sm"
              style={{ marginTop: 8 }}
              onClick={() => navigate('/clients')}
            >
              Go to clients
            </button>
          </div>
        ) : (
          <Field
            label="Client *"
            hint="The same company can be a vendor for more than one client — each gets its own assessment."
          >
            <select
              className="input"
              value={clientId}
              onChange={(e) => {
                setClientId(e.target.value)
                setError(null)
              }}
            >
              <option value="">Select a client…</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
        )}
      </Card>

      <div className="grid-2">
        <div className="stack">
          <Card title="Identity">
            <div className="stack-sm">
              <Field label="Trading name">
                <input className="input" value={form.name} onChange={set('name')} placeholder="Meridian Packaging Pvt Ltd" />
              </Field>
              <Field label="Legal name" hint="As it appears on statutory filings, if known">
                <input className="input" value={form.legalName} onChange={set('legalName')} placeholder="MERIDIAN PACKAGING PRIVATE LIMITED" />
              </Field>
              <Field label="Registered address">
                <textarea className="textarea" value={form.address} onChange={set('address')} />
              </Field>
              <Field label="Material or service supplied">
                <input className="input" value={form.material} onChange={set('material')} placeholder="Goods — Corrugated packaging" />
              </Field>
            </div>
          </Card>

          <Card title="Contact">
            <div className="stack-sm">
              <Field label="Single point of contact">
                <input className="input" value={form.spoc} onChange={set('spoc')} />
              </Field>
              <Field label="Designation">
                <input className="input" value={form.designation} onChange={set('designation')} />
              </Field>
            </div>
          </Card>
        </div>

        <div className="stack">
          <Card title="Identifiers" subtitle="Each one unlocks a different set of checks">
            <div className="stack-sm">
              <Field label="CIN" hint="Unlocks the whole MCA registry group — master data, directors, charges, filings and filed financials">
                <input className="input" value={form.cin} onChange={set('cin')} placeholder="U21029MH2013PTC245119" />
              </Field>
              <Field label="GSTIN" hint="No GST provider is configured yet, so this is recorded but not verified">
                <input className="input" value={form.gst} onChange={set('gst')} placeholder="27AAGCM4821K1Z9" />
              </Field>
              <Field label="PAN" hint="Used for duplicate-vendor matching in-house">
                <input className="input" value={form.pan} onChange={set('pan')} />
              </Field>
              <Field
                label="Website"
                hint={
                  domain ? (
                    <>
                      Domain parsed as <strong className="mono">{domain}</strong> — this feeds every
                      domain and archive check.
                    </>
                  ) : (
                    'Unlocks WHOIS history, SSL, reputation and the archive.org timeline'
                  )
                }
              >
                <input className="input" value={form.website} onChange={set('website')} placeholder="https://example.com" />
              </Field>
            </div>
          </Card>

          {advice.length > 0 && (
            <Callout kind="warn" title="Worth a second look — not a blocker">
              <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                {advice.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
              <p className="small" style={{ marginTop: 8 }}>
                You can file this vendor regardless. A malformed identifier will simply cause the
                checks that need it to be skipped, and that will be recorded.
              </p>
            </Callout>
          )}

          {!form.cin && (
            <Callout kind="info" title="No CIN entered">
              Without a CIN the MCA group cannot run directly. Select the{' '}
              <strong>Resolve company name → CIN</strong> check on the next screen and the system
              will try to find it — but if the entity is a proprietorship or partnership, MCA holds
              no record and that is a finding in itself, not an error.
            </Callout>
          )}
        </div>
      </div>
    </div>
  )
}
