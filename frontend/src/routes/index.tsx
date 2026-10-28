import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  Bell,
  Bot,
  Boxes,
  ChevronDown,
  CircleDollarSign,
  Cloud,
  CloudCog,
  Code2,
  Command,
  ExternalLink,
  Gauge,
  GitBranch,
  LayoutDashboard,
  MoreHorizontal,
  Play,
  Plus,
  Search,
  Server,
  Settings,
  ShieldCheck,
  Square,
  TerminalSquare,
  Users,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, demoData, type Workspace } from '../lib/api'

export const Route = createFileRoute('/')({ component: App })

type Page = 'Overview' | 'Workspaces' | 'Cloud accounts' | 'Costs' | 'AI agents'

const navItems = [
  { label: 'Overview', icon: LayoutDashboard },
  { label: 'Workspaces', icon: Boxes },
  { label: 'Cloud accounts', icon: CloudCog },
  { label: 'Costs', icon: CircleDollarSign },
  { label: 'AI agents', icon: Bot },
] as const

function App() {
  const navigate = useNavigate()
  const [page, setPage] = useState<Page>('Overview')
  const [showCreate, setShowCreate] = useState(false)
  const [selected, setSelected] = useState<Workspace | null>(null)
  const workspacesQuery = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => api.workspaces().catch(() => demoData.workspaces),
  })
  const summaryQuery = useQuery({
    queryKey: ['dashboard'],
    queryFn: () => api.dashboard().catch(() => demoData.dashboard),
  })
  const [workspaces, setWorkspaces] = useState<Workspace[]>(demoData.workspaces)
  useEffect(() => {
    if (workspacesQuery.data) setWorkspaces(workspacesQuery.data)
  }, [workspacesQuery.data])

  const openConsole = (workspace: Workspace) =>
    navigate({ to: '/console/$workspaceId', params: { workspaceId: workspace.id } })

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Command size={19} strokeWidth={2.4} /></div>
          <span>omniweb</span>
        </div>
        <button className="org-switcher">
          <span className="org-avatar">OL</span>
          <span><strong>Omniweb Labs</strong><small>Production</small></span>
          <ChevronDown size={15} />
        </button>
        <nav className="side-nav">
          <span className="nav-heading">Workspace</span>
          {navItems.map(({ label, icon: Icon }) => (
            <button
              key={label}
              aria-label={label}
              title={label}
              className={page === label ? 'active' : ''}
              onClick={() => setPage(label)}
            >
              <Icon size={17} /><span>{label}</span>
              {label === 'AI agents' && <em>3</em>}
            </button>
          ))}
          <span className="nav-heading nav-separator">Organization</span>
          <button><Users size={17} /><span>Team</span></button>
          <button><ShieldCheck size={17} /><span>Audit log</span></button>
          <button><Settings size={17} /><span>Settings</span></button>
        </nav>
        <div className="sidebar-foot">
          <div className="secure-note"><ShieldCheck size={15} /><span>All systems operational</span></div>
          <div className="profile">
            <span className="profile-avatar">AM</span>
            <span><strong>Avery Morgan</strong><small>Owner</small></span>
            <MoreHorizontal size={16} />
          </div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="searchbox"><Search size={16} /><input placeholder="Search workspaces, projects..." /><kbd>⌘ K</kbd></div>
          <div className="top-actions">
            <button className="icon-button"><Bell size={18} /><i /></button>
            <button className="primary-button" onClick={() => setShowCreate(true)}><Plus size={17} /> New workspace</button>
          </div>
        </header>

        <div className="page-content">
          {page === 'Overview' && (
            <Overview
              summary={summaryQuery.data ?? demoData.dashboard}
              workspaces={workspaces}
              onSelect={setSelected}
              onConsole={openConsole}
              onCreate={() => setShowCreate(true)}
              onPage={setPage}
            />
          )}
          {page === 'Workspaces' && (
            <WorkspaceList workspaces={workspaces} onSelect={setSelected} onConsole={openConsole} />
          )}
          {page === 'Cloud accounts' && <CloudAccounts />}
          {page === 'Costs' && <Costs workspaces={workspaces} />}
          {page === 'AI agents' && <Agents />}
        </div>
      </main>

      <nav className="mobile-nav" aria-label="Primary navigation">
        {navItems.map(({ label, icon: Icon }) => (
          <button
            key={label}
            aria-label={label}
            className={page === label ? 'active' : ''}
            onClick={() => setPage(label)}
          >
            <Icon size={18} />
            <span>{label === 'Cloud accounts' ? 'Cloud' : label}</span>
          </button>
        ))}
      </nav>

      {showCreate && (
        <CreateWorkspace
          onClose={() => setShowCreate(false)}
          onCreated={(workspace) => {
            setWorkspaces((items) => [workspace, ...items])
            setShowCreate(false)
            setSelected(workspace)
          }}
        />
      )}
      {selected && (
        <WorkspaceDrawer
          workspace={selected}
          onClose={() => setSelected(null)}
          onConsole={() => openConsole(selected)}
          onUpdated={(workspace) => {
            setWorkspaces((items) =>
              workspace.state === 'DELETED'
                ? items.filter((item) => item.id !== workspace.id)
                : items.map((item) => (item.id === workspace.id ? workspace : item)),
            )
            setSelected(workspace.state === 'DELETED' ? null : workspace)
          }}
        />
      )}
    </div>
  )
}

