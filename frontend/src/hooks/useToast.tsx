/**
 * Toasts.
 *
 * Two variants, because a failure and a confirmation do not deserve the
 * same treatment. A success message can slide past in three seconds; an
 * error explaining that a paid check was refused, or that a provider is
 * unconfigured, is the only place that reason will ever be shown — so it
 * stays up long enough to read, and until dismissed if it is long.
 */

import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'

import { errorMessage, errorTitle } from '@/api/http'

type Variant = 'info' | 'error'

type Toast = { message: string; title?: string; variant: Variant }

type ToastApi = {
  (message: string): void
  /** Show a failure, with the reason the server actually gave. */
  error: (error: unknown, fallback?: string) => void
}

const noop = Object.assign(() => {}, { error: () => {} }) as ToastApi
const ToastContext = createContext<ToastApi>(noop)

//: Long enough to read a sentence; errors get longer still.
const INFO_MS = 3200
const ERROR_MS = 9000

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<Toast | null>(null)
  const [timer, setTimer] = useState<number | null>(null)

  const show = useCallback(
    (next: Toast) => {
      if (timer) window.clearTimeout(timer)
      setToast(next)
      const ms = next.variant === 'error' ? ERROR_MS : INFO_MS
      setTimer(window.setTimeout(() => setToast(null), ms))
    },
    [timer],
  )

  const api = useCallback(
    (() => {
      const fn = ((message: string) =>
        show({ message, variant: 'info' })) as ToastApi
      fn.error = (error: unknown, fallback?: string) => {
        // The message the SERVER gave, never a generic replacement. The
        // backend distinguishes 402 refused, 501 not configured and 502
        // provider error on purpose; flattening them here would undo it.
        const message = errorMessage(error)
        show({
          message: message || fallback || 'Something went wrong.',
          title: errorTitle(error),
          variant: 'error',
        })
        // Keep the whole object for anyone with devtools open — the
        // ApiError carries the status and the raw response body.
        console.error('[vbc]', error)
      }
      return fn
    })(),
    [show],
  )

  return (
    <ToastContext.Provider value={api}>
      {children}
      {toast && (
        <div
          className={`toast${toast.variant === 'error' ? ' toast-error' : ''}`}
          role={toast.variant === 'error' ? 'alert' : 'status'}
          aria-live={toast.variant === 'error' ? 'assertive' : 'polite'}
        >
          {toast.title && <div className="toast-h">{toast.title}</div>}
          <div>{toast.message}</div>
          {toast.variant === 'error' && (
            <button
              type="button"
              className="toast-x"
              aria-label="Dismiss"
              onClick={() => setToast(null)}
            >
              ×
            </button>
          )}
        </div>
      )}
    </ToastContext.Provider>
  )
}

export const useToast = () => useContext(ToastContext)
