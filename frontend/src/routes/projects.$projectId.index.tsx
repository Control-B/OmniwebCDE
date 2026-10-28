import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import {
  ArrowLeft,
  ArrowUp,
  Check,
  CircleAlert,
  Database,
  FileCode2,
  KeyRound,
  ListChecks,
  Loader2,
  Maximize2,
  Minimize2,
  Monitor,
  MousePointerClick,
  PanelLeft,
  PanelRight,
  Plus,
  Rocket,
  ScrollText,
  Settings,
  Smartphone,
  Sparkles,
  Square,
  Tablet,
  Trash2,
  Waypoints,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Group, Panel, Separator, usePanelRef } from 'react-resizable-panels'
import { z } from 'zod'

import { RequireAuth } from '../components/studio/AppNav'
import { platform, type ChatMessage, type Execution, type Tier } from '../lib/api'
import { STATUS_LABEL, relativeTime, usd } from './projects.index'

export const Route = createFileRoute('/projects/$projectId/')({
  validateSearch: z.object({ start: z.boolean().optional() }),
  head: () => ({ meta: [{ title: 'Builder — Omniweb' }] }),
  component: () => (
    <div className="st st-full">
      <RequireAuth>
        <Studio />
      </RequireAuth>
    </div>
  ),
})

type LeftTab = 'chat' | 'progress' | 'requirements' | 'changes' | 'usage'
type RightTab = 'files' | 'database' | 'api' | 'env' | 'deploy' | 'logs'
type Device = 'desktop' | 'tablet' | 'mobile'

const TIERS: { value: Tier | ''; label: string }[] = [
  { value: '', label: 'Auto' },
  { value: 'economy', label: 'Economy' },
  { value: 'standard', label: 'Standard' },
  { value: 'advanced', label: 'Advanced' },
  { value: 'self_hosted', label: 'Self-hosted' },
]

