import { UserManager, WebStorageStateStore } from 'oidc-client-ts'
import { createContext, useCallback, useContext, useEffect, useState } from 'react'

export const OIDC_ISSUER: string | undefined = import.meta.env.VITE_OIDC_ISSUER
export const OIDC_CLIENT_ID: string = import.meta.env.VITE_OIDC_CLIENT_ID ?? 'omniweb-web'
export const oidcConfigured = Boolean(OIDC_ISSUER)

let manager: UserManager | null = null

export function userManager(): UserManager | null {
  if (!oidcConfigured || typeof window === 'undefined') return null
  manager ??= new UserManager({
    authority: OIDC_ISSUER!,
    client_id: OIDC_CLIENT_ID,
    redirect_uri: `${window.location.origin}/auth/callback`,
    post_logout_redirect_uri: `${window.location.origin}/`,
    response_type: 'code',
    scope: 'openid profile email',
    automaticSilentRenew: true,
    // Session storage limits token lifetime to the tab; refresh happens through the IdP session.
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
  })
  return manager
}

export async function accessToken(): Promise<string | null> {
  const user = await userManager()?.getUser()
  return user && !user.expired ? user.access_token : null
}

export interface Me {
  user_id: string
  organization_id: string
  email: string
  role: string
  display_name: string
  auth_mode: 'oidc' | 'development'
}

type Status = 'loading' | 'signed_in' | 'signed_out' | 'unavailable'

interface AuthState {
  status: Status
  me: Me | null
  signIn: (returnTo?: string) => Promise<void>
  signOut: () => Promise<void>
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthState>({
  status: 'loading',
  me: null,
  signIn: async () => {},
  signOut: async () => {},
  refresh: async () => {},
})

export function AuthProvider({ children, fetchMe }: { children: React.ReactNode; fetchMe: () => Promise<Me> }) {
  const [status, setStatus] = useState<Status>('loading')
  const [me, setMe] = useState<Me | null>(null)

  const refresh = useCallback(async () => {
    if (oidcConfigured && !(await accessToken())) {
      setMe(null)
      setStatus('signed_out')
      return
    }
    try {
      setMe(await fetchMe())
      setStatus('signed_in')
    } catch (error) {
      setMe(null)
      setStatus(error instanceof Error && /401|auth/i.test(error.message) ? 'signed_out' : 'unavailable')
    }
  }, [fetchMe])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const signIn = async (returnTo = '/projects') => {
    const users = userManager()
    if (!users) return
    await users.signinRedirect({ state: { returnTo } })
  }

  const signOut = async () => {
    const users = userManager()
    if (users) await users.signoutRedirect()
  }

  return <AuthContext.Provider value={{ status, me, signIn, signOut, refresh }}>{children}</AuthContext.Provider>
}

export const useAuth = () => useContext(AuthContext)
