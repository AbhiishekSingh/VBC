import { Navigate, Route, Routes, useLocation, useParams } from 'react-router-dom'
import { useEffect, useState } from 'react'

import {
  ActionBar,
  Breadcrumb,
  Sidebar,
  StepRail,
  ThemeToggle,
  useSidebarRail,
  type FlowRoute,
  FLOW_LABEL,
} from '@/components/Layout'
import { LoadingBlock } from '@/components/ui'
import { ToastProvider } from '@/hooks/useToast'
import { AuthProvider, useAuth } from '@/hooks/useAuth'
import { useVendor } from '@/hooks/useVendor'
import type { Vendor } from '@/types/domain'

import Dashboard from '@/pages/Dashboard'
import Login from '@/pages/Login'
import Clients from '@/pages/Clients'
import ClientDetail from '@/pages/ClientDetail'
import Submit from '@/pages/Submit'
import Select from '@/pages/Select'
import Findings from '@/pages/Findings'
import Manual from '@/pages/Manual'
import Surveillance from '@/pages/Surveillance'
import Scan from '@/pages/Scan'
import Risk from '@/pages/Risk'
import Report from '@/pages/Report'
import Decision from '@/pages/Decision'
import Outcome from '@/pages/Outcome'
import Audit from '@/pages/Audit'
import Costs from '@/pages/Costs'

export interface PageProps {
  vendor: Vendor
  setVendor: (v: Vendor) => void
  setPrimary: (node: React.ReactNode) => void
}

const FLOW_PAGES: Record<FlowRoute, React.ComponentType<PageProps>> = {
  submit: Submit,
  select: Select,
  findings: Findings,
  manual: Manual,
  surveillance: Surveillance,
  scan: Scan,
  risk: Risk,
  report: Report,
  decision: Decision,
}

/** Wraps a flow page with the furniture every one of them needs. */
function FlowPage() {
  const { id, page } = useParams<{ id: string; page: FlowRoute }>()
  const { vendor, setVendor, loading, error } = useVendor(id)
  const [primary, setPrimary] = useState<React.ReactNode>(null)

  const route = (page ?? 'findings') as FlowRoute
  const Page = FLOW_PAGES[route]

  if (loading) {
    return (
      <main className="content" id="main">
        <LoadingBlock label="Loading vendor…" />
      </main>
    )
  }
  if (error || !vendor) {
    return (
      <main className="content" id="main">
        <div className="callout k-adverse">{error ?? 'Vendor not found.'}</div>
      </main>
    )
  }
  if (!Page) return <Navigate to={`/vendor/${vendor.id}/findings`} replace />

  return (
    <>
      <main className="content" id="main">
        <Breadcrumb vendor={vendor} current={FLOW_LABEL[route]} />
        <StepRail vendor={vendor} current={route} />
        <Page vendor={vendor} setVendor={setVendor} setPrimary={setPrimary} />
      </main>
      <ActionBar vendor={vendor} current={route} primary={primary} />
    </>
  )
}

/** Governance pages sit outside the flow and share only the shell. */
function StandalonePage({
  title,
  children,
  crumb = true,
  bar = true,
}: {
  title: string
  children: React.ReactNode
  /** The dashboard IS the breadcrumb root, so it does not point at itself. */
  crumb?: boolean
  /** A "Back" button on the landing page has nowhere to go. */
  bar?: boolean
}) {
  return (
    <>
      <main className="content" id="main">
        {crumb && <Breadcrumb vendor={null} current={title} />}
        {children}
      </main>
      {bar && <ActionBar vendor={null} current={null} />}
    </>
  )
}

const RAIL_ICON =
  'M9 4v16M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v11a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 17.5v-11Z'

