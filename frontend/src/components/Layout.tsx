/**
 * The application shell: sidebar, topbar, breadcrumb, step rail, action bar.
 *
 * The vendor is part of the URL (`/vendor/:id/:page`), so a refresh keeps
 * position and any page can be linked to — which matters when an analyst
 * needs to send a colleague straight to a finding.
 */

import { NavLink, useNavigate, useParams } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useEffect } from 'react'

import type { Vendor } from '@/types/domain'
import { API_MODE } from '@/api'

export const FLOW = [
  'submit',
  'select',
  'findings',
  'manual',
  'surveillance',
  'scan',
  'risk',
  'report',
  'decision',
] as const

export type FlowRoute = (typeof FLOW)[number]

export const FLOW_LABEL: Record<FlowRoute, string> = {
  submit: 'Add a vendor',
  select: 'Choose what to check',
  findings: 'Findings',
  manual: 'Manual entries',
  surveillance: 'Site surveillance',
  scan: 'SCAN scoring',
  risk: 'Risk score',
  report: 'Report',
  decision: 'Record the decision',
}

const FLOW_SHORT: Record<FlowRoute, string> = {
  submit: 'Vendor',
  select: 'Checks',
  findings: 'Findings',
  manual: 'Manual',
  surveillance: 'Site visit',
  scan: 'SCAN',
  risk: 'Risk',
  report: 'Report',
  decision: 'Decision',
}

/** Whether a flow step has been completed for this vendor. */
export function stepDone(vendor: Vendor | null, route: FlowRoute): boolean {
  if (!vendor) return false
  switch (route) {
    case 'submit':
      return true
    case 'select':
      return vendor.selected.length > 0
    case 'findings':
      return Object.keys(vendor.checks).length > 0
    case 'manual':
      return vendor.manual.length > 0
    case 'surveillance':
      return vendor.surveillanceDone
    case 'scan':
      return Object.values(vendor.scan).some((v) => v !== null)
    case 'risk':
      return Object.keys(vendor.checks).length > 0
    case 'report':
      return Object.keys(vendor.checks).length > 0
    case 'decision':
      return vendor.decision !== null
  }
}

/**
 * Sidebar icons.
 *
 * Drawn inline rather than pulled from an icon package: nine glyphs do not
 * justify a dependency, and `currentColor` means they follow the active and
 * hover states for free.
 */
function Icon({ d }: { d: string }) {
  return (
    <svg
      className="nav-ico"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={d} />
    </svg>
  )
}

const ICON = {
  dashboard: 'M4 13h7V4H4v9Zm0 7h7v-5H4v5Zm9 0h7v-9h-7v9Zm0-16v5h7V4h-7Z',
  clients: 'M16 19v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm13 8v-1a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8',
  outcome: 'M9 12h6m-6 4h6M9 8h2M6 3h9l5 5v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Zm8 .5V8h4.5',
  audit: 'M12 8v4l3 2m6-2a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z',
  costs: 'M12 2v20M17 6H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6',
} as const

export function Sidebar({
  vendor,
  onNavigate,
}: {
  vendor: Vendor | null
  /** Closes the drawer on mobile. Harmless on desktop. */
  onNavigate?: () => void
}) {
  const cls = ({ isActive }: { isActive: boolean }) =>
    `nav-item${isActive ? ' is-active' : ''}`

  return (
    <aside
      className="sidebar"
      onClick={(e) => {
        if ((e.target as HTMLElement).closest('a')) onNavigate?.()
      }}
    >
      <div className="brand">
        <div className="brand-badge" aria-hidden="true">VB</div>
        <div>
          <div className="brand-mark">VBC</div>
          <div className="brand-sub">Vendor Intelligence</div>
        </div>
      </div>

      <nav className="nav" aria-label="Main">
        <NavLink to="/" end className={cls}>
          <Icon d={ICON.dashboard} />
          Dashboard
        </NavLink>
        <NavLink to="/clients" className={cls}>
          <Icon d={ICON.clients} />
          Clients
        </NavLink>

        <div className="nav-label">
          Vendor flow
          {/* Without a vendor the nine steps are unreachable. Saying so beats
              nine identically greyed rows that look like a broken menu. */}
          {vendor ? (
            <span className="nav-count">
              {FLOW.filter((r) => stepDone(vendor, r)).length}/{FLOW.length}
            </span>
          ) : (
            <span className="nav-count is-muted">none open</span>
          )}
        </div>

        <div className={`nav-flow${vendor ? '' : ' is-locked'}`}>
          {FLOW.map((route, i) => {
            const done = stepDone(vendor, route)
            const inner = (
              <>
                <span className={`nav-step${done ? ' is-done' : ''}`}>
                  {done ? '✓' : i + 1}
                </span>
                {FLOW_LABEL[route]}
              </>
            )
            if (!vendor) {
              return (
                <span key={route} className="nav-item is-disabled">
                  {inner}
                </span>
              )
            }
            return (
              <NavLink key={route} to={`/vendor/${vendor.id}/${route}`} className={cls}>
                {inner}
              </NavLink>
            )
          })}
        </div>

        <div className="nav-label">Governance</div>
        <NavLink to="/outcome" className={cls}>
          <Icon d={ICON.outcome} />
          Outcome sheet
        </NavLink>
        <NavLink to="/audit" className={cls}>
          <Icon d={ICON.audit} />
          Audit trail
        </NavLink>
        <NavLink to="/costs" className={cls}>
          <Icon d={ICON.costs} />
          API cost reference
        </NavLink>
      </nav>

      <div className="nav-foot">
        <span className={`dot${API_MODE === 'mock' ? ' is-warn' : ' is-ok'}`} aria-hidden="true" />
        <span className="small muted">
          {API_MODE === 'mock' ? 'Mock data — no backend' : 'Connected to API'}
        </span>
      </div>
    </aside>
  )
}

