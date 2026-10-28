import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { CircleAlert, KeyRound, RefreshCw, Search, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { AppNav, RequireAuth } from '../components/studio/AppNav'
import { platform, type ProviderStatus } from '../lib/api'
import { useAuth } from '../lib/auth'
import { BudgetBar } from './projects.$projectId.index'
import { relativeTime, usd } from './projects.index'

export const Route = createFileRoute('/usage')({
  head: () => ({ meta: [{ title: 'Usage and models — Omniweb' }] }),
  component: () => (
    <div className="st">
      <AppNav />
      <RequireAuth>
        <UsagePage />
      </RequireAuth>
    </div>
  ),
})

const TIER_LABEL = { economy: 'Economy', standard: 'Standard', advanced: 'Advanced', self_hosted: 'Self-hosted' }

function price(value: number | null) {
  return value === null ? '—' : `$${value < 1 ? value.toFixed(3) : value.toFixed(2)}`
}

function UsagePage() {
  const { me } = useAuth()
  const isAdmin = me?.role === 'owner' || me?.role === 'admin'
  const usage = useQuery({ queryKey: ['org-usage'], queryFn: platform.usage })
  const u = usage.data
  const monthly = u?.budgets.find((b) => b.scope === 'organization_monthly')
  return (
    <main className="st-page">
      <section className="st-hero-row">
        <div>
          <h1>Usage and models</h1>
          <p className="st-muted">AI spend across your organization, the providers Omniweb can use, and how requests are routed.</p>
        </div>
      </section>

      {usage.error && <div className="st-alert st-alert-error"><CircleAlert size={14} /> {usage.error.message}</div>}
      <div className="st-stat-grid">
        <div className="st-card"><small>This month</small><strong>{u ? usd(u.totals.cost_usd) : '—'}</strong></div>
        <div className="st-card"><small>Requests</small><strong>{u?.totals.requests ?? '—'}</strong></div>
        <div className="st-card"><small>Failed requests</small><strong>{u ? `${u.totals.failed} · ${usd(u.failed_cost_usd)}` : '—'}</strong></div>
        <div className="st-card"><small>Tokens (in / out / cached)</small><strong>{u ? `${u.totals.input_tokens.toLocaleString()} / ${u.totals.output_tokens.toLocaleString()} / ${u.totals.cached_tokens.toLocaleString()}` : '—'}</strong></div>
      </div>

      <div className="st-two">
        <section className="st-card st-section">
          <h2>Monthly budget</h2>
          {monthly && <BudgetBar label="Organization AI spend" spent={monthly.spent_usd} limit={monthly.limit_usd} />}
          {monthly && <OrgBudget limit={monthly.limit_usd} hard={monthly.hard_limit} isAdmin={isAdmin} />}
          {u?.alerts.length ? (
            <>
              <h4 className="st-h4">Alerts</h4>
              {u.alerts.map((a) => <div key={a.created_at + a.message} className="st-alert"><CircleAlert size={14} /> {a.message} · {relativeTime(a.created_at)}</div>)}
            </>
          ) : null}
        </section>
        <section className="st-card st-section" id="pricing">
          <h2>How AI usage is billed</h2>
          <div className="st-kv"><span><strong>Platform credentials</strong><br /><small className="st-muted">Omniweb’s provider keys. Usage counts against your budgets at provider list prices.</small></span></div>
          <div className="st-kv"><span><strong>Your own keys</strong><br /><small className="st-muted">Billed by your provider directly. Omniweb still meters usage and enforces your budgets.</small></span></div>
          <div className="st-kv"><span><strong>Self-hosted models</strong><br /><small className="st-muted">Ollama or OpenAI-compatible endpoints you run. Recorded at $0.</small></span></div>
          <p className="st-fine">Costs are estimates from token counts and registry prices, not invoices.</p>
        </section>
      </div>

      {u && u.by_model.length > 0 && (
        <section className="st-card st-section">
          <h2>Spend by model and agent</h2>
          <div className="st-two">
            <div>{u.by_model.map((m) => <div key={m.key} className="st-kv"><span>{m.key}</span><strong>{usd(m.cost_usd)} · {m.requests} req</strong></div>)}</div>
            <div>{u.by_agent.map((m) => <div key={m.key} className="st-kv"><span>{m.key} agent</span><strong>{usd(m.cost_usd)} · {m.requests} req</strong></div>)}</div>
          </div>
        </section>
      )}

      <Providers isAdmin={isAdmin} />
      <Tiers />
      <Registry />
    </main>
  )
}

function OrgBudget({ limit, hard, isAdmin }: { limit: number; hard: boolean; isAdmin: boolean }) {
  const queryClient = useQueryClient()
  const [value, setValue] = useState(String(limit))
  const [hardLimit, setHardLimit] = useState(hard)
  const save = useMutation({
    mutationFn: () => platform.orgBudget(Number(value), hardLimit),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['org-usage'] }),
  })
  if (!isAdmin) return <p className="st-fine">Only organization administrators can change this budget.</p>
  return (
    <div className="st-inline">
      <label className="st-field">Limit (USD)<input type="number" min={0} step="1" value={value} onChange={(e) => setValue(e.target.value)} /></label>
      <label className="st-check"><input type="checkbox" checked={hardLimit} onChange={(e) => setHardLimit(e.target.checked)} /> Hard limit</label>
      <button type="button" className="lv-btn lv-btn-light" onClick={() => save.mutate()} disabled={save.isPending || value === ''}>Save</button>
      {save.error && <span className="st-error">{save.error.message}</span>}
      {save.isSuccess && <span className="st-ok">Saved</span>}
    </div>
  )
}