function Topbar({
  onMenu,
  rail,
  onRail,
}: {
  onMenu: () => void
  rail: boolean
  onRail: () => void
}) {
  const { user, signOut } = useAuth()
  const [open, setOpen] = useState(false)

  return (
    <header className="topbar">
      <div className="topbar-left">
        <button type="button" className="menu-btn" onClick={onMenu} aria-label="Open navigation">
          <span aria-hidden="true">&#9776;</span>
        </button>
        <button
          type="button"
          className="icon-btn rail-collapse"
          onClick={onRail}
          aria-pressed={rail}
          aria-label={rail ? 'Expand sidebar' : 'Collapse sidebar'}
          title={rail ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d={RAIL_ICON} />
          </svg>
        </button>
        <span className="small muted topbar-motto">
          The system automates the data layer. The analyst retains the decision layer.
        </span>
      </div>

      <div className="topbar-right">
        <ThemeToggle />
        <div className="user-menu">
          <button
            type="button"
            className="user-chip"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
          >
            <span className="user-avatar" aria-hidden="true">
              {(user?.name ?? '?').slice(0, 1).toUpperCase()}
            </span>
            <span className="user-text">
              <span className="user-name">{user?.name}</span>
              <span className="user-role">{user?.role}</span>
            </span>
          </button>

          {open && (
            <>
              <button
                type="button"
                className="menu-scrim"
                aria-label="Close menu"
                onClick={() => setOpen(false)}
              />
              {/* role="menu" with plain <button> children misreports the
                  item count to a screen reader; the children have to be
                  menuitems for the role to mean anything. */}
              <div className="user-pop" role="menu" aria-label="Account">
                <div className="user-pop-head">
                  <div className="user-pop-name">{user?.name}</div>
                  <div className="small muted">{user?.email}</div>
                </div>
                <button
                  type="button"
                  role="menuitem"
                  className="user-pop-item"
                  onClick={() => {
                    setOpen(false)
                    void signOut()
                  }}
                >
                  Sign out
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  )
}


function Shell() {
  // Read the vendor id from the PATH, not from useParams.
  //
  // Shell sits ABOVE <Routes>, so useParams here always returned {} and
  // the sidebar never saw a vendor — every "Vendor flow" link rendered as
  // a disabled span. The step rail at the top of each page still worked,
  // which is why it went unnoticed.
  const { pathname } = useLocation()
  const id = pathname.match(/^\/vendor\/([^/]+)/)?.[1]
  const { vendor } = useVendor(id)
  const [navOpen, setNavOpen] = useState(false)
  const [rail, toggleRail] = useSidebarRail()

  // Lock the page behind the drawer on mobile; restore on close.
  //
  // The class was already being toggled here, but NO CSS rule consumed it,
  // so the page went on scrolling behind an open drawer. global.css now has
  // `body.nav-open { overflow: hidden }`.
  useEffect(() => {
    document.body.classList.toggle('nav-open', navOpen)
    return () => document.body.classList.remove('nav-open')
  }, [navOpen])

  // Escape closes the drawer. Every other dismissible surface in the app
  // can be closed from the keyboard; this one could only be closed by
  // clicking the scrim.
  useEffect(() => {
    if (!navOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setNavOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [navOpen])

  return (
    <div className={`app${navOpen ? ' is-nav-open' : ''}${rail ? ' is-rail' : ''}`}>
      {/* Thirteen navigation rows stand between a keyboard user and the
          page on every single route. */}
      <a className="skip-link" href="#main">Skip to content</a>
      {navOpen && (
        <button
          type="button"
          className="nav-scrim"
          aria-label="Close navigation"
          onClick={() => setNavOpen(false)}
        />
      )}
      <Sidebar vendor={vendor} onNavigate={() => setNavOpen(false)} />
      <div className="main">
        <Topbar onMenu={() => setNavOpen((o) => !o)} rail={rail} onRail={toggleRail} />
        <Routes>
          {/* Wrapped like every other standalone page. Rendered bare, the
              dashboard had no <main className="content"> around it, so it
              got no page padding and its header button collided with the
              topbar. */}
          <Route
            path="/"
            element={
              <StandalonePage title="Dashboard" crumb={false} bar={false}>
                <Dashboard />
              </StandalonePage>
            }
          />
          <Route
            path="/clients"
            element={
              <StandalonePage title="Clients">
                <Clients />
              </StandalonePage>
            }
          />
          <Route
            path="/clients/:clientId"
            element={
              <StandalonePage title="Client">
                <ClientDetail />
              </StandalonePage>
            }
          />
          <Route path="/vendor/new" element={<NewVendor />} />
          <Route path="/vendor/:id/:page" element={<FlowPage />} />
          <Route
            path="/outcome"
            element={
              <StandalonePage title="Outcome sheet">
                <Outcome />
              </StandalonePage>
            }
          />
          <Route
            path="/audit"
            element={
              <StandalonePage title="Audit trail">
                <Audit />
              </StandalonePage>
            }
          />
          <Route
            path="/costs"
            element={
              <StandalonePage title="API cost reference">
                <Costs />
              </StandalonePage>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </div>
  )
}

/**
 * The gate.
 *
 * No route renders until the session is known. Signed out shows the login
 * screen and nothing else — a page that renders first and redirects later
 * flashes real data at someone who is not signed in.
 *
 * This is a convenience, not the control: every endpoint checks the session
 * itself, so hiding a route here is only about not showing a door that the
 * server would refuse to open.
 */
function Gate() {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <div className="auth-shell">
        <LoadingBlock label="Checking your session…" />
      </div>
    )
  }
  return user ? <Shell /> : <Login />
}

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <Gate />
      </ToastProvider>
    </AuthProvider>
  )
}

/** Intake, outside the vendor flow because no vendor exists yet. */
function NewVendor() {
  const [primary, setPrimary] = useState<React.ReactNode>(null)
  return (
    <>
      <main className="content" id="main">
        <Breadcrumb vendor={null} current="Add a vendor" />
        <Submit vendor={null} setVendor={() => {}} setPrimary={setPrimary} />
      </main>
      <ActionBar vendor={null} current={null} primary={primary} />
    </>
  )
}