export function Breadcrumb({ vendor, current }: { vendor: Vendor | null; current: string }) {
  return (
    <nav className="crumb" aria-label="Breadcrumb">
      <NavLink to="/">Dashboard</NavLink>
      {/* The client sits between the dashboard and the vendor, so the trail
          says whose vendor this is at every step. */}
      {vendor?.clientId && (
        <>
          <span className="crumb-sep">›</span>
          <NavLink to={`/clients/${vendor.clientId}`}>
            {vendor.clientName || vendor.clientId}
          </NavLink>
        </>
      )}
      {vendor && (
        <>
          <span className="crumb-sep">›</span>
          <NavLink to={`/vendor/${vendor.id}/findings`}>
            #{vendor.id} {vendor.name}
          </NavLink>
        </>
      )}
      <span className="crumb-sep">›</span>
      <span className="crumb-current">{current}</span>
    </nav>
  )
}

export function StepRail({ vendor, current }: { vendor: Vendor; current: FlowRoute }) {
  const navigate = useNavigate()
  return (
    <div className="rail" role="navigation" aria-label="Flow steps">
      {FLOW.map((route, i) => {
        const isCurrent = route === current
        const done = stepDone(vendor, route)
        return (
          <button
            key={route}
            type="button"
            className={`rail-step${isCurrent ? ' is-current' : ''}${done && !isCurrent ? ' is-done' : ''}`}
            onClick={() => navigate(`/vendor/${vendor.id}/${route}`)}
            aria-current={isCurrent ? 'step' : undefined}
          >
            <span className="rail-n">{done && !isCurrent ? '✓' : i + 1}</span>
            {FLOW_SHORT[route]}
          </button>
        )
      })}
    </div>
  )
}

export function ActionBar({
  vendor,
  current,
  primary,
}: {
  vendor: Vendor | null
  current: FlowRoute | null
  primary?: ReactNode
}) {
  const navigate = useNavigate()
  const index = current ? FLOW.indexOf(current) : -1

  // Alt + arrow walks the flow — analysts move through this many times a day.
  useEffect(() => {
    if (!vendor || index < 0) return
    const onKey = (e: KeyboardEvent) => {
      if (!e.altKey) return
      if (e.key === 'ArrowLeft' && index > 0) {
        navigate(`/vendor/${vendor.id}/${FLOW[index - 1]}`)
      }
      if (e.key === 'ArrowRight' && index < FLOW.length - 1) {
        navigate(`/vendor/${vendor.id}/${FLOW[index + 1]}`)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [vendor, index, navigate])

  return (
    <div className="actionbar">
      <button
        type="button"
        className="btn"
        disabled={index <= 0 || !vendor}
        onClick={() => vendor && navigate(`/vendor/${vendor.id}/${FLOW[index - 1]}`)}
      >
        ← Back
      </button>
      <span className="actionbar-step">
        {index >= 0 ? `Step ${index + 1} of ${FLOW.length}` : ''}
      </span>
      <div className="row">{primary}</div>
    </div>
  )
}

export function useVendorId(): string | undefined {
  return useParams<{ id: string }>().id
}