import { HeadContent, Scripts, createRootRoute } from '@tanstack/react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import appCss from '../styles.css?url'
import omniwebCss from '../omniweb.css?url'
import builderCss from '../builder.css?url'
import studioCss from '../studio.css?url'
import { platform } from '../lib/api'
import { AuthProvider } from '../lib/auth'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 15_000, retry: 1 } },
})

export const Route = createRootRoute({
  head: () => ({
    meta: [
      {
        charSet: 'utf-8',
      },
      {
        name: 'viewport',
        content: 'width=device-width, initial-scale=1',
      },
      {
        title: 'Omniweb — Cloud development environments',
      },
    ],
    links: [
      { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' },
      {
        rel: 'stylesheet',
        href: appCss,
      },
      {
        rel: 'stylesheet',
        href: omniwebCss,
      },
      {
        rel: 'stylesheet',
        href: builderCss,
      },
      {
        rel: 'stylesheet',
        href: studioCss,
      },
    ],
  }),
  shellComponent: RootDocument,
})

function RootDocument({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <HeadContent />
      </head>
      <body>
        <QueryClientProvider client={queryClient}>
          <AuthProvider fetchMe={platform.me}>{children}</AuthProvider>
        </QueryClientProvider>
        <Scripts />
      </body>
    </html>
  )
}
