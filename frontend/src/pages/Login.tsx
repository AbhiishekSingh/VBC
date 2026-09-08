/**
 * Sign in.
 *
 * One error message for every failure. The server deliberately does not say
 * whether the email or the password was wrong, and repeating that here
 * keeps the form from becoming a way to find out who works at Q1SSL.
 */

import { useState } from 'react'

import { useAuth } from '@/hooks/useAuth'
import { errorMessage } from '@/api/http'

export default function Login() {
  const { signIn, bootError } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      await signIn(email.trim(), password)
    } catch (e) {
      // The API answers wrong-password and unknown-email identically,
      // on purpose, so the form is not a user-existence oracle. Show
      // whatever it said rather than substituting our own wording.
      setError(errorMessage(e))
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-shell">
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-brand">
          <span className="auth-mark">VBC</span>
          <div>
            <h1 className="auth-title">Vendor Intelligence</h1>
            <p className="small muted">Q1SSL onboarding due diligence</p>
          </div>
        </div>

        <label className="field">
          <span className="label">Email</span>
          <input
            className="input"
            type="email"
            autoComplete="username"
            autoFocus
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@q1ssl.com"
          />
        </label>

        <label className="field">
          <span className="label">Password</span>
          <input
            className="input"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>

        {(error ?? bootError) && (
          <div className="callout k-adverse auth-error" role="alert">
            {error ?? bootError}
          </div>
        )}

        <button type="submit" className="btn primary auth-submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>

        <p className="small muted auth-foot">
          The system automates the data layer. The analyst retains the decision layer.
        </p>
      </form>
    </div>
  )
}
