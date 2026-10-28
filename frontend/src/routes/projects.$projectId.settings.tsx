import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import { ArrowLeft, Cloud, GitBranch, Trash2, UserPlus } from 'lucide-react'
import { useEffect, useState } from 'react'

import { AppNav, RequireAuth } from '../components/studio/AppNav'
import { api, platform, type Preferences, type Project, type Tier } from '../lib/api'
import { useAuth } from '../lib/auth'
import { BudgetBar, EnvVars } from './projects.$projectId.index'

export const Route = createFileRoute('/projects/$projectId/settings')({
  head: () => ({ meta: [{ title: 'Project settings — Omniweb' }] }),
  component: () => (
    <div className="st">
      <AppNav />
      <RequireAuth>
        <SettingsPage />
      </RequireAuth>
    </div>
  ),
})

const SECTIONS = [
  ['general', 'Application'],
  ['models', 'Model preferences'],
  ['budget', 'Usage budget'],
  ['env', 'Environment variables'],
  ['credentials', 'Provider credentials'],
  ['github', 'GitHub'],
  ['deploy', 'Deployment targets'],
  ['people', 'Collaborators'],
  ['danger', 'Delete project'],
] as const

const TEMPLATE_OPTIONS = [
  ['react-web', 'Web application'],
  ['fastapi-backend', 'Backend API'],
  ['expo-mobile', 'Mobile application'],
  ['full-stack', 'Full-stack application'],
] as const

function SettingsPage() {
  const { projectId } = Route.useParams()
  const project = useQuery({ queryKey: ['project', projectId], queryFn: () => platform.project(projectId) })
  if (project.isLoading) return <div className="st-center"><span className="st-spinner" /></div>
  if (!project.data) {
    return (
      <div className="st-center st-stack">
        <h1>Project not found</h1>
        <Link to="/projects" className="lv-btn lv-btn-light">Back to projects</Link>
      </div>
    )
  }
  const p = project.data
  const canWrite = p.your_role !== 'viewer'
  const isOwner = p.your_role === 'owner'
  return (
    <main className="st-page st-settings">
      <Link to="/projects/$projectId" params={{ projectId }} search={{ start: false }} className="st-back"><ArrowLeft size={14} /> Back to builder</Link>
      <h1>{p.name} settings</h1>
      <div className="st-settings-grid">
        <nav className="st-settings-nav" aria-label="Settings sections">
          {SECTIONS.map(([id, label]) => <a key={id} href={`#${id}`}>{label}</a>)}
        </nav>
        <div className="st-settings-body">
          <General project={p} canWrite={canWrite} />
          <Models projectId={projectId} canWrite={canWrite} />
          <Budget projectId={projectId} canWrite={isOwner} />
          <section id="env" className="st-card st-section">
            <h2>Environment variables</h2>
            <EnvVars projectId={projectId} readOnly={!canWrite} />
          </section>
          <section id="credentials" className="st-card st-section">
            <h2>Provider credentials</h2>
            <p className="st-muted">
              AI provider keys belong to your organization and are stored only in the model gateway, encrypted. They are never sent to
              the browser, to generated applications, or to development environments.
            </p>
            <Link to="/usage" hash="providers" className="lv-btn lv-btn-ghost">Manage organization providers</Link>
          </section>
          <section id="github" className="st-card st-section">
            <h2><GitBranch size={16} /> GitHub</h2>
            <p className="st-muted">{p.github_repo ? `Connected to ${p.github_repo}.` : 'Not connected.'} Repository sync through a least-privilege GitHub App arrives in Milestone 6.</p>
            <button type="button" className="lv-btn lv-btn-ghost" disabled>Connect GitHub</button>
          </section>
          <DeployTargets />
          <People projectId={projectId} isOwner={isOwner} />
          {isOwner && <Danger project={p} />}
        </div>
      </div>
    </main>
  )
}

