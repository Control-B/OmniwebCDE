import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import {
  ArrowLeft,
  ArrowUp,
  Check,
  CircleAlert,
  Database,
  FileCode2,
  Hammer,
  KeyRound,
  ListChecks,
  Megaphone,
  Loader2,
  Maximize2,
  Minimize2,
  Monitor,
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
import { useCallback, useEffect, useRef, useState } from 'react'
import { Group, Panel, Separator, usePanelRef } from 'react-resizable-panels'
import { z } from 'zod'

import { CodePanel } from '../components/builder/CodePanel'
import { DeployPanel } from '../components/builder/DeployPanel'
import { ApprovalBanner, BuildLogs, HistoryPanel, RoutesPanel, RunCard, SchemaPanel, SpecView } from '../components/builder/Panels'
import { PreviewFrame, PreviewToolbarActions } from '../components/builder/Preview'
import { RequireAuth } from '../components/studio/AppNav'
import { platform, type ChatMessage, type Execution, type Tier } from '../lib/api'
import { builder, type Run } from '../lib/builder'
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
  const state = useQuery({
    queryKey: ['builder', projectId],
    queryFn: () => builder.state(projectId),
    refetchInterval: (q) => (q.state.data?.active ? 1500 : false),
  })
  const runs = useQuery({ queryKey: ['runs', projectId, state.data?.run?.id, state.data?.run?.status], queryFn: () => builder.runs(projectId) })
  const [leftTab, setLeftTab] = useState<LeftTab>('chat')
  const [rightTab, setRightTab] = useState<RightTab>('files')
  const [selecting, setSelecting] = useState(false)
  const [openPath, setOpenPath] = useState<string | null>(null)
  const [previewKey, setPreviewKey] = useState(0)
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

  const refreshBuilder = () => void queryClient.invalidateQueries({ queryKey: ['builder', projectId] })

  const edit = useMutation({
    mutationFn: (instruction: string) => builder.edit(projectId, instruction),
    onSettled: () => {
      refreshBuilder()
      void queryClient.invalidateQueries({ queryKey: ['messages', projectId] })
    },
  })

  const generate = useMutation({
    mutationFn: () => builder.generate(projectId),
    onSuccess: () => setMobilePane('center'),
    onSettled: refreshBuilder,
  })

  const cancelRun = (run: Run) => void builder.cancel(projectId, run.id).finally(refreshBuilder)

  const hasSpec = Boolean(state.data?.spec)
  const busy = Boolean(state.data?.active)

  const submit = (value: string) => {
    const content = value.trim()
    if (!content || send.isPending || edit.isPending) return
    setInput('')
    send.reset()
    edit.reset()
    if (hasSpec) edit.mutate(content)
    else send.mutate({ content, id: requestId() })
  }

  useEffect(() => {
    if (!start || autoStarted.current || !project.data || !state.data) return
    autoStarted.current = true
    void navigate({ to: '/projects/$projectId', params: { projectId }, search: {}, replace: true })
    if (!state.data.spec && !state.data.run && project.data.your_role !== 'viewer') generate.mutate()
  }, [start, project.data, state.data])

  const runStatus = state.data?.run?.status
  const headSha = state.data?.head_sha ?? null
  useEffect(() => {
    if (!runStatus) return
    refreshAll()
  }, [runStatus, headSha])

  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.data?.length, pending, runStatus])

  const openFile = useCallback((path: string) => {
    setOpenPath(path)
    setRightTab('files')
    setMobilePane('right')
  }, [])

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
            {messages.data?.length === 0 && !pending && !state.data?.run && (
              <div className="st-empty st-empty-tight">
                <Sparkles size={18} />
                <p className="st-muted">Refine the idea with the requirements assistant, or generate a working first version straight from your prompt. You can keep changing it in chat afterwards.</p>
                <div className="st-row">
                  <button type="button" className="lv-btn lv-btn-light" onClick={() => generate.mutate()} disabled={readOnly || generate.isPending}><Hammer size={14} /> Generate app</button>
                  <button type="button" className="lv-btn lv-btn-ghost" onClick={() => submit(p.prompt)} disabled={readOnly}>Discuss requirements first</button>
                </div>
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
            {state.data?.run && (busy || runStatus === 'awaiting_approval' || state.data.run.status === 'failed') && (
              <div className="bd-msg bd-msg-assistant">
                <span className="bd-avatar"><Hammer size={13} /></span>
                <RunCard run={state.data.run} onCancel={readOnly ? undefined : () => cancelRun(state.data!.run!)} />
              </div>
            )}
            {[send.error, edit.error, generate.error].filter(Boolean).map((error) => (
              <div key={error!.message} className="st-alert st-alert-error">
                <CircleAlert size={14} /> {error!.message}
              </div>
            ))}
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
              placeholder={readOnly ? 'You have view-only access' : hasSpec ? 'Ask for a change — “add a due date to tasks”, “make it green”…' : 'Describe a requirement or answer a question…'}
              aria-label={hasSpec ? 'Ask the builder for a change' : 'Message the requirements assistant'}
            />
            <div className="st-input-bar">
              {hasSpec && <span className="st-fine st-input-hint">{busy ? 'A build is running — send your next change when it finishes' : 'Changes are verified before the preview updates'}</span>}
              <label className="st-select" title="Model tier. Auto uses the project's preference." hidden={hasSpec}>
                <select value={tier} onChange={(event) => setTier(event.target.value as Tier | '')} aria-label="Model tier">
                  {TIERS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </label>
              <button type="submit" className="lv-send" disabled={!input.trim() || send.isPending || edit.isPending || readOnly || (hasSpec && busy)} aria-label="Send">
                <ArrowUp size={17} strokeWidth={2.5} />
              </button>
            </div>
          </form>
        </div>
      )}
      {leftTab === 'progress' && (
        <Progress runs={runs.data ?? []} executions={executions.data ?? []} loading={executions.isLoading || runs.isLoading} onCancel={readOnly ? undefined : cancelRun} />
      )}
      {leftTab === 'requirements' && (
        hasSpec || !latestRequirements ? (
          <SpecView spec={state.data?.spec ?? null} prompt={p.prompt} />
        ) : (
          <div className="st-scroll">
            <article className="st-doc">
              <p className="st-kicker">Latest draft from the requirements assistant</p>
              <div className="st-pre">{latestRequirements.content}</div>
              <p className="st-fine">Generate the app when you're happy with this. The architect turns the conversation into a specification you can keep editing.</p>
            </article>
          </div>
        )
      )}
      {leftTab === 'changes' && <HistoryPanel projectId={projectId} headSha={headSha} busy={busy} readOnly={readOnly} />}
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
        <PreviewToolbarActions state={state.data} selecting={selecting} onSelectingChange={setSelecting} onReload={() => setPreviewKey((k) => k + 1)} />
        <div className="bd-toolbar-right">
          {!readOnly && state.data?.spec && !busy && (
            <button type="button" className="bd-icon" onClick={() => generate.mutate()} disabled={generate.isPending} title="Rebuild from the specification and run every check"><Hammer size={15} /></button>
          )}
          <button type="button" className="bd-icon" onClick={() => setFullscreen(fullscreen === 'preview' ? 'none' : 'preview')} title={fullscreen === 'preview' ? 'Exit full screen' : 'Full-screen preview'}>
            {fullscreen === 'preview' ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
          </button>
        </div>
      </div>
      {state.data && state.data.approvals.length > 0 && (
        <ApprovalBanner projectId={projectId} approvals={state.data.approvals} projectName={p.name} readOnly={readOnly} />
      )}
      <PreviewFrame
        key={previewKey}
        projectId={projectId}
        state={state.data}
        device={device}
        selecting={selecting}
        onSelectingChange={setSelecting}
        readOnly={readOnly}
        onGenerate={() => generate.mutate()}
        onOpenFile={openFile}
      />
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
      {rightTab === 'files' && <CodePanel projectId={projectId} headSha={headSha} readOnly={readOnly} busy={busy} openPath={openPath} onOpen={setOpenPath} />}
      {rightTab === 'database' && <SchemaPanel projectId={projectId} headSha={headSha} />}
      {rightTab === 'api' && <RoutesPanel projectId={projectId} headSha={headSha} />}
      {rightTab === 'env' && <EnvVars projectId={projectId} readOnly={readOnly} />}
      {rightTab === 'deploy' && <DeployPanel projectId={projectId} projectName={p.name} state={state.data} readOnly={readOnly} />}
      {rightTab === 'logs' && (
        <>
          <BuildLogs projectId={projectId} state={state.data} />
          {executions.data && executions.data.length > 0 && (
            <details className="lg-agents">
              <summary>Requirements assistant log</summary>
              <Logs executions={executions.data} />
            </details>
          )}
        </>
      )}
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
          {(() => {
            const status = state.data?.generation_status ?? p.generation_status
            return <span className={`st-status st-status-${status}`}>{STATUS_LABEL[status] ?? status}</span>
          })()}
        </div>
        <div className="bd-switch bd-mobile-only" role="tablist">
          <button type="button" role="tab" aria-selected={mobilePane === 'left'} onClick={() => setMobilePane('left')}>Chat</button>
          <button type="button" role="tab" aria-selected={mobilePane === 'center'} onClick={() => setMobilePane('center')}>Preview</button>
          <button type="button" role="tab" aria-selected={mobilePane === 'right'} onClick={() => setMobilePane('right')}>Project</button>
        </div>
        <div className="bd-top-right">
          <span className="st-cost" title="AI usage for this project">{usd(p.estimated_usage_usd)}</span>
          <Link to="/projects/$projectId/growth" params={{ projectId }} className="bd-icon" title="Business and marketing workspace"><Megaphone size={16} /></Link>
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

function inlineMarkdown(text: string) {
  return text.split(/(\*\*[^*\n]+\*\*|(?<![\w])_[^_\n]+_(?![\w]))/g).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) return <strong key={i}>{part.slice(2, -2)}</strong>
    if (part.startsWith('_') && part.endsWith('_') && part.length > 2) return <em key={i}>{part.slice(1, -1)}</em>
    return part
  })
}