function useIsMobile(query = '(max-width: 860px)') {
  const [mobile, setMobile] = useState(false)
  useEffect(() => {
    const media = window.matchMedia(query)
    const update = () => setMobile(media.matches)
    update()
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [query])
  return mobile
}

function requestId() {
  return crypto.randomUUID().replaceAll('-', '')
}

function Studio() {
  const { projectId } = Route.useParams()
  const { start } = Route.useSearch()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const project = useQuery({ queryKey: ['project', projectId], queryFn: () => platform.project(projectId) })
  const messages = useQuery({ queryKey: ['messages', projectId], queryFn: () => platform.messages(projectId) })
  const executions = useQuery({ queryKey: ['executions', projectId], queryFn: () => platform.executions(projectId) })
  const [leftTab, setLeftTab] = useState<LeftTab>('chat')
  const [rightTab, setRightTab] = useState<RightTab>('env')
  const [device, setDevice] = useState<Device>('desktop')
  const [fullscreen, setFullscreen] = useState<'none' | 'preview' | 'code'>('none')
  const [leftOpen, setLeftOpen] = useState(true)
  const [rightOpen, setRightOpen] = useState(true)
  const [mobilePane, setMobilePane] = useState<'left' | 'center' | 'right'>('left')
  const leftPanel = usePanelRef()
  const rightPanel = usePanelRef()
  const [input, setInput] = useState('')
  const [tier, setTier] = useState<Tier | ''>('')
  const [pending, setPending] = useState<{ id: string; content: string } | null>(null)
  const [alerts, setAlerts] = useState<string[]>([])
  const isMobile = useIsMobile()
  const autoStarted = useRef(false)
  const chatEnd = useRef<HTMLDivElement>(null)

  const refreshAll = () => {
    void queryClient.invalidateQueries({ queryKey: ['messages', projectId] })
    void queryClient.invalidateQueries({ queryKey: ['executions', projectId] })
    void queryClient.invalidateQueries({ queryKey: ['project', projectId] })
    void queryClient.invalidateQueries({ queryKey: ['project-usage', projectId] })
  }

  const send = useMutation({
    mutationFn: ({ content, id }: { content: string; id: string }) => platform.send(projectId, content, id, tier || undefined),
    onMutate: ({ content, id }) => setPending({ id, content }),
    onSuccess: (result) => setAlerts(result.alerts),
    onSettled: () => {
      setPending(null)
      refreshAll()
    },
  })

  const submit = (value: string) => {
    const content = value.trim()
    if (!content || send.isPending) return
    setInput('')
    send.reset()
    send.mutate({ content, id: requestId() })
  }

  useEffect(() => {
    if (!start || autoStarted.current || !project.data || !messages.data) return
    autoStarted.current = true
    void navigate({ to: '/projects/$projectId', params: { projectId }, search: {}, replace: true })
    if (messages.data.length === 0) submit(project.data.prompt)
  }, [start, project.data, messages.data])

  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.data?.length, pending])

  const toggle = (side: 'left' | 'right') => {
    const panel = side === 'left' ? leftPanel.current : rightPanel.current
    if (!panel) return
    if (panel.isCollapsed()) panel.expand()
    else panel.collapse()
  }

  if (project.isLoading) return <div className="st-center"><span className="st-spinner" aria-label="Loading project" /></div>
  if (project.error || !project.data) {
    return (
      <div className="st-center st-stack">
        <h1>Project not found</h1>
        <p className="st-muted">It may have been deleted, or you may not have access to it.</p>
        <Link to="/projects" className="lv-btn lv-btn-light">Back to projects</Link>
      </div>
    )
  }

  const p = project.data
  const readOnly = p.your_role === 'viewer'
  const latestRequirements = [...(messages.data ?? [])].reverse().find((m) => m.role === 'assistant' && m.agent === 'requirements')

  const left = (
    <section className="st-panel" aria-label="Conversation and progress">
      <div className="st-tabs" role="tablist">
        {(
          [
            ['chat', 'Chat'],
            ['progress', 'Progress'],
            ['requirements', 'Requirements'],
            ['changes', 'Changes'],
            ['usage', 'Usage'],
          ] as [LeftTab, string][]
        ).map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={leftTab === id} onClick={() => setLeftTab(id)}>{label}</button>
        ))}
      </div>
      {leftTab === 'chat' && (
        <div className="st-chat">
          <div className="bd-messages">
            {messages.isLoading && <span className="st-spinner" aria-label="Loading messages" />}
            {messages.data?.length === 0 && !pending && (
              <div className="st-empty st-empty-tight">
                <Sparkles size={18} />
                <p className="st-muted">Describe what you want to build. The requirements assistant will turn it into user stories and ask only what matters.</p>
                <button type="button" className="lv-btn lv-btn-light" onClick={() => submit(p.prompt)} disabled={readOnly}>Start with the project prompt</button>
              </div>
            )}
            {messages.data?.map((message) => <Bubble key={message.id} message={message} />)}
            {pending && (
              <>
                <div className="bd-msg bd-msg-user"><div className="bd-bubble"><p>{pending.content}</p></div></div>
                <div className="bd-msg bd-msg-assistant">
                  <span className="bd-avatar"><Sparkles size={13} /></span>
                  <div className="bd-bubble st-thinking">
                    <span className="bd-typing"><span /><span /><span /></span>
                    <span className="st-muted">Requirements assistant is thinking</span>
                    <button type="button" className="st-link" onClick={() => void platform.cancel(projectId, pending.id)}>
                      <Square size={11} /> Stop
                    </button>
                  </div>
                </div>
              </>
            )}
            {send.error && (
              <div className="st-alert st-alert-error">
                <CircleAlert size={14} /> {send.error.message}
              </div>
            )}
            {alerts.map((alert) => <div key={alert} className="st-alert"><CircleAlert size={14} /> {alert}</div>)}
            <div ref={chatEnd} />
          </div>
          <form
            className="bd-input st-input"
            onSubmit={(event) => {
              event.preventDefault()
              submit(input)
            }}
          >
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  submit(input)
                }
              }}
              rows={2}
              disabled={readOnly}
              placeholder={readOnly ? 'You have view-only access' : 'Describe a requirement or answer a question…'}
              aria-label="Message the requirements assistant"
            />
            <div className="st-input-bar">
              <label className="st-select" title="Model tier. Auto uses the project's preference.">
                <select value={tier} onChange={(event) => setTier(event.target.value as Tier | '')} aria-label="Model tier">
                  {TIERS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </label>
              <button type="submit" className="lv-send" disabled={!input.trim() || send.isPending || readOnly} aria-label="Send">
                <ArrowUp size={17} strokeWidth={2.5} />
              </button>
            </div>
          </form>
        </div>
      )}
      {leftTab === 'progress' && <Progress executions={executions.data ?? []} loading={executions.isLoading} />}
      {leftTab === 'requirements' && (
        <div className="st-scroll">
          {latestRequirements ? (
            <article className="st-doc">
              <p className="st-kicker">Latest draft from the requirements assistant</p>
              <div className="st-pre">{latestRequirements.content}</div>
              <p className="st-fine">Structured requirements, acceptance criteria, and approval arrive with the generation pipeline in Milestone 2.</p>
            </article>
          ) : (
            <Empty icon={<ListChecks size={18} />} title="No requirements yet" text="Send a message in Chat and the assistant’s draft will appear here." />
          )}
        </div>
      )}
      {leftTab === 'changes' && (
        <Empty icon={<FileCode2 size={18} />} title="No file changes" text="Omniweb hasn’t generated code for this project. File diffs and Git checkpoints will appear here once code generation is enabled." />
      )}
      {leftTab === 'usage' && <ProjectUsage projectId={projectId} />}
    </section>
  )

  const center = (
    <section className={`st-panel st-center-panel${fullscreen === 'preview' ? ' st-fullscreen' : ''}`} aria-label="Preview">
      <div className="bd-toolbar">
        <div className="bd-switch bd-devices">
          <button type="button" aria-pressed={device === 'desktop'} onClick={() => setDevice('desktop')} title="Desktop"><Monitor size={15} /></button>
          <button type="button" aria-pressed={device === 'tablet'} onClick={() => setDevice('tablet')} title="Tablet"><Tablet size={15} /></button>
          <button type="button" aria-pressed={device === 'mobile'} onClick={() => setDevice('mobile')} title="Mobile"><Smartphone size={15} /></button>
        </div>
        <button type="button" className="bd-icon" disabled title="Select a component to edit (available once there is a preview)"><MousePointerClick size={15} /></button>
        <span className="bd-muted">No build yet</span>
        <div className="bd-toolbar-right">
          <button type="button" className="bd-icon" onClick={() => setFullscreen(fullscreen === 'preview' ? 'none' : 'preview')} title={fullscreen === 'preview' ? 'Exit full screen' : 'Full-screen preview'}>
            {fullscreen === 'preview' ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
          </button>
        </div>
      </div>
      <div className="bd-canvas">
        <div className={`bd-frame bd-frame-${device} st-preview-empty`}>
          <div>
            <Waypoints size={22} />
            <h3>No preview yet</h3>
            <p>Omniweb is gathering requirements. A live preview appears here after the first build, which runs in an isolated sandbox.</p>
            <span className="st-pill">Code generation: Milestone 2</span>
          </div>
        </div>
      </div>
    </section>
  )

  const right = (
    <section className={`st-panel${fullscreen === 'code' ? ' st-fullscreen' : ''}`} aria-label="Project details">
      <div className="st-tabs st-tabs-icons" role="tablist">
        {(
          [
            ['files', 'Files', FileCode2],
            ['database', 'Database', Database],
            ['api', 'API', Waypoints],
            ['env', 'Environment', KeyRound],
            ['deploy', 'Deploy', Rocket],
            ['logs', 'Logs', ScrollText],
          ] as const
        ).map(([id, label, Icon]) => (
          <button key={id} type="button" role="tab" aria-selected={rightTab === id} onClick={() => setRightTab(id)} title={label}>
            <Icon size={14} /> <span>{label}</span>
          </button>
        ))}
        <button type="button" className="bd-icon st-tab-end" onClick={() => setFullscreen(fullscreen === 'code' ? 'none' : 'code')} title={fullscreen === 'code' ? 'Exit full screen' : 'Full screen'}>
          {fullscreen === 'code' ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
        </button>
      </div>
      {rightTab === 'files' && <Empty icon={<FileCode2 size={18} />} title="No source files yet" text="Generated source appears here with a code editor. Everything Omniweb writes stays exportable." />}
      {rightTab === 'database' && <Empty icon={<Database size={18} />} title="No database schema yet" text="Tables, relationships, and migrations appear here once the database agent designs the schema." />}
      {rightTab === 'api' && <Empty icon={<Waypoints size={18} />} title="No API routes yet" text="Routes from the generated backend’s OpenAPI document will be listed here." />}
      {rightTab === 'env' && <EnvVars projectId={projectId} readOnly={readOnly} />}
      {rightTab === 'deploy' && (
        <div className="st-scroll">
          <div className="st-kv"><span>Status</span><strong>{STATUS_LABEL[p.deployment_status] ?? p.deployment_status}</strong></div>
          <div className="st-kv"><span>GitHub</span><strong>{p.github_repo ?? 'Not connected'}</strong></div>
          <p className="st-fine">Deployments to DigitalOcean always show estimated charges and require your explicit approval before any billable resource is created.</p>
          <button type="button" className="lv-btn lv-btn-ghost st-wide" disabled>Deploy (requires a successful build)</button>
        </div>
      )}
      {rightTab === 'logs' && <Logs executions={executions.data ?? []} />}
    </section>
  )

  return (
    <div className="st-studio" data-pane={mobilePane} data-fullscreen={fullscreen}>
      <header className="bd-top">
        <div className="bd-top-left">
          <Link to="/projects" className="bd-home" aria-label="Back to projects"><ArrowLeft size={16} /></Link>
          <span className="lv-mark" />
          <div className="bd-title">
            <strong>{p.name}</strong>
            <small>{p.template_label} · edited {relativeTime(p.updated_at)}</small>
          </div>
          <span className={`st-status st-status-${p.generation_status}`}>{STATUS_LABEL[p.generation_status]}</span>
        </div>
        <div className="bd-switch bd-mobile-only" role="tablist">
          <button type="button" role="tab" aria-selected={mobilePane === 'left'} onClick={() => setMobilePane('left')}>Chat</button>
          <button type="button" role="tab" aria-selected={mobilePane === 'center'} onClick={() => setMobilePane('center')}>Preview</button>
          <button type="button" role="tab" aria-selected={mobilePane === 'right'} onClick={() => setMobilePane('right')}>Project</button>
        </div>
        <div className="bd-top-right">
          <span className="st-cost" title="AI usage for this project">{usd(p.estimated_usage_usd)}</span>
          <button type="button" className="bd-icon st-desktop-only" onClick={() => toggle('left')} aria-pressed={leftOpen} title={leftOpen ? 'Hide conversation panel' : 'Show conversation panel'}><PanelLeft size={16} /></button>
          <button type="button" className="bd-icon st-desktop-only" onClick={() => toggle('right')} aria-pressed={rightOpen} title={rightOpen ? 'Hide project panel' : 'Show project panel'}><PanelRight size={16} /></button>
          <Link to="/projects/$projectId/settings" params={{ projectId }} className="bd-icon" title="Project settings"><Settings size={16} /></Link>
        </div>
      </header>
      <div className="st-body">
        {isMobile ? (
          <div className="st-mobile-stack">{mobilePane === 'left' ? left : mobilePane === 'center' ? center : right}</div>
        ) : (
        <Group orientation="horizontal" className="st-group" id="omniweb-studio">
          <Panel id="left" panelRef={leftPanel} defaultSize="28%" minSize="240px" collapsible collapsedSize={0} onResize={(size) => setLeftOpen(size.inPixels > 0)}>
            {left}
          </Panel>
          <Separator className="st-handle" />
          <Panel id="center" minSize="320px">
            {center}
          </Panel>
          <Separator className="st-handle" />
          <Panel id="right" panelRef={rightPanel} defaultSize="26%" minSize="240px" collapsible collapsedSize={0} onResize={(size) => setRightOpen(size.inPixels > 0)}>
            {right}
          </Panel>
        </Group>
        )}
      </div>
    </div>
  )
}

function Bubble({ message }: { message: ChatMessage }) {
  if (message.role === 'user') {
    return <div className="bd-msg bd-msg-user"><div className="bd-bubble"><p>{message.content}</p></div></div>
  }
  return (
    <div className="bd-msg bd-msg-assistant">
      <span className="bd-avatar"><Sparkles size={13} /></span>
      <div className="bd-bubble">
        <div className="st-pre">{message.content}</div>
        <div className="st-msg-meta">
          {message.development_model ? (
            <span className="st-pill st-pill-warn" title="No AI provider is configured. Add a key in Usage → Providers.">Development model · no AI</span>
          ) : (
            <span className="st-pill">{message.model}</span>
          )}
          <span>{message.input_tokens + message.output_tokens} tokens</span>
          <span>{usd(message.cost_usd)}</span>
        </div>
      </div>
    </div>
  )
}

function Empty({ icon, title, text }: { icon: React.ReactNode; title: string; text: string }) {
  return (
    <div className="st-empty st-empty-panel">
      {icon}
      <h3>{title}</h3>
      <p className="st-muted">{text}</p>
    </div>
  )
}

const STATUS_ICON = {
  running: <Loader2 size={13} className="bd-spin" />,
  succeeded: <Check size={13} />,
  failed: <X size={13} />,
  cancelled: <Square size={11} />,
}

function Progress({ executions, loading }: { executions: Execution[]; loading: boolean }) {
  if (loading) return <div className="st-scroll"><span className="st-spinner" /></div>
  if (executions.length === 0) return <Empty icon={<ListChecks size={18} />} title="No agent runs yet" text="Each assistant step, its model, attempts, and cost will be listed here." />
  return (
    <div className="st-scroll st-list">
      {executions.map((run) => (
        <div key={run.id} className={`st-run st-run-${run.status}`}>
          <span className="st-run-icon">{STATUS_ICON[run.status]}</span>
          <div>
            <strong>{run.agent[0].toUpperCase() + run.agent.slice(1)} agent</strong>
            <small>{run.model ?? 'No model'} · {usd(run.cost_usd)} · {relativeTime(run.started_at)}</small>
            {run.detail && <small className="st-run-detail">{run.detail}</small>}
            {run.attempts.length > 1 && (
              <small>{run.attempts.length} attempts: {run.attempts.map((a) => `${a.model} (${a.status})`).join(', ')}</small>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

function Logs({ executions }: { executions: Execution[] }) {
  if (executions.length === 0) return <Empty icon={<ScrollText size={18} />} title="No logs yet" text="Agent and build logs stream here." />
  return (
    <pre className="st-logs">
      {[...executions].reverse().flatMap((run) => [
        `${run.started_at.slice(11, 19)} ${run.agent} started (${run.stage})`,
        ...run.attempts.map((a) => `           attempt ${a.model} [${a.tier}] ${a.status}${a.error ? `: ${a.error}` : ''}`),
        run.finished_at ? `${run.finished_at.slice(11, 19)} ${run.agent} ${run.status}${run.detail ? `: ${run.detail}` : ''}` : '           running…',
      ]).join('\n')}
    </pre>
  )
}

function ProjectUsage({ projectId }: { projectId: string }) {
  const usage = useQuery({ queryKey: ['project-usage', projectId], queryFn: () => platform.projectUsage(projectId) })
  if (usage.isLoading) return <div className="st-scroll"><span className="st-spinner" /></div>
  if (usage.error || !usage.data) return <Empty icon={<CircleAlert size={18} />} title="Usage unavailable" text={usage.error?.message ?? 'Try again shortly.'} />
  const u = usage.data
  const project = u.budgets.find((b) => b.scope === 'project')
  return (
    <div className="st-scroll">
      <div className="st-stat-row">
        <div><small>Spent</small><strong>{usd(u.totals.cost_usd)}</strong></div>
        <div><small>Requests</small><strong>{u.totals.requests}</strong></div>
        <div><small>Tokens</small><strong>{(u.totals.input_tokens + u.totals.output_tokens).toLocaleString()}</strong></div>
      </div>
      {project && <BudgetBar label="Project budget" spent={project.spent_usd} limit={project.limit_usd} />}
      <h4 className="st-h4">By model</h4>
      {u.by_model.length === 0 ? <p className="st-muted">No requests yet.</p> : u.by_model.map((m) => (
        <div key={m.key} className="st-kv"><span>{m.key}</span><strong>{usd(m.cost_usd)} · {m.requests}</strong></div>
      ))}
      <Link to="/projects/$projectId/settings" params={{ projectId }} hash="budget" className="st-link">Change budget and model preferences</Link>
    </div>
  )
}

export function BudgetBar({ label, spent, limit }: { label: string; spent: number; limit: number }) {
  const ratio = limit > 0 ? Math.min(1, spent / limit) : 1
  return (
    <div className="st-budget">
      <div className="st-kv"><span>{label}</span><strong>{usd(spent)} of {usd(limit)}</strong></div>
      <div className="st-bar"><span style={{ width: `${Math.max(2, ratio * 100)}%` }} data-level={ratio >= 1 ? 'over' : ratio >= 0.8 ? 'warn' : 'ok'} /></div>
    </div>
  )
}

export function EnvVars({ projectId, readOnly }: { projectId: string; readOnly: boolean }) {
  const queryClient = useQueryClient()
  const env = useQuery({ queryKey: ['env', projectId], queryFn: () => platform.env(projectId) })
  const [key, setKey] = useState('')
  const [value, setValue] = useState('')
  const [environment, setEnvironment] = useState('development')
  const save = useMutation({
    mutationFn: () => platform.setEnv(projectId, key.trim(), value, environment),
    onSuccess: () => {
      setKey('')
      setValue('')
      void queryClient.invalidateQueries({ queryKey: ['env', projectId] })
    },
  })
  const remove = useMutation({
    mutationFn: (item: { key: string; environment: string }) => platform.deleteEnv(projectId, item.environment, item.key),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['env', projectId] }),
  })
  return (
    <div className="st-scroll">
      <p className="st-fine">Values are encrypted and write-only. They are never shown again and are injected only into approved runtimes.</p>
      {env.data?.length === 0 && <p className="st-muted">No variables yet.</p>}
      {env.data?.map((item) => (
        <div key={`${item.environment}:${item.key}`} className="st-env">
          <code>{item.key}</code>
          <span className="st-pill">{item.environment}</span>
          <span className="st-dots">••••••••</span>
          {!readOnly && (
            <button type="button" className="bd-icon" onClick={() => remove.mutate(item)} title={`Delete ${item.key}`}><Trash2 size={13} /></button>
          )}
        </div>
      ))}
      {!readOnly && (
        <form
          className="st-form"
          onSubmit={(event) => {
            event.preventDefault()
            if (key.trim() && value) save.mutate()
          }}
        >
          <input value={key} onChange={(event) => setKey(event.target.value.toUpperCase())} placeholder="KEY_NAME" aria-label="Variable name" />
          <input value={value} onChange={(event) => setValue(event.target.value)} placeholder="Value" type="password" autoComplete="off" aria-label="Variable value" />
          <select value={environment} onChange={(event) => setEnvironment(event.target.value)} aria-label="Environment">
            <option value="development">Development</option>
            <option value="production">Production</option>
          </select>
          <button type="submit" className="lv-btn lv-btn-light" disabled={!key.trim() || !value || save.isPending}><Plus size={14} /> Add</button>
          {save.error && <p className="st-error">{save.error.message}</p>}
        </form>
      )}
    </div>
  )
}
