/** Client data loading. */

import { useCallback, useEffect, useState } from 'react'

import { api } from '@/api'
import type { Client } from '@/types/domain'

export function useClients(includeInactive = false) {
  const [clients, setClients] = useState<Client[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(() => {
    setLoading(true)
    api
      .listClients(includeInactive)
      .then((rows) => {
        setClients(rows)
        setError(null)
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load clients.'))
      .finally(() => setLoading(false))
  }, [includeInactive])

  useEffect(reload, [reload])

  return { clients, loading, error, reload, setClients }
}

export function useClient(id: string | undefined) {
  const [client, setClient] = useState<Client | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) {
      setLoading(false)
      return
    }
    let alive = true
    setLoading(true)
    api
      .getClient(id)
      .then((c) => {
        if (!alive) return
        setClient(c)
        setError(c ? null : `No client with id ${id}`)
      })
      .catch((e) => alive && setError(e instanceof Error ? e.message : 'Load failed.'))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [id])

  return { client, setClient, loading, error }
}
