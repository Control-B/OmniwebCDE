import { useQueries, useQuery } from '@tanstack/react-query'
import { Link, createFileRoute } from '@tanstack/react-router'
import {
  Activity, ArrowLeft, BookOpen, Bot, BriefcaseBusiness, Contact, DraftingCompass, FileText,
  GitPullRequestArrow, Layers3, Megaphone, PanelTop, Sparkles, Workflow,
} from 'lucide-react'
import { useState } from 'react'

import { AppNav, RequireAuth } from '../components/studio/AppNav'
import {
  platform,
  type Asset,
  type BusinessPlan,
  type Campaign,
  type CrmContact,
  type EvolutionCase,
  type Funnel,
  type IntelligenceWorkflow,
} from '../lib/api'

export const Route = createFileRoute('/projects/$projectId/growth')({
  head: () => ({ meta: [{ title: 'Growth Workspace — Omniweb' }] }),
  component: () => (
    <div className="st growth">
      <AppNav />
      <RequireAuth><GrowthWorkspace /></RequireAuth>
    </div>
  ),
})

const tabs = [
  ['overview', 'Overview', Layers3],
  ['business', 'Business Planner', BriefcaseBusiness],
  ['campaigns', 'Campaigns', Megaphone],
  ['funnels', 'Funnels', PanelTop],
  ['blog', 'Blog CMS', BookOpen],
  ['content', 'Content Studio', FileText],
  ['crm', 'CRM & Leads', Contact],
  ['automation', 'Automations', Workflow],
  ['analytics', 'Analytics', Activity],
  ['improvements', 'Capability Improvements', GitPullRequestArrow],
] as const

type Tab = typeof tabs[number][0]