function Providers({ isAdmin }: { isAdmin: boolean }) {
  const queryClient = useQueryClient()
  const providers = useQuery({ queryKey: ['providers'], queryFn: platform.providers })
  const refresh = useMutation({
    mutationFn: platform.refreshRegistry,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['providers'] })
      void queryClient.invalidateQueries({ queryKey: ['models'] })
      void queryClient.invalidateQueries({ queryKey: ['tiers'] })
    },
  })
  return (
    <section className="st-card st-section" id="providers">
      <div className="st-section-head">
        <h2>Providers</h2>
        {isAdmin && (
          <button type="button" className="lv-btn lv-btn-ghost" onClick={() => refresh.mutate()} disabled={refresh.isPending}>
            <RefreshCw size={14} className={refresh.isPending ? 'bd-spin' : ''} /> Discover models
          </button>
        )}
      </div>
      <p className="st-muted">Keys are verified against the provider, encrypted in the model gateway, and never returned to the browser.</p>
      {refresh.data && (
        <p className="st-fine">
          {Object.entries(refresh.data).map(([name, result]) => `${name}: ${result.status}${result.models !== undefined ? ` (${result.models} models)` : ''}`).join(' · ')}
        </p>
      )}
      {refresh.error && <p className="st-error">{refresh.error.message}</p>}
      {providers.error && <p className="st-error">{providers.error.message}</p>}
      <div className="st-provider-grid">
        {providers.data?.map((provider) => <ProviderCard key={provider.provider} provider={provider} isAdmin={isAdmin} />)}
      </div>
    </section>
  )
}

function ProviderCard({ provider, isAdmin }: { provider: ProviderStatus; isAdmin: boolean }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [key, setKey] = useState('')
  const [baseUrl, setBaseUrl] = useState(provider.base_url)
  const done = () => {
    setOpen(false)
    setKey('')
    void queryClient.invalidateQueries({ queryKey: ['providers'] })
    void queryClient.invalidateQueries({ queryKey: ['tiers'] })
    void queryClient.invalidateQueries({ queryKey: ['models'] })
  }
  const save = useMutation({ mutationFn: () => platform.setCredential(provider.provider, key, baseUrl), onSuccess: done })
  const remove = useMutation({ mutationFn: () => platform.deleteCredential(provider.provider), onSuccess: done })
  const status =
    provider.configured === 'customer' ? 'Your key' : provider.configured === 'platform' ? (provider.kind === 'development' ? 'Built in' : 'Platform key') : 'Not configured'
  return (
    <div className={`st-provider${provider.configured ? ' on' : ''}`}>
      <div className="st-provider-head">
        <strong>{provider.label}</strong>
        <span className={`st-pill${provider.configured ? ' st-pill-ok' : ''}`}>{status}</span>
      </div>
      <small className="st-muted">
        {provider.models} models{provider.key_fingerprint ? ` · key …${provider.key_fingerprint.slice(-4)}` : ''}
        {provider.provider === 'openrouter' && !provider.configured && provider.models > 0 ? ' · public catalog, add a key to use' : ''}
        {provider.kind === 'development' ? ' · local replies without AI, development only' : ''}
      </small>
      {isAdmin && provider.kind !== 'development' && (
        open ? (
          <form className="st-form" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
            {provider.needs_key && <input type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder="API key" aria-label={`${provider.label} API key`} />}
            {(provider.needs_base_url || provider.provider === 'openai_compatible') && (
              <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder={provider.provider === 'ollama' ? 'http://localhost:11434' : 'https://host/v1'} aria-label="Base URL" />
            )}
            {!provider.needs_key && provider.provider === 'openai_compatible' && (
              <input type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder="API key (optional)" aria-label="API key" />
            )}
            <div className="st-row">
              <button type="submit" className="lv-btn lv-btn-light" disabled={save.isPending}><KeyRound size={14} /> {save.isPending ? 'Verifying…' : 'Verify and save'}</button>
              <button type="button" className="lv-btn lv-btn-ghost" onClick={() => setOpen(false)}>Cancel</button>
            </div>
            {save.error && <p className="st-error">{save.error.message}</p>}
          </form>
        ) : (
          <div className="st-row">
            <button type="button" className="lv-btn lv-btn-ghost" onClick={() => setOpen(true)}>{provider.configured === 'customer' ? 'Replace key' : 'Add your key'}</button>
            {provider.configured === 'customer' && (
              <button type="button" className="bd-icon" onClick={() => remove.mutate()} title="Remove your key"><Trash2 size={14} /></button>
            )}
          </div>
        )
      )}
    </div>
  )
}

