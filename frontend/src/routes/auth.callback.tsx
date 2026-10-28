import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import { useEffect, useState } from 'react'

import { useAuth, userManager } from '../lib/auth'

export const Route = createFileRoute('/auth/callback')({
  component: Callback,
})

function Callback() {
  const navigate = useNavigate()
  const { refresh } = useAuth()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const users = userManager()
    if (!users) {
      setError('Single sign-on is not configured.')
      return
    }
    users
      .signinRedirectCallback()
      .then(async (user) => {
        await refresh()
        const returnTo = (user.state as { returnTo?: string } | undefined)?.returnTo
        await navigate({ to: returnTo?.startsWith('/') ? returnTo : '/projects' })
      })
      .catch(() => setError('Sign-in could not be completed. The link may have expired.'))
  }, [navigate, refresh])

  return (
    <div className="st-center st-stack">
      {error ? (
        <>
          <h1>Sign-in failed</h1>
          <p className="st-muted">{error}</p>
          <Link to="/signin" className="lv-btn lv-btn-light">Try again</Link>
        </>
      ) : (
        <span className="st-spinner" aria-label="Completing sign-in" />
      )}
    </div>
  )
}