function Overview({ summary, workspaces, onSelect, onConsole, onCreate, onPage }: {
  summary: typeof demoData.dashboard
  workspaces: Workspace[]
  onSelect: (w: Workspace) => void
  onConsole: (w: Workspace) => void
  onCreate: () => void
  onPage: (page: Page) => void
}) {
  const stats = [
    ['Total workspaces', summary.total, Boxes, '+1 this month'],
    ['Running now', summary.running, Activity, 'Healthy'],
    ['Cloud accounts', summary.cloud_connections, Cloud, 'Connected'],
    ['Estimated spend', `$${summary.estimated_monthly_usd}`, Gauge, 'This month'],
  ] as const
  return (
    <>
      <div className="page-heading">
        <div><p className="eyebrow">Tuesday, October 27</p><h1>Good evening, Avery.</h1><p>Here’s what’s happening across your development cloud.</p></div>
        <button className="secondary-button" onClick={() => onPage('Costs')}><CircleDollarSign size={16} /> View cost report</button>
      </div>
      <section className="stat-grid">
        {stats.map(([label, value, Icon, note], index) => (
          <article className="stat-card" key={label}>
            <div className={`stat-icon tone-${index}`}><Icon size={18} /></div>
            <span>{label}</span><strong>{value}</strong>
            <small><i className={index === 3 ? 'amber' : ''} />{note}</small>
          </article>
        ))}
      </section>
      <section className="content-grid">
        <div className="panel workspace-panel">
          <div className="panel-head"><div><h2>Workspaces</h2><p>Your recent cloud development environments</p></div><button onClick={() => onPage('Workspaces')}>View all <ExternalLink size={14} /></button></div>
          <div className="workspace-table">
            {workspaces.slice(0, 4).map((workspace) => (
              <WorkspaceRow key={workspace.id} workspace={workspace} onSelect={onSelect} onConsole={onConsole} />
            ))}
          </div>
          <button className="create-row" onClick={onCreate}><Plus size={16} /> Create another workspace</button>
        </div>
        <div className="side-stack">
          <div className="panel activity-panel">
            <div className="panel-head"><div><h2>Recent activity</h2><p>Latest workspace events</p></div></div>
            {[
              ['Workspace started', 'design-system', '3 min ago', Play],
              ['Agent task completed', 'omniweb-core', '18 min ago', Bot],
              ['Workspace stopped', 'api-sandbox', 'Yesterday', Square],
              ['Cloud account verified', 'DigitalOcean', '2 days ago', ShieldCheck],
            ].map(([title, subtitle, time, Icon]) => (
              <div className="activity-item" key={title as string}>
                <div className="activity-icon"><Icon size={15} /></div>
                <div><strong>{title as string}</strong><span>{subtitle as string}</span></div><time>{time as string}</time>
              </div>
            ))}
          </div>
          <div className="agent-card">
            <div className="agent-art"><Bot size={23} /></div>
            <div><span>CODEX AGENT</span><h3>Ready for your next task</h3><p>3 sessions completed this week</p></div>
            <button onClick={() => onPage('AI agents')}>Open agent panel <span>→</span></button>
          </div>
        </div>
      </section>
    </>
  )
}