function GrowthWorkspace() {
  const { projectId } = Route.useParams()
  const [tab, setTab] = useState<Tab>('overview')
  const project = useQuery({ queryKey: ['project', projectId], queryFn: () => platform.project(projectId) })
  const queries = useQueries({
    queries: [
      { queryKey: ['workflows', projectId], queryFn: () => platform.intelligenceWorkflows(projectId) },
      { queryKey: ['plans', projectId], queryFn: () => platform.businessPlans(projectId) },
      { queryKey: ['campaigns', projectId], queryFn: () => platform.campaigns(projectId) },
      { queryKey: ['funnels', projectId], queryFn: () => platform.funnels(projectId) },
      { queryKey: ['assets', projectId], queryFn: () => platform.assets(projectId) },
      { queryKey: ['contacts', projectId], queryFn: () => platform.contacts(projectId) },
      { queryKey: ['analytics', projectId], queryFn: () => platform.analytics(projectId) },
      { queryKey: ['evolution', projectId], queryFn: () => platform.evolutionCases(projectId) },
    ],
  })
  const workflows = queries[0].data as IntelligenceWorkflow[] | undefined
  const plans = queries[1].data as BusinessPlan[] | undefined
  const campaigns = queries[2].data as Campaign[] | undefined
  const funnels = queries[3].data as Funnel[] | undefined
  const assets = queries[4].data as Asset[] | undefined
  const contacts = queries[5].data as CrmContact[] | undefined
  const analytics = queries[6].data as { events: Record<string, number>; visitors: number; leads: number; funnel_conversion_rate: number | null; note: string } | undefined
  const cases = queries[7].data as EvolutionCase[] | undefined
  const pending = queries.some((query) => query.isLoading)
  const error = queries.find((query) => query.error)?.error

  return (
    <main className="growth-shell">
      <header className="growth-workspace-head">
        <div>
          <Link to="/projects/$projectId" params={{ projectId }} search={{ start: false }} className="st-back"><ArrowLeft size={14} /> Application Studio</Link>
          <h1>{project.data?.name ?? 'Project workspace'}</h1>
          <p>Software, strategy, campaigns, creative assets, customers, and verified improvements in one context.</p>
        </div>
        <Link to="/create" className="growth-primary"><Sparkles size={15} /> Create with AI</Link>
      </header>
      <div className="growth-layout">
        <nav className="growth-sidebar" aria-label="Project workspace">
          {tabs.map(([id, label, Icon]) => <button key={id} type="button" aria-current={tab === id ? 'page' : undefined} onClick={() => setTab(id)}><Icon size={16} /><span>{label}</span>{countFor(id, { workflows, plans, campaigns, funnels, assets, contacts, cases })}</button>)}
          <Link to="/projects/$projectId/engineering" params={{ projectId }}><DraftingCompass size={16} /><span>Engineering Design</span></Link>
          <Link to="/usage"><Bot size={16} /><span>AI Usage & Budgets</span></Link>
        </nav>
        <section className="growth-content">
          {error ? <Empty title="This view could not be loaded" text={error.message} /> : pending ? <div className="growth-loading"><span className="st-spinner" /> Loading connected workspace…</div> : (
            <>
              {tab === 'overview' && <Overview data={{ workflows, plans, campaigns, funnels, assets, contacts, analytics, cases }} />}
              {tab === 'business' && <Collection title="Business plans" description="Editable plans separate sourced market evidence from assumptions and projections." rows={plans} empty="Ask Omniweb to create a business plan." render={(row) => <><strong>{row.title}</strong><p>Version {row.version} · {row.status}</p></>} />}
              {tab === 'campaigns' && <Collection title="Campaigns" description="Strategy, audiences, calendars, budgets, and publication approvals." rows={campaigns} empty="Create a campaign from Unified Create." render={(row) => <><strong>{row.name}</strong><p>{row.objective}</p><Meta left={row.status} right={`$${row.spend_usd.toFixed(2)} recorded spend`} /></>} />}
              {tab === 'funnels' && <Collection title="Funnels" description="Versioned multi-step journeys with previews, lead capture, analytics, and approval-gated publishing." rows={funnels} empty="Generate your first funnel from a campaign prompt." render={(row) => <><strong>{row.name}</strong><p>{row.funnel_type.replaceAll('_', ' ')} · {row.definition.steps?.length ?? 0} steps</p><Meta left={row.status} right={`v${row.current_version}`} /></>} />}
              {tab === 'blog' && <Empty title="Blog CMS" text="Create an editorial plan from Unified Create. Articles enforce sourced claims, SEO metadata, approval, sitemap, and RSS contracts." action="Create editorial plan" />}
              {tab === 'content' && <Collection title="Content library" description="Versioned text, image, and video assets with model, cost, rights, approval, and campaign lineage." rows={assets} empty="Generate campaign content, images, or a video brief." render={(row) => <><strong>{row.title}</strong><p>{row.content_type.replaceAll('_', ' ')} · v{row.current_version}</p><Meta left={row.status} right={`${row.provider ?? 'deterministic'} · $${row.cost_usd.toFixed(4)}`} /></>} />}
              {tab === 'crm' && <Collection title="CRM & leads" description="Consent-aware contacts created from authorized funnel submissions." rows={contacts} empty="Publish an approved funnel and capture your first authorized lead." render={(row) => <><strong>{[row.first_name, row.last_name].filter(Boolean).join(' ') || row.email}</strong><p>{row.email} · {row.company || 'No company'}</p><Meta left={row.stage} right={row.marketing_consent ? 'Marketing consent recorded' : 'No marketing consent'} /></>} />}
              {tab === 'automation' && <Empty title="Marketing automations" text="Build durable trigger-and-action workflows. Email, webhooks, generative actions, and external side effects remain provider- and approval-gated." action="Design an automation" />}
              {tab === 'analytics' && <Analytics data={analytics} />}
              {tab === 'improvements' && <Collection title="Capability improvements" description="Every software and marketing proposal stays linked to authorized evidence and a versioned lifecycle." rows={cases} empty="Record an evidence-backed marketing observation." render={(row) => <><strong>{row.title}</strong><p>{row.direction.replaceAll('_', ' ')} · {row.objective}</p><Meta left={row.state.replaceAll('_', ' ')} right="Traceable" /></>} />}
            </>
          )}
        </section>
      </div>
    </main>
  )
}

function countFor(id: Tab, data: Record<string, any>) {
  const value = ({ overview: data.workflows, business: data.plans, campaigns: data.campaigns, funnels: data.funnels, blog: [], content: data.assets, crm: data.contacts, automation: [], analytics: [], improvements: data.cases } as Record<Tab, unknown[]>)[id]?.length
  return value ? <small>{value}</small> : null
}

