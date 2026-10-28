import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Bot, Check, CircleAlert, Database, ExternalLink, GitCommitHorizontal, KeyRound, Loader2, Lock, Redo2, RotateCcw, ScrollText, ShieldAlert, Square, Undo2, User, Waypoints, X } from 'lucide-react'
import { useState } from 'react'

import { builder, type Approval, type AppSpec, type BuilderState, type Run } from '../../lib/builder'

function ago(iso: string) {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  return hours < 24 ? `${hours}h ago` : `${Math.round(hours / 24)}d ago`
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

const STAGE_LABEL: Record<string, string> = {
  understand: 'Planning the app',
  plan: 'Planning database changes',
  apply: 'Writing code',
  verify: 'Running checks',
  repair: 'Repairing failures',
  finalize: 'Publishing preview',
}

export function stepLabel(name: string) {
  return STAGE_LABEL[name] ?? name.replace(/^check:/, '').replace('.', ' · ')
}

export function RunCard({ run, onCancel, compact }: { run: Run; onCancel?: () => void; compact?: boolean }) {
  const active = run.status === 'queued' || run.status === 'running'
  const latest = new Map(run.steps.map((s, i) => [s.name, i]))
  const steps = run.steps.filter((s, i) => latest.get(s.name) === i)
  return (
    <div className={`rc rc-${run.status}`}>
      <div className="rc-head">
        {active ? <Loader2 size={14} className="bd-spin" /> : run.status === 'succeeded' ? <Check size={14} /> : run.status === 'awaiting_approval' ? <ShieldAlert size={14} /> : <X size={14} />}
        <strong>{{ generate: 'Building the app', edit: 'Applying your change', restore: 'Restoring a checkpoint', verify: 'Checking your edit' }[run.kind]}</strong>
        {active && onCancel && <button type="button" className="st-link" onClick={onCancel}><Square size={11} /> Stop</button>}
      </div>
      {!compact && (
        <ol className="rc-steps">
          {steps.map((step) => (
            <li key={step.name} data-status={step.status} data-check={step.name.startsWith('check:')}>
              {step.status === 'running' ? <Loader2 size={11} className="bd-spin" /> : step.status === 'failed' ? <X size={11} /> : <Check size={11} />}
              <span>{step.name.startsWith('check:') ? step.detail.split(' — ')[0] : stepLabel(step.name)}</span>
              {step.status !== 'running' && step.detail && !step.name.startsWith('check:') && <small>{step.detail}</small>}
              {step.name.startsWith('check:') && step.detail.includes(' — ') && <small>{step.detail.split(' — ')[1]}</small>}
            </li>
          ))}
          {active && steps.length === 0 && <li data-status="running"><Loader2 size={11} className="bd-spin" /><span>Queued</span></li>}
        </ol>
      )}
    </div>
  )
}

export function ApprovalBanner({ projectId, approvals, projectName, readOnly }: { projectId: string; approvals: Approval[]; projectName: string; readOnly: boolean }) {
  const queryClient = useQueryClient()
  const [confirm, setConfirm] = useState('')
  const decide = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: 'approve' | 'reject' }) => builder.decide(projectId, id, decision, confirm || undefined),
    onSuccess: () => {
      setConfirm('')
      void queryClient.invalidateQueries({ queryKey: ['builder', projectId] })
      void queryClient.invalidateQueries({ queryKey: ['deployments', projectId] })
    },
  })
  if (approvals.length === 0) return null
  const approval = approvals[0]
  const migration = (approval.details as { migration?: { destructive_summary: string[] } }).migration
  return (
    <div className="ab" role="alert">
      <ShieldAlert size={16} />
      <div className="ab-body">
        <strong>{approval.kind === 'destructive_migration' ? 'This change deletes data' : approval.kind.includes('rollback') ? 'Approve rollback' : 'Approve deployment'}</strong>
        <p>{approval.summary}</p>
        {migration && <ul>{migration.destructive_summary.map((line) => <li key={line}>{line}</li>)}</ul>}
        {approval.kind === 'destructive_migration' && <p className="st-fine">Preview data in the dropped columns or tables is removed. The migration stays in history, and undo adds the columns back empty.</p>}
        {approval.requires_confirmation && (
          <label className="st-field ab-confirm">
            Type <code>{projectName}</code> to approve a production change
            <input value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" />
          </label>
        )}
        {decide.error && <p className="st-error">{decide.error.message}</p>}
      </div>
      {!readOnly && (
        <div className="ab-actions">
          <button type="button" className="lv-btn lv-btn-ghost" disabled={decide.isPending} onClick={() => decide.mutate({ id: approval.id, decision: 'reject' })}>Reject</button>
          <button
            type="button"
            className={`lv-btn ${approval.kind === 'destructive_migration' || approval.kind.startsWith('production') ? 'st-btn-danger' : 'lv-btn-light'}`}
            disabled={decide.isPending || (approval.requires_confirmation && confirm !== projectName)}
            onClick={() => decide.mutate({ id: approval.id, decision: 'approve' })}
          >
            {decide.isPending && <Loader2 size={13} className="bd-spin" />} Approve
          </button>
        </div>
      )}
    </div>
  )
}

