/**
 * Vendor state.
 *
 * A small context rather than a state library: the flow is linear, one
 * vendor is active at a time, and every page mutates through the same API
 * adapter. Anything more would be scaffolding for its own sake.
 */

import { useCallback, useEffect, useState } from 'react'
import { api } from '@/api'
import type { Vendor } from '@/types/domain'

export function useVendor(id: string | undefined) {
  const [vendor, setVendor] = useState<Vendor | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) {
      setVendor(null)
      setLoading(false)
      return
    }
    let live = true
    setLoading(true)
    api
      .getVendor(id)
      .then((v) => {
        if (!live) return
        setVendor(v)
        setError(v ? null : `No vendor with id ${id}`)
      })
      .catch((e: Error) => live && setError(e.message))
      .finally(() => live && setLoading(false))
    return () => {
      live = false
    }
  }, [id])

  /** Apply an API call's returned vendor to local state. */
  const apply = useCallback((next: Vendor) => setVendor(next), [])

  return { vendor, setVendor: apply, loading, error }
}

export function useVendorList() {
  const [vendors, setVendors] = useState<Vendor[]>([])
  const [loading, setLoading] = useState(true)

  const reload = useCallback(() => {
    setLoading(true)
    api
      .listVendors()
      .then(setVendors)
      .finally(() => setLoading(false))
  }, [])

  useEffect(reload, [reload])
  return { vendors, loading, reload }
}