function General({ project, canWrite }: { project: Project; canWrite: boolean }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState(project.name)
  const [description, setDescription] = useState(project.description)
  const [template, setTemplate] = useState(project.template)
  const save = useMutation({
    mutationFn: () => platform.updateProject(project.id, { name, description, template }),
    onSuccess: (updated) => queryClient.setQueryData(['project', project.id], updated),
  })
  const dirty = name !== project.name || description !== project.description || template !== project.template
  return (
    <section id="general" className="st-card st-section">
      <h2>Application</h2>
      <label className="st-field">Name<input value={name} onChange={(e) => setName(e.target.value)} disabled={!canWrite} maxLength={80} /></label>
      <label className="st-field">Description<textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={4} disabled={!canWrite} /></label>
      <label className="st-field">
        Template
        <select value={template} onChange={(e) => setTemplate(e.target.value)} disabled={!canWrite}>
          {TEMPLATE_OPTIONS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
      </label>
      <div className="st-chips">{project.stack.map((item) => <span key={item}>{item}</span>)}</div>
      <div className="st-actions">
        {save.error && <span className="st-error">{save.error.message}</span>}
        {save.isSuccess && !dirty && <span className="st-ok">Saved</span>}
        <button type="button" className="lv-btn lv-btn-light" disabled={!canWrite || !dirty || name.trim().length < 2 || save.isPending} onClick={() => save.mutate()}>Save changes</button>
      </div>
    </section>
  )
}

function Models({ projectId, canWrite }: { projectId: string; canWrite: boolean }) {
  const queryClient = useQueryClient()
  const prefs = useQuery({ queryKey: ['prefs', projectId], queryFn: () => platform.projectPreferences(projectId) })
  const providers = useQuery({ queryKey: ['providers'], queryFn: platform.providers })
  const [draft, setDraft] = useState<Preferences | null>(null)
  useEffect(() => {
    if (prefs.data) setDraft(prefs.data)
  }, [prefs.data])
  const save = useMutation({
    mutationFn: (value: Preferences) =>
      platform.setProjectPreferences(projectId, {
        default_tier: value.default_tier,
        allowed_providers: value.allowed_providers,
        pinned_models: value.pinned_models,
        max_escalations: value.max_escalations,
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['prefs', projectId] }),
  })
  return (
    <section id="models" className="st-card st-section">
      <h2>Model preferences</h2>
      <p className="st-muted">Omniweb routes each task to a tier. Economy suits simple tasks; advanced is reserved for architecture and hard debugging. Escalation moves up at most the number of tiers you allow.</p>
      {!draft ? <span className="st-spinner" /> : (
        <>
          <label className="st-field">
            Default tier
            <select value={draft.default_tier} onChange={(e) => setDraft({ ...draft, default_tier: e.target.value as Tier })} disabled={!canWrite}>
              <option value="economy">Economy</option>
              <option value="standard">Standard</option>
              <option value="advanced">Advanced</option>
              <option value="self_hosted">Self-hosted</option>
            </select>
          </label>
          <label className="st-field">
            Maximum escalations after a failure
            <select value={draft.max_escalations} onChange={(e) => setDraft({ ...draft, max_escalations: Number(e.target.value) })} disabled={!canWrite}>
              <option value={0}>Never escalate</option>
              <option value={1}>Up to one tier</option>
              <option value={2}>Up to two tiers</option>
            </select>
          </label>
          <fieldset className="st-field">
            <legend>Allowed providers (none selected allows all configured providers)</legend>
            <div className="st-checks">
              {providers.data?.filter((p) => p.kind !== 'development').map((provider) => (
                <label key={provider.provider}>
                  <input
                    type="checkbox"
                    disabled={!canWrite}
                    checked={draft.allowed_providers.includes(provider.provider)}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        allowed_providers: e.target.checked
                          ? [...draft.allowed_providers, provider.provider]
                          : draft.allowed_providers.filter((item) => item !== provider.provider),
                      })
                    }
                  />
                  {provider.label}
                  {!provider.configured && <small>not configured</small>}
                </label>
              ))}
            </div>
          </fieldset>
          <p className="st-fine">Up to {draft.max_attempts ?? 3} attempts per request, including fallbacks to other models.</p>
          <div className="st-actions">
            {save.error && <span className="st-error">{save.error.message}</span>}
            {save.isSuccess && <span className="st-ok">Saved</span>}
            <button type="button" className="lv-btn lv-btn-light" disabled={!canWrite || save.isPending} onClick={() => save.mutate(draft)}>Save preferences</button>
          </div>
        </>
      )}
    </section>
  )
}

function Budget({ projectId, canWrite }: { projectId: string; canWrite: boolean }) {
  const queryClient = useQueryClient()
  const usage = useQuery({ queryKey: ['project-usage', projectId], queryFn: () => platform.projectUsage(projectId) })
  const budget = usage.data?.budgets.find((b) => b.scope === 'project')
  const [limit, setLimit] = useState('')
  const [hard, setHard] = useState(true)
  useEffect(() => {
    if (budget) {
      setLimit(String(budget.limit_usd))
      setHard(budget.hard_limit)
    }
  }, [budget?.limit_usd, budget?.hard_limit])
  const save = useMutation({
    mutationFn: () => platform.projectBudget(projectId, Number(limit), hard),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['project-usage', projectId] }),
  })
  return (
    <section id="budget" className="st-card st-section">
      <h2>Usage budget</h2>
      {usage.error && <p className="st-error">{usage.error.message}</p>}
      {budget && <BudgetBar label="Project AI spend" spent={budget.spent_usd} limit={budget.limit_usd} />}
      <div className="st-inline">
        <label className="st-field">
          Limit (USD)
          <input type="number" min={0} step="0.5" value={limit} onChange={(e) => setLimit(e.target.value)} disabled={!canWrite} />
        </label>
        <label className="st-check">
          <input type="checkbox" checked={hard} onChange={(e) => setHard(e.target.checked)} disabled={!canWrite} />
          Hard limit: block requests that could exceed it
        </label>
      </div>
      <p className="st-fine">You’ll see an alert at 80% of the limit. The monthly organization budget also applies.</p>
      <div className="st-actions">
        {!canWrite && <span className="st-muted">Only project owners can change the budget.</span>}
        {save.error && <span className="st-error">{save.error.message}</span>}
        {save.isSuccess && <span className="st-ok">Saved</span>}
        <button type="button" className="lv-btn lv-btn-light" disabled={!canWrite || limit === '' || Number(limit) < 0 || save.isPending} onClick={() => save.mutate()}>Save budget</button>
      </div>
    </section>
  )
}