export function SpecView({ spec, prompt }: { spec: AppSpec | null; prompt: string }) {
  if (!spec) {
    return (
      <div className="st-scroll">
        <article className="st-doc">
          <p className="st-kicker">Original request</p>
          <div className="st-pre">{prompt}</div>
          <p className="st-fine">When you generate the app, the architect turns this conversation into a specification: the data models, fields, screens, sign-in, and targets. It appears here, and every later change edits it.</p>
        </article>
      </div>
    )
  }
  return (
    <div className="st-scroll sv">
      <div className="sv-head">
        <span className="sv-swatch" style={{ background: spec.accent }} />
        <div>
          <strong>{spec.name}</strong>
          <p className="st-fine">{spec.tagline}</p>
        </div>
      </div>
      <div className="st-chips">
        {spec.targets.map((t) => <span key={t}>{{ web: 'React web app', api: 'FastAPI + PostgreSQL', mobile: 'Expo mobile app' }[t]}</span>)}
        {spec.auth && <span><Lock size={11} /> Email sign-in</span>}
        {spec.roles.map((r) => <span key={r}>{r}</span>)}
      </div>
      {spec.entities.map((entity) => (
        <section key={entity.name} className="sv-entity">
          <h4>{entity.label}</h4>
          {entity.description && <p className="st-fine">{entity.description}</p>}
          <ul>
            {entity.fields.map((f) => (
              <li key={f.name}><span>{f.label}</span><code>{f.type}</code>{f.required && <em>required</em>}</li>
            ))}
          </ul>
        </section>
      ))}
      <p className="st-fine">Ask for changes in chat, like “add a due date to loans” or “make it green”. Structural changes update every layer: database, API, tests, web, and mobile.</p>
    </div>
  )
}