function WorkspaceRow({ workspace, onSelect, onConsole }: {
  workspace: Workspace
  onSelect: (w: Workspace) => void
  onConsole: (w: Workspace) => void
}) {
  const running = workspace.state === 'READY'
  return (
    <div className="workspace-row" onClick={() => onSelect(workspace)}>
      <div className="workspace-symbol"><Code2 size={18} /></div>
      <div className="workspace-name"><strong>{workspace.name}</strong><span><GitBranch size={12} /> main</span></div>
      <div className="workspace-meta"><span className={`status ${running ? 'ready' : 'stopped'}`}><i />{running ? 'Running' : workspace.state.toLowerCase()}</span><small>{workspace.region} · {workspace.size}</small></div>
      <div className="workspace-actions">
        {running ? <><button onClick={(e) => { e.stopPropagation(); onConsole(workspace) }}><TerminalSquare size={15} /> Console</button><button onClick={(e) => e.stopPropagation()}><ExternalLink size={15} /> IDE</button></> : <button><Play size={15} /> Start</button>}
        <button className="dots"><MoreHorizontal size={17} /></button>
      </div>
    </div>
  )
}

function WorkspaceList({ workspaces, onSelect, onConsole }: { workspaces: Workspace[]; onSelect: (w: Workspace) => void; onConsole: (w: Workspace) => void }) {
  return (
    <>
      <div className="page-heading"><div><p className="eyebrow">Environments</p><h1>Workspaces</h1><p>Build, run, and manage development environments.</p></div></div>
      <div className="panel workspace-panel full-list">
        <div className="list-toolbar"><div className="mini-search"><Search size={15} /> Filter workspaces</div><button className="filter-chip">All states <ChevronDown size={14} /></button></div>
        {workspaces.map((workspace) => <WorkspaceRow key={workspace.id} workspace={workspace} onSelect={onSelect} onConsole={onConsole} />)}
      </div>
    </>
  )
}

function CloudAccounts() {
  const [showConnect, setShowConnect] = useState(false)
  const [label, setLabel] = useState('DigitalOcean')
  const [token, setToken] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const connections = useQuery({
    queryKey: ['cloud-connections'],
    queryFn: () => api.connections(),
  })
  const connect = async () => {
    setSaving(true)
    setError('')
    try {
      await api.connect(label, token)
      await connections.refetch()
      setShowConnect(false)
      setToken('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Connection failed')
    } finally {
      setSaving(false)
    }
  }
  return (
    <>
      <div className="page-heading"><div><p className="eyebrow">Infrastructure</p><h1>Cloud accounts</h1><p>Connect scoped credentials. Omniweb never stores your cloud password.</p></div><button className="primary-button" onClick={() => setShowConnect(true)}><Plus size={16} /> Connect account</button></div>
      {(connections.data ?? []).map((connection) => (
        <div className="panel account-card" key={connection.id}>
          <div className="do-logo">DO</div><div className="account-main"><span className={`status ${connection.healthy ? 'ready' : 'stopped'}`}><i />{connection.healthy ? 'Connected' : 'Unhealthy'}</span><h2>{connection.label}</h2><p>DigitalOcean · •••{connection.token_fingerprint.slice(-4)}</p></div>
          <div className="account-detail"><span>Last verified</span><strong>{connection.last_checked_at ? 'Recently' : 'Unknown'}</strong></div><div className="account-detail"><span>Account</span><strong>{connection.provider_account_id ?? 'Pending'}</strong></div>
          <button className="secondary-button" onClick={() => connections.refetch()}>Verify</button>
        </div>
      ))}
      {!connections.isLoading && !(connections.data ?? []).length && <div className="panel empty-account">No cloud account connected.</div>}
      <div className="security-banner"><ShieldCheck size={22} /><div><strong>Credentials are envelope-encrypted</strong><p>Provider tokens stay in the control plane and are never sent to browsers or workspace VMs.</p></div></div>
      {showConnect && (
        <div className="modal-backdrop" onMouseDown={() => setShowConnect(false)}>
          <section className="connect-modal" onMouseDown={(event) => event.stopPropagation()}>
            <header><div><span>CLOUD ACCOUNT</span><h2>Connect DigitalOcean</h2></div><button onClick={() => setShowConnect(false)}><X size={18} /></button></header>
            <div><label>Connection label<input value={label} onChange={(event) => setLabel(event.target.value)} /></label><label>Scoped API token<input type="password" autoComplete="off" value={token} onChange={(event) => setToken(event.target.value)} placeholder="dop_v1_••••••••" /></label><p>Use a scoped token with account, Droplet, region, size, image, action, VPC, and tag permissions. Never enter your password.</p>{error && <div className="form-error" role="alert">{error}</div>}</div>
            <footer><button className="secondary-button" onClick={() => setShowConnect(false)}>Cancel</button><button className="primary-button" disabled={saving || token.length < 8} onClick={connect}>{saving ? 'Verifying…' : 'Verify & connect'}</button></footer>
          </section>
        </div>
      )}
    </>
  )
}