function Overview({ data }: { data: Record<string, any> }) {
  const cards = [
    ['Business plans', data.plans?.length ?? 0, BriefcaseBusiness],
    ['Active campaigns', data.campaigns?.filter((item: any) => item.status === 'active').length ?? 0, Megaphone],
    ['Creative assets', data.assets?.length ?? 0, FileText],
    ['CRM contacts', data.contacts?.length ?? 0, Contact],
  ] as const
  return <><div className="growth-section-title"><div><span>Project command center</span><h2>Everything moves together.</h2><p>Business strategy informs product and campaigns. Verified releases can propose marketing updates; measured campaign evidence can propose software improvements.</p></div></div><div className="growth-metrics">{cards.map(([label, value, Icon]) => <article key={label}><Icon size={18} /><strong>{value}</strong><span>{label}</span></article>)}</div><div className="growth-panels"><article><h3>Recent unified runs</h3>{data.workflows?.slice(0, 4).map((row: any) => <div className="growth-line" key={row.id}><span className={`growth-dot ${row.status}`} /><div><strong>{row.prompt}</strong><small>{row.mode} · {row.tasks.length} tasks</small></div><span>{row.status}</span></div>) ?? null}{!data.workflows?.length && <p className="st-muted">No connected runs yet.</p>}</article><article><h3>Measured performance</h3><div className="growth-analytics-mini"><div><strong>{data.analytics?.visitors ?? 0}</strong><span>recorded visitors</span></div><div><strong>{data.analytics?.leads ?? 0}</strong><span>authorized leads</span></div><div><strong>{data.analytics?.funnel_conversion_rate == null ? '—' : `${(data.analytics.funnel_conversion_rate * 100).toFixed(1)}%`}</strong><span>funnel conversion</span></div></div><p className="st-fine">Only recorded first-party events are shown. Missing values are never estimated.</p></article></div></>
}

function Collection<T>({ title, description, rows, empty, render }: { title: string; description: string; rows?: T[]; empty: string; render: (row: T) => React.ReactNode }) {
  return <><div className="growth-section-title"><div><span>Connected project data</span><h2>{title}</h2><p>{description}</p></div><Link to="/create" className="growth-primary secondary"><Sparkles size={14} /> Create</Link></div>{rows?.length ? <div className="growth-card-grid">{rows.map((row: any) => <article key={row.id}>{render(row)}</article>)}</div> : <Empty title={`No ${title.toLowerCase()} yet`} text={empty} action="Start with a prompt" />}</>
}

function Meta({ left, right }: { left: string; right: string }) { return <div className="growth-meta"><span>{left}</span><span>{right}</span></div> }
function Empty({ title, text, action }: { title: string; text: string; action?: string }) { return <div className="growth-empty"><Sparkles size={21} /><h3>{title}</h3><p>{text}</p>{action && <Link to="/create" className="growth-primary secondary">{action} <ArrowLeft size={14} className="growth-arrow-forward" /></Link>}</div> }
function Analytics({ data }: { data: any }) { return <><div className="growth-section-title"><div><span>Actual first-party data</span><h2>Campaign analytics</h2><p>Consent-aware events, funnel abandonment, attribution, and experiments. Omniweb never fabricates performance.</p></div></div><div className="growth-metrics">{[['Visitors', data?.visitors ?? 0], ['Leads', data?.leads ?? 0], ['Conversion', data?.funnel_conversion_rate == null ? '—' : `${(data.funnel_conversion_rate * 100).toFixed(1)}%`], ['Event types', Object.keys(data?.events ?? {}).length]].map(([label, value]) => <article key={label}><Activity size={18} /><strong>{value}</strong><span>{label}</span></article>)}</div><div className="st-card"><h3>Recorded events</h3>{Object.entries(data?.events ?? {}).map(([key, value]) => <div className="st-kv" key={key}><span>{key.replaceAll('_', ' ')}</span><strong>{String(value)}</strong></div>)}{!Object.keys(data?.events ?? {}).length && <p className="st-muted">No authorized analytics events have been recorded.</p>}</div></> }
