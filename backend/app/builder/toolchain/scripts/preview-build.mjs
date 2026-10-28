// Builds a preview bundle for a generated app. Runs inside the build sandbox.
// Usage: node preview-build.mjs <web|mobile> <appDir> <outDir>
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { build } from 'vite'
import react from '@vitejs/plugin-react'
import { owLoc } from './ow-loc-plugin.mjs'

const [kind, appDir, outDir] = process.argv.slice(2)
const root = process.cwd()
const modules = path.resolve(import.meta.dirname, '..', 'node_modules')

if (kind === 'web') {
  await build({
    root: path.resolve(appDir),
    configFile: path.resolve(appDir, 'vite.config.ts'),
    base: './',
    logLevel: 'warn',
    plugins: [owLoc({ root })],
    build: { outDir: path.resolve(outDir), emptyOutDir: true },
  })
} else if (kind === 'mobile') {
  // Expo apps are previewed through react-native-web; native builds happen with EAS outside Omniweb.
  const shell = '/tmp/omniweb-mobile-preview'
  mkdirSync(shell, { recursive: true })
  const entry = path.resolve(appDir, 'App.tsx')
  writeFileSync(
    path.join(shell, 'index.html'),
    '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Mobile preview</title>' +
      '<style>html,body,#root{height:100%;margin:0}#root{display:flex}</style></head><body><div id="root"></div><script type="module" src="./entry.tsx"></script></body></html>',
  )
  writeFileSync(
    path.join(shell, 'entry.tsx'),
    `import { createRoot } from 'react-dom/client'\nimport App from ${JSON.stringify(entry)}\ncreateRoot(document.getElementById('root')!).render(<App />)\n`,
  )
  await build({
    root: shell,
    configFile: false,
    base: './',
    logLevel: 'warn',
    plugins: [owLoc({ root, native: true }), react()],
    define: {
      __DEV__: 'false',
      global: 'globalThis',
      'process.env.NODE_ENV': '"production"',
      'process.env.EXPO_PUBLIC_API_URL': '"api"',
    },
    resolve: {
      alias: [
        { find: /^react-native$/, replacement: path.join(modules, 'react-native-web') },
        { find: /^react-dom\/client$/, replacement: path.join(modules, 'react-dom/client.js') },
        { find: /^react\/jsx-runtime$/, replacement: path.join(modules, 'react/jsx-runtime.js') },
        { find: /^react$/, replacement: path.join(modules, 'react/index.js') },
      ],
      extensions: ['.web.tsx', '.web.ts', '.tsx', '.ts', '.web.js', '.js', '.json'],
    },
    build: { outDir: path.resolve(outDir), emptyOutDir: true },
  })
} else {
  console.error(`Unknown preview kind: ${kind}`)
  process.exit(2)
}