function DeployTargets() {
  const connections = useQuery({ queryKey: ['connections'], queryFn: api.connections })
  return (
    <section id="deploy" className="st-card st-section">
      <h2><Cloud size={16} /> Deployment targets</h2>
      <p className="st-muted">Omniweb deploys to cloud accounts you connect. Every deployment shows estimated charges and needs your approval.</p>
      {connections.data?.length ? connections.data.map((c) => (
        <div key={c.id} className="st-kv"><span>{c.label} · DigitalOcean</span><strong>{c.healthy ? 'Healthy' : 'Needs attention'}</strong></div>
      )) : <p className="st-muted">No cloud accounts connected.</p>}
      <Link to="/app" className="lv-btn lv-btn-ghost">Manage cloud accounts</Link>
    </section>
  )
}

function People({ projectId, isOwner }: { projectId: string; isOwner: boolean }) {
  const queryClient = useQueryClient()
  const members = useQuery({ queryKey: ['members', projectId], queryFn: () => platform.members(projectId) })
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<'editor' | 'viewer'>('editor')
  const add = useMutation({
    mutationFn: () => platform.addMember(projectId, email.trim(), role),
    onSuccess: () => {
      setEmail('')
      void queryClient.invalidateQueries({ queryKey: ['members', projectId] })
    },
  })
  const remove = useMutation({
    mutationFn: (userId: string) => platform.removeMember(projectId, userId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['members', projectId] }),
  })
  return (
    <section id="people" className="st-card st-section">
      <h2>Collaborators</h2>
      {members.data?.map((m) => (
        <div key={m.user_id} className="st-kv">
          <span>{m.display_name} <small className="st-muted">{m.email}</small></span>
          <span className="st-row">
            <span className="st-pill">{m.role}</span>
            {isOwner && m.role !== 'owner' && (
              <button type="button" className="bd-icon" onClick={() => remove.mutate(m.user_id)} title={`Remove ${m.email}`}><Trash2 size={13} /></button>
            )}
          </span>
        </div>
      ))}
      {isOwner && (
        <form className="st-form" onSubmit={(e) => { e.preventDefault(); if (email.trim()) add.mutate() }}>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="teammate@company.com" aria-label="Collaborator email" />
          <select value={role} onChange={(e) => setRole(e.target.value as 'editor' | 'viewer')} aria-label="Role">
            <option value="editor">Editor</option>
            <option value="viewer">Viewer</option>
          </select>
          <button type="submit" className="lv-btn lv-btn-light" disabled={!email.trim() || add.isPending}><UserPlus size={14} /> Add</button>
          {add.error && <p className="st-error">{add.error.message}</p>}
        </form>
      )}
      <p className="st-fine">Collaborators must already belong to your organization in the identity provider.</p>
    </section>
  )
}

function Danger({ project }: { project: Project }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { me } = useAuth()
  const [confirm, setConfirm] = useState('')
  const remove = useMutation({
    mutationFn: () => platform.deleteProject(project.id, confirm),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['projects'] })
      void navigate({ to: '/projects' })
    },
  })
  return (
    <section id="danger" className="st-card st-section st-danger">
      <h2>Delete project</h2>
      <p className="st-muted">This permanently deletes the conversation, agent history, and environment variables for {project.name}. AI usage records are kept for billing.</p>
      <label className="st-field">
        Type <strong>{project.name}</strong> to confirm
        <input value={confirm} onChange={(e) => setConfirm(e.target.value)} aria-label="Confirm project name" />
      </label>
      <div className="st-actions">
        {remove.error && <span className="st-error">{remove.error.message}</span>}
        <button type="button" className="lv-btn st-btn-danger" disabled={confirm !== project.name || remove.isPending || !me} onClick={() => remove.mutate()}>
          Delete project
        </button>
      </div>
    </section>
  )
}