function Costs({ workspaces }: { workspaces: Workspace[] }) {
  const total = workspaces.reduce((sum, workspace) => sum + Number(workspace.estimated_monthly_usd), 0)
  return (
    <>
      <div className="page-heading"><div><p className="eyebrow">Usage & budgets</p><h1>Estimated costs</h1><p>Infrastructure estimates are not provider invoices.</p></div><button className="secondary-button"><Bell size={16} /> Budget alerts</button></div>
      <div className="cost-hero"><div><span>ESTIMATED MONTHLY INFRASTRUCTURE</span><strong>${total.toFixed(2)}</strong><p>Compute and attached storage may continue billing while stopped.</p></div><div className="budget-ring"><span>39%</span><small>of $200 limit</small></div></div>
      <div className="panel cost-table">{workspaces.map((w) => <div key={w.id}><span><Code2 size={15} />{w.name}</span><em>{w.size}</em><strong>${Number(w.estimated_monthly_usd).toFixed(2)}/mo</strong></div>)}</div>
    </>
  )
}

function Agents() {
  return (
    <>
      <div className="page-heading"><div><p className="eyebrow">Coding automation</p><h1>AI agents</h1><p>Review active sessions, approvals, and execution history.</p></div><button className="primary-button"><Plus size={16} /> New task</button></div>
      <div className="agents-grid">
        {[
          ['Add workspace budget alerts', 'omniweb-core', 'Needs approval', 'Review infrastructure changes before applying.', 'amber'],
          ['Refactor authentication middleware', 'omniweb-core', 'Running', 'Analyzing cross-tenant authorization tests.', 'green'],
          ['Create responsive billing table', 'design-system', 'Completed', '8 files changed · 34 minutes ago', 'blue'],
        ].map(([title, workspace, state, detail, color]) => (
          <article className="panel agent-session" key={title}><div className={`agent-session-icon ${color}`}><Bot size={19} /></div><span className={`agent-state ${color}`}>{state}</span><h3>{title}</h3><p>{detail}</p><small><Code2 size={13} /> {workspace}</small><button>View session →</button></article>
        ))}
      </div>
    </>
  )
}