export function HistoryPanel({ projectId, headSha, busy, readOnly }: { projectId: string; headSha: string | null; busy: boolean; readOnly: boolean }) {
  const queryClient = useQueryClient()
  const history = useQuery({ queryKey: ['checkpoints', projectId, headSha], queryFn: () => builder.checkpoints(projectId), enabled: Boolean(headSha) })
  const [open, setOpen] = useState<string | null>(null)
  const diff = useQuery({ queryKey: ['diff', projectId, open], queryFn: () => builder.diff(projectId, open as string), enabled: Boolean(open) })
  const act = useMutation({
    mutationFn: (action: { kind: 'undo' } | { kind: 'redo' } | { kind: 'restore'; sha: string }) =>
      action.kind === 'restore' ? builder.restore(projectId, action.sha) : action.kind === 'undo' ? builder.undo(projectId) : builder.redo(projectId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['builder', projectId] }),
  })
  if (!headSha) return <Empty icon={<GitCommitHorizontal size={18} />} title="No checkpoints yet" text="Every build, edit, and restore is a Git commit you can inspect, undo, or restore." />
  const list = history.data?.checkpoints ?? []
  return (
    <div className="st-scroll hp">
      {!readOnly && (
        <div className="st-row hp-actions">
          <button type="button" className="lv-btn lv-btn-ghost" disabled={!history.data?.can_undo || busy || act.isPending} onClick={() => act.mutate({ kind: 'undo' })}><Undo2 size={13} /> Undo</button>
          <button type="button" className="lv-btn lv-btn-ghost" disabled={!history.data?.can_redo || busy || act.isPending} onClick={() => act.mutate({ kind: 'redo' })}><Redo2 size={13} /> Redo</button>
        </div>
      )}
      {act.error && <div className="st-alert st-alert-error"><CircleAlert size={14} /> {act.error.message}</div>}
      {history.isLoading && <span className="st-spinner" />}
      <ol className="hp-list">
        {list.map((c) => (
          <li key={c.sha} data-head={c.sha === headSha}>
            <button type="button" className="hp-item" onClick={() => setOpen(open === c.sha ? null : c.sha)} aria-expanded={open === c.sha}>
              <span className="hp-icon">{c.author === 'agent' ? <Bot size={12} /> : <User size={12} />}</span>
              <span className="hp-text">
                <strong>{c.message}</strong>
                <small><code>{c.sha.slice(0, 7)}</code> · {ago(c.created_at)} · {c.verified ? <span className="st-ok">checks passed</span> : <span className="hp-unverified">not verified</span>}</small>
              </span>
            </button>
            {open === c.sha && (
              <div className="hp-diff">
                {diff.isLoading && <span className="st-spinner" />}
                {diff.data && (
                  <>
                    <ul className="hp-files">
                      {diff.data.files.map((f) => <li key={f.path}><code>{f.path}</code><span className="hp-add">+{f.added}</span><span className="hp-del">−{f.removed}</span></li>)}
                    </ul>
                    <pre className="hp-patch">{diff.data.patch.split('\n').map((line, i) => <span key={i} data-kind={line.startsWith('+') && !line.startsWith('+++') ? 'add' : line.startsWith('-') && !line.startsWith('---') ? 'del' : line.startsWith('@@') ? 'hunk' : undefined}>{line}{'\n'}</span>)}</pre>
                    {diff.data.truncated && <p className="st-fine">Diff truncated.</p>}
                  </>
                )}
                {!readOnly && c.sha !== headSha && (
                  <button type="button" className="lv-btn lv-btn-ghost" disabled={busy || act.isPending} onClick={() => act.mutate({ kind: 'restore', sha: c.sha })}><RotateCcw size={13} /> Restore this version</button>
                )}
              </div>
            )}
          </li>
        ))}
      </ol>
    </div>
  )
}

export function SchemaPanel({ projectId, headSha }: { projectId: string; headSha: string | null }) {
  const schema = useQuery({ queryKey: ['schema', projectId, headSha], queryFn: () => builder.schema(projectId) })
  if (schema.isLoading) return <div className="st-scroll"><span className="st-spinner" /></div>
  if (!schema.data || schema.data.entities.length === 0) return <Empty icon={<Database size={18} />} title="No database schema yet" text="Tables and migrations appear here after the first build." />
  if (!schema.data.has_api) {
    return <Empty icon={<Database size={18} />} title="This app stores data in the browser" text="It has no backend yet. Ask “add a backend” in chat to get FastAPI, PostgreSQL, and migrations." />
  }
  return (
    <div className="st-scroll">
      {schema.data.auth && (
        <section className="sv-entity"><h4><KeyRound size={12} /> users</h4><p className="st-fine">Email, password hash (scrypt), role. The first account becomes the admin.</p></section>
      )}
      {schema.data.entities.map((e) => (
        <section key={e.name} className="sv-entity">
          <h4><code>{e.table}</code></h4>
          <ul>
            <li><span>id</span><code>integer</code><em>primary key</em></li>
            {e.fields.map((f) => <li key={f.name}><span>{f.name}</span><code>{f.type}</code>{f.required && <em>required in API</em>}</li>)}
            <li><span>created_at</span><code>datetime</code></li>
            {schema.data.auth && <li><span>owner_id</span><code>integer</code><em>users.id</em></li>}
          </ul>
        </section>
      ))}
      <h4 className="st-h4">Migrations</h4>
      <ol className="mg-list">
        {[...schema.data.migrations].reverse().map((m) => (
          <li key={m.revision} data-destructive={m.destructive}>
            <code>{m.revision}</code>
            <span>{m.message}</span>
            {m.destructive && <span className="st-pill st-pill-warn"><AlertTriangle size={11} /> approved deletion</span>}
          </li>
        ))}
      </ol>
      <p className="st-fine">Migrations are Alembic revisions in <code>services/api/migrations</code>. They are append-only, and any that delete data need your approval.</p>
    </div>
  )
}

