import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import { ArrowRight, KeyRound } from 'lucide-react'
import { useEffect } from 'react'
import { z } from 'zod'

import { OIDC_ISSUER, oidcConfigured, useAuth } from '../lib/auth'

export const Route = createFileRoute('/signin')({
  validateSearch: z.object({ returnTo: z.string().optional() }),
  head: () => ({ meta: [{ title: 'Sign in — Omniweb' }] }),
  component: SignIn,
})

function SignIn() {
  const { returnTo } = Route.useSearch()
  const { status, me, signIn } = useAuth()
  const navigate = useNavigate()
  const destination = returnTo?.startsWith('/') ? returnTo : '/projects'

  useEffect(() => {
    if (status === 'signed_in' && me?.auth_mode === 'oidc') void navigate({ to: destination })
  }, [status, me, navigate, destination])

  return (
    <div className="st-auth">
      <div className="lv-glow lv-glow-small" aria-hidden />
      <div className="st-auth-card">
        <Link to="/" className="lv-brand"><span className="lv-mark" />Omniweb</Link>
        <h1>Sign in to Omniweb</h1>
        {oidcConfigured ? (
          <>
            <p className="st-muted">You’ll continue to your organization’s identity provider. Omniweb never sees your password.</p>
            <button type="button" className="lv-btn lv-btn-light lv-btn-lg st-wide" onClick={() => void signIn(destination)}>
              <KeyRound size={16} /> Continue with single sign-on
            </button>
            <p className="st-fine">Identity provider: {OIDC_ISSUER}</p>
          </>
        ) : (
          <>
            <p className="st-muted">
              Single sign-on isn’t configured for this environment, so Omniweb is using a local development identity.
              Set <code>VITE_OIDC_ISSUER</code> and <code>OMNIWEB_OIDC_ISSUER</code> to enable OIDC sign-in.
            </p>
            <Link to={destination} className="lv-btn lv-btn-light lv-btn-lg st-wide">
              Continue as development user <ArrowRight size={16} />
            </Link>
          </>
        )}
      </div>
    </div>
  )
}
