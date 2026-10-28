"""Versioned templates that render an AppSpec into a repository.

Layout of every generated repository:
  apps/web            React + TypeScript + Vite + Tailwind CSS
  apps/mobile         Expo (React Native) app
  services/api        FastAPI + SQLAlchemy + Alembic
  packages/api-client Typed client shared by web and mobile
  infra/opentofu      DigitalOcean App Platform definition
"""

import json
import re
from pprint import pformat
from textwrap import dedent, indent

from .spec import AppSpec, EntitySpec, FieldSpec

TEMPLATE_VERSION = "2026.10.1"
SAMPLE_VALUES = {"string": "Sample", "text": "A longer description", "number": 42, "boolean": True, "date": "2026-01-15", "email": "person@example.com"}


def jsx_text(value: str) -> str:
    return "{" + json.dumps(value) + "}" if re.search(r"[{}<>]", value) or value != value.strip() else value


def page_component(entity: EntitySpec) -> str:
    return f"{entity.name}Page"


def _d(text: str) -> str:
    return dedent(text).lstrip("\n")


def render(spec: AppSpec, migrations: list[dict]) -> dict[str, str]:
    files: dict[str, str] = {}
    files.update(_root(spec))
    if "web" in spec.targets:
        files.update(_web(spec))
    if "mobile" in spec.targets:
        files.update(_mobile(spec))
    if "api" in spec.targets:
        files.update(_api(spec, migrations))
    if "api" in spec.targets and ({"web", "mobile"} & set(spec.targets)):
        files.update(_client())
    files.update(_infra(spec))
    return files


# --------------------------------------------------------------------------- shared schema

def _schema_ts(spec: AppSpec) -> str:
    entities = [
        {
            "name": e.name,
            "label": e.label,
            "slug": e.slug,
            "description": e.description,
            "fields": [{"name": f.name, "label": f.label, "type": f.type, "required": f.required} for f in e.fields],
        }
        for e in spec.entities
    ]
    return (
        _d(
            """
            // Generated from omniweb.json. Edit the spec in Omniweb, or change this file directly;
            // Omniweb will not overwrite files you have edited.
            export type FieldType = 'string' | 'text' | 'number' | 'boolean' | 'date' | 'email'
            export type FieldValue = string | number | boolean | null
            export type Row = { id: string; created_at: string } & { [field: string]: FieldValue }

            export interface FieldDef {
              name: string
              label: string
              type: FieldType
              required: boolean
            }

            export interface EntityDef {
              name: string
              label: string
              slug: string
              description: string
              fields: FieldDef[]
            }

            """
        )
        + "export const entities: EntityDef[] = "
        + json.dumps(entities, indent=2)
        + "\n\nexport function entityBySlug(slug: string): EntityDef | undefined {\n  return entities.find((entity) => entity.slug === slug)\n}\n"
    )


VALIDATE_TS = _d(
    """
    import type { EntityDef, FieldValue } from './schema'

    export type Draft = Record<string, FieldValue>

    const EMAIL = /^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/

    export function emptyDraft(entity: EntityDef): Draft {
      return Object.fromEntries(entity.fields.map((field) => [field.name, field.type === 'boolean' ? false : '']))
    }

    function isBlank(value: FieldValue | undefined): boolean {
      return value === '' || value === null || value === undefined
    }

    export function validate(entity: EntityDef, draft: Draft): Record<string, string> {
      const errors: Record<string, string> = {}
      for (const field of entity.fields) {
        const value = draft[field.name]
        if (field.required && field.type !== 'boolean' && isBlank(value)) {
          errors[field.name] = `${field.label} is required`
          continue
        }
        if (isBlank(value)) continue
        if (field.type === 'email' && !EMAIL.test(String(value))) errors[field.name] = 'Enter a valid email address'
        if (field.type === 'number' && Number.isNaN(Number(value))) errors[field.name] = 'Enter a number'
      }
      return errors
    }

    export function toPayload(entity: EntityDef, draft: Draft): Draft {
      return Object.fromEntries(
        entity.fields.map((field) => {
          const value = draft[field.name]
          if (field.type === 'boolean') return [field.name, Boolean(value)]
          if (isBlank(value)) return [field.name, null]
          if (field.type === 'number') return [field.name, Number(value)]
          return [field.name, value ?? null]
        }),
      )
    }

    export function formatValue(value: FieldValue | undefined, type: string): string {
      if (value === null || value === undefined || value === '') return '—'
      if (type === 'boolean') return value ? 'Yes' : 'No'
      if (type === 'number' && typeof value === 'number') return value.toLocaleString()
      return String(value)
    }
    """
)


# --------------------------------------------------------------------------- web

def _web(spec: AppSpec) -> dict[str, str]:
    api = "api" in spec.targets
    files: dict[str, str] = {}
    files["apps/web/package.json"] = json.dumps(
        {
            "name": f"{spec.slug}-web",
            "private": True,
            "version": "0.1.0",
            "type": "module",
            "scripts": {"dev": "vite", "build": "tsc --noEmit && vite build", "test": "vitest run", "preview": "vite preview"},
            "dependencies": {"react": "19.3.1", "react-dom": "19.3.1"},
            "devDependencies": {
                "@tailwindcss/vite": "4.3.3",
                "@types/react": "19.3.0",
                "@types/react-dom": "19.3.0",
                "@vitejs/plugin-react": "6.1.2",
                "tailwindcss": "4.3.3",
                "typescript": "6.0.3",
                "vite": "8.3.5",
                "vitest": "5.0.5",
            },
        },
        indent=2,
    ) + "\n"
    files["apps/web/tsconfig.json"] = json.dumps(
        {
            "compilerOptions": {
                "target": "ES2022",
                "lib": ["ES2022", "DOM", "DOM.Iterable"],
                "module": "ESNext",
                "moduleResolution": "Bundler",
                "jsx": "react-jsx",
                "strict": True,
                "noEmit": True,
                "skipLibCheck": True,
                "isolatedModules": True,
                "types": ["vite/client"],
            },
            "include": ["src"],
        },
        indent=2,
    ) + "\n"
    files["apps/web/vite.config.ts"] = _d(
        """
        import tailwindcss from '@tailwindcss/vite'
        import react from '@vitejs/plugin-react'
        import { defineConfig } from 'vite'

        export default defineConfig({
          plugins: [react(), tailwindcss()],
          server: { port: 5180, proxy: { '/api': 'http://localhost:8000' } },
        })
        """
    )
    files["apps/web/index.html"] = _d(
        f"""
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="UTF-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1.0" />
            <meta name="description" content="{_html(spec.tagline)}" />
            <title>{_html(spec.name)}</title>
          </head>
          <body>
            <div id="root"></div>
            <script type="module" src="/src/main.tsx"></script>
          </body>
        </html>
        """
    )
    files["apps/web/src/index.css"] = _d(
        f"""
        @import 'tailwindcss';

        @theme {{
          --color-accent: {spec.accent};
          --font-sans: 'Inter', ui-sans-serif, system-ui, sans-serif;
        }}

        body {{
          @apply bg-slate-50 text-slate-900 antialiased;
        }}
        """
    )
    files["apps/web/src/main.tsx"] = _d(
        """
        import { StrictMode } from 'react'
        import { createRoot } from 'react-dom/client'
        import App from './App'
        import './index.css'

        createRoot(document.getElementById('root')!).render(
          <StrictMode>
            <App />
          </StrictMode>,
        )
        """
    )
    files["apps/web/src/lib/router.ts"] = _d(
        """
        import { useEffect, useState } from 'react'

        function current(): string {
          return window.location.hash.replace(/^#/, '') || '/'
        }

        export function useRoute(): string {
          const [route, setRoute] = useState(current)
          useEffect(() => {
            const update = () => setRoute(current())
            window.addEventListener('hashchange', update)
            return () => window.removeEventListener('hashchange', update)
          }, [])
          return route
        }
        """
    )
    files["apps/web/src/data/schema.ts"] = _schema_ts(spec)
    files["apps/web/src/data/validate.ts"] = VALIDATE_TS
    files["apps/web/src/data/repository.ts"] = _web_repository(spec, api)
    files["apps/web/src/data/index.ts"] = (
        "import { apiRepository } from './repository'\n\nexport const repository = apiRepository()\n"
        if api
        else "import { localRepository } from './repository'\n\nexport const repository = localRepository()\n"
    )
    if api:
        files["apps/web/src/data/session.ts"] = _d(
            """
            const KEY = 'session-token'
            let token: string | null = readStored()
            const listeners = new Set<(token: string | null) => void>()

            function readStored(): string | null {
              try {
                return window.sessionStorage.getItem(KEY)
              } catch {
                return null
              }
            }

            export function getToken(): string | null {
              return token
            }

            export function setToken(value: string | null): void {
              token = value
              try {
                if (value) window.sessionStorage.setItem(KEY, value)
                else window.sessionStorage.removeItem(KEY)
              } catch {
                // Storage can be unavailable in private windows; the session then lasts for this tab only.
              }
              listeners.forEach((listener) => listener(value))
            }

            export function onTokenChange(listener: (token: string | null) => void): () => void {
              listeners.add(listener)
              return () => {
                listeners.delete(listener)
              }
            }
            """
        )
    files["apps/web/src/data/validate.test.ts"] = _d(
        """
        import { describe, expect, it } from 'vitest'
        import { entities } from './schema'
        import { emptyDraft, formatValue, toPayload, validate } from './validate'

        describe('validation', () => {
          it.each(entities.map((entity) => [entity.name, entity] as const))('%s requires its required fields', (_name, entity) => {
            const errors = validate(entity, emptyDraft(entity))
            for (const field of entity.fields.filter((f) => f.required && f.type !== 'boolean')) {
              expect(errors[field.name]).toContain('required')
            }
          })

          it('rejects malformed email addresses and numbers', () => {
            const entity = {
              name: 'Probe',
              label: 'Probes',
              slug: 'probes',
              description: '',
              fields: [
                { name: 'email', label: 'Email', type: 'email' as const, required: false },
                { name: 'count', label: 'Count', type: 'number' as const, required: false },
              ],
            }
            expect(validate(entity, { email: 'not-an-email', count: 'abc' })).toEqual({
              email: 'Enter a valid email address',
              count: 'Enter a number',
            })
            expect(toPayload(entity, { email: '', count: '3' })).toEqual({ email: null, count: 3 })
          })

          it('formats values for display', () => {
            expect(formatValue(true, 'boolean')).toBe('Yes')
            expect(formatValue(null, 'string')).toBe('—')
          })
        })
        """
    )
    if not api:
        files["apps/web/src/data/repository.test.ts"] = _d(
            """
            import { describe, expect, it } from 'vitest'
            import { localRepository, memoryStore } from './repository'

            describe('local repository', () => {
              it('creates, lists, and removes records', async () => {
                const repository = localRepository(memoryStore(), 'test')
                const created = await repository.create('things', { name: 'First' })
                expect(created.id).toBeTruthy()
                expect(await repository.list('things')).toHaveLength(1)
                await repository.remove('things', created.id)
                expect(await repository.list('things')).toHaveLength(0)
              })
            })
            """
        )
    files["apps/web/src/components/Layout.tsx"] = _web_layout(spec, api)
    files["apps/web/src/components/EntityManager.tsx"] = _web_entity_manager()
    files["apps/web/src/components/Count.tsx"] = _d(
        """
        import { useEffect, useState } from 'react'
        import { repository } from '../data'

        export function Count({ slug }: { slug: string }) {
          const [count, setCount] = useState<number | null>(null)
          useEffect(() => {
            repository
              .list(slug)
              .then((rows) => setCount(rows.length))
              .catch(() => setCount(null))
          }, [slug])
          return <>{count === null ? '—' : count.toLocaleString()}</>
        }
        """
    )
    files["apps/web/src/pages/Dashboard.tsx"] = _web_dashboard(spec)
    for index, entity in enumerate(spec.entities):
        files[f"apps/web/src/pages/{page_component(entity)}.tsx"] = _d(
            f"""
            import {{ EntityManager }} from '../components/EntityManager'
            import {{ entities }} from '../data/schema'

            const entity = entities[{index}]

            export function {page_component(entity)}() {{
              return (
                <div className="space-y-6">
                  <header>
                    <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{jsx_text(entity.label)}</h1>
                    <p className="mt-1 text-slate-600">{jsx_text(entity.description or f"Manage {entity.label.lower()}.")}</p>
                  </header>
                  <EntityManager entity={{entity}} />
                </div>
              )
            }}
            """
        )
    if spec.auth:
        files["apps/web/src/pages/SignIn.tsx"] = _web_sign_in(spec)
    files["apps/web/src/App.tsx"] = _web_app(spec)
    return files