const METHOD_CLASS: Record<string, string> = { GET: 'get', POST: 'post', PUT: 'put', DELETE: 'del', PATCH: 'put' }

export function RoutesPanel({ projectId, headSha }: { projectId: string; headSha: string | null }) {
  const routes = useQuery({ queryKey: ['routes', projectId, headSha], queryFn: () => builder.routes(projectId) })
  if (routes.isLoading) return <div className="st-scroll"><span className="st-spinner" /></div>
  if (!routes.data || routes.data.routes.length === 0) return <Empty icon={<Waypoints size={18} />} title="No API routes" text="Apps with a FastAPI backend list their routes here, with a link to the live OpenAPI docs." />
  return (
    <div className="st-scroll">
      {routes.data.docs_url && <a className="st-link rp-docs" href={routes.data.docs_url} target="_blank" rel="noreferrer"><ExternalLink size={12} /> Open interactive API docs (preview)</a>}
      <ul className="rp-list">
        {routes.data.routes.map((r) => (
          <li key={`${r.method} ${r.path}`}>
            <span className={`rp-method rp-${METHOD_CLASS[r.method]}`}>{r.method}</span>
            <code>{r.path}</code>
            {r.auth && <Lock size={11} aria-label="Requires sign-in" />}
            <small>{r.summary}</small>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function BuildLogs({ projectId, state }: { projectId: string; state: BuilderState | undefined }) {
  const run = state?.run
  const details = useQuery({ queryKey: ['run', projectId, run?.id, run?.status], queryFn: () => builder.run(projectId, run!.id), enabled: Boolean(run) })
  const steps = details.data?.verify?.length ? details.data.verify : (state?.last_build?.steps ?? [])
  const [open, setOpen] = useState<string | null>(null)
  if (!run && steps.length === 0) return <Empty icon={<ScrollText size={18} />} title="No build logs yet" text="Type-check, test, migration, and build output from the sandbox appears here." />
  return (
    <div className="st-scroll lg">
      {state?.last_build?.unavailable && <div className="st-alert"><CircleAlert size={14} /> {state.last_build.unavailable}</div>}
      {run?.error && run.status === 'failed' && <div className="st-alert st-alert-error"><CircleAlert size={14} /> {run.error}</div>}
      {steps.map((step) => (
        <div key={step.name} className="lg-step" data-ok={step.ok}>
          <button type="button" onClick={() => setOpen(open === step.name ? null : step.name)} aria-expanded={open === step.name || !step.ok}>
            {step.ok ? <Check size={13} /> : <X size={13} />}
            <strong>{step.label}</strong>
            <small>{step.duration.toFixed(1)}s</small>
          </button>
          {(open === step.name || !step.ok) && <pre>{step.output.trim() || 'No output.'}</pre>}
        </div>
      ))}
      {run && (
        <>
          <h4 className="st-h4">Pipeline</h4>
          <pre className="lg-pipeline">
            {run.steps.map((s) => `${s.at.slice(11, 19)}  ${s.status.padEnd(7)} ${stepLabel(s.name)}${s.detail ? ` — ${s.detail}` : ''}`).join('\n')}
          </pre>
        </>
      )}
    </div>
  )
}