function Tiers() {
  const tiers = useQuery({ queryKey: ['tiers'], queryFn: platform.tiers })
  return (
    <section className="st-card st-section">
      <h2>Routing tiers</h2>
      <p className="st-muted">The models each tier would use right now, in order. Failed requests fall back to the next model and escalate at most as far as your preferences allow.</p>
      <div className="st-tier-grid">
        {tiers.data?.map((tier) => (
          <div key={tier.tier} className="st-tier">
            <strong>{TIER_LABEL[tier.tier]}</strong>
            {tier.candidates.length === 0 ? (
              <small className="st-muted">No configured model qualifies</small>
            ) : (
              <ol>
                {tier.candidates.map((m) => (
                  <li key={`${m.provider}/${m.model_id}`}>
                    <span>{m.display_name}</span>
                    <small>{m.provider} · {price(m.input_usd_per_mtok)} / {price(m.output_usd_per_mtok)} per 1M</small>
                  </li>
                ))}
              </ol>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}

function Registry() {
  const models = useQuery({ queryKey: ['models'], queryFn: () => platform.models() })
  const [filter, setFilter] = useState('')
  const [page, setPage] = useState(50)
  useEffect(() => setPage(50), [filter])
  const visible = useMemo(
    () => (models.data ?? []).filter((m) => `${m.provider} ${m.model_id} ${m.display_name}`.toLowerCase().includes(filter.toLowerCase())),
    [models.data, filter],
  )
  return (
    <section className="st-card st-section">
      <div className="st-section-head">
        <h2>Model registry</h2>
        <label className="st-search">
          <Search size={14} />
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter models" aria-label="Filter models" />
        </label>
      </div>
      <p className="st-muted">{models.data?.length ?? 0} models discovered from provider APIs. Prices are per million tokens.</p>
      <div className="st-table-wrap">
        <table className="st-table">
          <thead>
            <tr><th>Model</th><th>Provider</th><th>Context</th><th>Input</th><th>Output</th><th>Capabilities</th><th>Status</th><th>Verified</th></tr>
          </thead>
          <tbody>
            {visible.slice(0, page).map((m) => (
              <tr key={`${m.provider}/${m.model_id}`}>
                <td><span className="st-model-name">{m.display_name}</span><small>{m.model_id}</small></td>
                <td>{m.provider}</td>
                <td>{m.context_window ? `${Math.round(m.context_window / 1000)}k` : '—'}</td>
                <td>{price(m.input_usd_per_mtok)}</td>
                <td>{price(m.output_usd_per_mtok)}</td>
                <td><div className="st-chips">{m.capabilities.slice(0, 4).map((c) => <span key={c}>{c.replace('_', ' ')}</span>)}</div></td>
                <td>{m.deprecated ? 'Deprecated' : !m.available ? 'Unavailable' : m.routable ? 'Routable' : 'Catalog only'}</td>
                <td>{relativeTime(m.last_verified_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {visible.length > page && <button type="button" className="lv-btn lv-btn-ghost" onClick={() => setPage(page + 100)}>Show more ({visible.length - page} remaining)</button>}
    </section>
  )
}