def _html(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _web_repository(spec: AppSpec, api: bool) -> str:
    head = _d(
        """
        import type { Row } from './schema'
        import type { Draft } from './validate'

        export interface Repository {
          list(resource: string): Promise<Row[]>
          create(resource: string, draft: Draft): Promise<Row>
          remove(resource: string, id: string): Promise<void>
        }
        """
    )
    if api:
        return (
            "import { createClient } from '../../../../packages/api-client/src/index'\n"
            "import { getToken, setToken } from './session'\n"
            + head
            + _d(
                """

                export const client = createClient({
                  baseUrl: import.meta.env.VITE_API_URL ?? 'api',
                  getToken,
                  onUnauthorized: () => setToken(null),
                })

                export function apiRepository(): Repository {
                  return {
                    list: (resource) => client.list(resource),
                    create: (resource, draft) => client.create(resource, draft),
                    remove: (resource, id) => client.remove(resource, id),
                  }
                }
                """
            )
        )
    return head + _d(
        f"""

        export interface KeyValueStore {{
          getItem(key: string): string | null
          setItem(key: string, value: string): void
        }}

        export function memoryStore(): KeyValueStore {{
          const data = new Map<string, string>()
          return {{
            getItem: (key) => data.get(key) ?? null,
            setItem: (key, value) => {{
              data.set(key, value)
            }},
          }}
        }}

        function browserStore(): KeyValueStore {{
          try {{
            const storage = window.localStorage
            storage.setItem('__probe', '1')
            storage.removeItem('__probe')
            return storage
          }} catch {{
            return memoryStore()
          }}
        }}

        // Records are kept in this browser. Add a backend to the project to share data between devices.
        export function localRepository(store: KeyValueStore = browserStore(), namespace = {json.dumps(spec.slug)}): Repository {{
          const key = (resource: string) => `${{namespace}}:${{resource}}`
          const read = (resource: string): Row[] => {{
            try {{
              return JSON.parse(store.getItem(key(resource)) ?? '[]') as Row[]
            }} catch {{
              return []
            }}
          }}
          return {{
            async list(resource) {{
              return read(resource)
            }},
            async create(resource, draft) {{
              const row = {{ ...draft, id: crypto.randomUUID(), created_at: new Date().toISOString() }} as Row
              store.setItem(key(resource), JSON.stringify([row, ...read(resource)]))
              return row
            }},
            async remove(resource, id) {{
              store.setItem(key(resource), JSON.stringify(read(resource).filter((row) => row.id !== id)))
            }},
          }}
        }}
        """
    )


def _web_layout(spec: AppSpec, api: bool) -> str:
    sign_out = spec.auth
    return _d(
        f"""
        import type {{ ReactNode }} from 'react'
        import {{ entities }} from '../data/schema'

        export function Layout({{ route, children{', onSignOut' if sign_out else ''} }}: {{ route: string; children: ReactNode{'; onSignOut: () => void' if sign_out else ''} }}) {{
          const links = [{{ href: '/', label: 'Overview' }}, ...entities.map((entity) => ({{ href: `/${{entity.slug}}`, label: entity.label }}))]
          return (
            <div className="min-h-screen md:flex">
              <aside className="border-b border-slate-200 bg-white md:sticky md:top-0 md:h-screen md:w-64 md:shrink-0 md:border-r md:border-b-0">
                <div className="flex items-center gap-2.5 px-5 py-4">
                  <span className="size-7 rounded-lg bg-accent" />
                  <span className="text-base font-semibold tracking-tight">{jsx_text(spec.name)}</span>
                </div>
                <nav className="flex gap-1 overflow-x-auto px-3 pb-3 md:flex-col md:pb-0" aria-label="Main">
                  {{links.map((link) => (
                    <a
                      key={{link.href}}
                      href={{`#${{link.href}}`}}
                      className={{`whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition ${{
                        route === link.href ? 'bg-accent/10 text-accent' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                      }}`}}
                    >
                      {{link.label}}
                    </a>
                  ))}}
                </nav>{'''
                <div className="hidden px-3 pt-6 md:block">
                  <button type="button" onClick={onSignOut} className="w-full rounded-lg px-3 py-2 text-left text-sm text-slate-500 hover:bg-slate-100">
                    Sign out
                  </button>
                </div>''' if sign_out else ''}
              </aside>
              <main className="min-w-0 flex-1 px-5 py-8 md:px-10 md:py-10">{{children}}</main>
            </div>
          )
        }}
        """
    )


def _web_entity_manager() -> str:
    return _d(
        """
        import { useCallback, useEffect, useState, type FormEvent } from 'react'
        import { repository } from '../data'
        import type { EntityDef, FieldDef, Row } from '../data/schema'
        import { emptyDraft, formatValue, toPayload, validate, type Draft } from '../data/validate'

        function message(error: unknown): string {
          return error instanceof Error ? error.message : 'Something went wrong. Try again.'
        }

        function Input({ field, value, onChange }: { field: FieldDef; value: Draft[string]; onChange: (value: Draft[string]) => void }) {
          const base = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent/20'
          if (field.type === 'boolean') {
            return <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} className="mt-2 size-4 accent-accent" />
          }
          if (field.type === 'text') {
            return <textarea value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} rows={3} className={base} />
          }
          const type = field.type === 'number' ? 'number' : field.type === 'date' ? 'date' : field.type === 'email' ? 'email' : 'text'
          return <input type={type} value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} className={base} />
        }

        export function EntityManager({ entity }: { entity: EntityDef }) {
          const [rows, setRows] = useState<Row[] | null>(null)
          const [loadError, setLoadError] = useState<string | null>(null)
          const [draft, setDraft] = useState<Draft>(() => emptyDraft(entity))
          const [errors, setErrors] = useState<Record<string, string>>({})
          const [saveError, setSaveError] = useState<string | null>(null)
          const [saving, setSaving] = useState(false)
          const [open, setOpen] = useState(false)
          const columns = entity.fields.slice(0, 4)

          const load = useCallback(() => {
            setLoadError(null)
            repository.list(entity.slug).then(setRows).catch((error: unknown) => setLoadError(message(error)))
          }, [entity.slug])

          useEffect(load, [load])

          const submit = async (event: FormEvent) => {
            event.preventDefault()
            const found = validate(entity, draft)
            setErrors(found)
            if (Object.keys(found).length > 0) return
            setSaving(true)
            setSaveError(null)
            try {
              const row = await repository.create(entity.slug, toPayload(entity, draft))
              setRows((current) => [row, ...(current ?? [])])
              setDraft(emptyDraft(entity))
              setOpen(false)
            } catch (error) {
              setSaveError(message(error))
            } finally {
              setSaving(false)
            }
          }

          const remove = async (row: Row) => {
            try {
              await repository.remove(entity.slug, row.id)
              setRows((current) => (current ?? []).filter((item) => item.id !== row.id))
            } catch (error) {
              setLoadError(message(error))
            }
          }

          return (
            <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
              <div className="flex items-center justify-between gap-4 border-b border-slate-100 px-5 py-4">
                <p className="text-sm text-slate-500">{rows ? `${rows.length} ${rows.length === 1 ? 'record' : 'records'}` : 'Loading…'}</p>
                <button type="button" onClick={() => setOpen((value) => !value)} className="rounded-lg bg-accent px-3.5 py-2 text-sm font-medium text-white shadow-sm hover:opacity-90">
                  {open ? 'Close' : `Add ${entity.name.replace(/([a-z])([A-Z])/g, '$1 $2').toLowerCase()}`}
                </button>
              </div>

              {open && (
                <form onSubmit={submit} className="grid gap-4 border-b border-slate-100 px-5 py-5 sm:grid-cols-2" noValidate>
                  {entity.fields.map((field) => (
                    <label key={field.name} className={`text-sm font-medium text-slate-700 ${field.type === 'text' ? 'sm:col-span-2' : ''}`}>
                      {field.label}
                      {field.required && <span className="text-accent"> *</span>}
                      <Input field={field} value={draft[field.name]} onChange={(value) => setDraft({ ...draft, [field.name]: value })} />
                      {errors[field.name] && <span className="mt-1 block text-xs font-normal text-red-600">{errors[field.name]}</span>}
                    </label>
                  ))}
                  <div className="flex items-center gap-3 sm:col-span-2">
                    <button type="submit" disabled={saving} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
                      {saving ? 'Saving…' : 'Save'}
                    </button>
                    {saveError && <span className="text-sm text-red-600">{saveError}</span>}
                  </div>
                </form>
              )}

              {loadError ? (
                <div className="px-5 py-10 text-center">
                  <p className="text-sm text-red-600">{loadError}</p>
                  <button type="button" onClick={load} className="mt-3 text-sm font-medium text-accent">Try again</button>
                </div>
              ) : rows === null ? (
                <div className="space-y-2 px-5 py-6">
                  {[0, 1, 2].map((i) => <div key={i} className="h-10 animate-pulse rounded-lg bg-slate-100" />)}
                </div>
              ) : rows.length === 0 ? (
                <div className="px-5 py-14 text-center">
                  <p className="font-medium text-slate-900">No {entity.label.toLowerCase()} yet</p>
                  <p className="mt-1 text-sm text-slate-500">Add the first one to get started.</p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="text-xs uppercase tracking-wide text-slate-500">
                      <tr>
                        {columns.map((field) => <th key={field.name} className="px-5 py-3 font-medium">{field.label}</th>)}
                        <th className="px-5 py-3" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {rows.map((row) => (
                        <tr key={row.id} className="hover:bg-slate-50">
                          {columns.map((field) => <td key={field.name} className="px-5 py-3 text-slate-700">{formatValue(row[field.name], field.type)}</td>)}
                          <td className="px-5 py-3 text-right">
                            <button type="button" onClick={() => void remove(row)} className="text-xs font-medium text-slate-400 hover:text-red-600">Delete</button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )
        }
        """
    )


def _web_dashboard(spec: AppSpec) -> str:
    cards = "\n".join(
        f"""        <a href="#/{e.slug}" className="group rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-accent/40 hover:shadow-md">
          <p className="text-sm font-medium text-slate-500">{jsx_text(e.label)}</p>
          <p className="mt-2 text-3xl font-semibold tracking-tight text-slate-900"><Count slug="{e.slug}" /></p>
          <p className="mt-3 text-sm text-slate-600">{jsx_text(e.description or f"Manage {e.label.lower()}.")}</p>
        </a>"""
        for e in spec.entities
    )
    return (
        "import { Count } from '../components/Count'\n\n"
        "export function Dashboard() {\n"
        "  return (\n"
        '    <div className="space-y-8">\n'
        '      <section className="rounded-3xl bg-gradient-to-br from-accent to-slate-900 px-6 py-10 text-white shadow-lg md:px-10">\n'
        f'        <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">{jsx_text(spec.name)}</h1>\n'
        f'        <p className="mt-3 max-w-2xl text-white/80">{jsx_text(spec.tagline or "Everything in one place.")}</p>\n'
        "      </section>\n"
        '      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">\n'
        f"{cards}\n"
        "      </section>\n"
        "    </div>\n"
        "  )\n"
        "}\n"
    )


def _web_sign_in(spec: AppSpec) -> str:
    return _d(
        f"""
        import {{ useState, type FormEvent }} from 'react'
        import {{ client }} from '../data/repository'

        export function SignIn({{ onSignedIn }}: {{ onSignedIn: (token: string) => void }}) {{
          const [mode, setMode] = useState<'sign-in' | 'register'>('sign-in')
          const [email, setEmail] = useState('')
          const [password, setPassword] = useState('')
          const [error, setError] = useState<string | null>(null)
          const [busy, setBusy] = useState(false)

          const submit = async (event: FormEvent) => {{
            event.preventDefault()
            setBusy(true)
            setError(null)
            try {{
              const result = mode === 'sign-in' ? await client.signIn(email, password) : await client.register(email, password)
              onSignedIn(result.access_token)
            }} catch (caught) {{
              setError(caught instanceof Error ? caught.message : 'Could not sign in')
            }} finally {{
              setBusy(false)
            }}
          }}

          return (
            <div className="flex min-h-screen items-center justify-center bg-slate-100 px-4">
              <form onSubmit={{submit}} className="w-full max-w-sm space-y-4 rounded-2xl border border-slate-200 bg-white p-7 shadow-sm">
                <div className="flex items-center gap-2.5">
                  <span className="size-7 rounded-lg bg-accent" />
                  <span className="font-semibold tracking-tight">{jsx_text(spec.name)}</span>
                </div>
                <h1 className="text-xl font-semibold tracking-tight">{{mode === 'sign-in' ? 'Sign in' : 'Create your account'}}</h1>
                <label className="block text-sm font-medium text-slate-700">
                  Email
                  <input type="email" required value={{email}} onChange={{(e) => setEmail(e.target.value)}} autoComplete="email" className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-accent" />
                </label>
                <label className="block text-sm font-medium text-slate-700">
                  Password
                  <input type="password" required minLength={{8}} value={{password}} onChange={{(e) => setPassword(e.target.value)}} autoComplete={{mode === 'sign-in' ? 'current-password' : 'new-password'}} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-accent" />
                </label>
                {{error && <p className="text-sm text-red-600">{{error}}</p>}}
                <button type="submit" disabled={{busy}} className="w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50">
                  {{busy ? 'Please wait…' : mode === 'sign-in' ? 'Sign in' : 'Create account'}}
                </button>
                <button type="button" onClick={{() => setMode(mode === 'sign-in' ? 'register' : 'sign-in')}} className="w-full text-center text-sm text-slate-500 hover:text-slate-900">
                  {{mode === 'sign-in' ? 'New here? Create an account' : 'Already have an account? Sign in'}}
                </button>
              </form>
            </div>
          )
        }}
        """
    )


def _web_app(spec: AppSpec) -> str:
    imports = "\n".join(f"import {{ {page_component(e)} }} from './pages/{page_component(e)}'" for e in spec.entities)
    cases = "\n".join(f"    case '/{e.slug}':\n      return <{page_component(e)} />" for e in spec.entities)
    not_found = _d(
        """
        function NotFound() {
          return (
            <div className="py-20 text-center">
              <h1 className="text-2xl font-semibold">Page not found</h1>
              <a href="#/" className="mt-4 inline-block text-sm font-medium text-accent">Back to overview</a>
            </div>
          )
        }
        """
    )
    router = f"function page(route: string) {{\n  switch (route) {{\n    case '/':\n      return <Dashboard />\n{cases}\n    default:\n      return <NotFound />\n  }}\n}}\n"
    if spec.auth:
        return (
            "import { useEffect, useState } from 'react'\n"
            "import { Layout } from './components/Layout'\n"
            "import { getToken, onTokenChange, setToken } from './data/session'\n"
            "import { useRoute } from './lib/router'\n"
            "import { Dashboard } from './pages/Dashboard'\n"
            "import { SignIn } from './pages/SignIn'\n"
            f"{imports}\n\n{not_found}\n{router}\n"
            + _d(
                """
                export default function App() {
                  const route = useRoute()
                  const [token, setTokenState] = useState(getToken)
                  useEffect(() => onTokenChange(setTokenState), [])
                  if (!token) return <SignIn onSignedIn={setToken} />
                  return (
                    <Layout route={route} onSignOut={() => setToken(null)}>
                      {page(route)}
                    </Layout>
                  )
                }
                """
            )
        )
    return (
        "import { Layout } from './components/Layout'\n"
        "import { useRoute } from './lib/router'\n"
        "import { Dashboard } from './pages/Dashboard'\n"
        f"{imports}\n\n{not_found}\n{router}\n"
        + _d(
            """
            export default function App() {
              const route = useRoute()
              return <Layout route={route}>{page(route)}</Layout>
            }
            """
        )
    )


# --------------------------------------------------------------------------- shared API client

def _client() -> dict[str, str]:
    return {
        "packages/api-client/package.json": json.dumps(
            {"name": "@app/api-client", "private": True, "version": "0.1.0", "type": "module", "main": "src/index.ts", "types": "src/index.ts"}, indent=2
        )
        + "\n",
        "packages/api-client/src/index.ts": _d(
            """
            // Typed client for the generated FastAPI service, shared by the web and mobile apps.
            export type FieldValue = string | number | boolean | null
            export type Row = { id: string; created_at: string } & { [field: string]: FieldValue }
            export type Payload = Record<string, FieldValue>

            export class ApiError extends Error {
              status: number
              constructor(status: number, message: string) {
                super(message)
                this.status = status
              }
            }

            export interface ClientOptions {
              baseUrl?: string
              getToken?: () => string | null
              onUnauthorized?: () => void
            }

            function describe(body: unknown, status: number): string {
              if (body && typeof body === 'object' && 'detail' in body) {
                const detail = (body as { detail: unknown }).detail
                if (typeof detail === 'string') return detail
                if (Array.isArray(detail)) {
                  return detail
                    .map((item) => (item && typeof item === 'object' && 'msg' in item ? String((item as { msg: unknown }).msg) : 'Invalid value'))
                    .join('; ')
                }
              }
              return `Request failed (${status})`
            }

            export function createClient(options: ClientOptions = {}) {
              const base = (options.baseUrl ?? 'api').replace(/\\/$/, '')

              async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
                const headers: Record<string, string> = { 'Content-Type': 'application/json' }
                const token = options.getToken?.()
                if (token) headers.Authorization = `Bearer ${token}`
                let response: Response
                try {
                  response = await fetch(`${base}${path}`, { ...init, headers })
                } catch {
                  throw new ApiError(0, 'Can’t reach the server. Check your connection and try again.')
                }
                if (response.status === 401 && token) options.onUnauthorized?.()
                if (!response.ok) {
                  const body: unknown = await response.json().catch(() => null)
                  throw new ApiError(response.status, describe(body, response.status))
                }
                if (response.status === 204) return undefined as T
                return (await response.json()) as T
              }

              const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) })

              return {
                list: (resource: string) => request<Row[]>(`/${resource}`),
                get: (resource: string, id: string) => request<Row>(`/${resource}/${id}`),
                create: (resource: string, payload: Payload) => request<Row>(`/${resource}`, json('POST', payload)),
                update: (resource: string, id: string, payload: Payload) => request<Row>(`/${resource}/${id}`, json('PUT', payload)),
                remove: (resource: string, id: string) => request<void>(`/${resource}/${id}`, { method: 'DELETE' }),
                register: (email: string, password: string) => request<{ access_token: string }>('/auth/register', json('POST', { email, password })),
                signIn: (email: string, password: string) => request<{ access_token: string }>('/auth/login', json('POST', { email, password })),
              }
            }

            export type Client = ReturnType<typeof createClient>
            """
        ),
    }


# --------------------------------------------------------------------------- API

PY_TYPES = {"string": ("String(255)", "str"), "email": ("String(320)", "str"), "text": ("Text", "str"), "number": ("Float", "float"), "boolean": ("Boolean", "bool"), "date": ("Date", "dt.date")}
SA_TYPES = {"string": "sa.String(255)", "email": "sa.String(320)", "text": "sa.Text()", "number": "sa.Float()", "boolean": "sa.Boolean()", "date": "sa.Date()"}


def _module(entity: EntitySpec) -> str:
    return entity.table


def _api(spec: AppSpec, migrations: list[dict]) -> dict[str, str]:
    files: dict[str, str] = {}
    files["services/api/requirements.txt"] = _d(
        """
        alembic==1.20.1
        fastapi==0.162.0
        pydantic==2.14.1
        pyjwt==2.15.1
        sqlalchemy==2.1.6
        uvicorn==0.54.0
        psycopg[binary]==3.3.2
        """
    )
    files["services/api/requirements-dev.txt"] = "-r requirements.txt\nhttpx==0.28.1\npytest==9.2.0\n"
    files["services/api/pyproject.toml"] = _d(
        f"""
        [project]
        name = "{spec.slug}-api"
        version = "0.1.0"
        requires-python = ">=3.12"

        [tool.pytest.ini_options]
        pythonpath = ["."]
        testpaths = ["tests"]
        """
    )
    files["services/api/Dockerfile"] = _d(
        """
        FROM python:3.12-slim
        ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
        RUN useradd --create-home --uid 10001 app
        WORKDIR /app
        COPY requirements.txt ./
        RUN pip install --no-cache-dir -r requirements.txt
        COPY . .
        USER app
        EXPOSE 8000
        CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
        """
    )
    files["services/api/app/__init__.py"] = ""
    files["services/api/app/config.py"] = _d(
        """
        import os
        import secrets


        def _database_url() -> str:
            url = os.getenv("DATABASE_URL", "sqlite:///./app.db")
            for prefix in ("postgres://", "postgresql://"):
                if url.startswith(prefix):
                    return "postgresql+psycopg://" + url[len(prefix):]
            return url


        class Settings:
            def __init__(self) -> None:
                self.environment = os.getenv("APP_ENV", "development")
                self.database_url = _database_url()
                secret = os.getenv("SECRET_KEY", "")
                if not secret:
                    if self.environment == "production":
                        raise RuntimeError("SECRET_KEY must be set in production")
                    # Development only: sessions reset when the process restarts.
                    secret = secrets.token_urlsafe(32)
                self.secret_key = secret
                self.cors_origins = [o for o in os.getenv("CORS_ORIGINS", "http://localhost:5180").split(",") if o]


        settings = Settings()
        """
    )
    files["services/api/app/db.py"] = _d(
        """
        from collections.abc import Iterator

        from sqlalchemy import create_engine
        from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

        from .config import settings

        connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
        engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
        SessionLocal = sessionmaker(engine, expire_on_commit=False)


        class Base(DeclarativeBase):
            pass


        def get_db() -> Iterator[Session]:
            with SessionLocal() as session:
                yield session
        """
    )
    files["services/api/app/models.py"] = _api_models(spec)
    files["services/api/app/schemas.py"] = _api_schemas(spec)
    files["services/api/app/routers/__init__.py"] = ""
    for entity in spec.entities:
        files[f"services/api/app/routers/{_module(entity)}.py"] = _api_router(entity, spec.auth)
    if spec.auth:
        files["services/api/app/auth.py"] = _api_auth(spec)
    routers = ", ".join(_module(e) for e in spec.entities)
    files["services/api/app/main.py"] = (
        "from fastapi import FastAPI\nfrom fastapi.middleware.cors import CORSMiddleware\n\n"
        + ("from . import auth\n" if spec.auth else "")
        + "from .config import settings\n"
        + f"from .routers import {routers}\n\n"
        + f"app = FastAPI(title={json.dumps(spec.name)}, version=\"0.1.0\", docs_url=\"/api/docs\", openapi_url=\"/api/openapi.json\")\n"
        + "app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=[\"*\"], allow_headers=[\"*\"])\n\n\n"
        + "@app.get(\"/api/health\", tags=[\"Operations\"])\ndef health() -> dict[str, str]:\n    return {\"status\": \"ok\"}\n\n\n"
        + ("app.include_router(auth.router)\n" if spec.auth else "")
        + "".join(f"app.include_router({_module(e)}.router)\n" for e in spec.entities)
    )
    files["services/api/alembic.ini"] = "[alembic]\nscript_location = migrations\nprepend_sys_path = .\n"
    files["services/api/migrations/script.py.mako"] = _d(
        '''
        """${message}

        Revision ID: ${up_revision}
        Revises: ${down_revision | comma,n}
        """
        import sqlalchemy as sa
        from alembic import op

        revision = ${repr(up_revision)}
        down_revision = ${repr(down_revision)}
        branch_labels = None
        depends_on = None


        def upgrade() -> None:
            ${upgrades if upgrades else "pass"}


        def downgrade() -> None:
            ${downgrades if downgrades else "pass"}
        '''
    )
    files["services/api/migrations/env.py"] = _d(
        """
        from alembic import context
        from sqlalchemy import engine_from_config, pool

        from app import models  # noqa: F401  registers tables on Base.metadata
        from app.config import settings
        from app.db import Base

        config = context.config
        config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
        target_metadata = Base.metadata


        def run_offline() -> None:
            context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
            with context.begin_transaction():
                context.run_migrations()


        def run_online() -> None:
            connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
            with connectable.connect() as connection:
                context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
                with context.begin_transaction():
                    context.run_migrations()


        if context.is_offline_mode():
            run_offline()
        else:
            run_online()
        """
    )
    for migration in migrations:
        files[f"services/api/migrations/versions/{migration['revision']}_{migration['slug']}.py"] = _migration_file(migration)
    files["services/api/tests/__init__.py"] = ""
    files["services/api/tests/conftest.py"] = _api_conftest(spec)
    files["services/api/tests/test_api.py"] = _api_tests(spec)
    return files


def _api_models(spec: AppSpec) -> str:
    used = {"String", "DateTime"} | {PY_TYPES[f.type][0].split("(")[0] for e in spec.entities for f in e.fields}
    lines = [
        "import datetime as dt",
        "import uuid",
        "",
        f"from sqlalchemy import {', '.join(sorted(used))}",
        "from sqlalchemy.orm import Mapped, mapped_column",
        "",
        "from .db import Base",
        "",
        "",
        "def new_id() -> str:",
        "    return str(uuid.uuid4())",
        "",
        "",
        "def utcnow() -> dt.datetime:",
        "    return dt.datetime.now(dt.UTC)",
    ]
    if spec.auth:
        lines += [
            "",
            "",
            "class User(Base):",
            '    __tablename__ = "users"',
            "",
            "    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)",
            "    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)",
            "    password_hash: Mapped[str] = mapped_column(String(255))",
            '    role: Mapped[str] = mapped_column(String(40), default="member")',
            "    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)",
        ]
    for entity in spec.entities:
        lines += [
            "",
            "",
            f"class {entity.name}(Base):",
            f'    __tablename__ = "{entity.table}"',
            "",
            "    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)",
            "    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)",
        ]
        for field in entity.fields:
            column, py = PY_TYPES[field.type]
            lines.append(f"    {field.name}: Mapped[{py} | None] = mapped_column({column}, nullable=True)")
    return "\n".join(lines) + "\n"


def _field_annotation(field: FieldSpec, optional: bool) -> str:
    py = PY_TYPES[field.type][1]
    if field.type == "boolean":
        return f"{field.name}: bool | None = False"
    if optional or not field.required:
        constraint = ""
        if field.type == "email":
            constraint = " = Field(default=None, max_length=320, pattern=EMAIL)"
        elif field.type in {"string"}:
            constraint = " = Field(default=None, max_length=255)"
        else:
            constraint = " = None"
        return f"{field.name}: {py} | None{constraint}"
    if field.type == "email":
        return f"{field.name}: str = Field(max_length=320, pattern=EMAIL)"
    if field.type == "string":
        return f"{field.name}: str = Field(min_length=1, max_length=255)"
    if field.type == "text":
        return f"{field.name}: str = Field(min_length=1)"
    return f"{field.name}: {py}"


def _api_schemas(spec: AppSpec) -> str:
    lines = [
        "import datetime as dt",
        "",
        "from pydantic import BaseModel, ConfigDict, Field",
        "",
        'EMAIL = r"^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$"',
    ]
    for entity in spec.entities:
        lines += ["", "", f"class {entity.name}In(BaseModel):"]
        lines += [f"    {_field_annotation(f, False)}" for f in entity.fields]
        lines += ["", "", f"class {entity.name}Out(BaseModel):", "    model_config = ConfigDict(from_attributes=True)", "", "    id: str", "    created_at: dt.datetime"]
        lines += [f"    {f.name}: {PY_TYPES[f.type][1]} | None = None" for f in entity.fields]
    return "\n".join(lines) + "\n"


def _api_router(entity: EntitySpec, auth: bool) -> str:
    var = entity.table
    singular = re.sub(r"(?<!^)(?=[A-Z])", "_", entity.name).lower()
    deps = ", dependencies=[Depends(current_user)]" if auth else ""
    return (
        "from fastapi import APIRouter, Depends, HTTPException, Response, status\n"
        "from sqlalchemy import select\n"
        "from sqlalchemy.orm import Session\n\n"
        + ("from ..auth import current_user\n" if auth else "")
        + "from ..db import get_db\n"
        + f"from ..models import {entity.name}\n"
        + f"from ..schemas import {entity.name}In, {entity.name}Out\n\n"
        + f'router = APIRouter(prefix="/api/{entity.slug}", tags=[{json.dumps(entity.label)}]{deps})\n\n\n'
        + f"def _get(db: Session, row_id: str) -> {entity.name}:\n"
        + f"    row = db.get({entity.name}, row_id)\n"
        + "    if row is None:\n"
        + f'        raise HTTPException(status_code=404, detail="{entity.name} not found")\n'
        + "    return row\n\n\n"
        + f'@router.get("", response_model=list[{entity.name}Out])\n'
        + f"def list_{var}(db: Session = Depends(get_db)) -> list[{entity.name}]:\n"
        + f"    return list(db.scalars(select({entity.name}).order_by({entity.name}.created_at.desc())))\n\n\n"
        + f'@router.post("", response_model={entity.name}Out, status_code=status.HTTP_201_CREATED)\n'
        + f"def create_{singular}(data: {entity.name}In, db: Session = Depends(get_db)) -> {entity.name}:\n"
        + f"    row = {entity.name}(**data.model_dump())\n"
        + "    db.add(row)\n    db.commit()\n    db.refresh(row)\n    return row\n\n\n"
        + f'@router.get("/{{row_id}}", response_model={entity.name}Out)\n'
        + f"def get_{singular}(row_id: str, db: Session = Depends(get_db)) -> {entity.name}:\n"
        + "    return _get(db, row_id)\n\n\n"
        + f'@router.put("/{{row_id}}", response_model={entity.name}Out)\n'
        + f"def update_{singular}(row_id: str, data: {entity.name}In, db: Session = Depends(get_db)) -> {entity.name}:\n"
        + "    row = _get(db, row_id)\n"
        + "    for key, value in data.model_dump().items():\n        setattr(row, key, value)\n"
        + "    db.commit()\n    db.refresh(row)\n    return row\n\n\n"
        + f'@router.delete("/{{row_id}}", status_code=status.HTTP_204_NO_CONTENT)\n'
        + f"def delete_{singular}(row_id: str, db: Session = Depends(get_db)) -> Response:\n"
        + "    db.delete(_get(db, row_id))\n    db.commit()\n    return Response(status_code=204)\n"
    )


def _api_auth(spec: AppSpec) -> str:
    first_role = json.dumps(spec.roles[0] if spec.roles else "member")
    return _d(
        f'''
        import base64
        import hashlib
        import hmac
        import os
        from datetime import UTC, datetime, timedelta

        import jwt
        from fastapi import APIRouter, Depends, HTTPException, status
        from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
        from pydantic import BaseModel, Field
        from sqlalchemy import func, select
        from sqlalchemy.orm import Session

        from .config import settings
        from .db import get_db
        from .models import User

        bearer = HTTPBearer(auto_error=False)
        router = APIRouter(prefix="/api/auth", tags=["Authentication"])
        DEFAULT_ROLE = {first_role}


        def hash_password(password: str) -> str:
            salt = os.urandom(16)
            digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
            return base64.b64encode(salt + digest).decode()


        def verify_password(password: str, stored: str) -> bool:
            raw = base64.b64decode(stored.encode())
            salt, digest = raw[:16], raw[16:]
            return hmac.compare_digest(digest, hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1))


        def issue_token(user: User) -> str:
            now = datetime.now(UTC)
            claims = {{"sub": user.id, "role": user.role, "iat": now, "exp": now + timedelta(hours=12)}}
            return jwt.encode(claims, settings.secret_key, algorithm="HS256")


        def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
            if credentials is None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in to continue")
            try:
                claims = jwt.decode(credentials.credentials, settings.secret_key, algorithms=["HS256"])
            except jwt.PyJWTError as exc:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your session has expired") from exc
            user = db.get(User, claims.get("sub"))
            if user is None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account not found")
            return user


        class Credentials(BaseModel):
            email: str = Field(max_length=320, pattern=r"^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$")
            password: str = Field(min_length=8, max_length=128)


        class Token(BaseModel):
            access_token: str
            token_type: str = "bearer"


        class Me(BaseModel):
            id: str
            email: str
            role: str


        @router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
        def register(data: Credentials, db: Session = Depends(get_db)) -> Token:
            email = data.email.lower()
            if db.scalar(select(User).where(User.email == email)):
                raise HTTPException(status_code=409, detail="An account with that email already exists")
            first = (db.scalar(select(func.count(User.id))) or 0) == 0
            user = User(email=email, password_hash=hash_password(data.password), role="admin" if first else DEFAULT_ROLE)
            db.add(user)
            db.commit()
            return Token(access_token=issue_token(user))


        @router.post("/login", response_model=Token)
        def login(data: Credentials, db: Session = Depends(get_db)) -> Token:
            user = db.scalar(select(User).where(User.email == data.email.lower()))
            if user is None or not verify_password(data.password, user.password_hash):
                raise HTTPException(status_code=401, detail="Email or password is incorrect")
            return Token(access_token=issue_token(user))


        @router.get("/me", response_model=Me)
        def me(user: User = Depends(current_user)) -> Me:
            return Me(id=user.id, email=user.email, role=user.role)
        '''
    )


def _api_conftest(spec: AppSpec) -> str:
    base = _d(
        """
        import os
        import tempfile

        _directory = tempfile.mkdtemp()
        os.environ["DATABASE_URL"] = f"sqlite:///{_directory}/test.db"
        os.environ.setdefault("SECRET_KEY", "generated-tests-only-secret-key-0123456789abcdef")

        import pytest  # noqa: E402
        from fastapi.testclient import TestClient  # noqa: E402

        from app.db import Base, engine  # noqa: E402
        from app.main import app  # noqa: E402


        @pytest.fixture()
        def client():
            Base.metadata.drop_all(engine)
            Base.metadata.create_all(engine)
            with TestClient(app) as test_client:
                yield test_client
        """
    )
    if spec.auth:
        base += _d(
            """


            @pytest.fixture()
            def api(client):
                response = client.post("/api/auth/register", json={"email": "owner@example.com", "password": "correct-horse-battery"})
                assert response.status_code == 201, response.text
                client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
                return client
            """
        )
    else:
        base += "\n\n@pytest.fixture()\ndef api(client):\n    return client\n"
    return base


def _api_tests(spec: AppSpec) -> str:
    samples = {e.slug: {f.name: SAMPLE_VALUES[f.type] for f in e.fields} for e in spec.entities}
    required = {e.slug: [f.name for f in e.fields if f.required and f.type != "boolean"] for e in spec.entities}
    text = (
        "import pytest\n\n"
        f"SAMPLES = {pformat(samples, indent=4, sort_dicts=False)}\n"
        f"REQUIRED = {pformat(required, indent=4, sort_dicts=False)}\n\n\n"
        + _d(
            """
            def test_health(client):
                assert client.get("/api/health").json() == {"status": "ok"}


            @pytest.mark.parametrize("resource", list(SAMPLES))
            def test_create_read_update_delete(api, resource):
                created = api.post(f"/api/{resource}", json=SAMPLES[resource])
                assert created.status_code == 201, created.text
                row = created.json()
                assert row["id"]
                assert any(item["id"] == row["id"] for item in api.get(f"/api/{resource}").json())
                assert api.get(f"/api/{resource}/{row['id']}").status_code == 200
                assert api.put(f"/api/{resource}/{row['id']}", json=SAMPLES[resource]).status_code == 200
                assert api.delete(f"/api/{resource}/{row['id']}").status_code == 204
                assert api.get(f"/api/{resource}/{row['id']}").status_code == 404


            @pytest.mark.parametrize("resource", [name for name, fields in REQUIRED.items() if fields])
            def test_required_fields_are_validated(api, resource):
                response = api.post(f"/api/{resource}", json={})
                assert response.status_code == 422
            """
        )
    )
    if spec.auth:
        text += _d(
            """


            def test_records_require_sign_in(client):
                resource = next(iter(SAMPLES))
                assert client.get(f"/api/{resource}").status_code == 401


            def test_sign_in_rejects_wrong_password(client):
                client.post("/api/auth/register", json={"email": "a@example.com", "password": "correct-horse-battery"})
                assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong-password"}).status_code == 401
                assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "correct-horse-battery"}).status_code == 200
            """
        )
    return text


def _sa_column(field: dict) -> str:
    return f'sa.Column("{field["name"]}", {SA_TYPES[field["type"]]}, nullable=True)'


def _migration_file(migration: dict) -> str:
    up: list[str] = []
    down: list[str] = []
    for op in migration["ops"]:
        kind = op["op"]
        if kind == "create_table":
            cols = ['sa.Column("id", sa.String(36), primary_key=True)', 'sa.Column("created_at", sa.DateTime(timezone=True))']
            if op["table"] == "users":
                cols += ['sa.Column("email", sa.String(320), nullable=False, unique=True)', 'sa.Column("password_hash", sa.String(255), nullable=False)', 'sa.Column("role", sa.String(40), nullable=False)']
            cols += [_sa_column(f) for f in op.get("fields", [])]
            up.append(f'op.create_table(\n        "{op["table"]}",\n        ' + ",\n        ".join(cols) + ",\n    )")
            if op["table"] == "users":
                up.append('op.create_index("ix_users_email", "users", ["email"], unique=True)')
            down.insert(0, f'op.drop_table("{op["table"]}")')
        elif kind == "add_column":
            up.append(f'with op.batch_alter_table("{op["table"]}") as batch:\n        batch.add_column({_sa_column(op["field"])})')
            down.insert(0, f'with op.batch_alter_table("{op["table"]}") as batch:\n        batch.drop_column("{op["field"]["name"]}")')
        elif kind == "drop_column":
            up.append(f'with op.batch_alter_table("{op["table"]}") as batch:\n        batch.drop_column("{op["column"]}")')
            down.insert(0, f'raise RuntimeError("Dropping {op["table"]}.{op["column"]} cannot be reversed; restore from a backup")')
        elif kind == "drop_table":
            up.append(f'op.drop_table("{op["table"]}")')
            down.insert(0, f'raise RuntimeError("Dropping {op["table"]} cannot be reversed; restore from a backup")')
    body_up = "\n    ".join(up) or "pass"
    body_down = "\n    ".join(down) or "pass"
    down_rev = json.dumps(migration["down_revision"]) if migration["down_revision"] else "None"
    return (
        f'"""{migration["message"]}\n\nRevision ID: {migration["revision"]}\nRevises: {migration["down_revision"] or ""}\n'
        + ("Destructive: yes. Approved before it was generated.\n" if migration.get("destructive") else "")
        + '"""\nimport sqlalchemy as sa\nfrom alembic import op\n\n'
        + f'revision = "{migration["revision"]}"\ndown_revision = {down_rev}\nbranch_labels = None\ndepends_on = None\n\n\n'
        + f"def upgrade() -> None:\n    {body_up}\n\n\ndef downgrade() -> None:\n    {body_down}\n"
    )


# --------------------------------------------------------------------------- mobile

def _mobile(spec: AppSpec) -> dict[str, str]:
    api = "api" in spec.targets
    bundle = re.sub(r"[^a-z0-9]", "", spec.slug) or "app"
    files: dict[str, str] = {}
    files["apps/mobile/package.json"] = json.dumps(
        {
            "name": f"{spec.slug}-mobile",
            "private": True,
            "version": "0.1.0",
            "main": "node_modules/expo/AppEntry.js",
            "scripts": {"start": "expo start", "android": "expo start --android", "ios": "expo start --ios", "web": "expo start --web"},
            "dependencies": {"expo": "~54.0.0", "react": "19.1.0", "react-native": "0.81.5", "react-native-web": "^0.21.0", "react-dom": "19.1.0"},
            "devDependencies": {"@types/react": "~19.1.0", "typescript": "~5.9.2"},
        },
        indent=2,
    ) + "\n"
    files["apps/mobile/app.json"] = json.dumps(
        {
            "expo": {
                "name": spec.name,
                "slug": spec.slug,
                "version": "0.1.0",
                "orientation": "portrait",
                "userInterfaceStyle": "light",
                "ios": {"bundleIdentifier": f"com.example.{bundle}", "supportsTablet": True},
                "android": {"package": f"com.example.{bundle}"},
            }
        },
        indent=2,
    ) + "\n"
    files["apps/mobile/tsconfig.json"] = json.dumps({"extends": "expo/tsconfig.base", "compilerOptions": {"strict": True}}, indent=2) + "\n"
    files["apps/mobile/src/schema.ts"] = _schema_ts(spec)
    files["apps/mobile/src/validate.ts"] = VALIDATE_TS
    files["apps/mobile/src/theme.ts"] = f"export const accent = {json.dumps(spec.accent)}\nexport const ink = '#0f172a'\nexport const muted = '#64748b'\nexport const line = '#e2e8f0'\n"
    if api:
        files["apps/mobile/src/store.ts"] = _d(
            """
            import { createClient } from '../../../packages/api-client/src/index'
            import type { Row } from './schema'
            import type { Draft } from './validate'

            let token: string | null = null
            export const setToken = (value: string | null) => {
              token = value
            }

            // Set EXPO_PUBLIC_API_URL to your deployed API, for example https://your-app.ondigitalocean.app/api.
            export const client = createClient({ baseUrl: process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000/api', getToken: () => token })

            export const store = {
              list: (resource: string): Promise<Row[]> => client.list(resource),
              create: (resource: string, draft: Draft): Promise<Row> => client.create(resource, draft),
              remove: (resource: string, id: string): Promise<void> => client.remove(resource, id),
            }
            """
        )
    else:
        files["apps/mobile/src/store.ts"] = _d(
            """
            import type { Row } from './schema'
            import type { Draft } from './validate'

            // Records live in memory for this session. Add a backend to the project to persist them.
            const data = new Map<string, Row[]>()

            export const store = {
              async list(resource: string): Promise<Row[]> {
                return data.get(resource) ?? []
              },
              async create(resource: string, draft: Draft): Promise<Row> {
                const row = { ...draft, id: Math.random().toString(36).slice(2), created_at: new Date().toISOString() } as Row
                data.set(resource, [row, ...(data.get(resource) ?? [])])
                return row
              },
              async remove(resource: string, id: string): Promise<void> {
                data.set(resource, (data.get(resource) ?? []).filter((row) => row.id !== id))
              },
            }
            """
        )
    files["apps/mobile/src/screens/HomeScreen.tsx"] = _d(
        f"""
        import {{ Pressable, ScrollView, StyleSheet, Text, View }} from 'react-native'
        import {{ entities, type EntityDef }} from '../schema'
        import {{ accent, ink, line, muted }} from '../theme'

        export function HomeScreen({{ onOpen }}: {{ onOpen: (entity: EntityDef) => void }}) {{
          return (
            <ScrollView contentContainerStyle={{styles.container}}>
              <View style={{styles.hero}}>
                <Text style={{styles.title}}>{jsx_text(spec.name)}</Text>
                <Text style={{styles.tagline}}>{jsx_text(spec.tagline or "Everything in one place.")}</Text>
              </View>
              {{entities.map((entity) => (
                <Pressable key={{entity.slug}} onPress={{() => onOpen(entity)}} style={{({{ pressed }}) => [styles.card, pressed && styles.pressed]}}>
                  <Text style={{styles.cardTitle}}>{{entity.label}}</Text>
                  <Text style={{styles.cardText}}>{{entity.description || `Manage ${{entity.label.toLowerCase()}}`}}</Text>
                </Pressable>
              ))}}
            </ScrollView>
          )
        }}

        const styles = StyleSheet.create({{
          container: {{ padding: 20, gap: 12 }},
          hero: {{ backgroundColor: accent, borderRadius: 20, padding: 22, marginBottom: 8 }},
          title: {{ color: '#fff', fontSize: 26, fontWeight: '700' }},
          tagline: {{ color: 'rgba(255,255,255,0.85)', marginTop: 6, fontSize: 15, lineHeight: 21 }},
          card: {{ backgroundColor: '#fff', borderRadius: 16, padding: 18, borderWidth: 1, borderColor: line }},
          pressed: {{ opacity: 0.7 }},
          cardTitle: {{ fontSize: 17, fontWeight: '600', color: ink }},
          cardText: {{ marginTop: 4, color: muted, fontSize: 14 }},
        }})
        """
    )
    files["apps/mobile/src/screens/EntityScreen.tsx"] = _d(
        """
        import { useCallback, useEffect, useState } from 'react'
        import { ActivityIndicator, FlatList, Pressable, StyleSheet, Switch, Text, TextInput, View } from 'react-native'
        import type { EntityDef, Row } from '../schema'
        import { store } from '../store'
        import { accent, ink, line, muted } from '../theme'
        import { emptyDraft, formatValue, toPayload, validate, type Draft } from '../validate'

        export function EntityScreen({ entity, onBack }: { entity: EntityDef; onBack: () => void }) {
          const [rows, setRows] = useState<Row[] | null>(null)
          const [error, setError] = useState<string | null>(null)
          const [draft, setDraft] = useState<Draft>(() => emptyDraft(entity))
          const [errors, setErrors] = useState<Record<string, string>>({})
          const [adding, setAdding] = useState(false)

          const load = useCallback(() => {
            setError(null)
            store.list(entity.slug).then(setRows).catch((e: unknown) => setError(e instanceof Error ? e.message : 'Could not load'))
          }, [entity.slug])
          useEffect(load, [load])

          const save = async () => {
            const found = validate(entity, draft)
            setErrors(found)
            if (Object.keys(found).length) return
            try {
              const row = await store.create(entity.slug, toPayload(entity, draft))
              setRows((current) => [row, ...(current ?? [])])
              setDraft(emptyDraft(entity))
              setAdding(false)
            } catch (e) {
              setError(e instanceof Error ? e.message : 'Could not save')
            }
          }

          const title = entity.fields[0]
          return (
            <View style={styles.screen}>
              <View style={styles.header}>
                <Pressable onPress={onBack} hitSlop={12}>
                  <Text style={styles.back}>‹ Back</Text>
                </Pressable>
                <Text style={styles.heading}>{entity.label}</Text>
                <Pressable onPress={() => setAdding(!adding)} hitSlop={12}>
                  <Text style={styles.add}>{adding ? 'Close' : 'Add'}</Text>
                </Pressable>
              </View>
              {adding && (
                <View style={styles.form}>
                  {entity.fields.map((field) => (
                    <View key={field.name} style={styles.field}>
                      <Text style={styles.label}>{field.label}{field.required ? ' *' : ''}</Text>
                      {field.type === 'boolean' ? (
                        <Switch value={Boolean(draft[field.name])} onValueChange={(value) => setDraft({ ...draft, [field.name]: value })} />
                      ) : (
                        <TextInput
                          value={String(draft[field.name] ?? '')}
                          onChangeText={(value) => setDraft({ ...draft, [field.name]: value })}
                          keyboardType={field.type === 'number' ? 'numeric' : field.type === 'email' ? 'email-address' : 'default'}
                          placeholder={field.type === 'date' ? 'YYYY-MM-DD' : ''}
                          multiline={field.type === 'text'}
                          style={styles.input}
                        />
                      )}
                      {errors[field.name] ? <Text style={styles.error}>{errors[field.name]}</Text> : null}
                    </View>
                  ))}
                  <Pressable onPress={() => void save()} style={styles.button}>
                    <Text style={styles.buttonText}>Save</Text>
                  </Pressable>
                </View>
              )}
              {error ? (
                <Text style={[styles.error, styles.pad]} onPress={load}>{error} · Tap to retry</Text>
              ) : rows === null ? (
                <ActivityIndicator style={styles.pad} color={accent} />
              ) : (
                <FlatList
                  data={rows}
                  keyExtractor={(row) => row.id}
                  contentContainerStyle={styles.list}
                  ListEmptyComponent={<Text style={styles.empty}>No {entity.label.toLowerCase()} yet</Text>}
                  renderItem={({ item }) => (
                    <View style={styles.row}>
                      <View style={styles.rowText}>
                        <Text style={styles.rowTitle}>{formatValue(item[title.name], title.type)}</Text>
                        {entity.fields.slice(1, 3).map((field) => (
                          <Text key={field.name} style={styles.rowMeta}>{field.label}: {formatValue(item[field.name], field.type)}</Text>
                        ))}
                      </View>
                      <Pressable onPress={() => void store.remove(entity.slug, item.id).then(load)} hitSlop={8}>
                        <Text style={styles.delete}>Delete</Text>
                      </Pressable>
                    </View>
                  )}
                />
              )}
            </View>
          )
        }

        const styles = StyleSheet.create({
          screen: { flex: 1 },
          header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 20, paddingVertical: 14, borderBottomWidth: 1, borderColor: line, backgroundColor: '#fff' },
          back: { color: accent, fontSize: 16 },
          heading: { fontSize: 17, fontWeight: '600', color: ink },
          add: { color: accent, fontSize: 16, fontWeight: '600' },
          form: { padding: 20, gap: 12, backgroundColor: '#fff', borderBottomWidth: 1, borderColor: line },
          field: { gap: 6 },
          label: { fontSize: 13, fontWeight: '600', color: ink },
          input: { borderWidth: 1, borderColor: line, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 15 },
          error: { color: '#dc2626', fontSize: 13 },
          button: { backgroundColor: accent, borderRadius: 12, paddingVertical: 13, alignItems: 'center' },
          buttonText: { color: '#fff', fontWeight: '600', fontSize: 15 },
          pad: { padding: 20 },
          list: { padding: 20, gap: 10 },
          empty: { textAlign: 'center', color: muted, paddingVertical: 40 },
          row: { flexDirection: 'row', alignItems: 'center', backgroundColor: '#fff', borderRadius: 14, padding: 16, borderWidth: 1, borderColor: line },
          rowText: { flex: 1, gap: 2 },
          rowTitle: { fontSize: 16, fontWeight: '600', color: ink },
          rowMeta: { fontSize: 13, color: muted },
          delete: { color: muted, fontSize: 13 },
        })
        """
    )
    sign_in = spec.auth
    if sign_in:
        files["apps/mobile/src/screens/SignInScreen.tsx"] = _d(
            f"""
            import {{ useState }} from 'react'
            import {{ Pressable, StyleSheet, Text, TextInput, View }} from 'react-native'
            import {{ client }} from '../store'
            import {{ accent, ink, line, muted }} from '../theme'

            export function SignInScreen({{ onSignedIn }}: {{ onSignedIn: (token: string) => void }}) {{
              const [register, setRegister] = useState(false)
              const [email, setEmail] = useState('')
              const [password, setPassword] = useState('')
              const [error, setError] = useState<string | null>(null)
              const submit = async () => {{
                setError(null)
                try {{
                  const result = register ? await client.register(email, password) : await client.signIn(email, password)
                  onSignedIn(result.access_token)
                }} catch (e) {{
                  setError(e instanceof Error ? e.message : 'Could not sign in')
                }}
              }}
              return (
                <View style={{styles.container}}>
                  <Text style={{styles.title}}>{jsx_text(spec.name)}</Text>
                  <Text style={{styles.subtitle}}>{{register ? 'Create your account' : 'Sign in to continue'}}</Text>
                  <TextInput value={{email}} onChangeText={{setEmail}} placeholder="Email" autoCapitalize="none" keyboardType="email-address" style={{styles.input}} />
                  <TextInput value={{password}} onChangeText={{setPassword}} placeholder="Password" secureTextEntry style={{styles.input}} />
                  {{error ? <Text style={{styles.error}}>{{error}}</Text> : null}}
                  <Pressable onPress={{() => void submit()}} style={{styles.button}}>
                    <Text style={{styles.buttonText}}>{{register ? 'Create account' : 'Sign in'}}</Text>
                  </Pressable>
                  <Pressable onPress={{() => setRegister(!register)}}>
                    <Text style={{styles.switch}}>{{register ? 'Have an account? Sign in' : 'New here? Create an account'}}</Text>
                  </Pressable>
                </View>
              )
            }}

            const styles = StyleSheet.create({{
              container: {{ flex: 1, justifyContent: 'center', padding: 28, gap: 12 }},
              title: {{ fontSize: 28, fontWeight: '700', color: ink }},
              subtitle: {{ fontSize: 15, color: muted, marginBottom: 8 }},
              input: {{ borderWidth: 1, borderColor: line, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, fontSize: 16, backgroundColor: '#fff' }},
              error: {{ color: '#dc2626' }},
              button: {{ backgroundColor: accent, borderRadius: 12, paddingVertical: 14, alignItems: 'center' }},
              buttonText: {{ color: '#fff', fontWeight: '600', fontSize: 16 }},
              switch: {{ textAlign: 'center', color: muted, marginTop: 6 }},
            }})
            """
        )
    files["apps/mobile/App.tsx"] = (
        "import { useState } from 'react'\n"
        "import { SafeAreaView, StyleSheet } from 'react-native'\n"
        "import type { EntityDef } from './src/schema'\n"
        "import { EntityScreen } from './src/screens/EntityScreen'\n"
        "import { HomeScreen } from './src/screens/HomeScreen'\n"
        + ("import { SignInScreen } from './src/screens/SignInScreen'\nimport { setToken } from './src/store'\n" if sign_in else "")
        + "\nexport default function App() {\n"
        + "  const [entity, setEntity] = useState<EntityDef | null>(null)\n"
        + ("  const [signedIn, setSignedIn] = useState(false)\n" if sign_in else "")
        + "  return (\n    <SafeAreaView style={styles.root}>\n"
        + (
            "      {!signedIn ? (\n        <SignInScreen onSignedIn={(token) => { setToken(token); setSignedIn(true) }} />\n      ) : entity ? (\n"
            if sign_in
            else "      {entity ? (\n"
        )
        + "        <EntityScreen entity={entity} onBack={() => setEntity(null)} />\n      ) : (\n        <HomeScreen onOpen={setEntity} />\n      )}\n"
        + "    </SafeAreaView>\n  )\n}\n\nconst styles = StyleSheet.create({ root: { flex: 1, backgroundColor: '#f8fafc' } })\n"
    )
    return files


# --------------------------------------------------------------------------- root and infrastructure

def _root(spec: AppSpec) -> dict[str, str]:
    parts = []
    if "web" in spec.targets:
        parts.append("- `apps/web` — React web app (Vite, TypeScript, Tailwind CSS)")
    if "mobile" in spec.targets:
        parts.append("- `apps/mobile` — Expo mobile app for iOS and Android")
    if "api" in spec.targets:
        parts.append("- `services/api` — FastAPI service with SQLAlchemy models and Alembic migrations")
    if "api" in spec.targets and ({"web", "mobile"} & set(spec.targets)):
        parts.append("- `packages/api-client` — typed API client shared by the apps")
    parts.append("- `infra/opentofu` — DigitalOcean App Platform definition")
    run = []
    if "api" in spec.targets:
        run.append("```bash\ncd services/api\npython -m venv .venv && . .venv/bin/activate\npip install -r requirements-dev.txt\nalembic upgrade head\nuvicorn app.main:app --reload --port 8000\npytest\n```")
    if "web" in spec.targets:
        run.append("```bash\ncd apps/web\nnpm install\nnpm run dev   # http://localhost:5180\nnpm test\n```")
    if "mobile" in spec.targets:
        run.append("```bash\ncd apps/mobile\nnpm install\nnpx expo start\n```\n\nPublishing to the App Store or Google Play requires your own developer accounts, signing credentials, and store review. Omniweb does not publish apps for you.")
    entities = "\n".join(f"- **{e.label}**: {', '.join(f.label for f in e.fields)}" for e in spec.entities)
    return {
        "README.md": f"# {spec.name}\n\n{spec.tagline}\n\n## What's here\n\n" + "\n".join(parts) + f"\n\n## Data\n\n{entities}\n\n## Run locally\n\n" + "\n\n".join(run)
        + "\n\n## Deploy\n\n`.do/app.yaml` describes a DigitalOcean App Platform app, and `infra/opentofu` manages the same app with OpenTofu. Set secrets such as `SECRET_KEY` in App Platform, never in this repository.\n",
        ".gitignore": "node_modules/\ndist/\n.env\n.env.*\n*.db\n__pycache__/\n.venv/\n.expo/\n.terraform/\n*.tfstate*\n.vite-cache/\n",
        "omniweb.json": json.dumps({"template_version": TEMPLATE_VERSION, "spec": spec.model_dump()}, indent=2) + "\n",
        ".github/workflows/ci.yml": _ci(spec),
    }


def _ci(spec: AppSpec) -> str:
    jobs = ["name: CI\n\non:\n  push:\n  pull_request:\n\npermissions:\n  contents: read\n\njobs:"]
    if "web" in spec.targets:
        jobs.append("  web:\n    runs-on: ubuntu-latest\n    defaults:\n      run:\n        working-directory: apps/web\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-node@v4\n        with:\n          node-version: 22\n      - run: npm install\n      - run: npm test\n      - run: npm run build")
    if "api" in spec.targets:
        jobs.append("  api:\n    runs-on: ubuntu-latest\n    defaults:\n      run:\n        working-directory: services/api\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.12'\n      - run: pip install -r requirements-dev.txt\n      - run: pytest -q")
    return "\n".join(jobs) + "\n"


def app_platform_spec(spec: AppSpec, repo: str, branch: str, region: str, environment: str) -> dict:
    """DigitalOcean App Platform spec. Used by the deploy service and written to .do/app.yaml."""
    name = f"{spec.slug}-{environment}"[:32].strip("-")
    github = {"repo": repo, "branch": branch, "deploy_on_push": False}
    app: dict = {"name": name, "region": region, "static_sites": [], "services": [], "databases": []}
    if "web" in spec.targets:
        app["static_sites"].append(
            {
                "name": "web",
                "github": github,
                "source_dir": "apps/web",
                "build_command": "npm install && npm run build",
                "output_dir": "dist",
                "catchall_document": "index.html",
                "routes": [{"path": "/"}],
                "envs": [{"key": "VITE_API_URL", "value": "/api", "scope": "BUILD_TIME"}],
            }
        )
    if "api" in spec.targets:
        app["services"].append(
            {
                "name": "api",
                "github": github,
                "source_dir": "services/api",
                "dockerfile_path": "services/api/Dockerfile",
                "http_port": 8000,
                "instance_count": 1,
                "instance_size_slug": "apps-s-1vcpu-0.5gb",
                "routes": [{"path": "/api", "preserve_path_prefix": True}],
                "health_check": {"http_path": "/api/health"},
                "envs": [
                    {"key": "APP_ENV", "value": "production", "scope": "RUN_TIME"},
                    {"key": "DATABASE_URL", "value": "${db.DATABASE_URL}", "scope": "RUN_TIME"},
                    {"key": "SECRET_KEY", "type": "SECRET", "scope": "RUN_TIME"},
                ],
            }
        )
        app["databases"].append({"name": "db", "engine": "PG", "production": False})
    return {key: value for key, value in app.items() if value}


def _yaml(value, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{pad}{key}:\n{_yaml(item, indent + 1)}")
            else:
                lines.append(f"{pad}{key}: {_scalar(item)}")
        return "\n".join(lines)
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                inner = _yaml(item, indent + 1).split("\n")
                lines.append(f"{pad}- {inner[0].strip()}")
                lines.extend(inner[1:])
            else:
                lines.append(f"{pad}- {_scalar(item)}")
        return "\n".join(lines)
    return f"{pad}{_scalar(value)}"


def _scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value in ({}, []):
        return json.dumps(value)
    return json.dumps(str(value))


def _infra(spec: AppSpec) -> dict[str, str]:
    app = app_platform_spec(spec, "OWNER/REPOSITORY", "main", "nyc", "production")
    files = {".do/app.yaml": "# Replace OWNER/REPOSITORY with your GitHub repository before using this file directly.\n" + _yaml(app) + "\n"}
    blocks = []
    if "web" in spec.targets:
        blocks.append(
            _d(
                """
                static_site {
                  name              = "web"
                  source_dir        = "apps/web"
                  build_command     = "npm install && npm run build"
                  output_dir        = "dist"
                  catchall_document = "index.html"
                  github {
                    repo           = var.github_repo
                    branch         = var.branch
                    deploy_on_push = false
                  }
                }
                """
            )
        )
    if "api" in spec.targets:
        blocks.append(
            _d(
                """
                service {
                  name               = "api"
                  source_dir         = "services/api"
                  dockerfile_path    = "services/api/Dockerfile"
                  http_port          = 8000
                  instance_count     = 1
                  instance_size_slug = "apps-s-1vcpu-0.5gb"
                  github {
                    repo           = var.github_repo
                    branch         = var.branch
                    deploy_on_push = false
                  }
                  env {
                    key   = "APP_ENV"
                    value = "production"
                  }
                  env {
                    key   = "DATABASE_URL"
                    value = "$${db.DATABASE_URL}"
                  }
                  env {
                    key   = "SECRET_KEY"
                    value = var.secret_key
                    type  = "SECRET"
                  }
                  health_check {
                    http_path = "/api/health"
                  }
                }

                database {
                  name       = "db"
                  engine     = "PG"
                  production = false
                }
                """
            )
        )
    sites = "".join("\n" + indent(block, "    ") for block in blocks)
    files["infra/opentofu/main.tf"] = (
        _d(
            """
            terraform {
              required_providers {
                digitalocean = {
                  source  = "digitalocean/digitalocean"
                  version = "~> 2.68"
                }
              }
            }

            # Authenticates with the DIGITALOCEAN_TOKEN environment variable. Never commit tokens.
            provider "digitalocean" {}

            resource "digitalocean_app" "this" {
              spec {
            """
        )
        + f'    name   = "{spec.slug[:32]}"\n    region = var.region\n'
        + sites.rstrip()
        + "\n  }\n}\n"
    )
    files["infra/opentofu/variables.tf"] = _d(
        """
        variable "github_repo" {
          description = "GitHub repository in OWNER/NAME form"
          type        = string
        }

        variable "branch" {
          type    = string
          default = "main"
        }

        variable "region" {
          type    = string
          default = "nyc"
        }
        """
    ) + (
        '\nvariable "secret_key" {\n  description = "Signing key for user sessions"\n  type        = string\n  sensitive   = true\n}\n'
        if "api" in spec.targets
        else ""
    )
    files["infra/opentofu/outputs.tf"] = 'output "live_url" {\n  value = digitalocean_app.this.live_url\n}\n'
    return files