function CreateWorkspace({ onClose, onCreated }: { onClose: () => void; onCreated: (w: Workspace) => void }) {
  const [step, setStep] = useState(1)
  const [name, setName] = useState('new-project')
  const [region, setRegion] = useState('nyc3')
  const [size, setSize] = useState('s-2vcpu-4gb')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const connections = useQuery({
    queryKey: ['cloud-connections'],
    queryFn: () => api.connections(),
  })
  const regions = useQuery({
    queryKey: ['regions'],
    queryFn: () => api.regions(),
  })
  const sizes = useQuery({
    queryKey: ['sizes', region],
    queryFn: () => api.sizes(region),
  })
  const availableRegions = regions.data ?? demoData.regions
  const availableSizes = sizes.data ?? demoData.sizes
  const selectedSize = availableSizes.find((item) => item.slug === size) ?? availableSizes[0]
  const connection = connections.data?.find((item) => item.healthy)

  const create = async () => {
    if (!connection || !selectedSize) {
      setError('Connect a healthy cloud account before creating a workspace.')
      return
    }
    setSubmitting(true)
    setError('')
    try {
      const workspace = await api.createWorkspace({
        name,
        cloud_connection_id: connection.id,
        region,
        size: selectedSize.slug,
        image: 'ubuntu-24-04-x64',
        template: 'full-stack',
        idempotency_key: `web-${name}-${crypto.randomUUID()}`,
        approved_estimated_monthly_usd: selectedSize.monthly_usd,
      })
      onCreated(workspace)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Workspace creation failed')
    } finally {
      setSubmitting(false)
    }
  }
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="create-modal" onMouseDown={(e) => e.stopPropagation()}>
        <header><div><span>NEW WORKSPACE</span><h2>Create a development environment</h2></div><button onClick={onClose}><X size={19} /></button></header>
        <div className="stepper">{['Cloud', 'Compute', 'Template', 'Review'].map((label, index) => <div className={step >= index + 1 ? 'done' : ''} key={label}><i>{index + 1}</i><span>{label}</span></div>)}</div>
        <div className="modal-body">
          {step === 1 && <><label>Workspace name<input value={name} onChange={(e) => setName(e.target.value)} /></label><label>Cloud account<div className={`choice-card ${connection ? 'selected' : ''}`}><div className="do-logo small">DO</div><span><strong>{connection?.label ?? 'No healthy account'}</strong><small>{connection ? 'Connected and healthy' : 'Connect DigitalOcean from Cloud accounts'}</small></span>{connection && <ShieldCheck size={18} />}</div></label><label>Region<select value={region} onChange={(e) => setRegion(e.target.value)}>{availableRegions.map((r) => <option key={r.slug} value={r.slug}>{r.name}</option>)}</select></label></>}
          {step === 2 && <><div className="form-intro"><Server size={18} /><div><strong>Choose compute</strong><p>Availability and pricing are checked before provisioning.</p></div></div><div className="size-grid">{availableSizes.map((item) => <button className={size === item.slug ? 'selected' : ''} onClick={() => setSize(item.slug)} key={item.slug}><span>{item.vcpus} vCPU · {item.memory_mb / 1024} GB</span><strong>${item.monthly_usd}<small>/mo</small></strong><em>{item.disk_gb} GB SSD</em></button>)}</div></>}
          {step === 3 && <><label>Development template<div className="choice-card selected"><div className="template-icon"><Code2 size={19} /></div><span><strong>Full-stack TypeScript</strong><small>Node.js LTS, Python, Docker, Git, Codex CLI</small></span><ShieldCheck size={18} /></div></label><label>Base image<select><option>Ubuntu 24.04 LTS</option></select></label><div className="security-inline"><ShieldCheck size={18} /><span><strong>Private by default</strong>No public inbound SSH port. Access is routed through the authenticated workspace agent.</span></div></>}
          {step === 4 && selectedSize && <><div className="review-title"><ShieldCheck size={22} /><div><strong>Ready to provision</strong><p>Review the cost and billing implications.</p></div></div><div className="review-grid"><span>Name<strong>{name}</strong></span><span>Region<strong>{region}</strong></span><span>Compute<strong>{selectedSize.vcpus} vCPU · {selectedSize.memory_mb / 1024} GB</strong></span><span>Image<strong>Ubuntu 24.04 LTS</strong></span></div><div className="price-review"><span>Estimated infrastructure cost<small>Provider billing is authoritative</small></span><strong>${selectedSize.monthly_usd}<small>/month</small></strong></div><p className="billing-note">Stopping may not eliminate all charges. Storage and reserved resources can continue billing until deleted.</p></>}
          {error && <div className="form-error" role="alert">{error}</div>}
        </div>
        <footer><button className="secondary-button" disabled={submitting} onClick={step === 1 ? onClose : () => setStep(step - 1)}>{step === 1 ? 'Cancel' : 'Back'}</button><button className="primary-button" disabled={submitting || (step === 1 && !connection)} onClick={step === 4 ? create : () => setStep(step + 1)}>{submitting ? 'Creating…' : step === 4 ? 'Approve & create' : 'Continue'} <span>→</span></button></footer>
      </section>
    </div>
  )
}