function Bubble({ message }: { message: ChatMessage }) {
  if (message.role === 'user') {
    return <div className="bd-msg bd-msg-user"><div className="bd-bubble"><p>{message.content}</p></div></div>
  }
  return (
    <div className="bd-msg bd-msg-assistant">
      <span className="bd-avatar"><Sparkles size={13} /></span>
      <div className="bd-bubble">
        <div className="st-pre">{inlineMarkdown(message.content)}</div>
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

function Progress({ runs, executions, loading, onCancel }: { runs: Run[]; executions: Execution[]; loading: boolean; onCancel?: (run: Run) => void }) {
  if (loading) return <div className="st-scroll"><span className="st-spinner" /></div>
  if (executions.length === 0 && runs.length === 0) return <Empty icon={<ListChecks size={18} />} title="No agent runs yet" text="Each build, its pipeline steps and checks, plus every assistant step with its model and cost, is listed here." />
  return (
    <div className="st-scroll st-list">
      {runs.map((run, index) => (
        <div key={run.id} className="st-progress-run">
          <RunCard run={run} compact={index > 0} onCancel={onCancel ? () => onCancel(run) : undefined} />
          <small className="st-fine">
            {run.instruction ? `“${run.instruction}” · ` : ''}{relativeTime(run.created_at)} · {usd(run.cost_usd)}
            {run.repair_attempts > 0 ? ` · ${run.repair_attempts} repair attempt${run.repair_attempts > 1 ? 's' : ''}` : ''}
          </small>
        </div>
      ))}
      {runs.length > 0 && executions.length > 0 && <h4 className="st-h4">Requirements assistant</h4>}
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
