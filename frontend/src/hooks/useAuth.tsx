/**
 * Who is signed in.
 *
 * The session lives in an HttpOnly cookie, so this never holds a token —
 * it holds the USER the server says the cookie belongs to. On load it asks
 * once; a 401 simply means "show the login screen".
 *
 * `can()` mirrors the server's permission set. It hides what the API would
 * refuse, so an analyst does not meet a "Record decision" button that
 * returns 403. The UI check is a courtesy; the server check is the control.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

import { api } from '@/api'
import type { User } from '@/types/domain'

interface AuthValue {
  user: User | null
  loading: boolean
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => Promise<void>
  can: (permission: string) => boolean
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true
    api
      .me()
      .then((u) => alive && setUser(u))
      .catch(() => alive && setUser(null))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [])

  const signIn = useCallback(async (email: string, password: string) => {
    setUser(await api.login(email, password))
  }, [])

  const signOut = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      // Clear locally even if the call failed — the user asked to leave.
      setUser(null)
    }
  }, [])

  const can = useCallback(
    (permission: string) => !!user?.permissions?.includes(permission),
    [user],
  )

  const value = useMemo(
    () => ({ user, loading, signIn, signOut, can }),
    [user, loading, signIn, signOut, can],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