function WorkspaceDrawer({ workspace, onClose, onConsole, onUpdated }: {
  workspace: Workspace
  onClose: () => void
  onConsole: () => void
  onUpdated: (workspace: Workspace) => void
}) {
  const navigate = useNavigate()
  const [pending, setPending] = useState('')
  const [error, setError] = useState('')
  const ready = workspace.state === 'READY'

  const openIde = async () => {
    setPending('ide')
    setError('')
    try {
      const link = await api.access(workspace.id, 'ide')
      const parsed = new URL(link.url, window.location.origin)
      await navigate({
        to: '/ide/$workspaceId',
        params: { workspaceId: workspace.id },
        search: { access_token: parsed.searchParams.get('access_token') ?? '' },
      })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not open IDE')
      setPending('')
    }
  }

  const lifecycle = async (action: 'start' | 'stop' | 'restart' | 'delete') => {
    if (action === 'delete' && !window.confirm(`Delete ${workspace.name}? Provider resources will be removed.`)) return
    setPending(action)
    setError('')
    try {
      onUpdated(await api.lifecycle(workspace.id, action))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : `Could not ${action} workspace`)
    } finally {
      setPending('')
    }
  }

  return (
    <div className="drawer-backdrop" onMouseDown={onClose}><aside className="drawer" onMouseDown={(e) => e.stopPropagation()}>
      <header><div className="workspace-symbol"><Code2 size={19} /></div><div><span className={`status ${ready ? 'ready' : 'stopped'}`}><i />{ready ? 'Running' : workspace.state.toLowerCase()}</span><h2>{workspace.name}</h2><p><GitBranch size={13} /> main · Updated 3 min ago</p></div><button onClick={onClose}><X size={19} /></button></header>
      <div className="drawer-actions"><button className="primary-button" disabled={!ready || Boolean(pending)} onClick={openIde}><ExternalLink size={16} /> {pending === 'ide' ? 'Opening…' : 'Open IDE'}</button><button className="secondary-button" disabled={!ready || Boolean(pending)} onClick={onConsole}><TerminalSquare size={16} /> Console</button></div>
      {error && <div className="form-error" role="alert">{error}</div>}
      <section><h3>Environment</h3><dl><div><dt>Provider</dt><dd>DigitalOcean</dd></div><div><dt>Region</dt><dd>{workspace.region}</dd></div><div><dt>Compute</dt><dd>{workspace.size}</dd></div><div><dt>Image</dt><dd>Ubuntu 24.04 LTS</dd></div><div><dt>Est. cost</dt><dd>${workspace.estimated_monthly_usd}/mo</dd></div></dl></section>
      <section><h3>Health</h3><div className="health-row"><span><i />Workspace agent</span><strong>Connected</strong></div><div className="health-row"><span><i />Coder transport</span><strong>Healthy</strong></div><div className="health-row"><span><i />Persistent disk</span><strong>Mounted</strong></div></section>
      <section><h3>Local IDE</h3><button className="guide-button"><Code2 size={17} /><span><strong>Open in VS Code</strong><small>Requires Coder extension</small></span><ExternalLink size={15} /></button><button className="guide-button"><Command size={17} /><span><strong>Open in Cursor</strong><small>Guided connection setup</small></span><ExternalLink size={15} /></button></section>
      <div className="danger-actions">
        {ready ? (
          <button disabled={Boolean(pending)} onClick={() => lifecycle('stop')}><Square size={15} /> {pending === 'stop' ? 'Stopping…' : 'Stop'}</button>
        ) : (
          <button disabled={Boolean(pending)} onClick={() => lifecycle('start')}><Play size={15} /> {pending === 'start' ? 'Starting…' : 'Start'}</button>
        )}
        <button className="danger" disabled={Boolean(pending)} onClick={() => lifecycle('delete')}>{pending === 'delete' ? 'Deleting…' : 'Delete workspace'}</button>
      </div>
    </aside></div>
  )
}
