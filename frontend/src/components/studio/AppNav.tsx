import { Link, useNavigate, useRouterState } from '@tanstack/react-router'
import { LogOut, ShieldCheck } from 'lucide-react'
import { useEffect } from 'react'

import { oidcConfigured, useAuth } from '../../lib/auth'

const LINKS = [
  { to: '/create', label: 'Create' },
  { to: '/projects', label: 'Projects' },
  { to: '/app', label: 'Cloud workspaces' },
  { to: '/usage', label: 'Usage' },
] as const

export function AppNav() {
  const { me, status, signOut } = useAuth()
  const path = useRouterState({ select: (state) => state.location.pathname })
  return (
    <header className="st-nav">
      <Link to="/" className="lv-brand">
        <span className="lv-mark" />
        Omniweb
      </Link>
      <nav className="st-nav-links" aria-label="Primary">
        {LINKS.map((link) => (
          <Link key={link.to} to={link.to} className={path.startsWith(link.to) ? 'active' : ''}>
            {link.label}
          </Link>
        ))}
      </nav>
      <div className="st-nav-user">
        {status === 'signed_in' && me && (
          <>
            {me.auth_mode === 'development' && (
              <span className="st-pill st-pill-warn" title="OIDC is not configured, so the API uses a local development identity">
                <ShieldCheck size={12} /> Development identity
              </span>
            )}
            <span className="st-avatar" title={`${me.display_name} · ${me.email} · ${me.role}`}>
              {(me.display_name || me.email).charAt(0).toUpperCase()}
            </span>
            {oidcConfigured && (
              <button type="button" className="bd-icon" onClick={() => void signOut()} title="Sign out">
                <LogOut size={15} />
              </button>
            )}
          </>
        )}
      </div>
    </header>
  )
}

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { status, refresh } = useAuth()
  const navigate = useNavigate()
  const path = useRouterState({ select: (state) => state.location.href })
  useEffect(() => {
    if (status === 'signed_out') void navigate({ to: '/signin', search: { returnTo: path } })
  }, [status, navigate, path])
  if (status === 'loading' || status === 'signed_out') {
    return <div className="st-center"><span className="st-spinner" aria-label="Loading" /></div>
  }
  if (status === 'unavailable') {
    return (
      <div className="st-center st-stack">
        <h1>Omniweb can’t reach its API</h1>
        <p className="st-muted">The control plane at port 8010 isn’t responding. Start it and try again.</p>
        <button type="button" className="lv-btn lv-btn-light" onClick={() => void refresh()}>Try again</button>
      </div>
    )
  }
  return <>{children}</>
}
