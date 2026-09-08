/**
 * Step 0 — the clients Q1SSL works for.
 *
 * The layer above vendors. Reliance is a client; Zepto is one of its
 * vendors. Two clients can each onboard the same company and each gets its
 * own assessment.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Card, EmptyState } from '@/components/ui'
import { useClients } from '@/hooks/useClients'
import { useToast } from '@/hooks/useToast'
import { api } from '@/api'
import { errorMessage } from '@/api/http'

const BLANK = { name: '', legalName: '', industry: '', spoc: '', email: '', phone: '', notes: '' }

export default function Clients() {
  const { clients, loading, error, reload } = useClients()
  const navigate = useNavigate()
  const toast = useToast()

  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState(BLANK)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const save = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!draft.name.trim() || saving) return
    setSaving(true)
    setFormError(null)
    try {
      const client = await api.createClient({ ...draft, name: draft.name.trim() })
      toast(`${client.name} added`)
      setDraft(BLANK)
      setAdding(false)
      reload()
    } catch (e) {
      setFormError(errorMessage(e))
    } finally {
      setSaving(false)
    }
  }

  const set = (key: keyof typeof BLANK) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setDraft((d) => ({ ...d, [key]: e.target.value }))

  if (loading) return <p className="muted">Loading clients…</p>

  return (
    <div className="stack">
      <div>
        <div className="kicker">Clients</div>
        <h2 className="page-h">Who we audit for</h2>
        <p className="page-sub">
          Every vendor belongs to one client. The same company can be a vendor for
          more than one client — each gets its own assessment.
        </p>
      </div>

      {error && <div className="callout k-adverse">{error}</div>}

      <Card
        title="Clients"
        subtitle={`${clients.length} on file`}
        aside={
          <button
            type="button"
            className={`btn ${adding ? 'ghost' : 'primary'}`}
            onClick={() => {
              setAdding((a) => !a)
              setFormError(null)
            }}
          >
            {adding ? 'Cancel' : 'Add a client'}
          </button>
        }
        tight
      >
        {adding && (
          <form className="client-form" onSubmit={save}>
            <div className="form-grid">
              <label className="field">
                <span className="label">Client name *</span>
                <input className="input" required autoFocus value={draft.name}
                       onChange={set('name')} placeholder="Reliance Industries" />
              </label>
              <label className="field">
                <span className="label">Legal name</span>
                <input className="input" value={draft.legalName} onChange={set('legalName')}
                       placeholder="Reliance Industries Limited" />
              </label>
              <label className="field">
                <span className="label">Industry</span>
                <input className="input" value={draft.industry} onChange={set('industry')}
                       placeholder="Conglomerate" />
              </label>
              <label className="field">
                <span className="label">Point of contact</span>
                <input className="input" value={draft.spoc} onChange={set('spoc')} />
              </label>
              <label className="field">
                <span className="label">Email</span>
                <input className="input" type="email" value={draft.email} onChange={set('email')} />
              </label>
              <label className="field">
                <span className="label">Phone</span>
                <input className="input" value={draft.phone} onChange={set('phone')} />
              </label>
            </div>

            {formError && <div className="callout k-adverse">{formError}</div>}

            <div className="form-actions">
              <button type="submit" className="btn primary" disabled={saving || !draft.name.trim()}>
                {saving ? 'Adding…' : 'Add client'}
              </button>
            </div>
          </form>
        )}

        {clients.length === 0 && !adding ? (
          <EmptyState
            title="No clients yet"
            body="Add the firm you are performing due diligence for. Its vendors go inside it."
            action={
              <button type="button" className="btn primary" onClick={() => setAdding(true)}>
                Add a client
              </button>
            }
          />
        ) : (
          <div className="card-grid">
            {clients.map((client) => (
              <button
                key={client.id}
                type="button"
                className="client-card"
                onClick={() => navigate(`/clients/${client.id}`)}
              >
                <div className="client-card-head">
                  <span className="client-avatar" aria-hidden="true">
                    {client.name.slice(0, 2).toUpperCase()}
                  </span>
                  <div className="client-id small mono muted">{client.id}</div>
                </div>

                <div className="client-name">{client.name}</div>
                <div className="small muted">{client.industry || 'Industry not recorded'}</div>

                <div className="client-stats">
                  <div>
                    <div className="client-stat">{client.vendorCount}</div>
                    <div className="small muted">
                      {client.vendorCount === 1 ? 'vendor' : 'vendors'}
                    </div>
                  </div>
                  <div>
                    <div className="client-stat">{client.decidedCount}</div>
                    <div className="small muted">decided</div>
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
