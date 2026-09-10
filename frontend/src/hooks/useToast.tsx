/**
 * Toasts.
 *
 * Two variants, because a failure and a confirmation do not deserve the
 * same treatment. A success message can slide past in three seconds; an
 * error explaining that a paid check was refused, or that a provider is
 * unconfigured, is the only place that reason will ever be shown — so it
 * stays up long enough to read, and until dismissed if it is long.
 *
 * WHY A STACK RATHER THAN A SINGLE TOAST
 * --------------------------------------
 * This held one toast in state and overwrote it on every call. The Select
 * page's dependency cascade fires several in a row — "added 3 prerequisite
 * checks", then "removed 2 dependents" — and every one but the last was
 * silently lost. The timer was also kept in state, so `show` was rebuilt
 * whenever it changed and any caller holding an older reference cleared
 * nothing: a pending 3.2s info timeout could dismiss a 9s error early.
 *
 * The queue is capped: a burst of twenty is noise, not information.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'

import { errorMessage, errorTitle } from '@/api/http'

type Variant = 'info' | 'error'

type Toast = { id: number; message: string; title?: string; variant: Variant }

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
const MAX_VISIBLE = 4

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  // Refs, not state: `show` must be stable, or a caller that captured an
  // older copy silently talks to a stale timer map.
  const timers = useRef(new Map<number, number>())
  const nextId = useRef(1)

  const dismiss = useCallback((id: number) => {
    const t = timers.current.get(id)
    if (t) window.clearTimeout(t)
    timers.current.delete(id)
    setToasts((list) => list.filter((x) => x.id !== id))
  }, [])

  const show = useCallback(
    (next: Omit<Toast, 'id'>) => {
      const id = nextId.current++
      setToasts((list) => [...list, { ...next, id }].slice(-MAX_VISIBLE))
      const ms = next.variant === 'error' ? ERROR_MS : INFO_MS
      timers.current.set(
        id,
        window.setTimeout(() => dismiss(id), ms),
      )
    },
    [dismiss],
  )

  // Nothing was clearing timeouts on unmount.
  useEffect(() => {
    const map = timers.current
    return () => {
      map.forEach((t) => window.clearTimeout(t))
      map.clear()
    }
  }, [])

  const apiRef = useRef<ToastApi | null>(null)
  if (!apiRef.current) {
    const fn = ((message: string) => show({ message, variant: 'info' })) as ToastApi
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
    apiRef.current = fn
  }

  // The toast used to be positioned at `bottom: actionbar-h + 16px`,
  // hard-coded to the action bar existing. On the Dashboard, which renders
  // no action bar, it floated 76px above the bottom of the viewport for no
  // reason. The bar is fixed, so its presence is a DOM question.
  const [hasBar, setHasBar] = useState(false)
  useEffect(() => {
    const check = () => setHasBar(!!document.querySelector('.actionbar'))
    check()
    const mo = new MutationObserver(check)
    mo.observe(document.body, { childList: true, subtree: true })
    return () => mo.disconnect()
  })

  return (
    <ToastContext.Provider value={apiRef.current}>
      {children}
      {toasts.length > 0 && (
        <div className={`toast-stack${hasBar ? '' : ' no-bar'}`}>
          {toasts.map((toast) => (
            <div
              key={toast.id}
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
                  onClick={() => dismiss(toast.id)}
                >
                  ×
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </ToastContext.Provider>
  )
}

export const useToast = () => useContext(ToastContext)
